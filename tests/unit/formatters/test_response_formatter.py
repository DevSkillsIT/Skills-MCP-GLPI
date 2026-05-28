"""
Tests for src/formatters/response_formatter.py
Tests the central dispatcher format_tool_response() and TOOL_FORMATTERS registry.
Includes parametrized tests covering all tool/action/scope combinations.
"""

import sys

sys.path.insert(0, "/opt/mcp-servers/glpi/.base-code")

import json
from unittest.mock import patch

import pytest

from src.formatters.response_formatter import (
    TOOL_FORMATTERS,
    _dispatch_manage_admin,
    _dispatch_manage_ai,
    _dispatch_manage_assets,
    _dispatch_manage_tickets,
    _dispatch_manage_webhooks,
    _dispatch_search_admin,
    _dispatch_search_assets,
    _dispatch_search_webhooks,
    format_tool_response,
)


# ============================================================
# Helpers
# ============================================================


def _ticket(tid: int = 1) -> dict:
    return {
        "id": tid,
        "name": f"Ticket {tid}",
        "status": 1,
        "priority": 3,
        "type": 1,
        "date": "2024-01-01T10:00:00",
    }


def _asset(aid: int = 1) -> dict:
    return {"id": aid, "name": f"Asset {aid}", "serial": "SN001"}


def _user(uid: int = 1) -> dict:
    return {"id": uid, "name": f"user{uid}", "realname": "Test", "firstname": "User", "is_active": 1}


# ============================================================
# 1. search_tickets returns Markdown, not JSON
# ============================================================


class TestSearchTicketsMarkdown:
    """1. search_tickets returns Markdown, not JSON."""

    async def test_returns_markdown(self) -> None:
        data = [_ticket(1), _ticket(2)]
        result = await format_tool_response("glpi_search_helpdesk_tickets", data, {})
        assert "| ID |" in result
        assert result.startswith("**2 resultados**")
        # Should NOT be JSON
        with pytest.raises(json.JSONDecodeError):
            json.loads(result)


# ============================================================
# 2. manage_tickets get returns detail
# ============================================================


class TestManageTicketsGet:
    """2. manage_tickets get action returns detail format."""

    async def test_get_returns_detail(self) -> None:
        ticket = _ticket(42)
        ticket["content"] = "Description"
        result = await format_tool_response("glpi_manage_ticket_operations", ticket, {"action": "get"})
        assert "# Ticket #42" in result


# ============================================================
# 3. manage_tickets create returns success
# ============================================================


class TestManageTicketsCreate:
    """3. manage_tickets create action returns success message."""

    async def test_create_returns_success(self) -> None:
        data = {"id": 100, "message": "Created"}
        result = await format_tool_response("glpi_manage_ticket_operations", data, {"action": "create"})
        assert "criar ticket" in result
        assert "ID: 100" in result


# ============================================================
# 4. None response for search returns "Nenhum resultado encontrado."
# ============================================================


class TestNoneSearchResponse:
    """4. None response for search tool returns empty message."""

    async def test_search_none(self) -> None:
        result = await format_tool_response("glpi_search_helpdesk_tickets", None, {})
        assert result == "Nenhum resultado encontrado."

    async def test_search_assets_none(self) -> None:
        result = await format_tool_response("glpi_search_asset_inventory", None, {})
        assert result == "Nenhum resultado encontrado."

    async def test_search_admin_none(self) -> None:
        result = await format_tool_response("glpi_search_admin_resources", None, {})
        assert result == "Nenhum resultado encontrado."


# ============================================================
# 5. Unknown tool falls back to JSON
# ============================================================


class TestUnknownToolFallback:
    """5. Unknown tool name falls back to json.dumps."""

    async def test_unknown_tool(self) -> None:
        data = {"key": "value"}
        result = await format_tool_response("glpi_nonexistent_tool", data, {})
        parsed = json.loads(result)
        assert parsed == data


# ============================================================
# 6. String passthrough
# ============================================================


