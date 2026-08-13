"""
Shared helpers for building GLPI Search API criteria.

@MX:ANCHOR: one definition of how a caller-supplied value becomes a criterion.
@MX:REASON: tickets and assets both accept "a name or an id" for actor-like
columns. Two copies of that rule drift apart — one starts trimming whitespace,
the other starts accepting booleans — and the difference only shows up as a
filter that quietly matches the wrong rows.
"""

from typing import Any, Dict, Optional


def as_field_id(value: Any) -> Optional[int]:
    """Return the value as an id when it denotes one, else None.

    A loose caller may send "42" instead of 42, so numeric strings count as
    ids. Booleans never do — bool is an int subclass and would otherwise be
    silently accepted as id 0 or 1.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def actor_criterion(field: int, value: Any) -> Dict[str, Any]:
    """Build a criterion for a column that renders a display name.

    Technician, group, requester, category and responsible user all come back
    from the Search API as rendered text. A name therefore matches loosely,
    which is what lets a question like "tickets assigned to Joao" work without
    a lookup round-trip; an id matches exactly, keeping programmatic calls
    precise.
    """
    resolved = as_field_id(value)
    if resolved is not None:
        return {"field": field, "searchtype": "equals", "value": resolved}
    return {"field": field, "searchtype": "contains", "value": str(value).strip()}


def resolve_sort_field(
    sort_by: Any,
    field_map: Dict[str, int],
    default_field: int,
    context: str = "search",
) -> int:
    """Translate a friendly sort field name into its numeric id.

    An unknown name falls back to the default instead of failing: sorting is a
    presentation preference, and refusing the whole query over it would trade a
    small annoyance for no result at all.
    """
    from src.utils.helpers import logger  # local import avoids a cycle

    if sort_by is None:
        return default_field

    resolved_id = as_field_id(sort_by)
    if resolved_id is not None:
        return resolved_id

    resolved = field_map.get(str(sort_by).strip().lower())
    if resolved is not None:
        return resolved

    logger.warning(
        f"{context}: unknown sort field '{sort_by}', falling back to the default column"
    )
    return default_field


def normalize_order(order: Any, default: str = "DESC") -> str:
    """Normalise a sort direction to what the Search API expects."""
    candidate = str(order or default).strip().upper()
    return candidate if candidate in ("ASC", "DESC") else default
