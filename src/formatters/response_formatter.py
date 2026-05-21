"""
Central interceptor: converts tool responses to Markdown.
Called in handlers.py at the tools/call handler.

IMPORTANT: Receives data as Python OBJECTS (dict), NOT JSON strings.
Pattern identical to Hudu (src/formatters/response-formatter.ts), adapted for Python.
NEVER do json.dumps -> json.loads round-trip.

SPEC-GLPI-ENHANCE-001/F01 — Section 4.1.3
"""

import json
from typing import Any, Iterable, Optional

from src.services.dropdown_cache import dropdown_cache
from src.formatters.glpi_formatters import (
    format_admin_detail,
    format_ai_analysis_result,
    format_asset_detail,
    format_asset_stats,
    format_assets_list,
    format_computer_details_enriched,
    format_entities_list,
    format_groups_list,
    format_knowledge_articles,
    format_locations_list,
    format_operation_success,
    format_prompts_list,
    format_reservations_list,
    format_resources_list,
    format_similar_tickets,
    format_ticket_detail,
    format_ticket_followups,
    format_ticket_history,
    format_ticket_stats,
    format_tickets_list,
    format_user_detail,
    format_users_list,
    format_webhook_deliveries,
    format_webhook_detail,
    format_webhook_stats,
    format_webhooks_list,
)
from src.formatters.markdown_helpers import check_response_size


# === DISPATCH FUNCTIONS (explicit, testable, debuggable) ===
# Pattern: dispatch functions with if/elif instead of nested lambda dicts.
# Reason: lambda dicts are hard to debug, test, and produce legible stack traces.
# Reference: Hudu uses simple if/Array.isArray branching.


def _format_prompt_template(data: Any) -> str:
    """Format prompt-template execution result as Markdown.

    Handles the dict shape produced by prompt_handler (prompt_name + compact body),
    falling back to a sensible textual representation for legacy callers.
    """
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        # Standard prompt_handler shape: {prompt_name, compact, ...}
        compact = data.get("compact")
        if isinstance(compact, str) and compact:
            name = data.get("prompt_name", "")
            header = f"# {name}\n\n" if name else ""
            return header + compact
        # Fallback: render dict as labelled lines
        lines = []
        for k, v in data.items():
            if k in ("compact",):
                continue
            lines.append(f"- **{k}:** {v}")
        return "\n".join(lines) if lines else json.dumps(data, ensure_ascii=False, default=str, indent=2)
    return json.dumps(data, ensure_ascii=False, default=str, indent=2)


def _dispatch_manage_tickets(data: Any, args: dict) -> str:
    """Dispatch for glpi_manage_tickets based on action."""
    action = args.get("action", "get")
    if action in ("get", "get_by_number"):
        return format_ticket_detail(data)
    elif action == "get_followups":
        return format_ticket_followups(data, args)
    elif action == "get_history":
        return format_ticket_history(data, args)
    elif action == "get_stats":
        return format_ticket_stats(data)
    elif action == "find_similar":
        return format_similar_tickets(data, args)
    elif action in ("create", "update", "delete", "assign", "close", "resolve", "add_followup"):
        action_labels = {
            "create": "criar ticket",
            "update": "atualizar ticket",
            "delete": "excluir ticket",
            "assign": "atribuir ticket",
            "close": "fechar ticket",
            "resolve": "resolver ticket",
            "add_followup": "adicionar acompanhamento",
        }
        return format_operation_success(data, action_labels[action])
    return format_ticket_detail(data)


def _dispatch_manage_ai(data: Any, args: dict) -> str:
    """Dispatch for glpi_manage_ai_analysis."""
    action = args.get("action", "get_result")
    if action == "get_result":
        return format_ai_analysis_result(data)
    if action == "trigger":
        # Must surface the job_id so the caller can poll get_result later.
        if isinstance(data, dict) and data.get("job_id"):
            status = data.get("status", "processing")
            return (
                f"Analise IA disparada com sucesso.\n\n"
                f"- **Job ID:** `{data['job_id']}`\n"
                f"- **Status:** {status}\n\n"
                f"Use action='get_result' com o job_id acima para consultar o resultado."
            )
        return format_operation_success(data, "trigger analise IA")
    if action == "publish":
        return format_operation_success(data, "publish analise IA")
    return format_ai_analysis_result(data)


def _dispatch_search_assets(data: Any, args: dict) -> str:
    """Dispatch for glpi_search_assets based on scope."""
    scope = args.get("scope", "all")
    if scope == "stats":
        return format_asset_stats(data)
    elif scope in ("reservations", "reservable"):
        return format_reservations_list(data, args)
    return format_assets_list(data, args)


def _dispatch_manage_assets(data: Any, args: dict) -> str:
    """Dispatch for glpi_manage_assets."""
    action = args.get("action", "get")
    if action == "get":
        return format_asset_detail(data)
    if action == "get_details":
        return format_computer_details_enriched(data, args)
    elif action == "get_reservations":
        return format_reservations_list(data, args)
    elif action in ("create", "update", "delete", "create_reservation", "update_reservation"):
        action_labels = {
            "create": "criar ativo",
            "update": "atualizar ativo",
            "delete": "excluir ativo",
            "create_reservation": "criar reserva",
            "update_reservation": "atualizar reserva",
        }
        return format_operation_success(data, action_labels[action])
    return format_asset_detail(data)


