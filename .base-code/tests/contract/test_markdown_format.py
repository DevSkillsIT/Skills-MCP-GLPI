"""
Contract tests for Markdown response format.

Golden response tests: ensures formatters output Markdown tables,
not raw JSON.
"""

import sys

sys.path.insert(0, "/opt/mcp-servers/glpi/.base-code")

import json

import pytest

from src.formatters.glpi_formatters import (
    format_assets_list,
    format_ticket_detail,
    format_tickets_list,
)
from src.formatters.response_formatter import TOOL_FORMATTERS, format_tool_response


# === Fixtures ===


@pytest.fixture
def sample_tickets() -> dict:
    """Sample GLPI ticket list response."""
    return {
        "data": [
            {
                "id": 101,
                "name": "Impressora nao imprime",
                "status": 1,
                "priority": 3,
                "type": 1,
                "date": "2025-01-15T10:30:00",
            },
            {
                "id": 102,
                "name": "Sem acesso ao sistema",
                "status": 2,
                "priority": 4,
                "type": 2,
                "date": "2025-01-16T14:00:00",
            },
        ],
        "totalcount": 2,
    }


@pytest.fixture
def sample_ticket_detail() -> dict:
    """Sample GLPI single ticket response."""
    return {
        "id": 101,
        "name": "Impressora nao imprime",
        "status": 1,
        "priority": 3,
        "type": 1,
        "entities_id": 5,
        "users_id_recipient": 12,
        "date": "2025-01-15T10:30:00",
        "date_mod": "2025-01-15T11:00:00",
        "time_to_resolve": "2025-01-16T10:30:00",
        "content": "<p>A impressora HP parou de funcionar</p>",
    }


@pytest.fixture
def sample_assets() -> dict:
    """Sample GLPI asset list response."""
    return {
        "data": [
            {
                "id": 201,
                "name": "Notebook Dell Latitude",
                "serial": "SN12345",
                "otherserial": "PAT001",
                "states_id": 1,
                "locations_id": 3,
            },
        ],
        "totalcount": 1,
    }


@pytest.fixture
def default_args() -> dict:
    """Default formatter arguments."""
    return {"limit": 10, "offset": 0}


# === Golden response: search_tickets returns Markdown table ===


class TestSearchTicketsMarkdown:
    """search_tickets must return Markdown table, not JSON."""

    def test_returns_table_with_id_header(
        self, sample_tickets: dict, default_args: dict
    ) -> None:
        """Output contains Markdown table header '| ID |'."""
        result = format_tickets_list(sample_tickets, default_args)
        assert "| ID |" in result

    def test_does_not_return_json(
        self, sample_tickets: dict, default_args: dict
    ) -> None:
        """Output must NOT contain JSON key patterns."""
        result = format_tickets_list(sample_tickets, default_args)
        assert '"id":' not in result
        assert '"name":' not in result

    def test_via_format_tool_response(
        self, sample_tickets: dict, default_args: dict
    ) -> None:
        """format_tool_response routes correctly to Markdown formatter."""
        result = format_tool_response(
            "glpi_search_ticket_incidents", sample_tickets, default_args
        )
        assert "| ID |" in result
        assert '"id":' not in result


# === Golden response: search_assets returns Markdown table ===


class TestSearchAssetsMarkdown:
    """search_assets must return Markdown table, not JSON."""

    def test_returns_table_not_json(
        self, sample_assets: dict, default_args: dict
    ) -> None:
        """Output has table separator and no JSON."""
        result = format_assets_list(sample_assets, default_args)
        assert "| ID |" in result
        assert '"id":' not in result


# === Golden response: manage_tickets get returns detail heading ===


class TestManageTicketsGetMarkdown:
    """manage_tickets with action=get returns '# Ticket' heading."""

    def test_returns_ticket_heading(self, sample_ticket_detail: dict) -> None:
        """Detail output starts with '# Ticket' heading."""
        result = format_ticket_detail(sample_ticket_detail)
        assert result.startswith("# Ticket")

    def test_contains_field_value_table(self, sample_ticket_detail: dict) -> None:
        """Detail output has '| Campo | Valor |' field-value table."""
        result = format_ticket_detail(sample_ticket_detail)
        assert "| Campo | Valor |" in result

    def test_via_dispatch(self, sample_ticket_detail: dict) -> None:
        """format_tool_response dispatches manage_tickets get correctly."""
        result = format_tool_response(
            "glpi_manage_ticket_operations",
            sample_ticket_detail,
            {"action": "get"},
        )
        assert "# Ticket" in result
        assert "| Campo | Valor |" in result


# === All search tools return Markdown (parametrized) ===


SEARCH_TOOL_NAMES = [
    "glpi_search_ticket_incidents",
    "glpi_search_asset_inventory",
    "glpi_search_admin_resources",
    "glpi_search_webhook_integrations",
    "glpi_search_knowledge_articles",
]


@pytest.fixture
def generic_list_data() -> dict:
    """Generic list data that works for any search formatter."""
    return {
        "data": [
            {
                "id": 1,
                "name": "Test Item",
                "status": 1,
                "priority": 3,
                "type": 1,
                "date": "2025-01-01T00:00:00",
                "serial": "SN001",
                "otherserial": "PAT001",
                "states_id": 1,
                "locations_id": 1,
                "is_active": True,
                "last_login": "2025-01-01T00:00:00",
                "realname": "Test",
                "firstname": "User",
                "url": "https://example.com/hook",
                "event": "ticket.create",
                "comment": "Test comment",
                "address": "123 Street",
                "entities_id": 1,
            },
        ],
        "totalcount": 1,
    }


class TestAllSearchToolsReturnMarkdown:
    """All search tools must return Markdown, not JSON."""

    @pytest.mark.parametrize("tool_name", SEARCH_TOOL_NAMES)
    def test_search_tool_returns_markdown(
        self, tool_name: str, generic_list_data: dict, default_args: dict
    ) -> None:
        """Each search tool returns Markdown containing '|' (table separator)."""
        result = format_tool_response(tool_name, generic_list_data, default_args)
        assert "|" in result, f"{tool_name} did not return Markdown table"
        assert '"id":' not in result, f"{tool_name} returned JSON instead of Markdown"


# === Empty list returns friendly message ===


class TestEmptyListFriendlyMessage:
    """Empty data returns a human-friendly message, not '[]'."""

    def test_empty_tickets_list(self, default_args: dict) -> None:
        """Empty ticket list returns Portuguese message."""
        result = format_tickets_list({"data": []}, default_args)
        assert result == "Nenhum ticket encontrado."
        assert "[]" not in result

    def test_empty_assets_list(self, default_args: dict) -> None:
        """Empty asset list returns Portuguese message."""
        result = format_assets_list({"data": []}, default_args)
        assert result == "Nenhum ativo encontrado."
        assert "[]" not in result

    def test_none_search_via_format_tool_response(self) -> None:
        """None data for search tool returns friendly message."""
        result = format_tool_response("glpi_search_ticket_incidents", None, {})
        assert result == "Nenhum resultado encontrado."
        assert "[]" not in result

    def test_empty_list_not_json_array(self, default_args: dict) -> None:
        """Empty list never returns raw JSON '[]'."""
        result = format_tickets_list([], default_args)
        assert result != "[]"
        assert "Nenhum" in result
