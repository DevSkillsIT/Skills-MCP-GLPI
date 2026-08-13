"""
Consolidated MCP tools for the ITIL records that are not incidents.

Two tools cover five itemtypes (Problem, Change, Project, Contract, Supplier):

  1. glpi_search_itil_records  -- list / text-search / cheap count
  2. glpi_manage_itil_records  -- get, create, update, delete, follow-ups,
                                  and linking a ticket to a problem or change

Why two and not ten
-------------------
A tool per entity would have produced ten near-identical schemas whose only
difference is a noun. Every one of them would then need its own filter list,
its own pagination and its own error wording, and a model choosing among them
picks by name similarity rather than by intent. One `record_type` argument
keeps the catalogue small and the behaviour identical across entities, which
is what makes "compare problems and changes this month" a two-call question
instead of a ten-tool guessing game.

All rendering lives here on purpose: this module owns its Markdown so it can
ship without touching the shared formatters other work is editing.
"""

from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from src.formatters.markdown_helpers import (
    esc,
    fmt_date,
    fmt_impact,
    fmt_priority,
    fmt_urgency,
    glpi_id_link,
    page_info,
    strip_html,
    truncate_field,
)
from src.models.exceptions import GLPIError, NotFoundError, ValidationError
from src.services.itil_service import (
    RECORD_TYPES,
    RecordSpec,
    get_spec,
    itil_service,
    resolve_record_type,
)
from src.utils.helpers import (
    DateTimeHelper,
    PaginationHelper,
    entity_resolver,
    input_sanitizer,
    logger,
)
from src.utils.safety_guard import safety_guard, require_safety_confirmation
from src.utils.validators import create_mcp_error, validate_positive_int

# Hard cap for result limits, aligned with the ticket surface.
MAX_LIMIT = 50

MANAGE_ACTIONS = [
    "get",
    "create",
    "update",
    "delete",
    "add_followup",
    "get_followups",
    "link_ticket",
]

ACTIONS_REQUIRING_RECORD_ID = [
    "get",
    "update",
    "delete",
    "add_followup",
    "get_followups",
    "link_ticket",
]

#: Actions only a subset of the record types can answer. Everything else is
#: supported everywhere.
_ACTION_REQUIREMENTS = {
    "add_followup": "followups",
    "get_followups": "followups",
    "link_ticket": "link",
}


def _delete_operation(record_type: str) -> str:
    """Safety-guard operation name for a record type's delete action."""
    return f"delete_{record_type[:-1] if record_type.endswith('s') else record_type}"


@contextmanager
def _protected(operation: str, description: str):
    """Make one ITIL delete visible to the shared guard for the length of a call.

    @MX:ANCHOR: every destructive action in this module passes through here.
    @MX:REASON: SafetyGuard challenges only the operation names it knows -- an
    unregistered name sails straight through `is_protected_operation` and the
    delete happens with no token and no reason. The guard exposes no
    registration API: PROTECTED_OPERATIONS is a class attribute that other
    modules read as a whole to reconcile registries, so writing into it
    permanently from here would redefine a global contract this module does not
    own. The name is therefore added for the duration of the check and removed
    afterwards; the challenge itself (token comparison, reason length, audit
    log) still runs unchanged inside SafetyGuard.

    `require_confirmation` is synchronous and awaits nothing, so no other
    coroutine can observe the temporary entry.
    """
    registry = safety_guard.PROTECTED_OPERATIONS
    added = operation not in registry
    if added:
        registry[operation] = description
    try:
        yield
    finally:
        if added:
            registry.pop(operation, None)


def require_itil_delete_confirmation(
    record_type: str,
    itemtype: str,
    record_id: Any,
    confirmation_token: Optional[str],
    reason: Optional[str],
) -> None:
    """Run the shared safety-guard challenge for an ITIL delete."""
    operation = _delete_operation(record_type)
    with _protected(operation, f"Deletar registro de {record_type} permanentemente"):
        require_safety_confirmation(
            operation,
            confirmation_token=confirmation_token,
            reason=reason,
            target_id=record_id,
            target_type=itemtype,
        )