def _dispatch_search_admin(data: Any, args: dict) -> str:
    """Dispatch for glpi_search_admin based on resource."""
    resource = args.get("resource", "users")
    formatters = {
        "users": format_users_list,
        "groups": format_groups_list,
        "entities": format_entities_list,
        "locations": format_locations_list,
    }
    formatter = formatters.get(resource, format_users_list)
    return formatter(data, args)


def _dispatch_manage_admin(data: Any, args: dict) -> str:
    """Dispatch for glpi_manage_admin."""
    action = args.get("action", "get")
    resource = args.get("resource", "users")
    if action == "get":
        if resource == "users":
            return format_user_detail(data)
        return format_admin_detail(data, resource)
    elif action in ("create", "update", "delete"):
        return format_operation_success(data, f"{action} {resource}")
    return format_admin_detail(data, resource)


def _dispatch_search_webhooks(data: Any, args: dict) -> str:
    """Dispatch for glpi_search_webhooks."""
    scope = args.get("scope", "list")
    if scope == "stats":
        return format_webhook_stats(data)
    elif scope == "deliveries":
        return format_webhook_deliveries(data, args)
    return format_webhooks_list(data, args)


def _dispatch_manage_webhooks(data: Any, args: dict) -> str:
    """Dispatch for glpi_manage_webhooks."""
    action = args.get("action", "get")
    if action == "get":
        return format_webhook_detail(data)
    elif action in ("create", "update", "delete", "test", "trigger", "enable", "disable", "retry"):
        return format_operation_success(data, f"{action} webhook")
    return format_webhook_detail(data)


# === TOOL_FORMATTERS (central registry — identical to Hudu TOOL_FORMATTERS) ===

TOOL_FORMATTERS: dict[str, Any] = {
    # === TICKETS (3 tools) — DIRETRIZES-OBRIGATORIAS names ===
    "glpi_search_ticket_requests": lambda data, args: format_tickets_list(data, args),
    "glpi_manage_ticket_operations": _dispatch_manage_tickets,
    "glpi_manage_ticket_ai_analysis": _dispatch_manage_ai,
    # === ASSETS (2 tools) ===
    "glpi_search_asset_inventory": _dispatch_search_assets,
    "glpi_manage_asset_operations": _dispatch_manage_assets,
    # === ADMIN (2 tools) ===
    "glpi_search_admin_resources": _dispatch_search_admin,
    "glpi_manage_admin_resources": _dispatch_manage_admin,
    # === WEBHOOKS (2 tools) ===
    "glpi_search_webhook_integrations": _dispatch_search_webhooks,
    "glpi_manage_webhook_integrations": _dispatch_manage_webhooks,
    # === KNOWLEDGE (1 tool) ===
    "glpi_search_knowledge_articles": format_knowledge_articles,
    # === BRIDGE TOOLS (4) — pass-through for Markdown ===
    "glpi_list_available_resources": lambda data, args: data if isinstance(data, str) else format_resources_list(data),
    "glpi_read_resource_by_uri": lambda data, args: data if isinstance(data, str) else str(data),
    "glpi_list_available_prompts": lambda data, args: data if isinstance(data, str) else format_prompts_list(data),
    "glpi_get_prompt_template": lambda data, args: _format_prompt_template(data),
}


# =====================================================================
# ID -> Name enrichment (Bugs #3/#4/#5)
# =====================================================================
# Substitui IDs crus por strings "Nome (#ID)" usando dropdown_cache.
# Roda ANTES do dispatch para que os formatters sync nao precisem awaitar.

# Mapeamento de campos GLPI -> itemtype no dropdown_cache
_ID_FIELD_TO_TYPE: dict[str, str] = {
    "entities_id": "Entity",
    "locations_id": "Location",
    "manufacturers_id": "Manufacturer",
    "states_id": "State",
    "groups_id": "Group",
    "operatingsystems_id": "OperatingSystem",
    "operatingsystemversions_id": "OperatingSystemVersion",
    "filesystems_id": "Filesystem",
    "users_id": "User",
    "users_id_recipient": "User",
    "users_id_lastupdater": "User",
    "softwares_id": "Software",
    "softwareversions_id": "SoftwareVersion",
    "deviceprocessors_id": "ItemDeviceProcessor",
    "devicememories_id": "ItemDeviceMemory",
}


async def _resolve_label(itemtype: str, value: Any) -> str:
    """Resolve ID -> 'Nome (#ID)'. Mantem fallback se cache miss."""
    if value is None or value == "":
        return ""
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        return str(value)
    name = await dropdown_cache.get_name(itemtype, ivalue, fallback="")
    if name and name != str(ivalue):
        return f"{name} (#{ivalue})"
    return str(ivalue)


async def _enrich_id_fields(obj: dict) -> None:
    """Substitui campos *_id por strings 'Nome (#ID)' in-place."""
    for field, itemtype in _ID_FIELD_TO_TYPE.items():
        if field in obj and obj[field] not in (None, ""):
            obj[field] = await _resolve_label(itemtype, obj[field])