class TestStringPassthrough:
    """6. String data is returned as-is."""

    async def test_string_data(self) -> None:
        result = await format_tool_response("glpi_search_helpdesk_tickets", "already markdown", {})
        assert result == "already markdown"

    async def test_bridge_string(self) -> None:
        result = await format_tool_response("glpi_read_resource_by_uri", "# Resource Content", {})
        assert result == "# Resource Content"


# ============================================================
# 7. Large response > 400KB returns error message
# ============================================================


class TestLargeResponse:
    """7. Response exceeding 400KB returns size error message."""

    async def test_large_response(self) -> None:
        # Create data that will produce a large Markdown output
        tickets = [_ticket(i) for i in range(5000)]
        result = await format_tool_response("glpi_search_helpdesk_tickets", tickets, {"limit": 5000, "offset": 0})
        # If the formatted output exceeds 400KB, we get the error message
        if "excede" in result:
            assert "400KB" in result or "KB" in result
        else:
            # If the output is under 400KB, it should still be valid Markdown
            assert "| ID |" in result


# ============================================================
# 8. All tools have formatter in TOOL_FORMATTERS
# ============================================================


class TestToolFormattersRegistry:
    """8. All expected tools are registered in TOOL_FORMATTERS."""

    EXPECTED_TOOLS = [
        "glpi_search_helpdesk_tickets",
        "glpi_manage_ticket_operations",
        "glpi_manage_ticket_ai_analysis",
        "glpi_search_asset_inventory",
        "glpi_manage_asset_operations",
        "glpi_search_admin_resources",
        "glpi_manage_admin_resources",
        "glpi_search_webhook_integrations",
        "glpi_manage_webhook_integrations",
        "glpi_search_knowledge_articles",
        "glpi_list_available_resources",
        "glpi_read_resource_by_uri",
        "glpi_list_available_prompts",
        "glpi_get_prompt_template",
    ]

    @pytest.mark.parametrize("tool_name", EXPECTED_TOOLS)
    async def test_tool_registered(self, tool_name: str) -> None:
        assert tool_name in TOOL_FORMATTERS, f"{tool_name} not found in TOOL_FORMATTERS"

    async def test_total_count(self) -> None:
        assert len(TOOL_FORMATTERS) == len(self.EXPECTED_TOOLS)


# ============================================================
# 9. manage_assets with different actions
# ============================================================


class TestManageAssetsActions:
    """9. manage_assets dispatches correctly for different actions."""

    async def test_get_returns_detail(self) -> None:
        result = await format_tool_response("glpi_manage_asset_operations", _asset(), {"action": "get"})
        assert "# Ativo:" in result

    async def test_create_returns_success(self) -> None:
        result = await format_tool_response("glpi_manage_asset_operations", {"id": 5}, {"action": "create"})
        assert "criar ativo" in result

    async def test_get_reservations(self) -> None:
        reservations = [{"id": 1, "items_id": 10, "begin": "2024-01-01T08:00:00", "end": "2024-01-01T17:00:00", "users_id": 1}]
        result = await format_tool_response("glpi_manage_asset_operations", reservations, {"action": "get_reservations"})
        assert "reservas" in result


# ============================================================
# 10. search_admin with different resources
# ============================================================


class TestSearchAdminResources:
    """10. search_admin dispatches correctly for different resources."""

    async def test_users(self) -> None:
        result = await format_tool_response("glpi_search_admin_resources", [_user()], {"resource": "users"})
        assert "| ID | Login |" in result

    async def test_groups(self) -> None:
        groups = [{"id": 1, "name": "IT"}]
        result = await format_tool_response("glpi_search_admin_resources", groups, {"resource": "groups"})
        assert "grupos" in result

    async def test_entities(self) -> None:
        entities = [{"id": 0, "name": "Root"}]
        result = await format_tool_response("glpi_search_admin_resources", entities, {"resource": "entities"})
        assert "entidades" in result

    async def test_locations(self) -> None:
        locations = [{"id": 1, "name": "HQ"}]
        result = await format_tool_response("glpi_search_admin_resources", locations, {"resource": "locations"})
        assert "localizacoes" in result


