"""
ITIL records beyond the incident: Problem, Change, Project, Contract, Supplier.

Why this module exists
----------------------
The MCP only ever spoke about Ticket. Everything an outsourced IT operation
reports on monthly -- recurring root causes (Problem), planned interventions
(Change), delivery workstreams (Project), what the customer actually signed
(Contract) and who supplies it (Supplier) -- was invisible. This service adds
those five itemtypes behind one query surface and one mutation surface.

@MX:ANCHOR: single place where an ITIL-adjacent itemtype is described.
@MX:REASON: every entity here needs the same four things (a field-id map, a
criteria builder, a sort resolver and a row normaliser). Writing them once per
itemtype is how the ticket path grew its divergences; a table of RecordSpec
keeps the behaviour identical and makes adding a sixth type a data change.

Field ids
---------
The numbers below were read from the GLPI 11.0.6 PHP sources of the target
instance, not guessed:

  * Problem / Change inherit CommonITILObject::getSearchOptionsMain() and
    getSearchOptionsActors(), so they share Ticket's core numbering
    (1 title, 2 id, 3 priority, 4 requester, 5 technician, 7 category,
    8 technician group, 10 urgency, 11 impact, 12 status, 15 opening date,
    16 close date, 17 solve date, 18 time to resolve, 19 last update,
    21 description, 22 writer, 80 entity).
  * Project, Contract and Supplier declare their own rawSearchOptions() and do
    NOT follow that numbering -- Supplier field 12 is a postal "State", not a
    status, and Contract field 3 is the contract number. Reusing the ticket
    map for them would filter on the wrong column while still returning rows.

Two traps found while reading the sources, both encoded below:

  * Search option 82 (`sla_ttr_is_late`) is declared for every CommonITILObject
    but the column exists only on glpi_tickets -- glpi_problems and
    glpi_changes do not have it. It is deliberately absent from the maps here;
    the real deadline lives in field 18 (`time_to_resolve`), which does exist.
  * Contract field 20 (`end_date`) has no column either: GLPI computes it from
    begin_date + duration as a `date_delay` datatype. It stays available for
    display, sorting and filtering (the search engine understands the datatype)
    but the default date range uses begin_date, which is a real column.

Static maps are still reconciled at runtime against listSearchOptions, exactly
like the ticket path, because ids move across versions, profiles and plugins.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional, Tuple

from src.formatters.markdown_helpers import strip_html
from src.models.exceptions import GLPIError, NotFoundError, ValidationError
from src.services.dropdown_cache import dropdown_cache
from src.services.glpi_client import emit_criteria, glpi_client
from src.services.search_options import search_options_cache
from src.utils.helpers import logger
from src.utils.text_search import (
    build_text_criteria,
    describe_stage,
    run_text_search,
    significant_terms,
    split_terms,
)
from src.utils.search_criteria import (
    actor_criterion,
    as_field_id,
    normalize_order,
    resolve_sort_field,
)

# ---------------------------------------------------------------------------
# Status vocabularies
# ---------------------------------------------------------------------------

# Problem::getAllStatusArray() -- GLPI 11.0.6.
PROBLEM_STATUS = {
    "new": 1,
    "accepted": 7,
    "assigned": 2,
    "planned": 3,
    "pending": 4,
    "solved": 5,
    "observed": 8,
    "closed": 6,
}

PROBLEM_STATUS_LABEL = {
    1: "Novo",
    2: "Atribuido",
    3: "Planejado",
    4: "Pendente",
    5: "Solucionado",
    6: "Fechado",
    7: "Aceito",
    8: "Em observacao",
}

# Change::getAllStatusArray() -- GLPI 11.0.6. A change has its own workflow
# (evaluation / approval / test / qualification) that a ticket never has, and
# reuses codes 5 and 8 with different meanings ("Applied", "Review"). Both the
# GLPI wording and the ticket-like synonym are accepted on input so a caller
# who says "solved" is not silently ignored.
CHANGE_STATUS = {
    "new": 1,
    "evaluation": 9,
    "approval": 10,
    "accepted": 7,
    "pending": 4,
    "test": 11,
    "qualification": 12,
    "applied": 5,
    "solved": 5,
    "review": 8,
    "observed": 8,
    "closed": 6,
    "canceled": 14,
    "cancelled": 14,
    "refused": 13,
}

CHANGE_STATUS_LABEL = {
    1: "Novo",
    4: "Pendente",
    5: "Aplicado",
    6: "Fechado",
    7: "Aceito",
    8: "Revisao",
    9: "Avaliacao",
    10: "Aprovacao",
    11: "Teste",
    12: "Qualificacao",
    13: "Recusado",
    14: "Cancelado",
}

# Supplier has no status enum: field 7 is the boolean `is_active`.
SUPPLIER_ACTIVE = {
    "active": 1,
    "ativo": 1,
    "yes": 1,
    "true": 1,
    "1": 1,
    "inactive": 0,
    "inativo": 0,
    "no": 0,
    "false": 0,
    "0": 0,
}


# ---------------------------------------------------------------------------
# Field maps (validated against the GLPI 11.0.6 sources -- see module docstring)
# ---------------------------------------------------------------------------

PROBLEM_FIELD: Dict[str, int] = {
    "name": 1,
    "id": 2,
    "priority": 3,
    "requester": 4,
    "tech_assign": 5,
    "supplier_assign": 6,
    "category": 7,
    "group_assign": 8,
    "urgency": 10,
    "impact": 11,
    "status": 12,
    "date": 15,
    "closedate": 16,
    "solvedate": 17,
    "time_to_resolve": 18,
    "date_mod": 19,
    "content": 21,
    "writer": 22,
    "entities_id": 80,
}

CHANGE_FIELD: Dict[str, int] = dict(PROBLEM_FIELD)

# Only own-table columns get a uid hint: those are the ones the live catalogue
# can re-derive without ambiguity. Actor columns (4/5/8) and the category reach
# the catalogue through joins, so they are checked for existence but never
# rewritten -- replacing a working id with a guess is worse than the drift.
_ITIL_UID_HINTS = {
    "name": "{t}.name",
    "id": "{t}.id",
    "priority": "{t}.priority",
    "urgency": "{t}.urgency",
    "impact": "{t}.impact",
    "status": "{t}.status",
    "date": "{t}.date",
    "closedate": "{t}.closedate",
    "solvedate": "{t}.solvedate",
    "time_to_resolve": "{t}.time_to_resolve",
    "date_mod": "{t}.date_mod",
    "content": "{t}.content",
}


def _uid_hints(itemtype: str, template: Dict[str, str]) -> Dict[str, str]:
    """Expand a uid-hint template for one itemtype."""
    return {key: value.format(t=itemtype) for key, value in template.items()}


PROJECT_FIELD: Dict[str, int] = {
    "name": 1,
    "id": 2,
    "priority": 3,
    "code": 4,
    "percent_done": 5,
    "plan_start_date": 7,
    "plan_end_date": 8,
    "real_start_date": 9,
    "real_end_date": 10,
    "state": 12,
    "type": 14,
    "date": 15,
    "comment": 16,
    "date_mod": 19,
    "content": 21,
    "manager": 24,
    "manager_group": 49,
    "entities_id": 80,
    "date_creation": 121,
}

_PROJECT_UID_HINTS = {
    "name": "Project.name",
    "id": "Project.id",
    "priority": "Project.priority",
    "code": "Project.code",
    "percent_done": "Project.percent_done",
    "plan_start_date": "Project.plan_start_date",
    "plan_end_date": "Project.plan_end_date",
    "real_start_date": "Project.real_start_date",
    "real_end_date": "Project.real_end_date",
    "date": "Project.date",
    "comment": "Project.comment",
    "date_mod": "Project.date_mod",
    "content": "Project.content",
    "date_creation": "Project.date_creation",
}

CONTRACT_FIELD: Dict[str, int] = {
    "name": 1,
    "id": 2,
    "num": 3,
    "type": 4,
    "begin_date": 5,
    "duration": 6,
    "notice": 7,
    "accounting_number": 10,
    "totalcost": 11,
    "expiration": 12,
    "comment": 16,
    "date_mod": 19,
    "end_date": 20,
    "periodicity": 21,
    "billing": 22,
    "renewal": 23,
    "supplier": 29,
    "state": 31,
    "entities_id": 80,
    "date_creation": 121,
}

_CONTRACT_UID_HINTS = {
    "name": "Contract.name",
    "id": "Contract.id",
    "num": "Contract.num",
    "begin_date": "Contract.begin_date",
    "duration": "Contract.duration",
    "notice": "Contract.notice",
    "accounting_number": "Contract.accounting_number",
    "comment": "Contract.comment",
    "date_mod": "Contract.date_mod",
    "periodicity": "Contract.periodicity",
    "billing": "Contract.billing",
    "renewal": "Contract.renewal",
    "date_creation": "Contract.date_creation",
}

SUPPLIER_FIELD: Dict[str, int] = {
    "name": 1,
    "id": 2,
    "address": 3,
    "website": 4,
    "phone": 5,
    "email": 6,
    "is_active": 7,
    "contact": 8,
    "type": 9,
    "fax": 10,
    "town": 11,
    "state": 12,
    "country": 13,
    "postcode": 14,
    "comment": 16,
    "date_mod": 19,
    "registration_number": 70,
    "entities_id": 80,
    "date_creation": 121,
}

_SUPPLIER_UID_HINTS = {
    "name": "Supplier.name",
    "id": "Supplier.id",
    "address": "Supplier.address",
    "website": "Supplier.website",
    "phone": "Supplier.phonenumber",
    "email": "Supplier.email",
    "is_active": "Supplier.is_active",
    "fax": "Supplier.fax",
    "town": "Supplier.town",
    "state": "Supplier.state",
    "country": "Supplier.country",
    "postcode": "Supplier.postcode",
    "comment": "Supplier.comment",
    "date_mod": "Supplier.date_mod",
    "registration_number": "Supplier.registration_number",
    "date_creation": "Supplier.date_creation",
}


# ---------------------------------------------------------------------------
# Record specifications
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordSpec:
    """Everything the generic code paths need to know about one itemtype."""

    record_type: str
    itemtype: str
    label: str
    fields: Dict[str, int]
    uid_hints: Dict[str, str]
    display: Tuple[str, ...]
    default_sort: str
    date_field: str
    #: enum | dropdown | bool | none -- decides how `status` becomes a criterion
    status_kind: str = "none"
    status_map: Dict[str, int] = dc_field(default_factory=dict)
    status_label: Dict[int, str] = dc_field(default_factory=dict)
    status_key: str = "status"
    priority_key: Optional[str] = None
    urgency_key: Optional[str] = None
    #: the classification dropdown this type answers `category` with
    category_key: Optional[str] = None
    entity_key: str = "entities_id"
    text_key: str = "name"
    #: every column a free-text query searches; defaults to `text_key` alone
    text_keys: Tuple[str, ...] = ()
    #: keys whose Search API value is a raw user id needing a name lookup
    user_keys: Tuple[str, ...] = ()
    group_keys: Tuple[str, ...] = ()
    followups: bool = False
    link_itemtype: Optional[str] = None
    link_parent_field: Optional[str] = None
    create_required: Tuple[str, ...] = ("name",)
    #: GLPI columns accepted on create/update, mapped from tool argument names
    writable: Dict[str, str] = dc_field(default_factory=dict)

    def field_id(self, key: str) -> int:
        return self.fields[key]


_COMMON_ITIL_DISPLAY = (
    "id",
    "name",
    "status",
    "priority",
    "urgency",
    "requester",
    "tech_assign",
    "group_assign",
    "category",
    "content",
    "date",
    "date_mod",
)

_ITIL_WRITABLE = {
    "name": "name",
    "content": "content",
    "status": "status",
    "priority": "priority",
    "urgency": "urgency",
    "impact": "impact",
    "category_id": "itilcategories_id",
    "entity_id": "entities_id",
}

RECORD_SPECS: Dict[str, RecordSpec] = {
    "problems": RecordSpec(
        record_type="problems",
        itemtype="Problem",
        label="problemas",
        fields=PROBLEM_FIELD,
        uid_hints=_uid_hints("Problem", _ITIL_UID_HINTS),
        display=_COMMON_ITIL_DISPLAY,
        text_keys=("name", "content"),
        default_sort="date_mod",
        date_field="date",
        status_kind="enum",
        status_map=PROBLEM_STATUS,
        status_label=PROBLEM_STATUS_LABEL,
        priority_key="priority",
        urgency_key="urgency",
        category_key="category",
        user_keys=("requester", "tech_assign"),
        group_keys=("group_assign",),
        followups=True,
        link_itemtype="Problem_Ticket",
        link_parent_field="problems_id",
        create_required=("name", "content"),
        writable=_ITIL_WRITABLE,
    ),
    "changes": RecordSpec(
        record_type="changes",
        itemtype="Change",
        label="mudancas",
        fields=CHANGE_FIELD,
        uid_hints=_uid_hints("Change", _ITIL_UID_HINTS),
        display=_COMMON_ITIL_DISPLAY,
        text_keys=("name", "content"),
        default_sort="date_mod",
        date_field="date",
        status_kind="enum",
        status_map=CHANGE_STATUS,
        status_label=CHANGE_STATUS_LABEL,
        priority_key="priority",
        urgency_key="urgency",
        category_key="category",
        user_keys=("requester", "tech_assign"),
        group_keys=("group_assign",),
        followups=True,
        link_itemtype="Change_Ticket",
        link_parent_field="changes_id",
        create_required=("name", "content"),
        writable=_ITIL_WRITABLE,
    ),
    "projects": RecordSpec(
        record_type="projects",
        itemtype="Project",
        label="projetos",
        fields=PROJECT_FIELD,
        uid_hints=_PROJECT_UID_HINTS,
        display=(
            "id",
            "name",
            "code",
            "state",
            "type",
            "priority",
            "percent_done",
            "manager",
            "plan_start_date",
            "plan_end_date",
            "date_mod",
        ),
        text_keys=("name", "content", "comment"),
        default_sort="date_mod",
        date_field="date",
        # A project's state is a dropdown row (glpi_projectstates), not an enum,
        # so it is matched by name or id like any other dropdown.
        status_kind="dropdown",
        status_key="state",
        priority_key="priority",
        category_key="type",
        create_required=("name",),
        writable={
            "name": "name",
            "content": "content",
            "comment": "comment",
            "priority": "priority",
            "code": "code",
            "percent_done": "percent_done",
            "entity_id": "entities_id",
            "manager_id": "users_id",
            "category_id": "projecttypes_id",
            "state_id": "projectstates_id",
            "begin_date": "plan_start_date",
            "end_date": "plan_end_date",
        },
    ),
    "contracts": RecordSpec(
        record_type="contracts",
        itemtype="Contract",
        label="contratos",
        fields=CONTRACT_FIELD,
        uid_hints=_CONTRACT_UID_HINTS,
        display=(
            "id",
            "name",
            "num",
            "type",
            "supplier",
            "begin_date",
            "end_date",
            "duration",
            "periodicity",
            "state",
        ),
        text_keys=("name", "num", "comment"),
        default_sort="date_mod",
        # begin_date is a real column; end_date (field 20) is computed by GLPI
        # from begin_date + duration, so it is opt-in via date_field.
        date_field="begin_date",
        status_kind="dropdown",
        status_key="state",
        category_key="type",
        create_required=("name",),
        writable={
            "name": "name",
            "comment": "comment",
            "num": "num",
            "entity_id": "entities_id",
            "category_id": "contracttypes_id",
            "state_id": "states_id",
            "begin_date": "begin_date",
            "duration": "duration",
            "notice": "notice",
            "periodicity": "periodicity",
            "billing": "billing",
            "accounting_number": "accounting_number",
        },
    ),
    "suppliers": RecordSpec(
        record_type="suppliers",
        itemtype="Supplier",
        label="fornecedores",
        fields=SUPPLIER_FIELD,
        uid_hints=_SUPPLIER_UID_HINTS,
        display=(
            "id",
            "name",
            "type",
            "is_active",
            "phone",
            "email",
            "town",
            "state",
            "website",
            "date_mod",
        ),
        text_keys=("name", "comment", "address", "contact"),
        default_sort="name",
        date_field="date_creation",
        # A supplier has no status: field 7 is the boolean `is_active`.
        status_kind="bool",
        status_key="is_active",
        category_key="type",
        create_required=("name",),
        writable={
            "name": "name",
            "comment": "comment",
            "entity_id": "entities_id",
            "category_id": "suppliertypes_id",
            "is_active": "is_active",
            "phone": "phonenumber",
            "email": "email",
            "website": "website",
            "address": "address",
            "town": "town",
            "registration_number": "registration_number",
        },
    ),
}

RECORD_TYPES: Tuple[str, ...] = tuple(RECORD_SPECS.keys())

#: Aliases a caller is likely to type instead of the canonical plural key.
_RECORD_ALIASES = {
    "problem": "problems",
    "problema": "problems",
    "problemas": "problems",
    "change": "changes",
    "mudanca": "changes",
    "mudancas": "changes",
    "project": "projects",
    "projeto": "projects",
    "projetos": "projects",
    "contract": "contracts",
    "contrato": "contracts",
    "contratos": "contracts",
    "supplier": "suppliers",
    "fornecedor": "suppliers",
    "fornecedores": "suppliers",
}


def resolve_record_type(record_type: Any) -> str:
    """Normalise a caller-supplied record type, raising on anything unknown.

    Unknown types fail loudly instead of defaulting: silently searching
    problems when the caller asked for changes would return a plausible table
    of the wrong entity, which is worse than an error.
    """
    if record_type is None:
        raise ValidationError(
            f"record_type e obrigatorio. Use um de: {list(RECORD_TYPES)}",
            "record_type",
        )
    key = str(record_type).strip().lower()
    if key in RECORD_SPECS:
        return key
    alias = _RECORD_ALIASES.get(key)
    if alias:
        return alias
    raise ValidationError(
        f"record_type '{record_type}' invalido. Use um de: {list(RECORD_TYPES)}",
        "record_type",
    )


def get_spec(record_type: Any) -> RecordSpec:
    """Return the RecordSpec for a caller-supplied record type."""
    return RECORD_SPECS[resolve_record_type(record_type)]


# ---------------------------------------------------------------------------
# Lazy reconciliation against the live search-options catalogue
# ---------------------------------------------------------------------------

_sync_lock = asyncio.Lock()
_synced: set = set()


async def ensure_field_map_synced(spec: RecordSpec) -> None:
    """Reconcile one itemtype's static field map with this instance, once.

    @MX:NOTE: best-effort by construction -- a failure here must never turn a
    working search into an error.
    @MX:REASON: the static map is what the code ships with and is derived from
    the target GLPI sources. Reconciliation exists to absorb version, profile
    and plugin drift across the instances this codebase serves, so it is a
    safety net and not a dependency.
    """
    if spec.itemtype in _synced:
        return

    async with _sync_lock:
        if spec.itemtype in _synced:
            return
        try:
            await search_options_cache.reconcile(
                spec.itemtype, spec.fields, spec.uid_hints
            )
        except Exception as exc:  # noqa: BLE001 -- never block a search
            logger.warning(
                f"{spec.itemtype} field reconciliation skipped: {exc}"
            )
        finally:
            _synced.add(spec.itemtype)


def reset_field_sync() -> None:
    """Forget which itemtypes were reconciled (tests and cache invalidation)."""
    _synced.clear()


# ---------------------------------------------------------------------------
# Criteria, sorting and row normalisation
# ---------------------------------------------------------------------------


def normalize_status(spec: RecordSpec, value: Any) -> Any:
    """Translate a caller's status into what this itemtype's column expects.

    Enum types (problem, change) take an integer code; dropdown types
    (project state, contract state) take a name or a row id; a supplier takes
    the boolean `is_active`.
    """
    if value is None or value == "":
        return None

    if spec.status_kind == "enum":
        numeric = as_field_id(value)
        if numeric is not None:
            return numeric
        code = spec.status_map.get(str(value).strip().lower())
        if code is None:
            raise ValidationError(
                f"status '{value}' nao existe em {spec.label}. "
                f"Valores aceitos: {sorted(set(spec.status_map))}",
                "status",
            )
        return code

    if spec.status_kind == "bool":
        if isinstance(value, bool):
            return 1 if value else 0
        flag = SUPPLIER_ACTIVE.get(str(value).strip().lower())
        if flag is None:
            raise ValidationError(
                f"status '{value}' invalido para {spec.label}. "
                "Use ativo/inativo (o GLPI guarda apenas is_active).",
                "status",
            )
        return flag

    # dropdown: a name matches loosely, an id matches exactly
    return value


def text_field_ids(spec: RecordSpec) -> List[int]:
    """Field ids a free-text query is matched against for this record type.

    @MX:NOTE: a supplier's notes column is searchable, not just its name.
    @MX:REASON: `text_key` alone meant "internet" never found the supplier
    whose name is a company and whose service is described in the comment —
    the caller sees a populated field and reasonably expects it to be searched.
    """
    keys = spec.text_keys or (spec.text_key,)
    ids: List[int] = []
    for key in keys:
        field = spec.fields.get(key)
        if field is not None and field not in ids:
            ids.append(field)
    return ids or [spec.fields[spec.text_key]]


def build_criteria(
    spec: RecordSpec,
    params: Dict[str, Any],
    text_override: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Build the Search API criteria shared by listing, text search and counting.

    @MX:ANCHOR: single source of truth for ITIL record filters.
    @MX:REASON: the ticket path once built criteria in two places and the text
    search branch quietly dropped every filter but the query. One builder,
    used by list / search / count alike, makes that class of bug impossible
    here -- including for the cheap count probe, which must count exactly what
    the list would return.
    """
    criteria: List[Dict[str, Any]] = []
    fields = spec.fields

    # @MX:NOTE: `text_override` carries groups already built by the escalation
    # ladder, so listing and counting filter identically at every stage.
    # @MX:REASON: a count that re-derives the text filter answers about a
    # different set than the list it heads, and the discrepancy reads as data.
    if text_override is not None:
        criteria.extend(text_override)
    else:
        query = params.get("query")
        if query not in (None, ""):
            terms, _ = split_terms(str(query).strip())
            criteria.extend(
                build_text_criteria(
                    text_field_ids(spec),
                    significant_terms(terms) if len(terms) > 1 else terms,
                    mode="all",
                )
            )

    status = params.get("status")
    if status not in (None, ""):
        resolved = normalize_status(spec, status)
        status_field = fields[spec.status_key]
        if spec.status_kind == "dropdown":
            criteria.append(actor_criterion(status_field, resolved))
        else:
            criteria.append(
                {"field": status_field, "searchtype": "equals", "value": resolved}
            )

    priority = params.get("priority")
    if priority not in (None, "") and spec.priority_key:
        criteria.append(
            {
                "field": fields[spec.priority_key],
                "searchtype": "equals",
                "value": priority,
            }
        )

    urgency = params.get("urgency")
    if urgency not in (None, "") and spec.urgency_key:
        criteria.append(
            {
                "field": fields[spec.urgency_key],
                "searchtype": "equals",
                "value": urgency,
            }
        )

    category = params.get("category")
    if category not in (None, "") and spec.category_key:
        criteria.append(actor_criterion(fields[spec.category_key], category))

    entity_id = params.get("entity_id")
    if entity_id is not None and entity_id != "":
        criteria.append(
            {"field": fields[spec.entity_key], "searchtype": "under", "value": entity_id}
        )

    date_from = params.get("date_from")
    date_to = params.get("date_to")
    if date_from or date_to:
        date_field = resolve_date_field(spec, params.get("date_field"))
        if date_from:
            criteria.append(
                {"field": date_field, "searchtype": "morethan", "value": date_from}
            )
        if date_to:
            criteria.append(
                {"field": date_field, "searchtype": "lessthan", "value": date_to}
            )

    return criteria


