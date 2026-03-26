"""
Consolidated MCP Tools - Webhooks (2 tools replacing 12)

Reduces 12 individual webhook tools into 2 consolidated tools:
  1. search_webhooks  (scope: list | stats | deliveries)
  2. manage_webhooks  (action: get | create | update | delete | test |
                               trigger | enable | disable | retry)

Delegates all business logic to the existing WebhookTools service layer.
"""

from typing import Any, Dict, List, Optional

from src.formatters.markdown_helpers import remove_heavy_fields
from src.tools.webhooks import webhook_tools
from src.utils.validators import create_mcp_error, validate_positive_int


# ---------------------------------------------------------------------------
# 1. search_webhooks
# ---------------------------------------------------------------------------

async def search_webhooks(
    scope: str,
    webhook_id: Optional[int] = None,
    limit: int = 10,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Consolidated search/read tool for webhooks.

    Args:
        scope: One of 'list', 'stats', 'deliveries'.
        webhook_id: Required when scope='deliveries'.
        limit: Max results per page (capped at 50).
        offset: Pagination offset.

    Returns:
        Dict with scope-specific data or an MCP error dict.
    """
    valid_scopes = ("list", "stats", "deliveries")
    if scope not in valid_scopes:
        return create_mcp_error(
            f"Invalid scope '{scope}'",
            f"Expected one of: {', '.join(valid_scopes)}",
            "Example: search_webhooks(scope='list')",
        )

    limit = min(limit, 50)

    # --- scope: list ---
    if scope == "list":
        result = await webhook_tools.list_webhooks(
            limit=limit,
            offset=offset,
        )
        if isinstance(result, dict) and "webhooks" in result:
            result["webhooks"] = [
                remove_heavy_fields(w) for w in result["webhooks"]
            ]
        return result

    # --- scope: stats ---
    if scope == "stats":
        return await webhook_tools.get_webhook_stats()

    # --- scope: deliveries ---
    if webhook_id is None:
        return create_mcp_error(
            "webhook_id is required when scope='deliveries'",
            "Provide a positive integer webhook_id",
            "Example: search_webhooks(scope='deliveries', webhook_id=42)",
        )

    check = validate_positive_int(webhook_id, "webhook_id")
    if not check["valid"]:
        return create_mcp_error(
            check["error"],
            "Expected a positive integer",
            "Example: search_webhooks(scope='deliveries', webhook_id=42)",
        )

    result = await webhook_tools.get_webhook_deliveries(
        webhook_id=str(check["value"]),
        limit=limit,
        offset=offset,
    )
    if isinstance(result, dict) and "deliveries" in result:
        result["deliveries"] = [
            remove_heavy_fields(d) for d in result["deliveries"]
        ]
    return result


# ---------------------------------------------------------------------------
# 2. manage_webhooks
# ---------------------------------------------------------------------------

async def manage_webhooks(
    action: str,
    webhook_id: Optional[int] = None,
    # create / update params
    name: Optional[str] = None,
    url: Optional[str] = None,
    event_type: Optional[str] = None,
    secret: Optional[str] = None,
    is_active: Optional[bool] = None,
    headers: Optional[Dict[str, str]] = None,
    # delete params
    confirmationToken: Optional[str] = None,
    reason: Optional[str] = None,
    # trigger params
    data: Optional[Dict[str, Any]] = None,
    webhook_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Consolidated management tool for webhooks.

    Args:
        action: One of 'get', 'create', 'update', 'delete', 'test',
                'trigger', 'enable', 'disable', 'retry'.
        webhook_id: Required for get/update/delete/test/enable/disable/retry
                    and deliveries lookup.
        name: Webhook name (create, update).
        url: Destination URL (create, update).
        event_type: Event type string (create, update, trigger).
        secret: HMAC secret (create, update).
        is_active: Active flag (create, update).
        headers: Custom headers dict (create, update).
        confirmationToken: Safety guard token (delete).
        reason: Deletion reason (delete).
        data: Event payload (trigger).
        webhook_ids: Specific webhook IDs to trigger (trigger).

    Returns:
        Dict with action-specific data or an MCP error dict.
    """
    valid_actions = (
        "get", "create", "update", "delete",
        "test", "trigger", "enable", "disable", "retry",
    )
    if action not in valid_actions:
        return create_mcp_error(
            f"Invalid action '{action}'",
            f"Expected one of: {', '.join(valid_actions)}",
            "Example: manage_webhooks(action='get', webhook_id=42)",
        )

    # Actions that require a valid webhook_id
    actions_requiring_id = (
        "get", "update", "delete", "test", "enable", "disable", "retry",
    )

    if action in actions_requiring_id:
        if webhook_id is None:
            return create_mcp_error(
                f"webhook_id is required for action '{action}'",
                "Provide a positive integer webhook_id",
                f"Example: manage_webhooks(action='{action}', webhook_id=42)",
            )
        check = validate_positive_int(webhook_id, "webhook_id")
        if not check["valid"]:
            return create_mcp_error(
                check["error"],
                "Expected a positive integer",
                f"Example: manage_webhooks(action='{action}', webhook_id=42)",
            )
        wh_id_str = str(check["value"])

    # --- action: get ---
    if action == "get":
        return await webhook_tools.get_webhook(webhook_id=wh_id_str)

    # --- action: create ---
    if action == "create":
        if not name:
            return create_mcp_error(
                "name is required for action 'create'",
                "Provide a non-empty webhook name",
                "Example: manage_webhooks(action='create', name='My Hook', "
                "url='https://example.com/hook', event_type='ticket.created')",
            )
        if not url:
            return create_mcp_error(
                "url is required for action 'create'",
                "Provide a valid HTTP(S) URL",
                "Example: manage_webhooks(action='create', name='My Hook', "
                "url='https://example.com/hook', event_type='ticket.created')",
            )
        if not event_type:
            return create_mcp_error(
                "event_type is required for action 'create'",
                "Provide a valid event type",
                "Example: manage_webhooks(action='create', name='My Hook', "
                "url='https://example.com/hook', event_type='ticket.created')",
            )
        return await webhook_tools.create_webhook(
            name=name,
            url=url,
            event_type=event_type,
            secret=secret,
            is_active=is_active if is_active is not None else True,
            headers=headers,
        )

    # --- action: update ---
    if action == "update":
        return await webhook_tools.update_webhook(
            webhook_id=wh_id_str,
            name=name,
            url=url,
            event_type=event_type,
            secret=secret,
            is_active=is_active,
            headers=headers,
        )

    # --- action: delete ---
    if action == "delete":
        return await webhook_tools.delete_webhook(
            webhook_id=wh_id_str,
            confirmationToken=confirmationToken,
            reason=reason,
        )

    # --- action: test ---
    if action == "test":
        return await webhook_tools.test_webhook(webhook_id=wh_id_str)

    # --- action: trigger ---
    if action == "trigger":
        if not event_type:
            return create_mcp_error(
                "event_type is required for action 'trigger'",
                "Provide the event type to trigger",
                "Example: manage_webhooks(action='trigger', "
                "event_type='ticket.created', data={'id': 1})",
            )
        return await webhook_tools.trigger_webhook(
            event_type=event_type,
            data=data or {},
            webhook_ids=webhook_ids,
        )

    # --- action: enable ---
    if action == "enable":
        return await webhook_tools.enable_webhook(webhook_id=wh_id_str)

    # --- action: disable ---
    if action == "disable":
        return await webhook_tools.disable_webhook(webhook_id=wh_id_str)

    # --- action: retry ---
    if action == "retry":
        return await webhook_tools.retry_failed_deliveries(
            webhook_id=wh_id_str,
        )

    # Unreachable, but satisfies type checker
    return create_mcp_error(
        f"Unhandled action '{action}'",
        f"Expected one of: {', '.join(valid_actions)}",
        "Example: manage_webhooks(action='get', webhook_id=42)",
    )
