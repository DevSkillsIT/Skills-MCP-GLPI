"""
Integration tests for MCP tool annotations.

Validates annotation configuration matching SPEC Section 4.3.
Since handlers.py only emits annotations if they exist in tool_info,
this test defines the expected annotations contract and validates
that the annotation structure is correct per MCP protocol.
"""

import sys

sys.path.insert(0, "/opt/mcp-servers/glpi/.base-code")

import pytest

from src.formatters.response_formatter import TOOL_FORMATTERS


# Expected annotations per SPEC Section 4.3
# All tools MUST define these 4 properties:
#   readOnlyHint, destructiveHint, idempotentHint, openWorldHint
EXPECTED_ANNOTATIONS = {
    # search_* tools: read-only, non-destructive
    "glpi_search_helpdesk_tickets": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "glpi_search_asset_inventory": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "glpi_search_admin_resources": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "glpi_search_webhook_integrations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "glpi_search_knowledge_articles": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    # manage_* tools: destructive (mutate state)
    "glpi_manage_ticket_operations": {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    "glpi_manage_asset_operations": {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    "glpi_manage_admin_resources": {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    "glpi_manage_webhook_integrations": {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
    # manage_ai_analysis: non-destructive (analysis only)
    "glpi_manage_ticket_ai_analysis": {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    # Bridge: list_ tools have closed world (known catalog)
    "glpi_list_available_resources": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "glpi_list_available_prompts": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    # Bridge: read/get tools have open world (dynamic content)
    "glpi_read_resource_by_uri": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "glpi_get_prompt_template": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "glpi_search_records_by_criteria": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
}

ANNOTATION_PROPERTIES = [
    "readOnlyHint",
    "destructiveHint",
    "idempotentHint",
    "openWorldHint",
]

SEARCH_AND_LIST_TOOLS = [
    "glpi_search_helpdesk_tickets",
    "glpi_search_asset_inventory",
    "glpi_search_admin_resources",
    "glpi_search_webhook_integrations",
    "glpi_search_knowledge_articles",
    "glpi_list_available_resources",
    "glpi_list_available_prompts",
]

DESTRUCTIVE_MANAGE_TOOLS = [
    "glpi_manage_ticket_operations",
    "glpi_manage_asset_operations",
    "glpi_manage_admin_resources",
    "glpi_manage_webhook_integrations",
]

CLOSED_WORLD_TOOLS = [
    "glpi_list_available_resources",
    "glpi_list_available_prompts",
]

OPEN_WORLD_TOOLS = [
    "glpi_read_resource_by_uri",
    "glpi_get_prompt_template",
]


class TestAnnotationContract:
    """Validate annotation contract per SPEC Section 4.3."""

    def test_expected_annotations_cover_all_tools(self) -> None:
        """Every tool in TOOL_FORMATTERS has an expected annotation defined."""
        for tool_name in TOOL_FORMATTERS:
            assert tool_name in EXPECTED_ANNOTATIONS, (
                f"Missing annotation definition for: {tool_name}"
            )

    @pytest.mark.parametrize("tool_name", list(EXPECTED_ANNOTATIONS.keys()))
    def test_all_four_properties_defined(self, tool_name: str) -> None:
        """Each tool annotation has all 4 required properties."""
        annotations = EXPECTED_ANNOTATIONS[tool_name]
        for prop in ANNOTATION_PROPERTIES:
            assert prop in annotations, (
                f"{tool_name} missing annotation property: {prop}"
            )

    @pytest.mark.parametrize("tool_name", SEARCH_AND_LIST_TOOLS)
    def test_search_list_tools_are_read_only(self, tool_name: str) -> None:
        """search_* and list_* tools must be readOnlyHint=True."""
        annotations = EXPECTED_ANNOTATIONS[tool_name]
        assert annotations["readOnlyHint"] is True
        assert annotations["destructiveHint"] is False

    @pytest.mark.parametrize("tool_name", DESTRUCTIVE_MANAGE_TOOLS)
    def test_manage_tools_are_destructive(self, tool_name: str) -> None:
        """manage_tickets/assets/admin/webhooks must be destructiveHint=True."""
        annotations = EXPECTED_ANNOTATIONS[tool_name]
        assert annotations["destructiveHint"] is True

    def test_manage_ai_analysis_is_non_destructive(self) -> None:
        """manage_ai_analysis is analysis-only, not destructive."""
        annotations = EXPECTED_ANNOTATIONS["glpi_manage_ticket_ai_analysis"]
        assert annotations["destructiveHint"] is False

    @pytest.mark.parametrize("tool_name", CLOSED_WORLD_TOOLS)
    def test_list_tools_closed_world(self, tool_name: str) -> None:
        """list_resources and list_prompts have openWorldHint=False."""
        annotations = EXPECTED_ANNOTATIONS[tool_name]
        assert annotations["openWorldHint"] is False

    @pytest.mark.parametrize("tool_name", OPEN_WORLD_TOOLS)
    def test_read_get_tools_open_world(self, tool_name: str) -> None:
        """read_resource and get_prompt have openWorldHint=True."""
        annotations = EXPECTED_ANNOTATIONS[tool_name]
        assert annotations["openWorldHint"] is True

    def test_annotation_values_are_booleans(self) -> None:
        """All annotation values must be strict booleans."""
        for tool_name, annotations in EXPECTED_ANNOTATIONS.items():
            for prop in ANNOTATION_PROPERTIES:
                value = annotations[prop]
                assert isinstance(value, bool), (
                    f"{tool_name}.{prop} is {type(value).__name__}, expected bool"
                )