def resolve_date_field(spec: RecordSpec, date_field: Any) -> int:
    """Resolve which column a date range applies to for this record type.

    Defaults to the type's principal date. An unknown name is rejected rather
    than silently ignored: a range applied to the wrong column, or dropped
    entirely, produces a confident answer about the wrong period.
    """
    if date_field in (None, ""):
        return spec.fields[spec.date_field]

    numeric = as_field_id(date_field)
    if numeric is not None:
        return numeric

    key = str(date_field).strip().lower()
    if key in spec.fields:
        return spec.fields[key]

    date_like = sorted(key for key in spec.fields if "date" in key)
    raise ValidationError(
        f"date_field '{date_field}' nao existe em {spec.label}. "
        f"Campos de data disponiveis: {date_like}",
        "date_field",
    )


def resolve_sort(spec: RecordSpec, params: Dict[str, Any]) -> Tuple[int, str]:
    """Resolve sort_by/order into the (field id, direction) the API expects."""
    sort_field = resolve_sort_field(
        params.get("sort_by"),
        spec.fields,
        spec.fields[spec.default_sort],
        context=f"search_itil_records({spec.record_type})",
    )
    return sort_field, normalize_order(params.get("order"))


def forcedisplay_for(spec: RecordSpec) -> List[int]:
    """Field ids the list must ask for, derived from the rendered columns.

    Asking for exactly what is displayed keeps the Search API call to one
    round-trip: every column arrives resolved instead of costing an N+1 lookup
    per row.
    """
    seen: List[int] = []
    for key in spec.display:
        fid = spec.fields.get(key)
        if fid is not None and fid not in seen:
            seen.append(fid)
    return seen


