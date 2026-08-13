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
    "glpi_search_helpdesk_tickets",
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
    # Busca por criterios livres (1)
    "glpi_search_records_by_criteria",
]

# Tools que NAO aparecem no registro de formatters porque ja devolvem Markdown
# pronto da propria camada de tool. Listadas aqui para que a diferenca seja uma
# decisao explicita, e nao um esquecimento — foi exatamente assim que a busca
# por criterios livres passou a devolver JSON cru sem ninguem notar.
SELF_FORMATTING_TOOLS = [
    "glpi_search_itil_records",
    "glpi_manage_itil_records",
    "glpi_search_knowledge_unified",
]

SEARCH_TOOLS = [
    "glpi_search_helpdesk_tickets",
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

    def test_registry_matches_the_expected_list(self) -> None:
        """The registry must be exactly the expected list — no more, no less.

        Comparing sets instead of counting: a fixed number ages badly and, worse,
        a count still passes when one tool is swapped for another.
        """
        assert set(TOOL_FORMATTERS) == set(EXPECTED_TOOLS)

    def test_self_formatting_tools_stay_out_of_the_registry(self) -> None:
        """Tools that build their own Markdown must not be registered twice."""
        for tool_name in SELF_FORMATTING_TOOLS:
            assert tool_name not in TOOL_FORMATTERS

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