async def _enrich_dict_keys(d: dict, itemtype: str) -> dict:
    """Substitui keys numericas (IDs) por 'Nome (#ID)'."""
    if not isinstance(d, dict) or not d:
        return d
    ids: list[Any] = []
    for k in d.keys():
        try:
            ids.append(int(k))
        except (TypeError, ValueError):
            pass
    if not ids:
        return d
    names = await dropdown_cache.get_many_names(itemtype, ids)
    new_d: dict[str, Any] = {}
    for k, v in d.items():
        try:
            ik = int(k)
            label = names.get(ik)
            new_d[f"{label} (#{ik})" if label else f"#{ik}"] = v
        except (TypeError, ValueError):
            new_d[str(k)] = v
    return new_d


async def _enrich_sub_items(items: Iterable[Any]) -> None:
    """Aplica _enrich_id_fields a cada dict da lista."""
    if not items:
        return
    for it in items:
        if isinstance(it, dict):
            await _enrich_id_fields(it)


async def enrich_response(tool_name: str, data: Any, args: Optional[dict] = None) -> Any:
    """Pre-resolve IDs no dict (in-place). Garante que formatters sync vejam nomes."""
    if not isinstance(data, dict):
        return data
    if data.get("isError") is True or data.get("error"):
        return data

    # Detalhes de asset/ticket: top-level fields
    await _enrich_id_fields(data)

    # asset enriched (data["asset"] e data["software"]/data["disks"]/etc.)
    asset = data.get("asset")
    if isinstance(asset, dict):
        await _enrich_id_fields(asset)
    for sub_key in ("operating_systems", "disks", "processors", "memories", "networks", "software"):
        sub = data.get(sub_key)
        if isinstance(sub, list):
            await _enrich_sub_items(sub)

    # Listas (assets/tickets): cada item tem entities_id/locations_id
    for list_key in ("data", "items", "users", "groups", "entities", "locations", "tickets", "assets"):
        lst = data.get(list_key)
        if isinstance(lst, list):
            await _enrich_sub_items(lst)

    # Stats com breakdowns
    if "by_location" in data and isinstance(data["by_location"], dict):
        data["by_location"] = await _enrich_dict_keys(data["by_location"], "Location")
    if "by_manufacturer" in data and isinstance(data["by_manufacturer"], dict):
        data["by_manufacturer"] = await _enrich_dict_keys(data["by_manufacturer"], "Manufacturer")
    if "by_entity" in data and isinstance(data["by_entity"], dict):
        data["by_entity"] = await _enrich_dict_keys(data["by_entity"], "Entity")

    return data


# =====================================================================


async def format_tool_response(
    tool_name: str,
    data: Any,
    args: Optional[dict] = None,
) -> str:
    """
    Central interceptor: converts tool response to Markdown.

    IMPORTANT: Receives data as Python OBJECTS (dict/list), NOT strings.
    Pattern identical to Hudu (src/formatters/response-formatter.ts).

    Args:
        tool_name: Tool name (e.g. 'glpi_search_tickets')
        data: Response data as Python OBJECT (not string)
        args: Original tool call arguments

    Returns:
        Markdown formatted response string
    """
    if args is None:
        args = {}

    # @MX:NOTE: Enrichment de IDs antes do dispatch (Bugs #3/#4/#5).
    # @MX:REASON: Pre-resolve para nomes via dropdown_cache, formatters seguem sync.
    try:
        data = await enrich_response(tool_name, data, args)
    except Exception:  # noqa: BLE001 — enrichment opcional, nao deve quebrar resposta
        pass

    # Case 0: MCP error envelope (isError=True or top-level error)
    # Must come BEFORE the dispatcher, otherwise detail formatters render
    # the error payload as a fake entity with N/A fields (e.g. ticket detail
    # with the error text leaked into the "Descricao" column).
    if isinstance(data, dict) and (data.get("isError") is True or data.get("error")):
        err_text = ""
        content = data.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                err_text = first.get("text", "") or ""
        if not err_text:
            err_text = str(data.get("error") or data.get("message") or "Erro desconhecido")
        return f"Erro: {err_text}"

    # Case 1: data is already a string (bridge tools return Markdown directly)
    if isinstance(data, str):
        return data

    # Case 2: search tools with None -> treat as empty list
    if data is None and "search_" in tool_name:
        return "Nenhum resultado encontrado."

    # Case 3: None for other tools
    if data is None:
        return ""

    # Case 4: find formatter
    formatter = TOOL_FORMATTERS.get(tool_name)
    if formatter:
        try:
            markdown = formatter(data, args)
        except Exception:
            # Safe fallback on formatter error
            markdown = json.dumps(data, ensure_ascii=False, default=str, indent=2)

        # Case 5: check response size
        size_check = check_response_size(markdown)
        if size_check["exceeded"]:
            return size_check["message"]

        return markdown

    # Fallback: json.dumps (should NOT happen in final delivery)
    return json.dumps(data, ensure_ascii=False, default=str, indent=2)
