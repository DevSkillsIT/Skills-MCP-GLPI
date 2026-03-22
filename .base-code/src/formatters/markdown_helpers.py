"""
Markdown helpers for MCP response formatting.
NEW — functions that DO NOT exist in utils/helpers.py.

SPEC-GLPI-ENHANCE-001/F01 — Section 4.1.1
Pattern: Adapted from Hudu src/formatters/markdown.ts + src/utils/html-stripper.ts
"""

import re
import html as html_module
from datetime import datetime
from typing import Any, Optional, Union


# --- GLPI Status/Priority/Type Maps ---

TICKET_STATUS = {
    1: "Novo",
    2: "Atribuido",
    3: "Planejado",
    4: "Pendente",
    5: "Solucionado",
    6: "Fechado",
}

TICKET_PRIORITY = {
    1: "Muito baixa",
    2: "Baixa",
    3: "Media",
    4: "Alta",
    5: "Muito alta",
    6: "Maior",
}

TICKET_TYPE = {
    1: "Incidente",
    2: "Requisicao",
}

# Fields always removed from responses
REMOVE_ALWAYS = {"links", "_links", "href", "completename"}
# Fields removed only in list mode (too large for tables)
REMOVE_LIST_ONLY = {"content", "description", "comment", "answer"}


def esc(value: Optional[Union[str, int, float]]) -> str:
    """Escape pipe characters that break Markdown tables."""
    if value is None:
        return ""
    return str(value).replace("|", "\\|")


def strip_html(text: Optional[str]) -> str:
    """
    Remove HTML tags and decode HTML entities.
    MANDATORY for GLPI fields (content, description, comment).
    GLPI uses TinyMCE — HTML can be complex.
    """
    if not text:
        return ""
    text = str(text)
    # Convert structural HTML to text BEFORE removing tags
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li>", "- ", text, flags=re.IGNORECASE)
    # Remove all remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode HTML entities AFTER tag removal (so &lt; doesn't become < and get stripped)
    text = html_module.unescape(text)
    # Clean excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def truncate_field(text: Optional[str], max_len: int = 300) -> str:
    """Truncate text applying strip_html first, then esc."""
    if not text:
        return ""
    clean = strip_html(str(text))
    if len(clean) <= max_len:
        return esc(clean)
    return esc(clean[:max_len]) + "..."


def page_info(count: int, limit: int, offset: int, total: Optional[int] = None) -> str:
    """
    Format pagination info for first line of Markdown lists.
    Uses offset/limit (GLPI API) instead of page/pageSize (Hudu API).
    """
    parts = [f"**{count} resultados**"]
    if total and total > count:
        page = (offset // limit) + 1 if limit > 0 else 1
        total_pages = (total + limit - 1) // limit if limit > 0 else 1
        parts.append(f"Pagina {page}/{total_pages} (total: {total}, limit: {limit})")
    else:
        parts.append("Mostrando todos")
    return " | ".join(parts)


def to_paged_response(data: Any, offset: int = 0, limit: int = 10) -> dict:
    """
    Standardized pagination wrapper (equivalent to Hudu toPagedResponse).
    Ensures uniform interface for all list formatters.
    """
    items = data if isinstance(data, list) else (
        data.get("data", []) if isinstance(data, dict) else []
    )
    total = data.get("totalcount", len(items)) if isinstance(data, dict) else len(items)
    return {
        "data": items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": len(items) >= limit,
    }


def check_response_size(text: str, max_bytes: int = 400 * 1024) -> dict:
    """Check if response size exceeds limit (400KB default)."""
    size = len(text.encode("utf-8"))
    if size > max_bytes:
        return {
            "exceeded": True,
            "size": size,
            "message": (
                f"Resposta excede {max_bytes // 1024}KB ({size // 1024}KB). "
                "Use filtros mais restritivos ou reduza o limit."
            ),
        }
    return {"exceeded": False, "size": size}


def remove_heavy_fields(data: dict, mode: str = "list") -> dict:
    """
    Remove heavy/internal fields from GLPI responses.
    mode='list' is more aggressive (removes content, description, etc).
    """
    if not isinstance(data, dict):
        return data

    result = {}
    for key, value in data.items():
        if key in REMOVE_ALWAYS:
            continue
        if mode == "list" and key in REMOVE_LIST_ONLY:
            continue
        if key.startswith("_") and key != "_id":
            continue
        result[key] = value
    return result


def fmt_date(iso_date: Optional[str]) -> str:
    """Format ISO date to DD/MM/YYYY HH:MM."""
    if not iso_date:
        return "N/A"
    try:
        dt = datetime.fromisoformat(str(iso_date).replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return str(iso_date)


def fmt_status(status_code: Optional[int]) -> str:
    """Format GLPI ticket status code to readable text."""
    if status_code is None:
        return "N/A"
    return TICKET_STATUS.get(int(status_code), f"Desconhecido ({status_code})")


def fmt_priority(priority_code: Optional[int]) -> str:
    """Format GLPI priority code to readable text."""
    if priority_code is None:
        return "N/A"
    return TICKET_PRIORITY.get(int(priority_code), f"Desconhecida ({priority_code})")


def fmt_type(type_code: Optional[int]) -> str:
    """Format GLPI ticket type code to readable text."""
    if type_code is None:
        return "N/A"
    return TICKET_TYPE.get(int(type_code), f"Desconhecido ({type_code})")