# ---------------------------------------------------------------------------
# Loose input coercion (mirrors the ticket tools)
# ---------------------------------------------------------------------------


def _coerce_int(value: Any) -> Any:
    """Best-effort int coercion for callers that ignore the JSON Schema type."""
    if isinstance(value, bool):  # bool subclasses int -- never coerce silently
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return int(text)
    return value


def _coerce_bool(value: Any, default: bool = False) -> bool:
    """Accept true / "true" / 1 / "sim" for the boolean flags."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("1", "true", "yes", "y", "sim", "on")


async def _resolve_entity(entity_name: str) -> int:
    """Resolve an entity name to its id, listing the alternatives on failure."""
    resolved_id = await entity_resolver.resolve_entity_name(entity_name)
    if resolved_id is not None:
        return resolved_id
    available = await entity_resolver.list_available_entities()
    raise ValidationError(
        f"Entidade '{entity_name}' nao encontrada. Disponiveis: "
        f"{[e['name'] for e in available[:10]]}",
        "entity_name",
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

#: Column headers, in Portuguese without accents, keyed by normalised field.
_HEADERS = {
    "id": "ID",
    "name": "Titulo",
    "status": "Status",
    "state": "Estado",
    "priority": "Prio",
    "urgency": "Urg",
    "impact": "Impacto",
    "requester": "Solicitante",
    "tech_assign": "Tecnico",
    "group_assign": "Grupo",
    "category": "Categoria",
    "type": "Tipo",
    "content": "Descricao",
    "date": "Criado",
    "date_mod": "Atualizado",
    "date_creation": "Criado",
    "code": "Codigo",
    "percent_done": "%",
    "manager": "Gerente",
    "manager_group": "Grupo gestor",
    "plan_start_date": "Inicio plan.",
    "plan_end_date": "Fim plan.",
    "real_start_date": "Inicio real",
    "real_end_date": "Fim real",
    "num": "Numero",
    "supplier": "Fornecedor",
    "begin_date": "Inicio",
    "end_date": "Fim",
    "duration": "Duracao",
    "periodicity": "Periodicidade",
    "totalcost": "Custo",
    "accounting_number": "Conta",
    "is_active": "Ativo",
    "phone": "Telefone",
    "email": "Email",
    "town": "Cidade",
    "website": "Site",
    "country": "Pais",
    "postcode": "CEP",
    "address": "Endereco",
    "registration_number": "Registro",
    "time_to_resolve": "Prazo",
    "solvedate": "Solucao",
    "closedate": "Fechamento",
    "comment": "Comentario",
}

_DATE_KEYS = {
    "date",
    "date_mod",
    "date_creation",
    "begin_date",
    "end_date",
    "plan_start_date",
    "plan_end_date",
    "real_start_date",
    "real_end_date",
    "solvedate",
    "closedate",
    "time_to_resolve",
}

_MONTHS_KEYS = {"duration", "periodicity", "notice"}

#: Column header overrides per record type, where the generic word misleads.
_HEADER_OVERRIDES = {
    "projects": {"name": "Nome"},
    "contracts": {"name": "Nome"},
    "suppliers": {"name": "Nome", "state": "UF"},
}

#: The GLPI column a detail payload carries the record's status in. The list
#: path reads the Search API field id; a direct GET returns the raw column,
#: which is only called `status` for problems and changes.
_DETAIL_STATUS_KEY = {
    "problems": "status",
    "changes": "status",
    "projects": "projectstates_id",
    "contracts": "states_id",
    "suppliers": "is_active",
}


def _header(spec: RecordSpec, key: str) -> str:
    """Column header for one field, honouring the per-type overrides."""
    override = _HEADER_OVERRIDES.get(spec.record_type, {})
    return override.get(key) or _HEADERS.get(key, key)


def _actor(value: Any, max_len: int = 60) -> str:
    """Render a dropdown / actor cell, joining the list shape GLPI returns."""
    if value is None or value in ("", "0", 0):
        return "—"
    if isinstance(value, (list, tuple)):
        parts = [str(v).strip() for v in value if v not in (None, "", 0, "0")]
        text = ", ".join(parts)
    else:
        text = str(value).replace("\r", "").replace("\n", ", ")
    text = text.strip(", ").strip()
    if not text or text == "0":
        return "—"
    return truncate_field(text, max_len) or "—"


def _fmt_status(spec: RecordSpec, value: Any) -> str:
    """Render the column this record type uses as its status."""
    if value in (None, ""):
        return "N/A"
    if spec.status_kind == "enum":
        try:
            return spec.status_label.get(int(value), f"Codigo {value}")
        except (TypeError, ValueError):
            return esc(value)
    if spec.status_kind == "bool":
        return "Sim" if str(value).strip() in ("1", "True", "true") else "Nao"
    return _actor(value)


def _fmt_months(value: Any) -> str:
    """GLPI stores contract duration / periodicity as a month count."""
    if value in (None, ""):
        return "—"
    try:
        months = int(value)
    except (TypeError, ValueError):
        return esc(value)
    if months == 0:
        return "—"
    return f"{months} mes" if months == 1 else f"{months} meses"


def _cell(spec: RecordSpec, key: str, value: Any) -> str:
    """Render one table cell for a normalised field."""
    if key == "id":
        return glpi_id_link(spec.itemtype, value)
    if key == spec.status_key:
        return _fmt_status(spec, value)
    if key == "priority":
        return fmt_priority(value)
    if key == "urgency":
        return fmt_urgency(value)
    if key == "impact":
        return fmt_impact(value)
    if key in _DATE_KEYS:
        return fmt_date(value)
    if key in _MONTHS_KEYS:
        return _fmt_months(value)
    if key == "percent_done":
        return "—" if value in (None, "") else f"{esc(value)}%"
    if key == "is_active":
        return "Sim" if str(value).strip() in ("1", "True", "true") else "Nao"
    if key == "content":
        return truncate_field(value, 300) or "—"
    if key == "name":
        return truncate_field(value, 150) or "—"
    return _actor(value, 80)


def _format_records_list(spec: RecordSpec, payload: Dict[str, Any], args: dict) -> str:
    """Render a paginated Markdown table for one record type."""
    items: List[Dict[str, Any]] = payload.get("items") or []
    # @MX:NOTE: a widened search is still reported as widened, including when it
    # found nothing.
    # @MX:REASON: "nenhum resultado" for a phrase and for a phrase plus every
    # relaxation of it are different facts. Collapsing them lets a caller
    # conclude the record does not exist when only the wording missed.
    notice = payload.get("search_notice")
    if not items:
        empty = f"Nenhum registro encontrado em {spec.label}."
        return f"{empty}\n\n_{notice}_" if notice else empty

    limit = int(payload.get("limit") or args.get("limit") or 10)
    offset = int(payload.get("offset") or args.get("offset") or 0)
    header = page_info(len(items), limit, offset, payload.get("total"))
    if notice:
        header = f"{header}\n\n_{notice}_"

    columns = list(spec.display)
    head = " | ".join(_header(spec, key) for key in columns)
    sep = "|".join("---" for _ in columns)

    rows = []
    for item in items:
        cells = [_cell(spec, key, item.get(key)) for key in columns]
        rows.append("| " + " | ".join(cells) + " |")

    return (
        f"{header}\n\n"
        f"| {head} |\n"
        f"|{sep}|\n" + "\n".join(rows)
    )


def _format_count(spec: RecordSpec, payload: Dict[str, Any]) -> str:
    """Render the answer of the cheap count probe."""
    return (
        f"**{payload.get('total', 0)}** registro(s) em {spec.label} "
        f"correspondem aos filtros informados.\n\n"
        f"_Contagem obtida via sonda `range=0-0` (somente `totalcount`), "
        f"sem paginar resultados._"
    )


#: Detail fields worth showing per record type, beyond the list columns.
_DETAIL_EXTRA = {
    "problems": (
        ("solvedate", "Solucionado em"),
        ("closedate", "Fechado em"),
        ("impactcontent", "Impacto"),
        ("causecontent", "Causa"),
        ("symptomcontent", "Sintomas"),
    ),
    "changes": (
        ("solvedate", "Solucionado em"),
        ("closedate", "Fechado em"),
        ("impactcontent", "Analise de impacto"),
        ("controlistcontent", "Lista de controle"),
        ("rolloutplancontent", "Plano de implantacao"),
        ("backoutplancontent", "Plano de retorno"),
        ("checklistcontent", "Checklist"),
    ),
    "projects": (
        ("comment", "Observacoes"),
        ("code", "Codigo"),
        ("percent_done", "Percentual concluido"),
        ("plan_start_date", "Inicio planejado"),
        ("plan_end_date", "Fim planejado"),
        ("real_start_date", "Inicio real"),
        ("real_end_date", "Fim real"),
    ),
    "contracts": (
        ("totalcost", "Custo total"),
        ("renewal", "Renovacao"),
        ("comment", "Observacoes"),
        ("num", "Numero"),
        ("begin_date", "Inicio"),
        ("duration", "Duracao"),
        ("notice", "Aviso previo"),
        ("periodicity", "Periodicidade"),
        ("billing", "Periodo de faturamento"),
        ("accounting_number", "Numero contabil"),
    ),
    "suppliers": (
        ("comment", "Observacoes"),
        ("phonenumber", "Telefone"),
        ("email", "Email"),
        ("website", "Site"),
        ("address", "Endereco"),
        ("town", "Cidade"),
        ("state", "Estado"),
        ("country", "Pais"),
        ("registration_number", "Registro"),
    ),
}


def _detail_value(key: str, value: Any) -> str:
    """Render one detail line value, stripping the HTML GLPI stores."""
    if value in (None, "", "0", 0):
        return "N/A"
    if key in _DATE_KEYS:
        return fmt_date(value)
    if key in _MONTHS_KEYS:
        return _fmt_months(value)
    if key.endswith("content") or key in ("content", "comment"):
        return truncate_field(value, 2000) or "N/A"
    return esc(value)


def _followups_section(followups: Any) -> str:
    """Render the follow-up conversation under a detail view."""
    if not followups or not isinstance(followups, list):
        return ""
    parts = [f"\n\n## Acompanhamentos ({len(followups)})\n"]
    for followup in followups:
        if not isinstance(followup, dict):
            continue
        date = fmt_date(followup.get("date"))
        author = esc(followup.get("author") or "?")
        private = " _(privado)_" if followup.get("is_private") else ""
        content = truncate_field(followup.get("content", ""), 1500) or "—"
        parts.append(f"\n**{date} — {author}{private}:**\n\n{content}\n")
    return "".join(parts)


def _format_detail(spec: RecordSpec, item: Dict[str, Any]) -> str:
    """Render a single record with everything the GET and enrichments found."""
    if not item:
        return f"Registro nao encontrado em {spec.label}."

    title = strip_html(str(item.get("name") or "")).strip() or "(sem titulo)"
    status_key = _DETAIL_STATUS_KEY.get(spec.record_type, spec.status_key)
    lines = [
        f"# {spec.itemtype} {glpi_id_link(spec.itemtype, item.get('id'))} — {esc(title)}",
        "",
        f"- **Status:** {_fmt_status(spec, item.get(status_key))}",
    ]

    if spec.priority_key:
        lines.append(f"- **Prioridade:** {fmt_priority(item.get('priority'))}")
    if spec.urgency_key:
        lines.append(f"- **Urgencia:** {fmt_urgency(item.get('urgency'))}")
        lines.append(f"- **Impacto:** {fmt_impact(item.get('impact'))}")

    lines.append(f"- **Entidade:** {_actor(item.get('entities_id'), 80)}")

    for key in ("requester", "tech_assign", "group_assign"):
        names = item.get(f"{key}_names")
        if names:
            lines.append(f"- **{_HEADERS.get(key, key)}:** {_actor(names, 120)}")

    if spec.category_key:
        raw_category = (
            item.get("itilcategories_id")
            or item.get("projecttypes_id")
            or item.get("contracttypes_id")
            or item.get("suppliertypes_id")
        )
        lines.append(f"- **Classificacao:** {_actor(raw_category, 80)}")

    for key, label in _DETAIL_EXTRA.get(spec.record_type, ()):
        if key in item:
            lines.append(f"- **{label}:** {_detail_value(key, item.get(key))}")

    lines.append(f"- **Criado:** {fmt_date(item.get('date') or item.get('date_creation'))}")
    lines.append(f"- **Atualizado:** {fmt_date(item.get('date_mod'))}")

    if item.get("linked_ticket_count") is not None:
        ids = item.get("linked_ticket_ids") or []
        suffix = f" (ids: {', '.join(str(i) for i in ids[:20])})" if ids else ""
        lines.append(
            f"- **Chamados vinculados:** {item.get('linked_ticket_count')}{suffix}"
        )

    description = item.get("content")
    if description:
        lines.append("")
        lines.append("## Descricao")
        lines.append("")
        lines.append(truncate_field(description, 4000) or "N/A")

    return "\n".join(lines) + _followups_section(item.get("followups"))


def _format_followups_list(spec: RecordSpec, record_id: Any, followups: Any) -> str:
    """Render the follow-ups of one record as a standalone answer."""
    if not followups:
        return (
            f"Nenhum acompanhamento em {spec.itemtype} "
            f"{record_id}."
        )
    header = f"**{len(followups)} acompanhamento(s)** em {spec.itemtype} {record_id}"
    return header + _followups_section(followups)


def _format_mutation(spec: RecordSpec, result: Dict[str, Any], action: str) -> str:
    """Render the outcome of a write, always naming what actually changed."""
    record_id = result.get("id")
    link = glpi_id_link(spec.itemtype, record_id)
    if action == "create":
        return f"Registro criado em {spec.label}: {spec.itemtype} {link}."
    if action == "delete":
        mode = "purgado (removido definitivamente)" if result.get("purged") else "movido para a lixeira"
        return f"{spec.itemtype} {record_id} {mode}."
    if action == "add_followup":
        return (
            f"Acompanhamento {result.get('followup_id')} adicionado em "
            f"{spec.itemtype} {link}."
        )
    if action == "link_ticket":
        return (
            f"Chamado {result.get('ticket_id')} vinculado a {spec.itemtype} {link} "
            f"via {result.get('link_itemtype')}."
        )
    return f"{spec.itemtype} {link} atualizado."


# ---------------------------------------------------------------------------
# Tool 1: glpi_search_itil_records
# ---------------------------------------------------------------------------


async def search_itil_records(
    record_type: str,
    query: Optional[str] = None,
    status: Optional[Any] = None,
    priority: Optional[int] = None,
    urgency: Optional[int] = None,
    category: Optional[Any] = None,
    entity_id: Optional[int] = None,
    entity_name: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    date_field: Optional[str] = None,
    sort_by: Optional[str] = None,
    order: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
    count_only: bool = False,
) -> Any:
    """
    Search / list ITIL records that are not incidents.

    Args:
        record_type: problems, changes, projects, contracts or suppliers.
        query: Free text matched against the title / name (min 2 chars).
        status: Problem and change take the status name or code; project and
            contract take the state name or id; supplier takes ativo/inativo.
        priority: 1-6, for problems, changes and projects.
        urgency: 1-5, for problems and changes only.
        category: ITIL category (problem/change), project type, contract type
            or supplier type -- name or id.
        entity_id: Entity id, searched recursively over child entities.
        entity_name: Entity name, resolved to entity_id automatically.
        date_from: Lower bound of the date range.
        date_to: Upper bound of the date range.
        date_field: Which date column the range applies to. Defaults to the
            opening date (problem/change), creation date (project),
            begin_date (contract) or date_creation (supplier).
        sort_by: Field name or id to sort by. Defaults to last update.
        order: ASC or DESC.
        limit: Max rows (default 10, hard cap 50).
        offset: Pagination offset.
        count_only: Return only the total, using a range=0-0 probe that reads
            `totalcount` without fetching or paginating any row.

    Returns:
        A Markdown table (or a one-line total when count_only is set).
    """
    try:
        try:
            spec = get_spec(record_type)
        except ValidationError as exc:
            return create_mcp_error(
                exc.message,
                f"record_type deve ser um de: {list(RECORD_TYPES)}",
                "Exemplo: glpi_search_itil_records(record_type='problems')",
            )

        priority = _coerce_int(priority)
        urgency = _coerce_int(urgency)
        entity_id = _coerce_int(entity_id)
        count_only = _coerce_bool(count_only)

        logger.info(
            f"search_itil_records: record_type={spec.record_type}, query={query}, "
            f"status={status}, limit={limit}, offset={offset}, count_only={count_only}"
        )

        if entity_name:
            entity_id = await _resolve_entity(entity_name)
            logger.info(
                f"search_itil_records: entity_name '{entity_name}' -> id {entity_id}"
            )

        if query is not None:
            query = input_sanitizer.sanitize_search_query(query)
            if not query or len(query) < 2:
                raise ValidationError(
                    "A busca textual precisa de pelo menos 2 caracteres", "query"
                )

        if priority is not None:
            if not spec.priority_key:
                raise ValidationError(
                    f"{spec.label} nao possui prioridade no GLPI.", "priority"
                )
            if not isinstance(priority, int) or priority < 1 or priority > 6:
                raise ValidationError(
                    "priority deve ser um inteiro entre 1 e 6", "priority"
                )

        if urgency is not None:
            if not spec.urgency_key:
                raise ValidationError(
                    f"{spec.label} nao possui urgencia no GLPI. "
                    "Disponivel apenas para problems e changes.",
                    "urgency",
                )
            if not isinstance(urgency, int) or urgency < 1 or urgency > 5:
                raise ValidationError(
                    "urgency deve ser um inteiro entre 1 e 5", "urgency"
                )

        if date_from or date_to:
            date_from, date_to = DateTimeHelper.parse_date_range(date_from, date_to)

        offset, limit = PaginationHelper.validate_pagination_params(offset, limit)
        limit = min(int(limit), MAX_LIMIT)

        filters: Dict[str, Any] = {
            "query": query,
            "status": status,
            "priority": priority,
            "urgency": urgency,
            "category": category,
            "entity_id": entity_id,
            "date_from": date_from,
            "date_to": date_to,
            "date_field": date_field,
            "sort_by": sort_by,
            "order": order,
        }

        if count_only:
            payload = await itil_service.count_records(spec.record_type, **filters)
            return _format_count(spec, payload)

        payload = await itil_service.search_records(
            spec.record_type, limit=limit, offset=offset, **filters
        )
        return _format_records_list(spec, payload, {"limit": limit, "offset": offset})

    except (ValidationError, GLPIError) as exc:
        logger.error(f"search_itil_records error: {exc.message}")
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error(f"search_itil_records unexpected error: {exc}")
        raise GLPIError(500, f"Falha ao buscar registros ITIL: {exc}")


# ---------------------------------------------------------------------------
# Tool 2: glpi_manage_itil_records
# ---------------------------------------------------------------------------


async def manage_itil_records(
    record_type: str,
    action: str,
    record_id: Optional[int] = None,
    # create / update
    name: Optional[str] = None,
    content: Optional[str] = None,
    comment: Optional[str] = None,
    status: Optional[Any] = None,
    priority: Optional[int] = None,
    urgency: Optional[int] = None,
    impact: Optional[int] = None,
    category_id: Optional[int] = None,
    state_id: Optional[int] = None,
    entity_id: Optional[int] = None,
    entity_name: Optional[str] = None,
    begin_date: Optional[str] = None,
    end_date: Optional[str] = None,
    duration: Optional[int] = None,
    periodicity: Optional[int] = None,
    num: Optional[str] = None,
    manager_id: Optional[int] = None,
    percent_done: Optional[int] = None,
    code: Optional[str] = None,
    is_active: Optional[Any] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    website: Optional[str] = None,
    fields: Optional[Dict[str, Any]] = None,
    # follow-ups
    followup_content: Optional[str] = None,
    is_private: bool = False,
    # link_ticket
    ticket_id: Optional[int] = None,
    # delete safety
    confirmation_token: Optional[str] = None,
    reason: Optional[str] = None,
    purge: bool = False,
) -> Any:
    """
    Read and mutate a single ITIL record that is not an incident.

    Args:
        record_type: problems, changes, projects, contracts or suppliers.
        action: get, create, update, delete, add_followup, get_followups or
            link_ticket. Follow-ups and link_ticket exist only for problems
            and changes.
        record_id: Target record id (every action except create).
        name: Title / name (create, update).
        content: Description (create, update).
        comment: Free-form comment (create, update).
        status: Status / state / active flag, per record type (create, update).
        priority: 1-6 (problems, changes, projects).
        urgency: 1-5 (problems, changes).
        impact: 1-5 (problems, changes).
        category_id: ITIL category id, project type id, contract type id or
            supplier type id, per record type.
        state_id: Dropdown state id (projects, contracts).
        entity_id: Entity id.
        entity_name: Entity name, resolved to entity_id automatically.
        begin_date: Contract start date, or a project's planned start.
        end_date: Project planned end date.
        duration: Contract duration in months.
        periodicity: Contract periodicity in months.
        num: Contract number.
        manager_id: Manager user id (projects).
        percent_done: Completion percentage (projects).
        code: Project code.
        is_active: Supplier active flag.
        email: Supplier email.
        phone: Supplier phone.
        website: Supplier website.
        fields: Raw GLPI column overrides for anything not named above.
        followup_content: Follow-up text (add_followup).
        is_private: Whether the follow-up is private (add_followup).
        ticket_id: Ticket to attach (link_ticket).
        confirmation_token: Safety token (delete).
        reason: Reason for the deletion, min 10 chars (delete).
        purge: Delete permanently instead of moving to the bin (delete).

    Returns:
        A Markdown answer describing the record or the effect of the write.
    """
    try:
        try:
            record_key = resolve_record_type(record_type)
        except ValidationError as exc:
            return create_mcp_error(
                exc.message,
                f"record_type deve ser um de: {list(RECORD_TYPES)}",
                "Exemplo: glpi_manage_itil_records(record_type='problems', "
                "action='get', record_id=42)",
            )
        spec = get_spec(record_key)

        if action not in MANAGE_ACTIONS:
            return create_mcp_error(
                f"Acao '{action}' desconhecida",
                f"Esperado um de: {MANAGE_ACTIONS}",
                "Exemplo: glpi_manage_itil_records(record_type='changes', "
                "action='get', record_id=7)",
            )

        requirement = _ACTION_REQUIREMENTS.get(action)
        if requirement == "followups" and not spec.followups:
            return create_mcp_error(
                f"A acao '{action}' nao existe para {spec.label}",
                "Acompanhamentos existem apenas para problems e changes",
                "Exemplo: glpi_manage_itil_records(record_type='problems', "
                "action='get_followups', record_id=42)",
            )
        if requirement == "link" and not spec.link_itemtype:
            return create_mcp_error(
                f"A acao '{action}' nao existe para {spec.label}",
                "Vinculo de chamado existe apenas para problems e changes",
                "Exemplo: glpi_manage_itil_records(record_type='changes', "
                "action='link_ticket', record_id=7, ticket_id=123)",
            )

        record_id = _coerce_int(record_id)
        priority = _coerce_int(priority)
        urgency = _coerce_int(urgency)
        impact = _coerce_int(impact)
        category_id = _coerce_int(category_id)
        state_id = _coerce_int(state_id)
        entity_id = _coerce_int(entity_id)
        manager_id = _coerce_int(manager_id)
        percent_done = _coerce_int(percent_done)
        duration = _coerce_int(duration)
        periodicity = _coerce_int(periodicity)
        ticket_id = _coerce_int(ticket_id)
        is_private = _coerce_bool(is_private)
        purge = _coerce_bool(purge)

        logger.info(
            f"manage_itil_records: record_type={spec.record_type}, action={action}, "
            f"record_id={record_id}"
        )

        if action in ACTIONS_REQUIRING_RECORD_ID:
            check = validate_positive_int(record_id, "record_id")
            if not check["valid"]:
                return create_mcp_error(
                    check["error"],
                    "record_id deve ser um inteiro positivo",
                    "Exemplo: glpi_manage_itil_records(record_type='problems', "
                    "action='get', record_id=42)",
                )
            record_id = check["value"]

        if entity_name and action in ("create", "update"):
            entity_id = await _resolve_entity(entity_name)
            logger.info(
                f"manage_itil_records: entity_name '{entity_name}' -> id {entity_id}"
            )

        # --- read actions ---

        if action == "get":
            item = await itil_service.get_record(spec.record_type, record_id)
            return _format_detail(spec, item)

        if action == "get_followups":
            followups = await itil_service.get_followups(spec.record_type, record_id)
            return _format_followups_list(spec, record_id, followups)

        # --- write actions ---

        if action == "add_followup":
            text = followup_content or content
            if not text or len(str(text).strip()) < 5:
                raise ValidationError(
                    "followup_content deve ter pelo menos 5 caracteres",
                    "followup_content",
                )
            text = input_sanitizer.sanitize_string(str(text), allow_html=True)
            result = await itil_service.add_followup(
                spec.record_type, record_id, text, is_private=is_private
            )
            return _format_mutation(spec, result, action)

        if action == "link_ticket":
            check_ticket = validate_positive_int(ticket_id, "ticket_id")
            if not check_ticket["valid"]:
                return create_mcp_error(
                    check_ticket["error"],
                    "ticket_id deve ser um inteiro positivo",
                    "Exemplo: glpi_manage_itil_records(record_type='problems', "
                    "action='link_ticket', record_id=42, ticket_id=123)",
                )
            result = await itil_service.link_ticket(
                spec.record_type, record_id, check_ticket["value"]
            )
            return _format_mutation(spec, result, action)

        if action == "delete":
            require_itil_delete_confirmation(
                spec.record_type,
                spec.itemtype,
                record_id,
                confirmation_token,
                reason,
            )
            result = await itil_service.delete_record(
                spec.record_type, record_id, purge=purge
            )
            return _format_mutation(spec, result, action)

        payload = _write_payload(
            name=name,
            content=content,
            comment=comment,
            status=status,
            priority=priority,
            urgency=urgency,
            impact=impact,
            category_id=category_id,
            state_id=state_id,
            entity_id=entity_id,
            begin_date=begin_date,
            end_date=end_date,
            duration=duration,
            periodicity=periodicity,
            num=num,
            manager_id=manager_id,
            percent_done=percent_done,
            code=code,
            is_active=is_active,
            email=email,
            phone=phone,
            website=website,
            fields=fields,
        )

        if action == "create":
            result = await itil_service.create_record(spec.record_type, **payload)
            return _format_mutation(spec, result, action)

        if action == "update":
            item = await itil_service.update_record(
                spec.record_type, record_id, **payload
            )
            return _format_detail(spec, item)

        # Unreachable given the action validation above, kept as a guard.
        return create_mcp_error(
            f"Acao '{action}' nao tratada",
            f"Esperado um de: {MANAGE_ACTIONS}",
            "Exemplo: glpi_manage_itil_records(record_type='problems', "
            "action='get', record_id=42)",
        )

    except (NotFoundError, ValidationError) as exc:
        logger.error(f"manage_itil_records ({action}) error: {exc.message}")
        raise
    except GLPIError as exc:
        logger.error(f"manage_itil_records ({action}) GLPI error: {exc.message}")
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error(f"manage_itil_records ({action}) unexpected error: {exc}")
        raise GLPIError(500, f"Falha ao executar '{action}' em registros ITIL: {exc}")


def _write_payload(**kwargs: Any) -> Dict[str, Any]:
    """Drop unset arguments and sanitise the free-text ones.

    Only keys the caller actually supplied reach the service, so an update
    never blanks a field the caller never mentioned.
    """
    payload: Dict[str, Any] = {}
    for key, value in kwargs.items():
        if value is None:
            continue
        if key in ("name", "content", "comment", "num", "code") and isinstance(
            value, str
        ):
            # content/comment sao texto rico do GLPI; name/num/code sao escalares.
            value = input_sanitizer.sanitize_string(
                value, allow_html=key in ("content", "comment")
            )
        payload[key] = value
    return payload
