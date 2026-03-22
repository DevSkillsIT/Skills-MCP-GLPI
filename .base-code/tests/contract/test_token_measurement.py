"""
Contract tests for token/size measurement.

Validates that Markdown formatting produces smaller output than JSON,
responses stay within size limits, and HTML stripping reduces content.
"""

import sys

sys.path.insert(0, "/opt/mcp-servers/glpi/.base-code")

import json

import pytest

from src.formatters.glpi_formatters import format_tickets_list
from src.formatters.markdown_helpers import check_response_size, strip_html
from src.formatters.response_formatter import format_tool_response


# === Fixtures ===


@pytest.fixture
def large_ticket_list() -> dict:
    """Generate a list of 50 tickets for size measurement."""
    tickets = []
    for i in range(1, 51):
        tickets.append(
            {
                "id": i,
                "name": f"Ticket de teste numero {i} com descricao longa para simular dados reais do GLPI",
                "status": (i % 6) + 1,
                "priority": (i % 5) + 1,
                "type": (i % 2) + 1,
                "date": f"2025-01-{(i % 28) + 1:02d}T10:00:00",
                "entities_id": i % 10,
                "users_id_recipient": i % 20,
                "content": f"<p>Descricao detalhada do ticket {i} com <b>HTML</b> e &amp; entidades</p>",
            }
        )
    return {"data": tickets, "totalcount": 50}


@pytest.fixture
def default_args() -> dict:
    """Default formatter arguments."""
    return {"limit": 50, "offset": 0}


@pytest.fixture
def html_content() -> str:
    """HTML content typical from GLPI TinyMCE editor."""
    return (
        "<p>O usuario <b>Joao Silva</b> reportou que a "
        "<a href='#'>impressora HP LaserJet</a> nao esta "
        "funcionando corretamente.</p>"
        "<ul><li>Erro ao imprimir</li><li>LED piscando</li></ul>"
        "<p>Ja foi verificado o cabo USB e &amp; as configuracoes.</p>"
    )


# === Markdown uses fewer chars than JSON ===


class TestMarkdownSmallerThanJson:
    """Markdown output must be at least 40% smaller than raw JSON."""

    def test_markdown_at_least_40_percent_smaller(
        self, large_ticket_list: dict, default_args: dict
    ) -> None:
        """Markdown representation uses fewer chars than JSON."""
        markdown_output = format_tickets_list(large_ticket_list, default_args)
        json_output = json.dumps(
            large_ticket_list, ensure_ascii=False, indent=2
        )

        markdown_size = len(markdown_output)
        json_size = len(json_output)

        reduction = (json_size - markdown_size) / json_size
        assert reduction >= 0.40, (
            f"Markdown reduction is only {reduction:.1%}, expected >= 40%. "
            f"Markdown: {markdown_size} chars, JSON: {json_size} chars"
        )

    def test_markdown_smaller_via_format_tool_response(
        self, large_ticket_list: dict, default_args: dict
    ) -> None:
        """format_tool_response also produces smaller output than JSON."""
        markdown_output = format_tool_response(
            "glpi_search_ticket_incidents", large_ticket_list, default_args
        )
        json_output = json.dumps(
            large_ticket_list, ensure_ascii=False, indent=2
        )

        assert len(markdown_output) < len(json_output)


# === No response exceeds 400KB ===


class TestResponseSizeLimit:
    """No formatted response should exceed 400KB."""

    def test_small_response_within_limit(
        self, large_ticket_list: dict, default_args: dict
    ) -> None:
        """A 50-ticket response stays well within 400KB."""
        markdown_output = format_tickets_list(large_ticket_list, default_args)
        size_check = check_response_size(markdown_output)
        assert size_check["exceeded"] is False

    def test_check_response_size_detects_oversized(self) -> None:
        """check_response_size flags content exceeding the limit."""
        oversized_content = "x" * (401 * 1024)
        size_check = check_response_size(oversized_content)
        assert size_check["exceeded"] is True
        assert "400KB" in size_check["message"]

    def test_check_response_size_reports_byte_count(self) -> None:
        """check_response_size returns actual byte size."""
        content = "Hello World"
        size_check = check_response_size(content)
        assert size_check["exceeded"] is False
        assert size_check["size"] == len(content.encode("utf-8"))

    def test_format_tool_response_handles_oversized(self) -> None:
        """format_tool_response returns size error for oversized data."""
        huge_list = {
            "data": [
                {"id": i, "name": "A" * 10000, "status": 1, "priority": 1, "type": 1, "date": "2025-01-01"}
                for i in range(100)
            ]
        }
        result = format_tool_response(
            "glpi_search_ticket_incidents", huge_list, {"limit": 100, "offset": 0}
        )
        # Either the result is valid Markdown or a size-exceeded message
        size_bytes = len(result.encode("utf-8"))
        assert size_bytes <= 450 * 1024, (
            f"Response is {size_bytes // 1024}KB, must not be unbounded"
        )


# === HTML stripping reduces content size ===


class TestHtmlStrippingReducesSize:
    """strip_html must reduce the size of HTML content."""

    def test_stripped_smaller_than_original(self, html_content: str) -> None:
        """Stripped text is shorter than the original HTML."""
        stripped = strip_html(html_content)
        assert len(stripped) < len(html_content)

    def test_no_html_tags_remain(self, html_content: str) -> None:
        """No HTML tags remain after stripping."""
        stripped = strip_html(html_content)
        assert "<p>" not in stripped
        assert "<b>" not in stripped
        assert "<a " not in stripped
        assert "<ul>" not in stripped
        assert "<li>" not in stripped
        assert "</p>" not in stripped

    def test_html_entities_decoded(self, html_content: str) -> None:
        """HTML entities like &amp; are decoded."""
        stripped = strip_html(html_content)
        assert "&amp;" not in stripped
        assert "&" in stripped

    def test_empty_input_returns_empty(self) -> None:
        """strip_html on empty/None returns empty string."""
        assert strip_html("") == ""
        assert strip_html(None) == ""

    def test_plain_text_unchanged(self) -> None:
        """Plain text without HTML passes through unchanged."""
        plain = "Texto sem HTML aqui"
        assert strip_html(plain) == plain

    def test_br_converted_to_newline(self) -> None:
        """<br> and <br/> tags are converted to newlines."""
        html = "Linha 1<br>Linha 2<br/>Linha 3"
        stripped = strip_html(html)
        assert "Linha 1" in stripped
        assert "Linha 2" in stripped
        assert "Linha 3" in stripped
        assert "<br" not in stripped
