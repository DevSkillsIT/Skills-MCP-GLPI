"""
Serviço de gerenciamento de tickets GLPI - Integração Real
"""

import asyncio
import base64
import binascii
import json
import mimetypes
import re
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from src.services.glpi_client import glpi_client
from src.services.dropdown_cache import dropdown_cache
from src.services.search_options import search_options_cache
from src.utils.search_criteria import (
    actor_criterion as _actor_criterion,
    as_field_id,
    normalize_order,
    resolve_sort_field,
)
from src.services.similarity_service import similarity_service
from src.formatters.markdown_helpers import strip_html
from src.models.exceptions import (
    GLPIError, 
    NotFoundError, 
    ValidationError
)
from src.utils.helpers import logger
from src.utils.text_search import describe_stage, run_text_search


# GLPI ticket status string -> internal integer code.
# Used for both list filters (Search API field 12) and update PUT payloads.
STATUS_MAP = {
    "new": 1,
    "assigned": 2,
    "planned": 3,
    "pending": 4,
    "solved": 5,
    "closed": 6,
}

# Caller-facing update field -> GLPI ticket column. Declared as data so an
# unsupported field can be refused instead of silently dropped (see
# TicketService.update_ticket). "status" is handled apart because its value is
# translated through STATUS_MAP.
_UPDATE_FIELDS = {
    "title": "name",
    "description": "content",
    "priority": "priority",
    "urgency": "urgency",
    "impact": "impact",
    "assignee_id": "users_id_assign",
    "category_id": "itilcategories_id",
    "location_id": "locations_id",
    "entity_id": "entities_id",
}

# ---------------------------------------------------------------------------
# ITIL coverage constants (tasks, validations, actors, links, documents)
# ---------------------------------------------------------------------------

# CommonITILActor role codes. In GLPI the role of an actor travels in the
# `type` column of the link table (Ticket_User, Group_Ticket) — the endpoint
# only says WHICH kind of actor (user or group) is being linked.
#
# @MX:WARN: ASSIGNED is 2 and OBSERVER is 3, not the other way round.
# @MX:REASON: confirmed three ways against this deployment, because getting it
# backwards silently files an assignment as a watcher: the ticket ETL query in
# knowledge_base/extract_tickets.sql, written against the live database, reads
# tecnicos from tickets_users.type=2, observadores from type=3 and
# grupos_atribuidos from groups_tickets.type=2; assign_ticket() below has been
# assigning technicians with type=2 in production; and search option 8
# ("grupo atribuido") joins on the same ASSIGN constant it uses.
ACTOR_TYPE = {"requester": 1, "assigned": 2, "observer": 3}

# CommonITILValidation status codes. Kept in sync with the labels rendered by
# the formatter; changing one side without the other flips "aprovado" and
# "recusado" in the UI, which is worse than showing a raw code.
VALIDATION_STATUS = {"waiting": 2, "refused": 3, "accepted": 4}

# Answers accepted from the caller for answer_validation (pt-BR and English).
# A model asked to "aprovar" should not have to know that accepted == 4.
_VALIDATION_ANSWERS = {
    "accept": 4, "accepted": 4, "approve": 4, "approved": 4, "ok": 4,
    "aceita": 4, "aceito": 4, "aprovada": 4, "aprovado": 4, "aprovar": 4,
    "deny": 3, "denied": 3, "refuse": 3, "refused": 3, "reject": 3,
    "rejected": 3, "negado": 3, "recusada": 3, "recusado": 3, "recusar": 3,
    "reprovada": 3, "reprovado": 3,
}

# Ticket_Ticket link codes and the friendly names accepted for them.
_LINK_TYPES = {
    "1": 1, "link": 1, "linked": 1, "relacionado": 1, "simples": 1, "vinculo": 1,
    "2": 2, "duplicate": 2, "duplicada": 2, "duplicado": 2, "duplicidade": 2,
    "3": 3, "child": 3, "filho": 3, "son": 3, "son_of": 3,
    "4": 4, "pai": 4, "parent": 4, "parent_of": 4,
}

# Sub-item itemtypes that make up the unified timeline. Each entry lists the
# candidate itemtypes in preference order: GLPI renamed TicketFollowup to
# ITILFollowup, and instances still answer on the old path in some setups.
_TIMELINE_SOURCES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("followup", ("ITILFollowup", "TicketFollowup")),
    ("task", ("TicketTask",)),
    ("solution", ("ITILSolution",)),
    ("validation", ("TicketValidation",)),
)

# Upload ceiling for add_document. GLPI has its own limit, but reading an
# arbitrarily large file into memory before we ever reach the network is the
# failure we can actually prevent here.
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# GLPI Search API field IDs for Ticket (core search options, stable across
# GLPI 9/10/11 — defined in CommonITILObject::rawSearchOptions + Ticket).
# Ref: https://glpi-developer-documentation.readthedocs.io (search options)
# These ids return RENDERED display values (e.g. requester NAME, category by
# extenso) directly from /search/Ticket — no N+1 lookups required.
TICKET_FIELD = {
    "name": 1,            # titulo
    "id": 2,
    "priority": 3,
    "requester": 4,       # solicitante(s) — nome renderizado
    "tech_assign": 5,     # tecnico(s) atribuido(s) — nome renderizado
    "category": 7,        # itilcategories_id — nome completo
    "group_assign": 8,    # grupo tecnico atribuido
    "request_source": 9,  # origem da requisicao
    "urgency": 10,
    "impact": 11,
    "status": 12,
    "type": 14,
    "date": 15,           # abertura
    "closedate": 16,      # fechamento
    "solvedate": 17,      # solucao
    "date_mod": 19,       # ultima atualizacao
    "content": 21,        # descricao
    "entities_id": 80,
    "time_to_resolve": 82,  # prazo SLA de resolucao
}

# Campos exibidos na listagem rica. Inclui um superset util: a Search API
# devolve tudo numa unica chamada, entao o custo extra e desprezivel perto do
# ganho de visao (atores/categoria/SLA resolvidos, sem N+1).
TICKET_FORCEDISPLAY = [
    TICKET_FIELD["name"],
    TICKET_FIELD["id"],
    TICKET_FIELD["priority"],
    TICKET_FIELD["requester"],
    TICKET_FIELD["tech_assign"],
    TICKET_FIELD["category"],
    TICKET_FIELD["group_assign"],
    TICKET_FIELD["urgency"],
    TICKET_FIELD["impact"],
    TICKET_FIELD["status"],
    TICKET_FIELD["type"],
    TICKET_FIELD["date"],
    TICKET_FIELD["solvedate"],
    TICKET_FIELD["date_mod"],
    TICKET_FIELD["entities_id"],
    # Campo 82 na Search API NAO e o prazo de SLA — e a FLAG "atrasado" (1 quando
    # o TTR foi estourado, vazio caso contrario). Usamos como indicador na lista.
    # O prazo (datetime) confiavel vem no detalhe via campo nomeado
    # 'time_to_resolve' do GET direto /Ticket/{id}.
    TICKET_FIELD["time_to_resolve"],  # = 82, interpretado como sla_late flag
    # Descricao (campo 21) JA na listagem: o usuario quer o teor do chamado sem
    # abrir um a um. Vira 'desc_snippet' (texto puro) no normalizer.
    TICKET_FIELD["content"],
]


# Status codes that still count as open: 1 new, 2 assigned, 3 planned,
# 4 pending. 5 solved and 6 closed are not.
#
# @MX:WARN: NAO usar lessthan/morethan sobre status. Enumere os codigos.
# @MX:REASON: status e um campo "specific" no GLPI e os operadores de ordem
# nao se comportam como comparacao: medido na instancia real, "lessthan N"
# devolve exatamente os registros com status N — ou seja, age como igualdade.
# Uma versao anterior deste codigo concluiu que o operador era "menor ou
# igual", porque a amostra que ela observou era compativel com as duas
# hipoteses; a contagem por status desmentiu isso (lessthan 5 devolveu os 14
# solucionados, lessthan 6 devolveu os 9270 fechados). Com o limite em 4, a
# busca por chamados em aberto escondia os novos, atribuidos e planejados —
# respondia 3 onde havia 7, sem qualquer aviso. Enumerar e a unica forma
# correta, e vai como grupo aninhado para que filtros posteriores continuem
# restringindo.
_OPEN_STATUS_CODES = (1, 2, 3, 4)

#: Preposicoes de sobrenome pt-BR. Nao identificam ninguem e, usadas como
#: token de busca, casam com metade da base.
_NAME_STOPWORDS = frozenset({"da", "de", "do", "das", "dos", "dr", "sr", "sra"})

#: Teto do grupo OR gerado por um filtro de pessoa. Um nome muito generico
#: ("Silva") pode casar dezenas de usuarios; a URL da Search API tem limite.
_MAX_PERSON_FILTER_MATCHES = 25

# Keys of TICKET_FIELD that map to a column on glpi_tickets itself. Only these
# can be re-derived from the live catalogue without ambiguity — the remaining
# entries (requester, assigned tech/group, category, source, SLA flag) arrive
# through joins and are merely checked for existence.
_TICKET_UID_HINTS = {
    "name": "Ticket.name",
    "id": "Ticket.id",
    "priority": "Ticket.priority",
    "urgency": "Ticket.urgency",
    "impact": "Ticket.impact",
    "status": "Ticket.status",
    "type": "Ticket.type",
    "date": "Ticket.date",
    "closedate": "Ticket.closedate",
    "solvedate": "Ticket.solvedate",
    "date_mod": "Ticket.date_mod",
    "content": "Ticket.content",
}

# Guards the lazy reconciliation so concurrent searches trigger a single pass.
_field_sync_lock = asyncio.Lock()
_field_sync_done = False


async def _ensure_field_map_synced() -> None:
    """Reconcile TICKET_FIELD with this instance's catalogue, once per process.

    @MX:NOTE: deliberately best-effort and non-blocking on failure.
    @MX:REASON: the static map is what production runs on today and is known to
    work. Reconciliation is a safety net against version/plugin drift across
    the instances we serve, so it must never be able to break a search that
    would otherwise succeed.
    """
    global _field_sync_done
    if _field_sync_done:
        return

    async with _field_sync_lock:
        if _field_sync_done:
            return
        try:
            await search_options_cache.reconcile(
                "Ticket", TICKET_FIELD, _TICKET_UID_HINTS
            )
        except Exception as exc:  # noqa: BLE001 — never block a search
            logger.warning(f"Ticket field reconciliation skipped: {exc}")
        finally:
            _field_sync_done = True