def _pick(row: Dict[str, Any], field_id: int, key: str) -> Any:
    """Read a value from a Search row by numeric field id, or by named key.

    /search returns ``{"1": "...", "12": 2}`` while a direct GET returns
    ``{"name": "...", "status": 2}``. Reading both shapes here lets the same
    normaliser serve list and detail.
    """
    value = row.get(str(field_id))
    if value is None or value == "":
        value = row.get(key)
    if value in ("", "0", 0) and key not in ("is_active", "percent_done", "id"):
        return None
    return value


def normalize_row(spec: RecordSpec, row: Dict[str, Any]) -> Dict[str, Any]:
    """Map one Search API row to the named keys the formatters read."""
    normalized: Dict[str, Any] = {}
    for key in spec.display:
        fid = spec.fields.get(key)
        if fid is None:
            continue
        value = _pick(row, fid, key)
        if value is not None:
            normalized[key] = value

    # The description arrives as TinyMCE HTML; the list renders plain text.
    raw_content = normalized.get("content")
    if raw_content:
        snippet = strip_html(str(raw_content)).strip()
        normalized["content"] = snippet[:400] if snippet else None
        if not normalized["content"]:
            normalized.pop("content")
    return normalized


def _actor_ids(value: Any) -> List[int]:
    """Extract numeric ids from a Search API actor cell (scalar or list)."""
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple)) else [value]
    out: List[int] = []
    for item in items:
        text = str(item).strip()
        if text.isdigit():
            out.append(int(text))
    return out


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ItilService:
    """Query and mutation surface for the non-incident ITIL itemtypes."""

    def __init__(self) -> None:
        logger.info("ItilService initialized")

    # -- helpers ----------------------------------------------------------

    async def _resolve_actor_names(
        self, spec: RecordSpec, rows: List[Dict[str, Any]]
    ) -> None:
        """Replace raw actor ids with display names, in place.

        The Search API returns the actor meta-columns (requester, technician,
        technician group) as raw ids and does not expand them even with
        expand_dropdowns, so they are resolved in bulk through the shared
        dropdown cache -- one lookup per page, not per row.
        """
        if not spec.user_keys and not spec.group_keys:
            return

        user_ids: set = set()
        group_ids: set = set()
        for row in rows:
            for key in spec.user_keys:
                user_ids.update(_actor_ids(row.get(key)))
            for key in spec.group_keys:
                group_ids.update(_actor_ids(row.get(key)))

        if not user_ids and not group_ids:
            return

        user_names = (
            await dropdown_cache.get_many_names("User", list(user_ids))
            if user_ids
            else {}
        )
        group_names = (
            await dropdown_cache.get_many_names("Group", list(group_ids))
            if group_ids
            else {}
        )

        def _map(value: Any, names: Dict[int, Any]) -> Any:
            ids = _actor_ids(value)
            if not ids:
                return value
            resolved = [names.get(i) or str(i) for i in ids]
            return resolved if len(resolved) > 1 else resolved[0]

        for row in rows:
            for key in spec.user_keys:
                if key in row:
                    row[key] = _map(row[key], user_names)
            for key in spec.group_keys:
                if key in row:
                    row[key] = _map(row[key], group_names)

    # -- read -------------------------------------------------------------

    async def search_records(self, record_type: Any, **kwargs) -> Dict[str, Any]:
        """List or text-search one record type, returning a paginated payload."""
        spec = get_spec(record_type)
        await ensure_field_map_synced(spec)

        limit = max(int(kwargs.get("limit", 10) or 10), 1)
        offset = max(int(kwargs.get("offset", 0) or 0), 0)

        sort_field, order = resolve_sort(spec, kwargs)
        entity_id = kwargs.get("entity_id")

        async def _run(text_groups, fetch_limit):
            result = await glpi_client.search(
                item_type=spec.itemtype,
                criteria=build_criteria(spec, kwargs, text_override=text_groups),
                forcedisplay=forcedisplay_for(spec),
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

        query = kwargs.get("query")
        notice = None
        if query not in (None, ""):
            rows, total, stage, terms = await run_text_search(
                str(query), text_field_ids(spec), _run, limit
            )
            notice = describe_stage(stage, terms, found=bool(rows))
        else:
            rows, total = await _run(None, limit)

        items = [normalize_row(spec, row) for row in rows if isinstance(row, dict)]
        await self._resolve_actor_names(spec, items)

        return {
            "record_type": spec.record_type,
            "itemtype": spec.itemtype,
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "search_notice": notice,
        }

    async def count_records(self, record_type: Any, **kwargs) -> Dict[str, Any]:
        """Return only how many records match, without fetching any of them.

        @MX:ANCHOR: the cheap count probe.
        @MX:REASON: `range=0-0` makes GLPI answer with `totalcount` and an
        empty (or single-row) payload. Paginating through results to count
        them costs one round-trip per page and grows with the customer's
        history, which is exactly the shape of report that gets asked for
        every month.
        """
        spec = get_spec(record_type)
        await ensure_field_map_synced(spec)

        criteria = build_criteria(spec, kwargs)
        params: Dict[str, Any] = {"range": "0-0"}
        emit_criteria(params, criteria)

        if kwargs.get("entity_id") is not None:
            params["is_recursive"] = 1

        # @MX:NOTE: errors propagate instead of degrading to zero.
        # @MX:REASON: a silent 0 reads exactly like "nothing matched" and has
        # already fooled a model into reporting an empty month.
        result = await glpi_client.get(
            f"/apirest.php/search/{spec.itemtype}", params=params, use_cache=False
        )
        total = 0
        if isinstance(result, dict):
            try:
                total = int(result.get("totalcount", 0) or 0)
            except (TypeError, ValueError):
                total = 0

        return {
            "record_type": spec.record_type,
            "itemtype": spec.itemtype,
            "total": total,
            "count_only": True,
        }

    async def get_record(self, record_type: Any, record_id: Any) -> Dict[str, Any]:
        """Fetch one record with dropdowns resolved, plus best-effort context.

        The base GET is authoritative; actors, follow-ups and linked-ticket
        counts are enrichments and never fail the call.
        """
        spec = get_spec(record_type)
        item_id = self._require_id(record_id, spec)

        item = await glpi_client.get(
            f"/apirest.php/{spec.itemtype}/{item_id}",
            params={"expand_dropdowns": 1},
            use_cache=False,
        )
        if not isinstance(item, dict) or "id" not in item:
            raise NotFoundError(spec.itemtype, item_id)

        item["record_type"] = spec.record_type
        item["itemtype"] = spec.itemtype

        await self._enrich_actors(spec, item, item_id)
        await self._enrich_followups(spec, item, item_id)
        await self._enrich_linked_tickets(spec, item, item_id)
        return item

    async def _enrich_actors(
        self, spec: RecordSpec, item: Dict[str, Any], item_id: int
    ) -> None:
        """Attach requester / technician / group names to a detail payload."""
        if not spec.user_keys and not spec.group_keys:
            return
        try:
            await ensure_field_map_synced(spec)
            keys = tuple(spec.user_keys) + tuple(spec.group_keys)
            result = await glpi_client.search(
                item_type=spec.itemtype,
                criteria=[
                    {
                        "field": spec.fields["id"],
                        "searchtype": "equals",
                        "value": item_id,
                    }
                ],
                forcedisplay=[spec.fields["id"]]
                + [spec.fields[k] for k in keys if k in spec.fields],
                range_limit=1,
                is_recursive=True,
                expand_dropdowns=True,
            )
            rows = (
                result.get("data", [])
                if isinstance(result, dict)
                else (result or [])
            )
            if not rows:
                return
            holder = {
                key: rows[0].get(str(spec.fields[key]))
                for key in keys
                if key in spec.fields
            }
            await self._resolve_actor_names(spec, [holder])
            for key, value in holder.items():
                if value:
                    item[f"{key}_names"] = value
        except Exception as exc:  # noqa: BLE001 -- enrichment is best-effort
            logger.warning(
                f"get_record: actor enrichment failed for "
                f"{spec.itemtype} {item_id}: {exc}"
            )

    async def _enrich_followups(
        self, spec: RecordSpec, item: Dict[str, Any], item_id: int
    ) -> None:
        """Embed the follow-up conversation when the type supports one."""
        if not spec.followups:
            return
        try:
            followups = await self.get_followups(spec.record_type, item_id)
            item["followups"] = followups
        except Exception as exc:  # noqa: BLE001 -- enrichment is best-effort
            logger.warning(
                f"get_record: followup enrichment failed for "
                f"{spec.itemtype} {item_id}: {exc}"
            )

    async def _enrich_linked_tickets(
        self, spec: RecordSpec, item: Dict[str, Any], item_id: int
    ) -> None:
        """Count the tickets linked to this problem or change."""
        if not spec.link_itemtype:
            return
        try:
            links = await glpi_client.get_subitems(
                spec.itemtype, item_id, spec.link_itemtype
            )
            rows = _as_list(links)
            item["linked_ticket_count"] = len(rows)
            item["linked_ticket_ids"] = [
                row.get("tickets_id")
                for row in rows
                if isinstance(row, dict) and row.get("tickets_id") is not None
            ]
        except Exception as exc:  # noqa: BLE001 -- enrichment is best-effort
            logger.warning(
                f"get_record: linked ticket count failed for "
                f"{spec.itemtype} {item_id}: {exc}"
            )

    async def get_followups(
        self, record_type: Any, record_id: Any
    ) -> List[Dict[str, Any]]:
        """List the follow-ups of a problem or change, authors resolved."""
        spec = get_spec(record_type)
        self._require_followups(spec)
        item_id = self._require_id(record_id, spec)

        raw = await glpi_client.get_subitems(spec.itemtype, item_id, "ITILFollowup")
        rows = [row for row in _as_list(raw) if isinstance(row, dict)]

        author_ids: set = set()
        for row in rows:
            author_ids.update(_actor_ids(row.get("users_id")))
        author_names = (
            await dropdown_cache.get_many_names("User", list(author_ids))
            if author_ids
            else {}
        )

        followups: List[Dict[str, Any]] = []
        for row in rows:
            ids = _actor_ids(row.get("users_id"))
            author = author_names.get(ids[0]) if ids else None
            followups.append(
                {
                    "id": row.get("id"),
                    "date": row.get("date") or row.get("date_creation"),
                    "author": author
                    or (str(row.get("users_id")) if row.get("users_id") else "?"),
                    "is_private": str(row.get("is_private")) in ("1", "True"),
                    "content": row.get("content", ""),
                }
            )
        return followups

    # -- write ------------------------------------------------------------

    async def create_record(self, record_type: Any, **data) -> Dict[str, Any]:
        """Create one record from tool-level argument names."""
        spec = get_spec(record_type)
        payload = self._build_payload(spec, data)

        missing = [key for key in spec.create_required if not payload.get(key)]
        if missing:
            raise ValidationError(
                f"Campos obrigatorios ausentes para criar em {spec.label}: {missing}",
                missing[0],
            )

        result = await glpi_client.post(f"/apirest.php/{spec.itemtype}", data=payload)
        created_id = _created_id(result)
        if created_id is None:
            raise GLPIError(
                500,
                f"Nao foi possivel criar o registro em {spec.label}: "
                "o GLPI nao devolveu um id.",
            )
        return {
            "record_type": spec.record_type,
            "itemtype": spec.itemtype,
            "id": created_id,
            "created": True,
        }

    async def update_record(
        self, record_type: Any, record_id: Any, **data
    ) -> Dict[str, Any]:
        """Update one record and return its refreshed state."""
        spec = get_spec(record_type)
        item_id = self._require_id(record_id, spec)
        payload = self._build_payload(spec, data)

        if not payload:
            raise ValidationError(
                f"Nenhum campo valido para atualizar em {spec.label}. "
                f"Campos aceitos: {sorted(spec.writable)}",
                "fields",
            )

        # Fail on a missing record before writing, so the caller gets a 404
        # instead of a GLPI error about an unknown id.
        await glpi_client.get(
            f"/apirest.php/{spec.itemtype}/{item_id}", use_cache=False
        )
        await glpi_client.put(f"/apirest.php/{spec.itemtype}/{item_id}", data=payload)
        return await self.get_record(spec.record_type, item_id)

    async def delete_record(
        self, record_type: Any, record_id: Any, purge: bool = False
    ) -> Dict[str, Any]:
        """Delete one record. Without `purge` GLPI moves it to the bin."""
        spec = get_spec(record_type)
        item_id = self._require_id(record_id, spec)

        await glpi_client.get(
            f"/apirest.php/{spec.itemtype}/{item_id}", use_cache=False
        )

        endpoint = f"/apirest.php/{spec.itemtype}/{item_id}"
        if purge:
            endpoint += "?force_purge=true"
        await glpi_client.delete(endpoint)

        return {
            "record_type": spec.record_type,
            "itemtype": spec.itemtype,
            "id": item_id,
            "deleted": True,
            "purged": bool(purge),
        }

    async def add_followup(
        self,
        record_type: Any,
        record_id: Any,
        content: str,
        is_private: bool = False,
    ) -> Dict[str, Any]:
        """Add a follow-up to a problem or change via the generic ITILFollowup."""
        spec = get_spec(record_type)
        self._require_followups(spec)
        item_id = self._require_id(record_id, spec)

        if not content or not str(content).strip():
            raise ValidationError("content e obrigatorio", "content")

        await glpi_client.get(
            f"/apirest.php/{spec.itemtype}/{item_id}", use_cache=False
        )

        # GLPI 11 dropped the per-type followup classes (TicketFollowup and
        # friends); ITILFollowup carries itemtype + items_id instead.
        result = await glpi_client.post(
            "/apirest.php/ITILFollowup",
            data={
                "itemtype": spec.itemtype,
                "items_id": item_id,
                "content": content,
                "is_private": 1 if is_private else 0,
            },
        )
        followup_id = _created_id(result)
        if followup_id is None:
            raise GLPIError(
                500,
                f"Nao foi possivel adicionar o acompanhamento em {spec.label} "
                f"{item_id}: o GLPI nao devolveu um id.",
            )
        return {
            "record_type": spec.record_type,
            "itemtype": spec.itemtype,
            "id": item_id,
            "followup_id": followup_id,
            "created": True,
        }

    async def link_ticket(
        self, record_type: Any, record_id: Any, ticket_id: Any
    ) -> Dict[str, Any]:
        """Attach an existing ticket to a problem or change.

        GLPI models this as its own itemtype (Problem_Ticket / Change_Ticket)
        rather than a column on either side, which is why the link is created
        and not "updated" onto the record.
        """
        spec = get_spec(record_type)
        if not spec.link_itemtype or not spec.link_parent_field:
            raise ValidationError(
                f"{spec.label} nao aceita vinculo de chamado. "
                "Disponivel apenas para problems e changes.",
                "record_type",
            )

        item_id = self._require_id(record_id, spec)
        linked = as_field_id(ticket_id)
        if linked is None or linked <= 0:
            raise ValidationError(
                "ticket_id deve ser um inteiro positivo", "ticket_id"
            )

        try:
            result = await glpi_client.post(
                f"/apirest.php/{spec.link_itemtype}",
                data={spec.link_parent_field: item_id, "tickets_id": linked},
            )
        except GLPIError as exc:
            # GLPI answers a duplicate link with a bare ERROR_GLPI_ADD, which
            # tells the caller nothing about what to do next.
            if "ERROR_GLPI_ADD" in str(exc):
                raise GLPIError(
                    409,
                    f"Nao foi possivel vincular o chamado {linked} a "
                    f"{spec.itemtype} {item_id}: o vinculo ja existe ou um dos "
                    "ids e invalido.",
                ) from exc
            raise

        return {
            "record_type": spec.record_type,
            "itemtype": spec.itemtype,
            "id": item_id,
            "ticket_id": linked,
            "link_itemtype": spec.link_itemtype,
            "link_id": _created_id(result),
            "linked": True,
        }

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _require_id(record_id: Any, spec: RecordSpec) -> int:
        resolved = as_field_id(record_id)
        if resolved is None or resolved <= 0:
            raise ValidationError(
                f"record_id deve ser um inteiro positivo para {spec.label}",
                "record_id",
            )
        return resolved

    @staticmethod
    def _require_followups(spec: RecordSpec) -> None:
        if not spec.followups:
            raise ValidationError(
                f"{spec.label} nao possui acompanhamentos no GLPI. "
                "Disponivel apenas para problems e changes.",
                "action",
            )

    @staticmethod
    def _build_payload(spec: RecordSpec, data: Dict[str, Any]) -> Dict[str, Any]:
        """Translate tool argument names into GLPI column names.

        Unknown arguments are dropped rather than forwarded: GLPI accepts
        unknown keys silently, so a typo would look like a successful write
        that changed nothing.
        """
        payload: Dict[str, Any] = {}
        for arg, column in spec.writable.items():
            if arg not in data:
                continue
            value = data[arg]
            if value is None:
                continue
            if arg == "status":
                value = normalize_status(spec, value)
            if arg == "is_active" and not isinstance(value, int):
                value = normalize_status(spec, value)
            payload[column] = value

        extra = data.get("fields")
        if isinstance(extra, dict):
            for column, value in extra.items():
                if value is not None:
                    payload[str(column)] = value
        return payload


def _as_list(payload: Any) -> List[Any]:
    """Normalise the two shapes GLPI uses for collections."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return data
    return []


def _created_id(result: Any) -> Optional[int]:
    """Extract the new id from a GLPI POST answer (dict, list or bare int)."""
    if isinstance(result, dict):
        return as_field_id(result.get("id"))
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict):
            return as_field_id(first.get("id"))
        return as_field_id(first)
    return as_field_id(result)


# Module-level singleton, mirroring ticket_service / asset_service.
itil_service = ItilService()
