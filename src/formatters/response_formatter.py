"""
Central interceptor: converts tool responses to Markdown.
Called in handlers.py at the tools/call handler.

IMPORTANT: Receives data as Python OBJECTS (dict), NOT JSON strings.
Pattern identical to Hudu (src/formatters/response-formatter.ts), adapted for Python.
NEVER do json.dumps -> json.loads round-trip.

SPEC-GLPI-ENHANCE-001/F01 — Section 4.1.3
"""

import json
from typing import Any, Optional

from src.formatters.glpi_formatters import (
    format_admin_detail,
    format_ai_analysis_result,
    format_asset_detail,
    format_asset_stats,
    format_assets_list,
    format_entities_list,
    format_groups_list,
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
    elif action in ("trigger", "publish"):
        return format_operation_success(data, f"{action} analise IA")
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
    if action in ("get", "get_details"):
        return format_asset_detail(data)
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
    "glpi_search_knowledge_articles": lambda data, args: format_tickets_list(data, args),
    # === BRIDGE TOOLS (4) — pass-through for Markdown ===
    "glpi_list_available_resources": lambda data, args: data if isinstance(data, str) else format_resources_list(data),
    "glpi_read_resource_by_uri": lambda data, args: data if isinstance(data, str) else str(data),
    "glpi_list_available_prompts": lambda data, args: data if isinstance(data, str) else format_prompts_list(data),
    "glpi_get_prompt_template": lambda data, args: data if isinstance(data, str) else str(data),
}


def format_tool_response(
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