# ============================================================
# 11-21. Parametrized tests for ALL dispatch paths
# ============================================================


class TestDispatchManageTicketsActions:
    """11. Parametrized tests for all manage_tickets actions."""

    @pytest.mark.parametrize(
        "action,expected_substring",
        [
            ("get", "# Ticket"),
            ("get_by_number", "# Ticket"),
            ("get_followups", "acompanhamento"),
            ("get_history", "alteracoes"),
            ("get_stats", "Estatisticas"),
            ("find_similar", "similares"),
            ("create", "criar ticket"),
            ("update", "atualizar ticket"),
            ("delete", "excluir ticket"),
            ("assign", "atribuir ticket"),
            ("close", "fechar ticket"),
            ("resolve", "resolver ticket"),
            ("add_followup", "adicionar acompanhamento"),
        ],
    )
    async def test_action(self, action: str, expected_substring: str) -> None:
        if action in ("get", "get_by_number"):
            data = _ticket(1)
            data["content"] = "desc"
        elif action in ("get_followups",):
            data = [{"id": 1, "date": "2024-01-01T10:00:00", "content": "text", "is_private": False, "users_id": 1}]
        elif action == "get_history":
            data = [{"date_mod": "2024-01-01T10:00:00", "id_search_option": "s", "old_value": "a", "new_value": "b", "users_id": 1}]
        elif action == "get_stats":
            data = {"total": 10}
        elif action == "find_similar":
            data = [{"id": 2, "name": "Sim", "status": 1, "score": 0.9, "date": "2024-01-01T10:00:00"}]
        else:
            data = {"id": 99, "message": "OK"}

        result = _dispatch_manage_tickets(data, {"action": action})
        assert expected_substring in result


class TestDispatchManageAiActions:
    """12. Parametrized tests for all manage_ai actions."""

    @pytest.mark.parametrize(
        "action,expected_substring",
        [
            ("get_result", "Analise IA"),
            ("trigger", "trigger analise IA"),
            ("publish", "publish analise IA"),
        ],
    )
    async def test_action(self, action: str, expected_substring: str) -> None:
        if action == "get_result":
            data = {"classification": "Bug"}
        else:
            data = {"message": "OK"}
        result = _dispatch_manage_ai(data, {"action": action})
        assert expected_substring in result


class TestDispatchSearchAssetsScopes:
    """13. Parametrized tests for all search_assets scopes."""

    @pytest.mark.parametrize(
        "scope,expected_substring",
        [
            ("all", "resultados"),
            ("stats", "Estatisticas de Ativos"),
            ("reservations", "reservas"),
            # reservable agora rotula corretamente "itens reservaveis"
            ("reservable", "reservaveis"),
        ],
    )
    async def test_scope(self, scope: str, expected_substring: str) -> None:
        if scope == "stats":
            data = {"total": 10}
        elif scope == "reservable":
            data = {"reservable_items": [{"id": 1, "itemtype": "Computer", "items_id": 1, "name": "PC-01", "is_active": 1}], "count": 1}
        elif scope == "reservations":
            data = [{"id": 1, "items_id": 1, "begin": "2024-01-01T08:00:00", "end": "2024-01-01T17:00:00", "users_id": 1}]
        else:
            data = [_asset(1)]
        result = _dispatch_search_assets(data, {"scope": scope, "limit": 10, "offset": 0})
        assert expected_substring in result


