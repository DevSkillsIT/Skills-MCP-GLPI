"""
Advanced search tool: free-form criteria, cheap counting and field discovery.

The client layer has always supported multiple criteria, forcedisplay, sorting
and dropdown expansion — but nothing exposed it. Any question outside the
pre-baked filters had no path at all, for the model and for us when
diagnosing. This is one consolidated tool with a `scope`, not three atomic
ones: the catalogue stays small and the capability becomes reachable.
"""

from typing import Any, Dict, List, Optional

from src.formatters.markdown_helpers import (
    fmt_impact,
    fmt_priority,
    fmt_status,
    fmt_type,
    fmt_urgency,
    page_info,
    truncate_field,
)
from src.models.exceptions import ValidationError
from src.services.glpi_client import emit_criteria, glpi_client
from src.services.search_options import search_options_cache
from src.utils.helpers import logger
from src.utils.search_criteria import normalize_order

VALID_SCOPES = ("search", "count", "fields")

#: Itemtypes ITIL cujos codigos de status/prioridade/urgencia/impacto/tipo
#: seguem a mesma tabela do Ticket.
_ITIL_ITEMTYPES = ("Ticket", "Problem", "Change")

#: Colunas cujo valor numerico do GLPI e um codigo, nao um numero.
#: expand_dropdowns=true resolve tabelas de dropdown, mas status/prioridade e
#: companhia sao inteiros na propria tabela do chamado e voltam crus.
_ENUM_DECODERS = {
    "status": fmt_status,
    "priority": fmt_priority,
    "urgency": fmt_urgency,
    "impact": fmt_impact,
    "type": fmt_type,
}

# Search operators accepted by the GLPI Search API.
VALID_SEARCHTYPES = (
    "contains",
    "notcontains",
    "equals",
    "notequals",
    "lessthan",
    "morethan",
    "under",
    "notunder",
    "empty",
)

#: Operadores que prometem ordem. Aceitos apenas em coluna de data.
_ORDERING_SEARCHTYPES = ("lessthan", "morethan")

#: Datatypes do GLPI em que a comparacao de ordem foi verificada como real.
#: Confirmado em Ticket.date e Contract.begin_date: desigualdade estrita,
#: insensivel ao formato ("2022-01-03" e "2022-01-03 00:00:00" coincidem).
_DATE_DATATYPES = ("date", "datetime", "date_delay")

VALID_LINKS = ("AND", "OR", "AND NOT", "OR NOT")

MAX_LIMIT = 50
MAX_CRITERIA = 12

# Itemtypes worth suggesting when the caller gets the name wrong. GLPI accepts
# many more; these are the ones this server works with day to day.
COMMON_ITEMTYPES = (
    "Ticket",
    "Problem",
    "Change",
    "Computer",
    "Monitor",
    "Printer",
    "NetworkEquipment",
    "Phone",
    "Peripheral",
    "Software",
    "User",
    "Group",
    "Entity",
    "Location",
    "Supplier",
    "Contract",
    "Project",
    "KnowbaseItem",
    "Document",
)


async def _resolve_criterion(itemtype: str, raw: Dict[str, Any], position: int) -> Dict[str, Any]:
    """Turn one caller-supplied criterion into what the Search API expects.

    The field may arrive as a numeric id or as a name. Names go through the
    live catalogue, so the caller never has to know GLPI's internal numbering —
    which is the whole point of not hardcoding ids elsewhere in this server.
    """
    if not isinstance(raw, dict):
        raise ValidationError(
            f"Criterio {position} invalido: esperado um objeto com field, searchtype e value.",
            "criteria",
        )

    field = raw.get("field")
    if field in (None, ""):
        raise ValidationError(
            f"Criterio {position} sem 'field'. Informe o nome do campo (ex: status) "
            f"ou o ID numerico. Use scope=fields para descobrir os campos disponiveis.",
            "criteria",
        )

    resolved = await search_options_cache.resolve(itemtype, field)
    if resolved is None:
        raise ValidationError(
            f"Campo '{field}' nao existe na busca de {itemtype} nesta instancia do GLPI. "
            f"Use scope=fields para listar os campos disponiveis.",
            "criteria",
        )

    searchtype = str(raw.get("searchtype") or "contains").strip().lower()
    if searchtype not in VALID_SEARCHTYPES:
        raise ValidationError(
            f"Operador '{searchtype}' invalido no criterio {position}. "
            f"Valores aceitos: {', '.join(VALID_SEARCHTYPES)}.",
            "criteria",
        )

    # @MX:ANCHOR: operadores de ordem so passam em coluna de data.
    # @MX:REASON: medido nesta instancia, com verdade de base lida linha a
    # linha antes de comparar. Em coluna de DATA eles funcionam de verdade
    # (desigualdade estrita, insensivel ao formato). Em coluna numerica ou de
    # enum eles COLAPSAM para igualdade: varredura completa de 0 a 7 sobre
    # Ticket.priority, que tem 6 valores distintos e reais, deu
    # morethan(N) == lessthan(N) == equals(N) em TODOS os pontos. Nao e
    # off-by-one nem inclusivo-versus-exclusivo: o "maior/menor" e ignorado.
    # Uma faixa de prioridade devolveria uma fatia exata com cara de intervalo
    # — numero plausivel, silencioso e errado. Recusar custa uma mensagem;
    # aceitar custa um relatorio em que ninguem duvida.
    if searchtype in _ORDERING_SEARCHTYPES:
        datatype = await search_options_cache.datatype_of(itemtype, resolved)
        if datatype is not None and datatype not in _DATE_DATATYPES:
            raise ValidationError(
                f"Criterio {position}: o operador '{searchtype}' nao e uma "
                f"comparacao confiavel no campo '{field}' (tipo '{datatype}') "
                f"desta instalacao do GLPI — ele se comporta como 'equals' e "
                f"devolveria uma fatia exata parecendo um intervalo. "
                f"Use 'equals' para um valor, varios criterios com link OR para "
                f"um conjunto, ou aplique a faixa a uma coluna de data.",
                "criteria",
            )

    criterion: Dict[str, Any] = {
        "field": resolved,
        "searchtype": searchtype,
        "value": raw.get("value", ""),
    }

    link = raw.get("link")
    if link:
        link_upper = str(link).strip().upper()
        if link_upper not in VALID_LINKS:
            raise ValidationError(
                f"Conector '{link}' invalido no criterio {position}. "
                f"Valores aceitos: {', '.join(VALID_LINKS)}.",
                "criteria",
            )
        criterion["link"] = link_upper
    elif position > 0:
        criterion["link"] = "AND"

    return criterion


