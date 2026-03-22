"""
Integration tests for TOOL_FORMATTERS registry in response_formatter.py

Validates that the central tool registry has all expected tools registered.
"""

import sys

sys.path.insert(0, "/opt/mcp-servers/glpi/.base-code")

import pytest

from src.formatters.response_formatter import TOOL_FORMATTERS


# All 14 tool names expected in the TOOL_FORMATTERS registry
EXPECTED_TOOLS = [
    # Tickets (3)
    "glpi_search_ticket_incidents",
    "glpi_manage_ticket_operations",
    "glpi_manage_ticket_ai_analysis",
    # Assets (2)
    "glpi_search_asset_inventory",
    "glpi_manage_asset_operations",
    # Admin (2)
    "glpi_search_admin_resources",
    "glpi_manage_admin_resources",
    # Webhooks (2)
    "glpi_search_webhook_integrations",
    "glpi_manage_webhook_integrations",
    # Knowledge (1)
    "glpi_search_knowledge_articles",
    # Bridge (4)
    "glpi_list_available_resources",
    "glpi_read_resource_by_uri",
    "glpi_list_available_prompts",
    "glpi_get_prompt_template",
]

SEARCH_TOOLS = [
    "glpi_search_ticket_incidents",
    "glpi_search_asset_inventory",
    "glpi_search_admin_resources",
    "glpi_search_webhook_integrations",
    "glpi_search_knowledge_articles",
]

MANAGE_TOOLS = [
    "glpi_manage_ticket_operations",
    "glpi_manage_asset_operations",
    "glpi_manage_admin_resources",
    "glpi_manage_webhook_integrations",
    "glpi_manage_ticket_ai_analysis",
]

BRIDGE_TOOLS = [
    "glpi_list_available_resources",
    "glpi_read_resource_by_uri",
    "glpi_list_available_prompts",
    "glpi_get_prompt_template",
]


class TestToolsRegistry:
    """Tests for TOOL_FORMATTERS central registry."""

    def test_total_tools_count_is_14(self) -> None:
        """TOOL_FORMATTERS must have exactly 14 entries."""
        assert len(TOOL_FORMATTERS) == 14

    def test_all_expected_tools_present(self) -> None:
        """Every expected tool name must exist as a key."""
        for tool_name in EXPECTED_TOOLS:
            assert tool_name in TOOL_FORMATTERS, f"Missing tool: {tool_name}"

    def test_no_unexpected_tools(self) -> None:
        """No extra tools beyond the expected 14."""
        extra = set(TOOL_FORMATTERS.keys()) - set(EXPECTED_TOOLS)
        assert extra == set(), f"Unexpected tools: {extra}"

    @pytest.mark.parametrize("tool_name", SEARCH_TOOLS)
    def test_search_tools_present(self, tool_name: str) -> None:
        """All search_* tools are registered."""
        assert tool_name in TOOL_FORMATTERS

    @pytest.mark.parametrize("tool_name", MANAGE_TOOLS)
    def test_manage_tools_present(self, tool_name: str) -> None:
        """All manage_* tools are registered."""
        assert tool_name in TOOL_FORMATTERS

    @pytest.mark.parametrize("tool_name", BRIDGE_TOOLS)
    def test_bridge_tools_present(self, tool_name: str) -> None:
        """All bridge tools are registered."""
        assert tool_name in TOOL_FORMATTERS

    def test_all_formatters_are_callable(self) -> None:
        """Every formatter value must be callable."""
        for tool_name, formatter in TOOL_FORMATTERS.items():
            assert callable(formatter), f"{tool_name} formatter is not callable"