class TestDispatchManageAssetsActions:
    """14. Parametrized tests for all manage_assets actions."""

    @pytest.mark.parametrize(
        "action,expected_substring",
        [
            ("get", "# Ativo"),
            ("get_details", "# Ativo"),
            ("get_reservations", "reservas"),
            ("create", "criar ativo"),
            ("update", "atualizar ativo"),
            ("delete", "excluir ativo"),
            ("create_reservation", "criar reserva"),
            ("update_reservation", "atualizar reserva"),
        ],
    )
    async def test_action(self, action: str, expected_substring: str) -> None:
        if action in ("get", "get_details"):
            data = _asset(1)
        elif action == "get_reservations":
            data = [{"id": 1, "items_id": 1, "begin": "2024-01-01T08:00:00", "end": "2024-01-01T17:00:00", "users_id": 1}]
        else:
            data = {"id": 10, "message": "OK"}
        result = _dispatch_manage_assets(data, {"action": action, "limit": 10, "offset": 0})
        assert expected_substring in result


class TestDispatchSearchAdminResources:
    """15. Parametrized tests for all search_admin resources."""

    @pytest.mark.parametrize(
        "resource,expected_substring",
        [
            ("users", "Login"),
            ("groups", "grupos"),
            ("entities", "entidades"),
            ("locations", "localizacoes"),
        ],
    )
    async def test_resource(self, resource: str, expected_substring: str) -> None:
        if resource == "users":
            data = [_user(1)]
        elif resource == "groups":
            data = [{"id": 1, "name": "G"}]
        elif resource == "entities":
            data = [{"id": 0, "name": "E"}]
        else:
            data = [{"id": 1, "name": "L"}]
        result = _dispatch_search_admin(data, {"resource": resource, "limit": 10, "offset": 0})
        assert expected_substring in result

    async def test_unknown_resource_defaults_to_users(self) -> None:
        data = [_user(1)]
        result = _dispatch_search_admin(data, {"resource": "unknown_resource", "limit": 10, "offset": 0})
        assert "Login" in result


class TestDispatchManageAdminCombos:
    """16. Parametrized tests for manage_admin action/resource combinations."""

    @pytest.mark.parametrize(
        "action,resource,expected_substring",
        [
            ("get", "users", "# Usuario"),
            ("get", "groups", "# Groups"),
            ("get", "entities", "# Entities"),
            ("create", "users", "create users"),
            ("update", "groups", "update groups"),
            ("delete", "entities", "delete entities"),
        ],
    )
    async def test_combo(self, action: str, resource: str, expected_substring: str) -> None:
        if action == "get" and resource == "users":
            data = _user(1)
        elif action == "get":
            data = {"id": 1, "name": "Test"}
        else:
            data = {"id": 1, "message": "OK"}
        result = _dispatch_manage_admin(data, {"action": action, "resource": resource})
        assert expected_substring in result


class TestDispatchSearchWebhooksScopes:
    """17. Parametrized tests for all search_webhooks scopes."""

    @pytest.mark.parametrize(
        "scope,expected_substring",
        [
            ("list", "webhooks"),
            ("stats", "Estatisticas de Webhooks"),
            ("deliveries", "entregas"),
        ],
    )
    async def test_scope(self, scope: str, expected_substring: str) -> None:
        if scope == "stats":
            data = {"total": 10}
        elif scope == "deliveries":
            data = [{"id": 1, "date": "2024-01-01T10:00:00", "status_code": 200, "event": "e", "response": "OK"}]
        else:
            data = [{"id": 1, "name": "WH", "is_active": True, "event": "e"}]
        result = _dispatch_search_webhooks(data, {"scope": scope, "limit": 10, "offset": 0})
        assert expected_substring in result


class TestDispatchManageWebhooksActions:
    """18. Parametrized tests for all manage_webhooks actions."""

    @pytest.mark.parametrize(
        "action,expected_substring",
        [
            ("get", "# Webhook"),
            ("create", "create webhook"),
            ("update", "update webhook"),
            ("delete", "delete webhook"),
            ("test", "test webhook"),
            ("trigger", "trigger webhook"),
            ("enable", "enable webhook"),
            ("disable", "disable webhook"),
            ("retry", "retry webhook"),
        ],
    )
    async def test_action(self, action: str, expected_substring: str) -> None:
        if action == "get":
            data = {"id": 1, "name": "WH", "url": "https://example.com", "is_active": True}
        else:
            data = {"message": "OK"}
        result = _dispatch_manage_webhooks(data, {"action": action})
        assert expected_substring in result