async def _build_criteria(itemtype: str, criteria: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if not criteria:
        return []
    if not isinstance(criteria, list):
        raise ValidationError(
            "criteria deve ser uma lista de objetos com field, searchtype e value.",
            "criteria",
        )
    if len(criteria) > MAX_CRITERIA:
        raise ValidationError(
            f"Maximo de {MAX_CRITERIA} criterios por consulta; recebidos {len(criteria)}.",
            "criteria",
        )
    return [await _resolve_criterion(itemtype, raw, i) for i, raw in enumerate(criteria)]


def _validate_itemtype(itemtype: Optional[str]) -> str:
    if not itemtype or not str(itemtype).strip():
        raise ValidationError(
            f"itemtype e obrigatorio. Exemplos comuns no GLPI: {', '.join(COMMON_ITEMTYPES[:8])}.",
            "itemtype",
        )
    return str(itemtype).strip()


async def _count(itemtype: str, criteria: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Read only the total, without pulling a single row.

    @MX:NOTE: range=0-0 asks GLPI for an empty window and reads totalcount.
    @MX:REASON: counting by paginating results is both wrong past the page cap
    and needlessly expensive — the caller only wants the number.
    """
    params: Dict[str, Any] = {"range": "0-0"}
    emit_criteria(params, criteria)

    result = await glpi_client.get(
        f"/apirest.php/search/{itemtype}", params=params, use_cache=False
    )
    total = 0
    if isinstance(result, dict):
        total = int(result.get("totalcount", 0) or 0)
    return {"itemtype": itemtype, "total": total, "criteria_count": len(criteria)}


async def search_records(
    itemtype: Optional[str] = None,
    scope: str = "search",
    criteria: Optional[List[Dict[str, Any]]] = None,
    fields: Optional[List[Any]] = None,
    sort_by: Optional[Any] = None,
    order: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
    field_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Free-form query against any GLPI itemtype.

    Args:
        itemtype: GLPI itemtype (Ticket, Computer, User, ...).
        scope: search (rows), count (total only) or fields (discover columns).
        criteria: list of {field, searchtype, value, link}; field by name or id.
        fields: columns to return, by name or id.
        sort_by: column to sort by, by name or id.
        order: asc or desc.
        limit: max rows (capped).
        offset: pagination offset.
        field_filter: substring filter for scope=fields.
    """
    scope = (scope or "search").strip().lower()
    if scope not in VALID_SCOPES:
        raise ValidationError(
            f"scope invalido: '{scope}'. Valores aceitos: {', '.join(VALID_SCOPES)}.",
            "scope",
        )

    itemtype = _validate_itemtype(itemtype)

    # --- scope: fields -> discovery, no search performed
    if scope == "fields":
        catalogue = await search_options_cache.available_fields(itemtype, limit=200)
        if not catalogue:
            raise ValidationError(
                f"Nao foi possivel ler os campos de busca de '{itemtype}' no GLPI. "
                f"Verifique se o itemtype existe (ex: {', '.join(COMMON_ITEMTYPES[:6])}).",
                "itemtype",
            )
        if field_filter:
            needle = str(field_filter).strip().lower()
            catalogue = {k: v for k, v in catalogue.items() if needle in k.lower()}
        return {
            "itemtype": itemtype,
            "fields": catalogue,
            "total": len(catalogue),
            "scope": "fields",
            # @MX:WARN: este escopo NAO pagina, e precisa dizer isso.
            # @MX:REASON: `limit` e validado contra o maximo do schema e depois
            # ignorado aqui, e `offset` nunca chega a ser lido -- passar
            # offset=50 devolvia a mesma lista completa, sem erro e sem aviso.
            # Um parametro que parece funcionar e nao faz nada e pior que um
            # parametro ausente: quem pagina conclui que viu tudo em duas
            # paginas, ou que um campo nao existe porque "ficou na pagina 2".
            # O catalogo volta inteiro por definicao.
            "paging_applies": False,
        }

    resolved_criteria = await _build_criteria(itemtype, criteria)

    # --- scope: count -> cheap probe
    if scope == "count":
        return {**await _count(itemtype, resolved_criteria), "scope": "count"}

    # --- scope: search
    limit = max(1, min(int(limit or 10), MAX_LIMIT))
    offset = max(0, int(offset or 0))

    forcedisplay: List[int] = []
    for raw_field in fields or []:
        resolved = await search_options_cache.resolve(itemtype, raw_field)
        if resolved is None:
            logger.warning(
                f"search_records: campo '{raw_field}' ignorado em {itemtype} (nao encontrado)"
            )
            continue
        forcedisplay.append(resolved)

    sort_field = None
    if sort_by is not None:
        sort_field = await search_options_cache.resolve(itemtype, sort_by)
        if sort_field is None:
            logger.warning(
                f"search_records: ordenacao por '{sort_by}' ignorada em {itemtype}"
            )

    result = await glpi_client.search(
        item_type=itemtype,
        criteria=resolved_criteria,
        forcedisplay=forcedisplay or None,
        range_limit=limit,
        range_offset=offset,
        sort=sort_field,
        order=normalize_order(order) if (order or sort_field) else None,
        expand_dropdowns=True,
    )

    rows = result.get("data", []) if isinstance(result, dict) else (result or [])
    total = result.get("totalcount") if isinstance(result, dict) else None

    # @MX:ANCHOR: never hand raw GLPI search-option ids to the caller as column
    # headers.
    # @MX:REASON: /search/{itemtype} keys every row by field id, so the table
    # went out as `| 2 | 1 | 12 | 19 | 4 |` with `1` under status and `228` under
    # requester. A model cannot tell field 12 from field 2 and will label the
    # columns by guessing. The catalogue that resolves names on the way IN is the
    # same one that names them on the way OUT.
    column_labels: Dict[str, str] = {}
    column_columns: Dict[str, str] = {}
    catalogue = await search_options_cache.get_catalogue(itemtype)
    if catalogue:
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in row:
                skey = str(key)
                if skey in column_labels:
                    continue
                option = catalogue.by_id.get(int(key)) if str(key).isdigit() else None
                if option:
                    column_labels[skey] = option.name
                    if option.field:
                        column_columns[skey] = str(option.field).lower()

    return {
        "itemtype": itemtype,
        "scope": "search",
        "rows": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
        "column_labels": column_labels,
        "column_columns": column_columns,
    }


def format_search_records(data: Any, args: Dict[str, Any]) -> str:
    """Render the three scopes as Markdown."""
    if not isinstance(data, dict):
        return "Nenhum resultado encontrado."

    itemtype = data.get("itemtype", "?")
    scope = data.get("scope")

    if scope == "count":
        total = data.get("total", 0)
        return (
            f"**{total}** registro(s) de `{itemtype}` no GLPI"
            f"{' com os criterios informados' if data.get('criteria_count') else ' no total'}."
        )

    if scope == "fields":
        fields = data.get("fields") or {}
        if not fields:
            return f"Nenhum campo encontrado para `{itemtype}`."
        rows = "\n".join(
            f"| {name} | {fid} |" for name, fid in sorted(fields.items(), key=lambda kv: kv[1])
        )
        filtered = " (filtrado)" if data.get("field_filter") else ""
        return (
            f"**{len(fields)} campo(s)** de busca em `{itemtype}`{filtered}\n\n"
            f"_Catalogo completo — `limit` e `offset` nao se aplicam a este "
            f"escopo._\n\n"
            f"| Campo | ID |\n|---|---|\n{rows}"
        )

    rows = data.get("rows") or []
    if not rows:
        return f"Nenhum registro de `{itemtype}` encontrado com os criterios informados."

    columns: List[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    columns = columns[:10]

    labels = data.get("column_labels") or {}
    col_names = data.get("column_columns") or {}
    is_itil = str(itemtype) in _ITIL_ITEMTYPES

    def _head(col: Any) -> str:
        label = labels.get(str(col))
        return f"{label} (#{col})" if label else f"#{col}"

    def _cell(col: Any, row: Dict[str, Any]) -> str:
        value = row.get(col, "")
        decoder = _ENUM_DECODERS.get(col_names.get(str(col), "")) if is_itil else None
        if decoder is not None and str(value).strip().isdigit():
            return truncate_field(decoder(int(value)), 120)
        return truncate_field(str(value), 120)

    header = page_info(len(rows), data.get("limit", 10), data.get("offset", 0), data.get("total"))
    head = "| " + " | ".join(_head(c) for c in columns) + " |"
    sep = "|" + "---|" * len(columns)
    body = "\n".join(
        "| " + " | ".join(_cell(c, row) for c in columns) + " |" for row in rows
    )
    return f"{header}\n\n{head}\n{sep}\n{body}"