def _build_ticket_criteria(kwargs: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build the criteria shared by listing and text search.

    @MX:ANCHOR: single source of truth for ticket filters.
    @MX:REASON: listing and text search used to build criteria independently,
    and the text-search path only ever handled the query and the entity. Every
    other filter the caller passed was accepted, validated and then dropped, so
    "open tickets mentioning printer" silently returned tickets in any status.
    Both paths now build filters here, which makes that divergence impossible.
    """
    criteria: List[Dict[str, Any]] = []

    status = kwargs.get("status")
    if status:
        # Accept both string ("pending") and int code; Search API needs int.
        status_code = STATUS_MAP.get(status, status) if isinstance(status, str) else status
        criteria.append({"field": TICKET_FIELD["status"], "searchtype": "equals", "value": status_code})
    elif kwargs.get("open_only"):
        # Only when no explicit status was given — an explicit status is the
        # more specific instruction and must win.
        #
        # The open statuses go as a nested OR group so any filter added after
        # this one still narrows the result instead of being absorbed by the
        # OR chain.
        criteria.append({
            "criteria": [
                {
                    "field": TICKET_FIELD["status"],
                    "searchtype": "equals",
                    "value": code,
                    **({"link": "OR"} if position else {}),
                }
                for position, code in enumerate(_OPEN_STATUS_CODES)
            ]
        })

    priority = kwargs.get("priority")
    if priority:
        criteria.append({"field": TICKET_FIELD["priority"], "searchtype": "equals", "value": priority})

    urgency = kwargs.get("urgency")
    if urgency:
        criteria.append({"field": TICKET_FIELD["urgency"], "searchtype": "equals", "value": urgency})

    # @MX:NOTE: pessoas (solicitante/tecnico) NAO entram aqui.
    # @MX:REASON: o nome que a listagem EXIBE ("Azeredo Da Silva Guimaraes
    # Erica") nao e o texto que a Search API PROCURA no campo 4/5 — la o valor
    # comparado e o login (`ericaguimaraes`). Um `contains` com o nome completo
    # nunca casa, e o filtro devolvia zero chamados sem erro nenhum. Resolver
    # pessoa exige consultar /User, o que e async; feito em
    # TicketService._expand_person_filters depois desta montagem.
    for param, field in (
        ("assigned_group", TICKET_FIELD["group_assign"]),
        ("category", TICKET_FIELD["category"]),
    ):
        value = kwargs.get(param)
        if value not in (None, ""):
            criteria.append(_actor_criterion(field, value))

    entity_id = kwargs.get("entity_id")
    if entity_id is not None:
        criteria.append({"field": TICKET_FIELD["entities_id"], "searchtype": "under", "value": entity_id})

    date_after = kwargs.get("date_created_after")
    if date_after:
        criteria.append({"field": TICKET_FIELD["date"], "searchtype": "morethan", "value": date_after})
    date_before = kwargs.get("date_created_before")
    if date_before:
        criteria.append({"field": TICKET_FIELD["date"], "searchtype": "lessthan", "value": date_before})

    return criteria


def _resolve_sort(kwargs: Dict[str, Any]) -> tuple:
    """Resolve sort_by/order into the (field_id, direction) the API expects.

    Defaults to most recently updated first, which is the behaviour callers
    relied on before sorting became configurable.
    """
    sort_field = resolve_sort_field(
        kwargs.get("sort_by"),
        TICKET_FIELD,
        TICKET_FIELD["date_mod"],
        context="list_tickets",
    )
    return sort_field, normalize_order(kwargs.get("order"))


def _actor_ids(value: Any) -> List[int]:
    """Extrai IDs numericos de um campo de ator da Search API (escalar ou lista
    de strings/ints). Ignora vazios/nao-numericos."""
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple)) else [value]
    out: List[int] = []
    for x in items:
        s = str(x).strip()
        if s.isdigit():
            out.append(int(s))
    return out


def _pick(row: Dict[str, Any], field_id: int, named_key: str) -> Any:
    """Read a value from a Search row by numeric field id, falling back to the
    named key (getAllItems shape). Returns None when absent so callers can drop
    empty fields."""
    val = row.get(str(field_id))
    if val is None or val == "":
        val = row.get(named_key)
    # GLPI search devolve '' para atores/categoria vazios; normaliza p/ None.
    if val == "" or val == 0 or val == "0":
        return None if named_key in ("requester", "tech_assign", "category", "group_assign") else val
    return val


def _normalize_search_ticket(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map a GLPI Search API ticket row (numeric field keys) to named keys.

    The Search API returns ``{"1": "...", "12": 2, ...}`` while the getAllItems
    endpoint returns ``{"name": "...", "status": 2, ...}``. Normalizing here lets
    the same formatters handle both code paths and exposes the FULL field set
    (solicitante, tecnico, categoria, urgencia, impacto, SLA) to the formatter.
    """
    f = TICKET_FIELD
    normalized = {
        "id": _pick(row, f["id"], "id"),
        "name": _pick(row, f["name"], "name"),
        "status": _pick(row, f["status"], "status"),
        "priority": _pick(row, f["priority"], "priority"),
        "urgency": _pick(row, f["urgency"], "urgency"),
        "impact": _pick(row, f["impact"], "impact"),
        "type": _pick(row, f["type"], "type"),
        "requester": _pick(row, f["requester"], "requester"),
        "tech_assign": _pick(row, f["tech_assign"], "tech_assign"),
        "group_assign": _pick(row, f["group_assign"], "group_assign"),
        "category": _pick(row, f["category"], "category"),
        "date": _pick(row, f["date"], "date"),
        "date_mod": _pick(row, f["date_mod"], "date_mod"),
        "solvedate": _pick(row, f["solvedate"], "solvedate"),
        # Campo 82 = flag de atraso (1 = TTR estourado). Vira "sla_late".
        "sla_late": _pick(row, f["time_to_resolve"], "sla_late"),
        "entities_id": _pick(row, f["entities_id"], "entities_id"),
        # content (HTML cru) p/ similaridade; removido na exibicao da lista.
        "content": row.get(str(f["content"])) or row.get("content"),
    }
    # desc_snippet: texto puro da descricao p/ exibir NA LISTAGEM (chave propria,
    # nao e removida por remove_heavy_fields). Limita p/ nao inflar o JSON.
    raw_content = row.get(str(f["content"])) or row.get("content")
    if raw_content:
        snippet = strip_html(str(raw_content)).strip()
        if snippet:
            normalized["desc_snippet"] = snippet[:400]
    return {k: v for k, v in normalized.items() if v is not None}


def _as_item_list(response: Any) -> List[Dict[str, Any]]:
    """Normalise a GLPI sub-item response into a list of dicts.

    The sub-item endpoints answer with a bare list while /search answers with a
    {"data": [...]} envelope. Callers should not have to know which one they
    got, and a scalar/None answer must degrade to an empty list rather than
    raising halfway through a merge.
    """
    if isinstance(response, list):
        return [item for item in response if isinstance(item, dict)]
    if isinstance(response, dict):
        data = response.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    return []


def _first_id(value: Any) -> Optional[int]:
    """First numeric id from a GLPI actor field (scalar or list)."""
    ids = _actor_ids(value)
    return ids[0] if ids else None


def _is_flag(value: Any) -> bool:
    """GLPI booleans travel as 0/1, "0"/"1" or true/false depending on path."""
    return str(value).strip().lower() in ("1", "true", "yes")


def _timeline_followup(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "kind": "followup",
        "id": item.get("id"),
        "date": item.get("date") or item.get("date_creation"),
        "author_id": _first_id(item.get("users_id")),
        "content": item.get("content", "") or "",
        "is_private": _is_flag(item.get("is_private")),
    }


def _timeline_task(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "kind": "task",
        "id": item.get("id"),
        "date": item.get("date") or item.get("date_creation"),
        "author_id": _first_id(item.get("users_id")),
        "assignee_id": _first_id(item.get("users_id_tech")),
        "content": item.get("content", "") or "",
        "is_private": _is_flag(item.get("is_private")),
        "actiontime": item.get("actiontime"),
        "state": item.get("state"),
    }


def _timeline_solution(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "kind": "solution",
        "id": item.get("id"),
        "date": item.get("date_creation") or item.get("date") or item.get("date_mod"),
        "author_id": _first_id(item.get("users_id")),
        "content": item.get("content", "") or "",
        "solution_status": item.get("status"),
        "is_private": False,
    }


def _timeline_validation(item: Dict[str, Any]) -> Dict[str, Any]:
    # @MX:NOTE: the approval target is read from both the legacy column and the
    # polymorphic pair.
    # @MX:REASON: GLPI moved the validation target from users_id_validate to
    # itemtype_target/items_id_target so a GROUP can approve. Reading only one
    # of them renders "Aprovador: —" on half of the instances we serve.
    target_type = str(item.get("itemtype_target") or "User")
    target = item.get("users_id_validate")
    if target in (None, "", 0, "0"):
        target = item.get("items_id_target")
    else:
        target_type = "User"
    return {
        "kind": "validation",
        "id": item.get("id"),
        "date": item.get("submission_date") or item.get("date_creation") or item.get("date_mod"),
        "author_id": _first_id(item.get("users_id")),
        "approver_id": _first_id(target),
        "approver_type": target_type if target_type in ("User", "Group") else "User",
        "content": item.get("comment_submission", "") or "",
        "answer": item.get("comment_validation", "") or "",
        "validation_status": item.get("status"),
        "validation_date": item.get("validation_date"),
        "is_private": False,
    }


_TIMELINE_BUILDERS = {
    "followup": _timeline_followup,
    "task": _timeline_task,
    "solution": _timeline_solution,
    "validation": _timeline_validation,
}


def _timeline_sort_key(entry: Dict[str, Any]) -> Tuple[int, str]:
    """Chronological order, undated entries last.

    GLPI datetimes are 'YYYY-MM-DD HH:MM:SS', so lexicographic order is already
    chronological — parsing them would only add a failure mode.
    """
    date = entry.get("date")
    return (1, "") if not date else (0, str(date))


def _resolve_link_type(value: Any) -> int:
    """Translate a friendly link name (or code) into the Ticket_Ticket code."""
    if value is None:
        return 1
    if isinstance(value, bool):
        raise ValidationError("link_type invalido", "link_type")
    key = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    code = _LINK_TYPES.get(key)
    if code is None:
        raise ValidationError(
            "link_type invalido: use 'link' (1), 'duplicate' (2), "
            "'son' (3, este chamado e filho do outro) ou 'parent' (4)",
            "link_type",
        )
    return code


def _resolve_validation_answer(value: Any) -> int:
    """Translate an approval answer into a CommonITILValidation status code."""
    if value is None:
        raise ValidationError("status e obrigatorio (aprovado ou recusado)", "status")
    coerced = as_field_id(value)
    if coerced is not None:
        if coerced in (VALIDATION_STATUS["accepted"], VALIDATION_STATUS["refused"]):
            return coerced
        raise ValidationError(
            f"status de aprovacao invalido: {coerced}. "
            f"Use {VALIDATION_STATUS['accepted']} (aprovado) ou "
            f"{VALIDATION_STATUS['refused']} (recusado)",
            "status",
        )
    code = _VALIDATION_ANSWERS.get(str(value).strip().lower())
    if code is None:
        raise ValidationError(
            "status de aprovacao invalido: use 'aprovado' ou 'recusado'", "status"
        )
    return code


def _guess_mime_type(file_name: str) -> str:
    """Derive the MIME type from the file extension.

    GLPI validates the declared type against its allowed-document-types table,
    so sending application/octet-stream for everything gets uploads rejected on
    stricter instances.
    """
    guessed, _ = mimetypes.guess_type(file_name)
    return guessed or "application/octet-stream"


def _encode_multipart(
    fields: Dict[str, str],
    file_field: str,
    file_name: str,
    file_bytes: bytes,
    mime_type: str,
) -> Tuple[bytes, str]:
    """Encode a multipart/form-data body, returning (body, content_type).

    @MX:NOTE: the body is built here instead of being delegated to httpx.
    @MX:REASON: the shared session client declares Content-Type:
    application/json for every request it makes. httpx only fills in the
    multipart boundary header when no Content-Type is present, so the upload
    would travel labelled as JSON and GLPI would populate neither $_POST (the
    manifest) nor $_FILES (the file). Encoding here lets us set the header
    explicitly and keeps the wire format under test.
    """
    boundary = uuid.uuid4().hex
    marker = f"--{boundary}".encode("utf-8")
    crlf = b"\r\n"
    parts: List[bytes] = []

    for name, value in fields.items():
        parts.append(marker + crlf)
        parts.append(
            f'Content-Disposition: form-data; name="{name}"'.encode("utf-8") + crlf
        )
        parts.append(b"Content-Type: application/json" + crlf)
        parts.append(crlf)
        parts.append(str(value).encode("utf-8") + crlf)

    safe_name = file_name.replace('"', "")
    parts.append(marker + crlf)
    parts.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{safe_name}"'.encode(
            "utf-8"
        )
        + crlf
    )
    parts.append(f"Content-Type: {mime_type}".encode("utf-8") + crlf)
    parts.append(crlf)
    parts.append(file_bytes + crlf)
    parts.append(marker + b"--" + crlf)

    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class TicketService:
    """Serviço de gerenciamento de tickets GLPI - Integração Real."""

    def __init__(self):
        """Inicializa o serviço de tickets."""
        logger.info("TicketService initialized")

    async def _resolve_actor_names(
        self, rows: List[Dict[str, Any]], resolve_groups: bool = True
    ) -> None:
        """Substitui IDs de ator (solicitante/tecnico/grupo) por NOMES.

        A Search API devolve as meta-colunas de ator (campos 4/5/8) como IDs
        crus — e nao as expande nem com expand_dropdowns. Resolvemos via
        dropdown_cache (cacheado + concorrente), coletando todos os IDs da
        pagina de uma vez para minimizar chamadas. Mutaciona os dicts in place.

        resolve_groups=False na LISTAGEM (que nao exibe grupo) evita um
        get_many_names("Group") desperdiçado; o DETALHE usa True.
        """
        user_ids: set = set()
        group_ids: set = set()
        for r in rows:
            user_ids.update(_actor_ids(r.get("requester")))
            user_ids.update(_actor_ids(r.get("tech_assign")))
            if resolve_groups:
                group_ids.update(_actor_ids(r.get("group_assign")))
        if not user_ids and not group_ids:
            return

        user_names = await dropdown_cache.get_many_names("User", list(user_ids)) if user_ids else {}
        group_names = await dropdown_cache.get_many_names("Group", list(group_ids)) if group_ids else {}

        def _map(value: Any, names: Dict[int, Any]) -> Any:
            ids = _actor_ids(value)
            if not ids:
                return value
            resolved = [names.get(i) or str(i) for i in ids]
            return resolved if len(resolved) > 1 else resolved[0]

        for r in rows:
            if "requester" in r:
                r["requester"] = _map(r["requester"], user_names)
            if "tech_assign" in r:
                r["tech_assign"] = _map(r["tech_assign"], user_names)
            if resolve_groups and "group_assign" in r:
                r["group_assign"] = _map(r["group_assign"], group_names)

    async def list_tickets(self, **kwargs) -> List[Dict[str, Any]]:
        """Lista tickets com filtros.

        Quando há filtros (status/priority/entity/date), usa a Search API
        (/apirest.php/search/Ticket), que é o único endpoint que processa
        ``criteria[]``. Sem filtros, usa o endpoint getAllItems (mais leve),
        que já retorna campos nomeados.

        @MX:ANCHOR: list_tickets é a base de search_tickets e find_similar.
        @MX:REASON: O endpoint getAllItems IGNORA criteria[] — usar /search.
        """
        limit = max(int(kwargs.get("limit", 50)), 1)
        offset = max(int(kwargs.get("offset", 0)), 0)

        # Reconcile the static field map with this instance before using it.
        await _ensure_field_map_synced()

        # Build advanced criteria for the Search API
        criteria = await self._expand_person_filters(_build_ticket_criteria(kwargs), kwargs)
        entity_id = kwargs.get("entity_id")

        # @MX:NOTE: SEMPRE via /search/Ticket — mesmo sem filtro (criteria=[]).
        # O endpoint getAllItems devolve IDs crus (solicitante/categoria como
        # numero); a Search API + expand_dropdowns devolve NOMES ja renderizados
        # numa unica chamada. Sem criterio, /search retorna todos os visiveis.
        # @MX:REASON: retornos "podados" — atores/categoria/SLA agora expostos.

        # find_similar precisa do conteudo p/ calcular similaridade; a listagem
        # comum NAO pede content (campo pesado, removido depois de qualquer jeito).
        forcedisplay = list(TICKET_FORCEDISPLAY)
        if kwargs.get("_with_content"):
            forcedisplay.append(TICKET_FIELD["content"])

        sort_field, order = _resolve_sort(kwargs)

        result = await glpi_client.search(
            item_type="Ticket",
            criteria=criteria,
            forcedisplay=forcedisplay,
            range_limit=limit,
            range_offset=offset,
            is_recursive=entity_id is not None,
            sort=sort_field,
            order=order,
            expand_dropdowns=True,
        )
        rows = result.get("data", []) if isinstance(result, dict) else (result or [])
        normalized = [_normalize_search_ticket(r) for r in rows]
        # @MX:NOTE: resolve_groups=True — the group column is filterable now, so
        # it must render a name; otherwise the user filters by group and sees a
        # raw id back.
        await self._resolve_actor_names(normalized, resolve_groups=True)
        return normalized
    
    async def get_ticket(self, ticket_id: int) -> Dict[str, Any]:
        """Obtém um ticket específico.

        @MX:NOTE: use_cache=False — detalhe de ticket precisa refletir escritas
        recentes (update/resolve/assign). Com cache, retornava estado obsoleto.
        """
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        result = await glpi_client.get(
            f"/apirest.php/Ticket/{ticket_id}", use_cache=False
        )
        if not isinstance(result, dict) or "id" not in result:
            raise NotFoundError("Ticket", ticket_id)
        return result
    
    async def get_ticket_detail(self, ticket_id: int) -> Dict[str, Any]:
        """Detalhe MAXIMO do ticket para a acao 'get'.

        Combina 3 fontes (atores e anexos = 1-2 chamadas extras, conforme
        escolhido pelo usuario):
          1. GET /Ticket/{id}?expand_dropdowns=1 -> entidade, categoria, origem,
             localizacao, SLA e 'registrado por' resolvidos por NOME (nao ID).
          2. /search/Ticket (campos 4/5/8) -> solicitante, tecnico e grupo
             atribuidos, ja renderizados, numa unica chamada.
          3. /Ticket/{id}/Document_Item -> contagem de anexos.

        @MX:NOTE: get_ticket() permanece enxuto (sem enriquecimento) para os
        fluxos de mutacao que so precisam do estado cru.
        @MX:REASON: detalhe vinha "podado" — IDs crus e sem atores/anexos/SLA.
        """
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")

        ticket = await glpi_client.get(
            f"/apirest.php/Ticket/{ticket_id}",
            params={"expand_dropdowns": 1},
            use_cache=False,
        )
        if not isinstance(ticket, dict) or "id" not in ticket:
            raise NotFoundError("Ticket", ticket_id)

        # --- Atores resolvidos (1 chamada /search) ---
        try:
            actor_result = await glpi_client.search(
                item_type="Ticket",
                criteria=[{"field": TICKET_FIELD["id"], "searchtype": "equals", "value": ticket_id}],
                forcedisplay=[
                    TICKET_FIELD["id"],
                    TICKET_FIELD["requester"],
                    TICKET_FIELD["tech_assign"],
                    TICKET_FIELD["group_assign"],
                    TICKET_FIELD["request_source"],
                ],
                range_limit=1,
                is_recursive=True,
                expand_dropdowns=True,
            )
            rows = actor_result.get("data", []) if isinstance(actor_result, dict) else (actor_result or [])
            if rows:
                r = rows[0]
                # Os campos 4/5/8 voltam como IDs de usuario/grupo — resolve p/ nome.
                holder = {
                    "requester": r.get(str(TICKET_FIELD["requester"])),
                    "tech_assign": r.get(str(TICKET_FIELD["tech_assign"])),
                    "group_assign": r.get(str(TICKET_FIELD["group_assign"])),
                }
                await self._resolve_actor_names([holder])
                ticket["requester_names"] = holder.get("requester") or None
                ticket["assign_tech_names"] = holder.get("tech_assign") or None
                ticket["assign_group_names"] = holder.get("group_assign") or None
                src = r.get(str(TICKET_FIELD["request_source"]))
                if src:
                    ticket.setdefault("request_source_name", src)
        except Exception as e:  # noqa: BLE001 — enriquecimento e best-effort
            logger.warning(f"get_ticket_detail: actor enrichment failed for {ticket_id}: {e}")

        # --- Ativos vinculados ao chamado ---
        #
        # @MX:ANCHOR: o chamado diz de qual equipamento ele fala.
        # @MX:REASON: medido nesta instancia, 18.580 vinculos Item_Ticket para
        # 9.292 chamados — dois por chamado em media, e nenhum aparecia em
        # lugar nenhum do MCP. "De qual maquina e esse chamado?" e a primeira
        # pergunta de quem vai atender, e a resposta ja estava cadastrada.
        try:
            linked = await glpi_client.get_subitems(
                "Ticket", ticket_id, "Item_Ticket",
                params={"expand_dropdowns": "true"},
            )
            rows = linked if isinstance(linked, list) else (
                linked.get("data", []) if isinstance(linked, dict) else []
            )
            items = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                items.append(
                    {
                        "itemtype": row.get("itemtype"),
                        "name": row.get("items_id"),
                        "id": row.get("items_id"),
                    }
                )
            if items:
                ticket["linked_items"] = items
        except Exception as e:  # noqa: BLE001 — enriquecimento e best-effort
            logger.warning(
                f"get_ticket_detail: linked items failed for {ticket_id}: {e}"
            )

        # --- Contagem de anexos: direto no Ticket + nos followups ---
        # @MX:NOTE: no GLPI o anexo costuma ser ligado ao FOLLOWUP (ITILFollowup),
        # nao ao Ticket — por isso contar so /Ticket/{id}/Document_Item dava 0
        # mesmo havendo anexo. Somamos os dois niveis.
        def _count_docs(resp: Any) -> int:
            items = resp if isinstance(resp, list) else (
                resp.get("data", []) if isinstance(resp, dict) else []
            )
            return len(items)

        attach_ticket = None
        attach_followups = 0
        try:
            docs = await glpi_client.get_subitems("Ticket", ticket_id, "Document_Item")
            attach_ticket = _count_docs(docs)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"get_ticket_detail: ticket attachment count failed for {ticket_id}: {e}")

        try:
            fups = await glpi_client.get_subitems("Ticket", ticket_id, "TicketFollowup")
            fu_list = fups if isinstance(fups, list) else (
                fups.get("data", []) if isinstance(fups, dict) else []
            )
            fu_ids: List[int] = []
            for f in fu_list:
                if isinstance(f, dict) and f.get("id") is not None:
                    try:
                        fu_ids.append(int(f["id"]))
                    except (ValueError, TypeError):
                        continue
            fu_ids = fu_ids[:30]

            sem = asyncio.Semaphore(5)  # limita conexoes concorrentes ao GLPI

            async def _fu_docs(fid: int) -> int:
                async with sem:
                    for itemtype in ("ITILFollowup", "TicketFollowup"):
                        try:
                            d = await glpi_client.get_subitems(itemtype, fid, "Document_Item")
                            n = _count_docs(d)
                            if n:
                                return n
                        except Exception:  # noqa: BLE001
                            continue
                    return 0

            if fu_ids:
                counts = await asyncio.gather(*[_fu_docs(f) for f in fu_ids])
                attach_followups = sum(counts)

            # Embute os follow-ups (acompanhamentos) NO DETALHE — p/ responder
            # "o tecnico ja respondeu?" sem precisar de outra tool. Autor -> nome.
            author_ids: set = set()
            for f in fu_list:
                if isinstance(f, dict):
                    author_ids.update(_actor_ids(f.get("users_id")))
            author_names = (
                await dropdown_cache.get_many_names("User", list(author_ids))
                if author_ids else {}
            )
            followups: List[Dict[str, Any]] = []
            for f in fu_list[:50]:
                if not isinstance(f, dict):
                    continue
                ids = _actor_ids(f.get("users_id"))
                author = author_names.get(ids[0]) if ids else None
                followups.append({
                    "date": f.get("date") or f.get("date_creation"),
                    "author": author or (str(f.get("users_id")) if f.get("users_id") else "?"),
                    "is_private": str(f.get("is_private")) in ("1", "True"),
                    "content": f.get("content", ""),
                })
            ticket["followups"] = followups
        except Exception as e:  # noqa: BLE001
            logger.warning(f"get_ticket_detail: followup enrichment failed for {ticket_id}: {e}")

        if attach_ticket is None and attach_followups == 0:
            ticket["attachment_count"] = None
        else:
            ticket["attachment_count"] = (attach_ticket or 0) + attach_followups
            ticket["attachment_breakdown"] = {
                "ticket": attach_ticket or 0,
                "followups": attach_followups,
            }

        return ticket

    async def get_ticket_by_number(self, ticket_number: str) -> Optional[Dict[str, Any]]:
        """Busca ticket por número público.

        In stock GLPI, the ticket "number" is the same as the numeric id.
        Some installs use a custom number (e.g. formatnumber plugin), which
        is typically stored in the ticket name/title. Strategy:
        1. If ticket_number is numeric, try direct id lookup.
        2. Fall back to a /search/Ticket on field 1 (name) contains match.

        @MX:ANCHOR: only a genuine 404 may fall through to the title search.
        @MX:REASON: GLPI answers ERROR_RIGHT_MISSING (403) when the profile
        behind the token cannot read the ticket, and the title search then finds
        nothing, so the caller was told "chamado nao encontrado" for a ticket
        that exists and is merely out of reach. A model reading that reports the
        ticket as nonexistent. Anything that is not a 404 is re-raised so the
        permission error reaches the caller as a permission error.
        """
        if not ticket_number or not ticket_number.strip():
            raise ValidationError("ticket_number is required", "ticket_number")

        number = ticket_number.strip()

        # Strategy 1: numeric → direct /Ticket/{id}
        if number.isdigit():
            try:
                ticket = await glpi_client.get(f"/apirest.php/Ticket/{int(number)}")
                if ticket and ticket.get("id"):
                    return ticket
            except NotFoundError:
                pass
            except GLPIError as e:
                if getattr(e, "code", 0) not in (404,):
                    logger.error(
                        f"get_ticket_by_number: direct id lookup for {number} failed "
                        f"with a non-404 error, re-raising instead of reporting "
                        f"'not found': {e}"
                    )
                    raise

        # Strategy 2: /search/Ticket on title (field 1)
        params = {
            "criteria[0][field]": "1",
            "criteria[0][searchtype]": "contains",
            "criteria[0][value]": number,
            "range": "0-0",
        }
        result = await glpi_client.get("/apirest.php/search/Ticket", params=params)
        if isinstance(result, dict) and result.get("data"):
            hit = result["data"][0]
            if hit.get("2") or hit.get("id"):
                # Re-fetch full ticket for consistent shape
                return await self.get_ticket(int(hit.get("2") or hit.get("id")))
        return None
    
    async def create_ticket(self, title: str, description: str, **kwargs) -> Dict[str, Any]:
        """Cria um novo ticket.

        @MX:NOTE: optional fields are only sent when the caller informed them,
        and an explicit None falls back to the default instead of overwriting it.
        @MX:REASON: same silent-discard class already fixed in the ticket
        filters. location_id was accepted by the tool, forwarded here and never
        written, so "abrir chamado na sala 12" produced a ticket with no
        location and no warning; and kwargs.get(key, default) returned None
        whenever the tool forwarded an unset parameter, sending null to GLPI
        instead of the documented default.
        """
        if not title or not description:
            raise ValidationError("title and description are required")

        def _or_default(key: str, default: Any) -> Any:
            value = kwargs.get(key)
            return default if value is None else value

        data: Dict[str, Any] = {
            "name": title,
            "content": description,
            "entities_id": _or_default("entity_id", 0),
            "priority": _or_default("priority", 3),
            "urgency": _or_default("urgency", 3),
            "impact": _or_default("impact", 3),
            "itilcategories_id": _or_default("category_id", 0),
            "type": _or_default("type", 1),  # 1 = Incident, 2 = Request
        }

        for param, field in (
            ("requester_id", "users_id_recipient"),
            ("assignee_id", "users_id_assign"),
            ("location_id", "locations_id"),
        ):
            value = kwargs.get(param)
            if value not in (None, ""):
                data[field] = value

        result = await glpi_client.post("/apirest.php/Ticket", data=data)
        if not result or "id" not in result:
            raise GLPIError(500, "Failed to create ticket")
        return result

    async def update_ticket(self, ticket_id: int, **kwargs) -> Dict[str, Any]:
        """Atualiza um ticket existente.

        @MX:ANCHOR: every accepted update field is declared in _UPDATE_FIELDS.
        @MX:REASON: same silent-discard class already fixed in the ticket
        filters. The consolidated tool forwards category_id and solution here;
        category_id was never written and solution never can be (a solution is
        an ITILSolution, not a ticket column), so "mudar a categoria e registrar
        a solucao" reported success having applied neither. Anything this method
        cannot apply is now refused instead of dropped.
        """
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")

        # Verificar se o chamado existe: get_ticket levanta NotFoundError quando
        # nao existe, entao a chamada e a propria validacao.
        await self.get_ticket(ticket_id)

        data = {}
        for param, value in kwargs.items():
            if param == "status":
                # GLPI stores status as int. Accept the string enum from the
                # schema ("pending") and map to the code (4). Passing the raw
                # string causes a MySQL "Incorrect integer value" error.
                data["status"] = (
                    STATUS_MAP.get(value, value) if isinstance(value, str) else value
                )
                continue
            if param == "solution":
                raise ValidationError(
                    "solution nao e aplicavel em action='update': no GLPI a solucao "
                    "e um registro proprio. Use action='resolve' (ou 'close') para "
                    "registrar a solucao do chamado.",
                    "solution",
                )
            field = _UPDATE_FIELDS.get(param)
            if field is None:
                raise ValidationError(
                    f"Campo '{param}' nao pode ser atualizado. Campos aceitos: "
                    f"{sorted(_UPDATE_FIELDS) + ['status']}",
                    param,
                )
            data[field] = value

        if not data:
            raise ValidationError("No valid fields to update")

        # GLPI API PUT retorna 200 OK com body vazio em sucesso
        await glpi_client.put(f"/apirest.php/Ticket/{ticket_id}", data=data)
        
        # Retornar ticket atualizado
        return await self.get_ticket(ticket_id)
    
    async def delete_ticket(self, ticket_id: int) -> bool:
        """Remove um ticket."""
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        
        # Verificar se ticket existe
        await self.get_ticket(ticket_id)
        
        await glpi_client.delete(f"/apirest.php/Ticket/{ticket_id}")
        return True
    
    async def assign_ticket(self, ticket_id: int, assignee_id: int) -> Dict[str, Any]:
        """Atribui um ticket a um usuário como técnico."""
        if ticket_id <= 0 or assignee_id <= 0:
            raise ValidationError("ticket_id and assignee_id must be positive")
        
        # No GLPI, técnicos são atribuídos via Ticket_User com type=2 (assigned)
        # Referência: https://github.com/glpi-project/glpi/blob/main/apirest.md#add-items
        ticket_user_data = {
            "tickets_id": ticket_id,
            "users_id": assignee_id,
            "type": 2,  # 2 = Técnico atribuído (assigned)
            "use_notification": 1
        }
        
        try:
            await glpi_client.post("/apirest.php/Ticket_User", data=ticket_user_data)
        except GLPIError as e:
            # GLPI rejeita vinculo Ticket_User duplicado com ERROR_GLPI_ADD e detalhe
            # vazio. Traduz para mensagem acionavel em vez de repassar o codigo cru.
            if "ERROR_GLPI_ADD" in str(e):
                raise GLPIError(
                    409,
                    f"Nao foi possivel atribuir o tecnico {assignee_id} ao ticket {ticket_id}: "
                    f"o tecnico ja esta atribuido a este chamado ou o ID de usuario e invalido. "
                    f"Use glpi_search_admin_resources(resource='users') para obter IDs de tecnicos validos."
                ) from e
            raise

        # Retornar ticket atualizado
        return await self.get_ticket(ticket_id)
    
    async def close_ticket(self, ticket_id: int, resolution: str, **kwargs) -> Dict[str, Any]:
        """Fecha um ticket com resolução."""
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        if not resolution:
            raise ValidationError("resolution is required")
        
        data = {
            "status": 6,  # Closed
            "content": resolution,
            "solutiontypes_id": kwargs.get("solution_type", 5)
        }
        
        result = await glpi_client.put(f"/apirest.php/Ticket/{ticket_id}", data=data)
        # PUT pode retornar vazio (200 OK) ou {"success": True, "id": ...}
        if not result:
            return {"id": ticket_id, "closed": True, "status": 6}
        return result
    
    async def find_similar_tickets(self, ticket_id: int, **kwargs) -> List[Dict[str, Any]]:
        """
        Encontra tickets similares usando SimilarityService.
        Integração requerida pela SPEC (RF03 / AC06).
        """
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        
        reference = await self.get_ticket(ticket_id)

        # Buscar candidatos (limitados para performance). _with_content garante
        # que a Search API traga o campo 21 (descricao) p/ a similaridade.
        candidates = await self.list_tickets(
            limit=kwargs.get("max_items", 200), _with_content=True
        )

        # Index candidates by id so we can re-attach displayable fields
        # (name/status/date) to the similarity scores afterwards.
        cand_by_id = {t.get("id"): t for t in candidates if t.get("id") != ticket_id}

        scored = await similarity_service.find_similar_tickets(
            target_ticket={
                "id": reference.get("id"),
                "title": reference.get("name", ""),
                # @MX:NOTE: reference vem do GET direto (HTML cru); candidatos vem
                # da Search API (campo 21). Normaliza ambos com strip_html p/
                # similaridade justa (texto vs HTML davam score assimetrico).
                "content": strip_html(reference.get("content", "")),
            },
            candidate_tickets=[
                {"id": cid, "title": t.get("name", ""), "content": strip_html(t.get("content", "") or "")}
                for cid, t in cand_by_id.items()
            ],
            threshold=kwargs.get("threshold", 0.3),
            max_results=kwargs.get("max_results", 10),
        )

        # Map similarity results back to ticket-shaped dicts the formatter
        # understands (id/name/status/date/score). The raw scorer only returns
        # {id1, id2, combined, ...}.
        results: List[Dict[str, Any]] = []
        for s in scored:
            cid = s.get("id2")
            cand = cand_by_id.get(cid, {})
            results.append({
                "id": cid,
                "name": cand.get("name", ""),
                "status": cand.get("status"),
                "date": cand.get("date"),
                "score": round(float(s.get("combined", 0.0)), 3),
            })
        return results
    
    async def search_tickets(self, query: str, **kwargs) -> Dict[str, Any]:
        """Busca textual de tickets (título + conteúdo) via Search API.

        Usa /apirest.php/search/Ticket, que processa ``criteria[]``. O endpoint
        getAllItems NÃO suporta busca textual, por isso o filtro era ignorado.
        """
        if not query or len(query.strip()) < 2:
            raise ValidationError("Search query must be at least 2 characters")

        limit = max(int(kwargs.get("limit", 50)), 1)
        offset = max(int(kwargs.get("offset", 0)), 0)

        # @MX:WARN: a busca textual precisa cobrir titulo E descricao.
        # @MX:REASON: o criterio era apenas o campo de titulo, embora este
        # comentario afirmasse que "contains varre o conteudo" e a descricao da
        # tool prometesse "titulo e conteudo". Medido na instancia real: um
        # chamado com o termo somente na descricao NAO era encontrado. Buscar
        # por mensagem de erro ou sintoma — o uso principal — devolvia "nenhum
        # resultado" como se fosse fato.
        #
        # @MX:NOTE: o grupo de texto lidera e todo o resto vem do builder
        # compartilhado. Vai ANINHADO para que os filtros seguintes continuem
        # restringindo, em vez de serem absorvidos pela cadeia OR.
        await _ensure_field_map_synced()

        entity_id = kwargs.get("entity_id")
        sort_field, order = _resolve_sort(kwargs)
        text_fields = [TICKET_FIELD["name"], TICKET_FIELD["content"]]

        # Resolvido UMA vez: _run e reexecutado por estagio de busca textual, e
        # cada resolucao de pessoa custa consultas a /User.
        base_criteria = await self._expand_person_filters(_build_ticket_criteria(kwargs), kwargs)

        async def _run(text_groups, fetch_limit):
            criteria: List[Dict[str, Any]] = list(text_groups or [])
            criteria.extend(base_criteria)
            result = await glpi_client.search(
                item_type="Ticket",
                criteria=criteria,
                forcedisplay=TICKET_FORCEDISPLAY,
                range_limit=fetch_limit,
                range_offset=offset,
                is_recursive=entity_id is not None,
                sort=sort_field,
                order=order,
                expand_dropdowns=True,
            )
            data = result.get("data", []) if isinstance(result, dict) else (result or [])
            count = None
            if isinstance(result, dict) and result.get("totalcount") is not None:
                try:
                    count = int(result["totalcount"])
                except (TypeError, ValueError):
                    count = None
            return data, count

        rows, total, stage, terms = await run_text_search(
            query.strip(), text_fields, _run, limit
        )
        normalized = [_normalize_search_ticket(r) for r in rows]
        await self._resolve_actor_names(normalized, resolve_groups=True)
        return {
            "items": normalized,
            "totalcount": total,
            "search_notice": describe_stage(stage, terms, found=bool(normalized)),
        }

    async def get_ticket_stats(self, **kwargs) -> Dict[str, Any]:
        """Obtém estatísticas de tickets agregadas por status.

        GLPI ticket status codes:
            1 = new, 2 = assigned, 3 = planned, 4 = pending,
            5 = solved, 6 = closed
        Uses /search/Ticket with range=0-0 to fetch only totalcount per status.
        """
        entity_id = kwargs.get("entity_id")
        date_from = kwargs.get("date_from")
        date_to = kwargs.get("date_to")

        async def _count(extra_criteria: Optional[List[Dict[str, Any]]] = None) -> int:
            params: Dict[str, Any] = {"range": "0-0"}
            idx = 0
            criteria = list(extra_criteria or [])
            if entity_id is not None:
                criteria.append(
                    {"field": TICKET_FIELD["entities_id"], "searchtype": "under", "value": entity_id}
                )
            if date_from:
                criteria.append(
                    {"field": TICKET_FIELD["date"], "searchtype": "morethan", "value": date_from}
                )
            if date_to:
                criteria.append(
                    {"field": TICKET_FIELD["date"], "searchtype": "lessthan", "value": date_to}
                )
            for c in criteria:
                if idx > 0:
                    params[f"criteria[{idx}][link]"] = "AND"
                params[f"criteria[{idx}][field]"] = c["field"]
                params[f"criteria[{idx}][searchtype]"] = c["searchtype"]
                params[f"criteria[{idx}][value]"] = c["value"]
                idx += 1
            # @MX:NOTE: Propaga erro em vez de retornar 0 silenciosamente.
            # @MX:REASON: Bug #2 — zeros silenciosos enganavam o LLM quando auth/API falhava.
            result = await glpi_client.get(
                "/apirest.php/search/Ticket", params=params, use_cache=False
            )
            if isinstance(result, dict):
                return int(result.get("totalcount", 0) or 0)
            return 0

        # Field ids come from TICKET_FIELD, which the reconciliation pass keeps
        # aligned with this instance's catalogue.
        status_map = {
            "new": 1,
            "assigned": 2,
            "planned": 3,
            "pending": 4,
            "solved": 5,
            "closed": 6,
        }

        total = await _count()
        by_status = {}
        for label, code in status_map.items():
            by_status[label] = await _count(
                [{"field": TICKET_FIELD["status"], "searchtype": "equals", "value": code}]
            )

        open_tickets = by_status["new"] + by_status["assigned"] + by_status["planned"] + by_status["pending"]
        closed_tickets = by_status["solved"] + by_status["closed"]

        return {
            "total_tickets": total,
            "open_tickets": open_tickets,
            "closed_tickets": closed_tickets,
            "by_status": by_status,
            "entity_id": entity_id if entity_id is not None else "all",
            "date_from": date_from,
            "date_to": date_to,
        }
    
    async def get_ticket_history(self, ticket_id: int) -> List[Dict[str, Any]]:
        """Obtém histórico de alterações de um ticket."""
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        
        result = await glpi_client.get(f"/apirest.php/Ticket/{ticket_id}/Log")
        return result if isinstance(result, list) else (result.get("data", []) if isinstance(result, dict) else [])
    
    async def add_ticket_followup(self, ticket_id: int, content: str, **kwargs) -> Dict[str, Any]:
        """Adiciona um acompanhamento a um ticket."""
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        if not content:
            raise ValidationError("content is required")
        
        # Verificar se ticket existe
        await self.get_ticket(ticket_id)
        
        data = {
            "items_id": ticket_id,
            "itemtype": "Ticket",
            "content": content,
            "is_private": kwargs.get("is_private", 0)
        }
        
        result = await glpi_client.post("/apirest.php/TicketFollowup", data=data)
        # POST pode retornar {"id": ...} ou array com ids
        if not result:
            raise GLPIError(500, "Failed to add followup")
        # Se result é lista com ids
        if isinstance(result, list) and len(result) > 0:
            return {"id": result[0], "ticket_id": ticket_id, "created": True}
        # Se result já tem id
        if isinstance(result, dict) and "id" in result:
            return result
        # Fallback
        return {"ticket_id": ticket_id, "created": True}

    async def post_private_note(self, ticket_id: int, text: str) -> Dict[str, Any]:
        """Cria uma nota privada (followup is_private=1)."""
        return await self.add_ticket_followup(ticket_id, text, is_private=1)

    async def get_ticket_followups(self, ticket_id: int) -> List[Dict[str, Any]]:
        """Lista followups de um ticket."""
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        result = await glpi_client.get_subitems("Ticket", ticket_id, "TicketFollowup")
        return result if isinstance(result, list) else (result.get("data", []) if isinstance(result, dict) else [])

    async def resolve_ticket(self, ticket_id: int, solution: str, **kwargs) -> Dict[str, Any]:
        """Marca ticket como resolvido (status 5) com solução."""
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        if not solution:
            raise ValidationError("solution is required", "solution")
        data = {
            "status": 5,  # solved
            "content": solution,
            "solutiontypes_id": kwargs.get("solution_type", 5)
        }
        result = await glpi_client.put(f"/apirest.php/Ticket/{ticket_id}", data=data)
        # PUT pode retornar vazio (200 OK) ou {"success": True, "id": ...}
        if not result:
            return {"id": ticket_id, "resolved": True, "status": 5}
        return result

    # -----------------------------------------------------------------
    # ITIL coverage: timeline, tasks, validations, actors, links, docs
    # -----------------------------------------------------------------

    @staticmethod
    def _created_id(result: Any) -> Optional[int]:
        """Extract the id GLPI returns after a create.

        A POST answers with {"id": N}, [{"id": N}] or a bare list of ids
        depending on the endpoint and version.
        """
        raw: Any = None
        if isinstance(result, dict):
            raw = result.get("id")
        elif isinstance(result, list) and result:
            first = result[0]
            raw = first.get("id") if isinstance(first, dict) else first
        return as_field_id(raw)

    def _confirm_created(self, result: Any, what: str, extra: Dict[str, Any]) -> Dict[str, Any]:
        """Turn a create response into a result dict, refusing to fake success.

        @MX:ANCHOR: every ITIL create funnels through here.
        @MX:REASON: the followup path used to answer {"created": True} whatever
        came back, so a rejected write was reported to the user as done. A
        create is only "done" when GLPI either returned an id or explicitly
        acknowledged the write.
        """
        created_id = self._created_id(result)
        if created_id is None and not (isinstance(result, dict) and result.get("success")):
            raise GLPIError(500, f"O GLPI nao confirmou a criacao de {what}: {result!r}")
        payload = {"id": created_id, "created": True, **extra}
        if created_id is None:
            payload["warning"] = (
                f"O GLPI aceitou a criacao de {what} mas nao devolveu o id do registro"
            )
        return payload

    async def _fetch_subitems_any(
        self, ticket_id: int, itemtypes: Tuple[str, ...]
    ) -> List[Dict[str, Any]]:
        """Read a ticket sub-collection, trying each itemtype in turn.

        The first itemtype that answers wins. Raises the last error when none
        answers, so the caller can report that source as unavailable instead of
        pretending it was empty.
        """
        last_error: Optional[Exception] = None
        for itemtype in itemtypes:
            try:
                return _as_item_list(
                    await glpi_client.get_subitems("Ticket", ticket_id, itemtype)
                )
            except Exception as exc:  # noqa: BLE001 — tried in order, reported below
                last_error = exc
                continue
        raise last_error if last_error else GLPIError(500, "Nenhuma origem consultada")

    @staticmethod
    async def _resolve_entry_actors(entries: List[Dict[str, Any]]) -> None:
        """Replace the *_id actor keys of timeline entries with names, in place.

        All ids are collected across the whole page first so the lookup costs
        one call per itemtype instead of one per entry.
        """
        user_ids: set = set()
        group_ids: set = set()
        for entry in entries:
            for key in ("author_id", "assignee_id"):
                if entry.get(key):
                    user_ids.add(entry[key])
            if entry.get("approver_id"):
                if entry.get("approver_type") == "Group":
                    group_ids.add(entry["approver_id"])
                else:
                    user_ids.add(entry["approver_id"])

        users = await dropdown_cache.get_many_names("User", list(user_ids)) if user_ids else {}
        groups = await dropdown_cache.get_many_names("Group", list(group_ids)) if group_ids else {}

        for entry in entries:
            if entry.get("author_id"):
                entry["author"] = users.get(entry["author_id"]) or str(entry["author_id"])
            if entry.get("assignee_id"):
                entry["assignee"] = users.get(entry["assignee_id"]) or str(entry["assignee_id"])
            if entry.get("approver_id"):
                pool = groups if entry.get("approver_type") == "Group" else users
                entry["approver"] = pool.get(entry["approver_id"]) or str(entry["approver_id"])

    async def get_ticket_timeline(self, ticket_id: int, limit: int = 100) -> Dict[str, Any]:
        """Unified chronological timeline: followups + tasks + solutions + approvals.

        The four collections are read concurrently and merged into a single
        date-ordered list.

        @MX:ANCHOR: partial failure is a first-class outcome here.
        @MX:REASON: the four sources have different profile permissions in
        GLPI — restricted technicians routinely cannot read TicketValidation.
        Letting one 403 abort the gather would leave the caller with nothing
        when three quarters of the history were available, so failures are
        collected per source and reported alongside the entries that did load.
        """
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        limit = max(int(limit or 100), 1)

        results = await asyncio.gather(
            *[
                self._fetch_subitems_any(ticket_id, itemtypes)
                for _, itemtypes in _TIMELINE_SOURCES
            ],
            return_exceptions=True,
        )

        entries: List[Dict[str, Any]] = []
        failed_sources: List[Dict[str, str]] = []
        counts: Dict[str, int] = {}
        for (kind, _itemtypes), result in zip(_TIMELINE_SOURCES, results):
            if isinstance(result, BaseException):
                failed_sources.append({"source": kind, "error": str(result)})
                logger.warning(
                    f"get_ticket_timeline: source '{kind}' unavailable for "
                    f"ticket {ticket_id}: {result}"
                )
                continue
            builder = _TIMELINE_BUILDERS[kind]
            built = [builder(item) for item in result]
            counts[kind] = len(built)
            entries.extend(built)

        await self._resolve_entry_actors(entries)
        entries.sort(key=_timeline_sort_key)

        total = len(entries)
        truncated = total > limit
        if truncated:
            # Keep the MOST RECENT window: an old ticket's first followups
            # matter far less than what happened last.
            entries = entries[-limit:]

        return {
            "ticket_id": ticket_id,
            "entries": entries,
            "counts": counts,
            "total_entries": total,
            "truncated": truncated,
            "failed_sources": failed_sources,
        }

    async def add_ticket_task(self, ticket_id: int, content: str, **kwargs) -> Dict[str, Any]:
        """Create a task (TicketTask) on a ticket.

        @MX:NOTE: the write goes to /TicketTask with tickets_id in the payload,
        while the read uses /Ticket/{id}/TicketTask.
        @MX:REASON: the GLPI REST router takes the itemtype from the FIRST path
        element on POST and ignores the rest, so posting to
        /Ticket/{id}/TicketTask would create a new TICKET. The sub-item path is
        only a read route. This mirrors add_ticket_followup, which posts to
        /TicketFollowup for the same reason.
        """
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        if not content or not str(content).strip():
            raise ValidationError("content is required", "content")

        await self.get_ticket(ticket_id)

        data: Dict[str, Any] = {
            "tickets_id": ticket_id,
            "content": content,
            "is_private": 1 if kwargs.get("is_private") else 0,
        }

        actiontime = kwargs.get("actiontime")
        if actiontime is not None:
            seconds = as_field_id(actiontime)
            if seconds is None or seconds < 0:
                raise ValidationError(
                    "actiontime deve ser a duracao prevista em SEGUNDOS (ex: 3600 = 1h)",
                    "actiontime",
                )
            data["actiontime"] = seconds

        task_category_id = kwargs.get("task_category_id")
        if task_category_id is not None:
            resolved_category = as_field_id(task_category_id)
            if resolved_category is not None:
                data["taskcategories_id"] = resolved_category

        result = await glpi_client.post("/apirest.php/TicketTask", data=data)
        return self._confirm_created(
            result, "a tarefa", {"ticket_id": ticket_id, "is_private": bool(data["is_private"])}
        )

    async def get_ticket_tasks(self, ticket_id: int) -> Dict[str, Any]:
        """List the tasks of a ticket, with author and assignee resolved."""
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        items = _as_item_list(
            await glpi_client.get_subitems("Ticket", ticket_id, "TicketTask")
        )
        entries = [_timeline_task(item) for item in items]
        await self._resolve_entry_actors(entries)
        entries.sort(key=_timeline_sort_key)
        return {"ticket_id": ticket_id, "tasks": entries, "total": len(entries)}

    async def _search_actor_candidates(
        self, itemtype: str, name: str
    ) -> List[Tuple[int, str]]:
        """Loose name search over the Search API, returning (id, label) pairs."""
        result = await glpi_client.search(
            item_type=itemtype,
            criteria=[_actor_criterion(1, name)],
            forcedisplay=[2, 1],
            range_limit=25,
            is_recursive=True,
        )
        candidates: List[Tuple[int, str]] = []
        for row in _as_item_list(result):
            row_id = as_field_id(row.get("2") if row.get("2") is not None else row.get("id"))
            if row_id is None:
                continue
            label = row.get("1") if row.get("1") is not None else row.get("name")
            candidates.append((row_id, str(label or row_id)))
        return candidates

    @staticmethod
    async def _search_users_by_realname(name: str) -> List[Tuple[int, str]]:
        """Fallback lookup for users typed by full name instead of login."""
        result = await glpi_client.get(
            "/apirest.php/User",
            params={"range": "0-24", "searchText[realname]": name},
            use_cache=True,
        )
        candidates: List[Tuple[int, str]] = []
        for row in _as_item_list(result):
            row_id = as_field_id(row.get("id"))
            if row_id is None:
                continue
            label = f"{row.get('realname', '') or ''} {row.get('firstname', '') or ''}".strip()
            candidates.append((row_id, label or str(row.get("name") or row_id)))
        return candidates

    async def _find_users_by_any_name_part(self, name: str) -> List[Tuple[int, str]]:
        """Find users by ANY part of the name — login, first name or surname.

        @MX:ANCHOR: um filtro de pessoa aceita qualquer pedaco do nome.
        @MX:REASON: no GLPI o nome de uma pessoa esta partido em tres colunas
        (`name` = login, `firstname`, `realname` = sobrenomes) e a Search API
        compara UMA delas por vez. Quem pergunta escreve o nome como a
        listagem o exibe — "Azeredo Da Silva Guimaraes Erica" — que nao existe
        inteiro em coluna nenhuma: `realname` guarda "Azeredo Da Silva
        Guimaraes" e `firstname` guarda "Erica". Procurar a string inteira em
        qualquer coluna da zero, e zero chamado e uma resposta que parece um
        fato ("essa pessoa nao abriu nada") quando e so um filtro que nao
        casou. Entao: quebra em tokens, procura o mais distintivo nas tres
        colunas, e classifica os candidatos pela cobertura dos demais tokens.
        """
        tokens = [t for t in re.split(r"[\s,]+", str(name or "").strip()) if t]
        # Preposicoes de sobrenome nao distinguem ninguem e casam com meio GLPI.
        meaningful = [
            t for t in tokens if len(t) >= 3 and t.lower() not in _NAME_STOPWORDS
        ]
        if not meaningful:
            meaningful = tokens
        if not meaningful:
            return []

        # Uma consulta por coluna, com o token mais longo (o mais seletivo).
        probe = max(meaningful, key=len)
        found: Dict[int, str] = {}
        for column in ("realname", "firstname", "name"):
            try:
                result = await glpi_client.get(
                    "/apirest.php/User",
                    params={"range": "0-49", f"searchText[{column}]": probe},
                    use_cache=True,
                )
            except (GLPIError, NotFoundError) as exc:
                logger.warning(
                    f"_find_users_by_any_name_part: busca por {column}~'{probe}' falhou: {exc}"
                )
                continue
            for row in _as_item_list(result):
                row_id = as_field_id(row.get("id"))
                if row_id is None or row_id in found:
                    continue
                found[row_id] = " ".join(
                    str(row.get(key) or "") for key in ("name", "firstname", "realname")
                ).strip()

        if not found:
            return []

        lowered = [t.lower() for t in meaningful]

        def coverage(label: str) -> int:
            haystack = label.lower()
            return sum(1 for token in lowered if token in haystack)

        scored = [(coverage(label), uid, label) for uid, label in found.items()]
        best = max(score for score, _, _ in scored)
        # Só o melhor grupo: quem casa 4 dos 5 tokens não deve concorrer com
        # quem casou só o sobrenome comum.
        return [(uid, label) for score, uid, label in scored if score == best][
            :_MAX_PERSON_FILTER_MATCHES
        ]

    async def _person_criterion(self, field: int, value: Any) -> Dict[str, Any]:
        """Criterion for a person filter: exact id, or an OR over every match."""
        resolved = as_field_id(value)
        if resolved is not None:
            return {"field": field, "searchtype": "equals", "value": resolved}

        name = str(value or "").strip()
        matches = await self._find_users_by_any_name_part(name)
        if not matches:
            # Sem candidato, mantem o comportamento antigo: a Search API ainda
            # pode casar por login. Melhor tentar do que descartar o filtro.
            logger.info(
                f"_person_criterion: nenhum usuario casou '{name}', "
                f"caindo para busca textual no campo {field}"
            )
            return {"field": field, "searchtype": "contains", "value": name}

        if len(matches) == 1:
            return {"field": field, "searchtype": "equals", "value": matches[0][0]}

        logger.info(
            f"_person_criterion: '{name}' casou {len(matches)} usuarios "
            f"({', '.join(label for _, label in matches[:5])}) — filtrando por todos"
        )
        return {
            "criteria": [
                {
                    "field": field,
                    "searchtype": "equals",
                    "value": uid,
                    **({"link": "OR"} if position else {}),
                }
                for position, (uid, _label) in enumerate(matches)
            ]
        }

    async def _expand_person_filters(
        self, criteria: List[Dict[str, Any]], kwargs: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Append the requester / assigned-tech filters, resolved to user ids."""
        for param, field in (
            ("assigned_tech", TICKET_FIELD["tech_assign"]),
            ("requester", TICKET_FIELD["requester"]),
        ):
            value = kwargs.get(param)
            if value not in (None, ""):
                criteria.append(await self._person_criterion(field, value))
        return criteria

    async def _resolve_actor_id(self, itemtype: str, value: Any, label: str) -> int:
        """Resolve "a name or an id" into the numeric id a write needs.

        @MX:NOTE: same acceptance rule as utils.search_criteria.actor_criterion —
        an id is taken literally, a name matches loosely — but a write cannot
        act on a loose match.
        @MX:REASON: a filter that matches two groups just lists more rows; an
        assignment that matches two groups would pick one at random and hand
        the ticket to the wrong team. Ambiguity is therefore refused with the
        candidates spelled out instead of resolved silently.
        """
        resolved = as_field_id(value)
        if resolved is not None:
            if resolved <= 0:
                raise ValidationError(f"{label} invalido: {value}", "id")
            return resolved

        name = str(value or "").strip()
        if not name:
            raise ValidationError(f"{label} e obrigatorio", "name")

        candidates = await self._search_actor_candidates(itemtype, name)
        if not candidates and itemtype == "User":
            # Field 1 of /search/User is the LOGIN; callers usually type the
            # person's full name, which lives in realname.
            candidates = await self._search_users_by_realname(name)

        if not candidates:
            raise ValidationError(
                f"{label} '{name}' nao encontrado no GLPI. "
                f"Use glpi_search_admin_resources para obter o id correto.",
                "name",
            )

        exact = [c for c in candidates if c[1].strip().lower() == name.lower()]
        if len(exact) == 1:
            return exact[0][0]
        if len(candidates) == 1:
            return candidates[0][0]

        preview = ", ".join(f"{cname} (id {cid})" for cid, cname in candidates[:5])
        raise ValidationError(
            f"{label} '{name}' e ambiguo ({len(candidates)} correspondencias): "
            f"{preview}. Informe o id.",
            "name",
        )

    async def _post_supported_shape(
        self, endpoint: str, shapes: List[Dict[str, Any]], what: str
    ) -> Any:
        """POST the first payload shape this GLPI instance accepts.

        @MX:WARN: this replays a write after a failure.
        @MX:REASON: only shape errors are being recovered from — GLPI rejects an
        unknown column at INSERT time, so the first attempt provably created
        nothing. The alternative is hard-coding one schema and breaking on every
        instance that runs the other one.
        """
        last_error: Optional[Exception] = None
        for payload in shapes:
            try:
                return await glpi_client.post(endpoint, data=payload)
            except (GLPIError, NotFoundError, ValidationError) as exc:
                last_error = exc
                logger.warning(
                    f"{what}: payload shape {sorted(payload.keys())} rejected by GLPI: {exc}"
                )
        raise last_error if last_error else GLPIError(500, f"{what} falhou")

    async def request_ticket_validation(
        self, ticket_id: int, approver: Any, comment: Optional[str] = None
    ) -> Dict[str, Any]:
        """Open an approval request (TicketValidation) for a ticket."""
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")

        approver_id = await self._resolve_actor_id("User", approver, "Usuario aprovador")
        await self.get_ticket(ticket_id)

        base: Dict[str, Any] = {
            "tickets_id": ticket_id,
            "status": VALIDATION_STATUS["waiting"],
        }
        if comment:
            base["comment_submission"] = comment

        # @MX:NOTE: two payload shapes, newest first.
        # @MX:REASON: GLPI moved the approval target from users_id_validate to
        # the polymorphic itemtype_target/items_id_target pair when group
        # approvals were introduced. Both shapes are in production across the
        # instances this server talks to.
        shapes = [
            {**base, "itemtype_target": "User", "items_id_target": approver_id},
            {**base, "users_id_validate": approver_id},
        ]
        result = await self._post_supported_shape(
            "/apirest.php/TicketValidation", shapes, "request_validation"
        )
        return self._confirm_created(
            result,
            "a solicitacao de aprovacao",
            {"ticket_id": ticket_id, "approver_id": approver_id},
        )

    async def get_ticket_validations(self, ticket_id: int) -> Dict[str, Any]:
        """List the approval requests of a ticket, with approver resolved."""
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        items = _as_item_list(
            await glpi_client.get_subitems("Ticket", ticket_id, "TicketValidation")
        )
        entries = [_timeline_validation(item) for item in items]
        await self._resolve_entry_actors(entries)
        entries.sort(key=_timeline_sort_key)
        return {"ticket_id": ticket_id, "validations": entries, "total": len(entries)}

    async def answer_ticket_validation(
        self,
        validation_id: Optional[int] = None,
        status: Any = None,
        comment: Optional[str] = None,
        ticket_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Answer an approval request: accepted (4) or refused (3)."""
        status_code = _resolve_validation_answer(status)

        resolved_id = as_field_id(validation_id)
        if resolved_id is None or resolved_id <= 0:
            resolved_id = await self._resolve_pending_validation(ticket_id)

        data: Dict[str, Any] = {"status": status_code}
        if comment:
            # GLPI refuses a refusal without a justification, and the field is
            # the same one for both answers.
            data["comment_validation"] = comment
        elif status_code == VALIDATION_STATUS["refused"]:
            raise ValidationError(
                "comment e obrigatorio ao recusar uma aprovacao no GLPI", "comment"
            )

        await glpi_client.put(f"/apirest.php/TicketValidation/{resolved_id}", data=data)
        return {
            "validation_id": resolved_id,
            "ticket_id": ticket_id,
            "status": status_code,
            "updated": True,
        }

    async def _resolve_pending_validation(self, ticket_id: Optional[int]) -> int:
        """Find the single WAITING approval of a ticket, or refuse to guess."""
        resolved_ticket = as_field_id(ticket_id)
        if resolved_ticket is None or resolved_ticket <= 0:
            raise ValidationError(
                "informe validation_id (ou ticket_id, para responder a aprovacao "
                "pendente do chamado)",
                "validation_id",
            )
        listing = await self.get_ticket_validations(resolved_ticket)
        waiting = [
            v
            for v in listing.get("validations", [])
            if as_field_id(v.get("validation_status")) == VALIDATION_STATUS["waiting"]
        ]
        if len(waiting) == 1 and waiting[0].get("id") is not None:
            return int(waiting[0]["id"])
        if not waiting:
            raise ValidationError(
                f"O chamado {resolved_ticket} nao possui aprovacao pendente para responder",
                "validation_id",
            )
        ids = ", ".join(str(v.get("id")) for v in waiting)
        raise ValidationError(
            f"O chamado {resolved_ticket} possui {len(waiting)} aprovacoes pendentes "
            f"(ids: {ids}). Informe validation_id.",
            "validation_id",
        )

    async def assign_ticket_group(
        self, ticket_id: int, group: Any, group_type: str = "assigned"
    ) -> Dict[str, Any]:
        """Link a GROUP to a ticket through Group_Ticket.

        @MX:NOTE: the actor role travels in the `type` column (see ACTOR_TYPE:
        1 requester, 2 assigned, 3 observer) — Group_Ticket carries all three,
        so "assigned" is a value, not a different endpoint.
        """
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")

        type_code = ACTOR_TYPE.get(str(group_type or "assigned").strip().lower())
        if type_code is None:
            raise ValidationError(
                f"group_type invalido: use um de {sorted(ACTOR_TYPE)}", "group_type"
            )

        group_id = await self._resolve_actor_id("Group", group, "Grupo")
        await self.get_ticket(ticket_id)

        data = {"tickets_id": ticket_id, "groups_id": group_id, "type": type_code}
        try:
            result = await glpi_client.post("/apirest.php/Group_Ticket", data=data)
        except GLPIError as e:
            if "ERROR_GLPI_ADD" in str(e):
                raise GLPIError(
                    409,
                    f"Nao foi possivel vincular o grupo {group_id} ao chamado {ticket_id}: "
                    f"o grupo ja esta vinculado com esse papel ou o id de grupo e invalido. "
                    f"Use glpi_search_admin_resources(resource='groups') para obter ids validos.",
                ) from e
            raise

        group_name = await dropdown_cache.get_name("Group", group_id, fallback=str(group_id))
        return self._confirm_created(
            result,
            "o vinculo do grupo",
            {
                "ticket_id": ticket_id,
                "group_id": group_id,
                "group_name": group_name,
                "type": type_code,
            },
        )

    async def link_tickets(
        self, ticket_id: int, linked_ticket_id: int, link_type: Any = "link"
    ) -> Dict[str, Any]:
        """Link two tickets through Ticket_Ticket."""
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        resolved_other = as_field_id(linked_ticket_id)
        if resolved_other is None or resolved_other <= 0:
            raise ValidationError(
                "linked_ticket_id must be positive", "linked_ticket_id"
            )
        if resolved_other == ticket_id:
            raise ValidationError(
                "Um chamado nao pode ser vinculado a ele mesmo", "linked_ticket_id"
            )

        code = _resolve_link_type(link_type)

        # Both sides are checked so a typo answers "chamado X nao existe"
        # instead of the opaque ERROR_GLPI_ADD the link table returns.
        await asyncio.gather(self.get_ticket(ticket_id), self.get_ticket(resolved_other))

        data = {
            "tickets_id_1": ticket_id,
            "tickets_id_2": resolved_other,
            "link": code,
        }
        try:
            result = await glpi_client.post("/apirest.php/Ticket_Ticket", data=data)
        except GLPIError as e:
            if "ERROR_GLPI_ADD" in str(e):
                raise GLPIError(
                    409,
                    f"Nao foi possivel vincular os chamados {ticket_id} e {resolved_other}: "
                    f"o vinculo ja existe ou o tipo informado nao e aceito.",
                ) from e
            raise

        return self._confirm_created(
            result,
            "o vinculo entre chamados",
            {
                "ticket_id": ticket_id,
                "linked_ticket_id": resolved_other,
                "link_type": code,
            },
        )

    @staticmethod
    async def _post_multipart(
        endpoint: str, fields: Dict[str, str], file_field: str,
        file_name: str, file_bytes: bytes, mime_type: str,
    ) -> Any:
        """Send a multipart/form-data POST reusing the authenticated session.

        @MX:NOTE: this is the only call in the server that does not go through
        session_manager, which speaks JSON exclusively.
        @MX:REASON: widening the shared HTTP layer for a single caller would put
        an upload code path in front of every ticket read. Instead the already
        authenticated httpx client is borrowed from the session (base_url,
        App-Token, Session-Token, timeouts and rate limiting all come with it)
        and only the encoding is done here.
        @MX:WARN: the read cache must be cleared by hand afterwards.
        @MX:REASON: session_manager.post() invalidates it after every write; a
        successful upload that skips that step leaves attachment counts and the
        ticket detail showing the pre-upload state.
        """
        session = glpi_client.session
        # noqa comment kept next to the call: _ensure_session is the only entry
        # point that both resolves the caller's session and charges the rate
        # limit, which an upload must respect like any other write.
        client = await session._ensure_session("default")  # noqa: SLF001
        body, content_type = _encode_multipart(
            fields, file_field, file_name, file_bytes, mime_type
        )
        response = await client.post(
            endpoint, content=body, headers={"Content-Type": content_type}
        )
        if response.status_code >= 400:
            raise GLPIError(
                response.status_code,
                f"Falha no upload para o GLPI: {response.text[:500]}",
            )
        session.clear_cache()
        text = response.text.strip()
        if not text:
            return {"success": True}
        try:
            return response.json()
        except (ValueError, json.JSONDecodeError):
            return {"success": True, "raw": text[:500]}

    @staticmethod
    def _read_upload_bytes(
        file_path: Optional[str], file_base64: Optional[str], file_name: Optional[str]
    ) -> Tuple[bytes, str]:
        """Resolve the upload payload into (bytes, file name)."""
        if file_base64:
            if not file_name or not str(file_name).strip():
                raise ValidationError(
                    "file_name e obrigatorio quando o arquivo vem em file_base64",
                    "file_name",
                )
            try:
                content = base64.b64decode(str(file_base64), validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValidationError(
                    f"file_base64 nao e um base64 valido: {exc}", "file_base64"
                ) from exc
            return content, Path(str(file_name)).name

        if file_path:
            path = Path(str(file_path)).expanduser()
            if not path.is_file():
                raise ValidationError(
                    f"Arquivo nao encontrado no servidor: {file_path}", "file_path"
                )
            return path.read_bytes(), (
                Path(str(file_name)).name if file_name else path.name
            )

        raise ValidationError(
            "Informe file_path (caminho no servidor) ou file_base64 + file_name",
            "file_path",
        )

    async def add_ticket_document(
        self,
        ticket_id: int,
        file_path: Optional[str] = None,
        file_base64: Optional[str] = None,
        file_name: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Attach a file to a ticket through a multipart POST /Document.

        @MX:ANCHOR: the ticket link is declared INSIDE the upload manifest.
        @MX:REASON: creating the Document first and then POSTing Document_Item
        looks equivalent but fails for restricted profiles, which are not
        allowed to create the link row on its own. Declaring itemtype/items_id
        in the manifest makes GLPI create the link as part of the upload, under
        the permissions the upload already has.
        @MX:NOTE: the manifest travels as a plain text field, not as a file
        part. GLPI reads it from $_POST while the part carrying `filename`
        lands in $_FILES; sending the manifest as a file makes GLPI see an
        upload with no input at all.
        """
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")

        content, resolved_name = self._read_upload_bytes(file_path, file_base64, file_name)
        if not content:
            raise ValidationError("O arquivo esta vazio", "file_path")
        if len(content) > _MAX_UPLOAD_BYTES:
            raise ValidationError(
                f"Arquivo com {len(content) // 1024}KB excede o limite de "
                f"{_MAX_UPLOAD_BYTES // (1024 * 1024)}MB para upload",
                "file_path",
            )

        await self.get_ticket(ticket_id)

        mime_type = _guess_mime_type(resolved_name)
        manifest = {
            "input": {
                "name": title or resolved_name,
                "_filename": [resolved_name],
                "itemtype": "Ticket",
                "items_id": ticket_id,
            }
        }

        result = await self._post_multipart(
            "/apirest.php/Document",
            {"uploadManifest": json.dumps(manifest, ensure_ascii=False)},
            "filename[0]",
            resolved_name,
            content,
            mime_type,
        )

        # GLPI answers 201 even when the file itself was rejected, reporting the
        # reason inside upload_result — surface it instead of claiming success.
        if isinstance(result, dict):
            upload_result = result.get("upload_result")
            errors = _collect_upload_errors(upload_result)
            if errors:
                raise GLPIError(
                    400, f"O GLPI recusou o arquivo enviado: {'; '.join(errors)}"
                )

        return self._confirm_created(
            result,
            "o documento",
            {
                "ticket_id": ticket_id,
                "file_name": resolved_name,
                "mime_type": mime_type,
                "size_bytes": len(content),
                "linked_to_ticket": True,
            },
        )


def _collect_upload_errors(upload_result: Any) -> List[str]:
    """Extract the error messages GLPI nests inside upload_result."""
    errors: List[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            error = node.get("error")
            if error:
                errors.append(str(error))
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for value in node:
                _walk(value)

    _walk(upload_result)
    return errors


# Instância global do serviço de tickets
ticket_service = TicketService()