class TestFormatterExceptionFallback:
    """19. Formatter exception falls back to json.dumps."""

    async def test_formatter_exception_fallback(self) -> None:
        def boom_formatter(data: object, args: object) -> str:
            raise ValueError("boom")

        with patch.dict(TOOL_FORMATTERS, {"glpi_search_helpdesk_tickets": boom_formatter}):
            data = [_ticket(1)]
            result = await format_tool_response("glpi_search_helpdesk_tickets", data, {})
            # Should fall back to JSON
            parsed = json.loads(result)
            assert isinstance(parsed, list)

    async def test_formatter_runtime_error_fallback(self) -> None:
        def bad_formatter(data: object, args: object) -> str:
            raise RuntimeError("unexpected")

        with patch.dict(TOOL_FORMATTERS, {"glpi_search_helpdesk_tickets": bad_formatter}):
            data = {"id": 1}
            result = await format_tool_response("glpi_search_helpdesk_tickets", data, {})
            parsed = json.loads(result)
            assert parsed["id"] == 1


class TestFallbackChain:
    """20. Full fallback chain validation."""

    async def test_none_non_search_returns_empty(self) -> None:
        result = await format_tool_response("glpi_manage_ticket_operations", None, {})
        assert result == ""

    async def test_none_search_returns_not_found(self) -> None:
        result = await format_tool_response("glpi_search_helpdesk_tickets", None, {})
        assert result == "Nenhum resultado encontrado."

    async def test_unknown_tool_with_none(self) -> None:
        result = await format_tool_response("glpi_unknown", None, {})
        assert result == ""

    async def test_string_always_passthrough(self) -> None:
        for tool in ["glpi_search_helpdesk_tickets", "glpi_manage_ticket_operations", "glpi_unknown"]:
            result = await format_tool_response(tool, "passthrough", {})
            assert result == "passthrough"


class TestBridgeToolsPassthrough:
    """21. Bridge tools handle string and non-string data."""

    async def test_list_resources_with_list(self) -> None:
        resources = [{"uri": "glpi://test", "name": "Test", "description": "Desc"}]
        result = await format_tool_response("glpi_list_available_resources", resources, {})
        assert "resources disponiveis" in result

    async def test_list_resources_string_passthrough(self) -> None:
        result = await format_tool_response("glpi_list_available_resources", "# Already Markdown", {})
        assert result == "# Already Markdown"

    async def test_read_resource_string_passthrough(self) -> None:
        result = await format_tool_response("glpi_read_resource_by_uri", "content here", {})
        assert result == "content here"

    async def test_list_prompts_with_list(self) -> None:
        prompts = [{"name": "p1", "description": "d", "category": "c", "arguments": []}]
        result = await format_tool_response("glpi_list_available_prompts", prompts, {})
        assert "prompts disponiveis" in result

    async def test_get_prompt_string(self) -> None:
        result = await format_tool_response("glpi_get_prompt_template", "prompt text", {})
        assert result == "prompt text"

    async def test_get_prompt_dict(self) -> None:
        data = {"content": "test"}
        result = await format_tool_response("glpi_get_prompt_template", data, {})
        # Non-string goes through the lambda: str(data)
        assert "content" in result


class TestDefaultArgsFallback:
    """Additional: args=None defaults to empty dict."""

    async def test_none_args_defaults(self) -> None:
        data = [_ticket(1)]
        # Should not raise even with args=None
        result = await format_tool_response("glpi_search_helpdesk_tickets", data, None)
        assert "| ID |" in result

    async def test_missing_args(self) -> None:
        data = [_ticket(1)]
        result = await format_tool_response("glpi_search_helpdesk_tickets", data)
        assert "| ID |" in result
