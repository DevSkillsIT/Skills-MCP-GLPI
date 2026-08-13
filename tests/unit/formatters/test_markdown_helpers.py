"""
Tests for src/formatters/markdown_helpers.py
Covers all public functions: esc, strip_html, truncate_field, page_info,
to_paged_response, check_response_size, remove_heavy_fields,
fmt_date, fmt_status, fmt_priority, fmt_type.
"""

import sys

sys.path.insert(0, "/opt/mcp-servers/glpi/.base-code")


from src.formatters.markdown_helpers import (
    check_response_size,
    esc,
    fmt_date,
    fmt_priority,
    fmt_status,
    fmt_type,
    page_info,
    remove_heavy_fields,
    strip_html,
    to_paged_response,
    truncate_field,
)


# ============================================================
# esc
# ============================================================


class TestEsc:
    """Tests for the esc() pipe-escaping helper."""

    def test_pipe_escaped(self) -> None:
        assert esc("foo|bar") == "foo\\|bar"

    def test_multiple_pipes(self) -> None:
        assert esc("a|b|c") == "a\\|b\\|c"

    def test_none_returns_empty(self) -> None:
        assert esc(None) == ""

    def test_integer_converted(self) -> None:
        assert esc(42) == "42"

    def test_float_converted(self) -> None:
        assert esc(3.14) == "3.14"

    def test_no_pipe_unchanged(self) -> None:
        assert esc("hello world") == "hello world"

    def test_empty_string(self) -> None:
        assert esc("") == ""


# ============================================================
# strip_html
# ============================================================


class TestStripHtml:
    """Tests for the strip_html() HTML cleaner."""

    def test_tags_removed(self) -> None:
        assert strip_html("<b>bold</b>") == "bold"

    def test_entities_decoded(self) -> None:
        assert strip_html("&amp; &lt; &gt;") == "& < >"

    def test_br_to_newline(self) -> None:
        result = strip_html("line1<br>line2")
        assert "line1\nline2" in result

    def test_br_self_closing(self) -> None:
        result = strip_html("line1<br/>line2")
        assert "line1\nline2" in result

    def test_p_to_newline(self) -> None:
        result = strip_html("<p>para1</p><p>para2</p>")
        assert "para1" in result
        assert "para2" in result
        assert "\n" in result

    def test_empty_returns_empty(self) -> None:
        assert strip_html("") == ""

    def test_none_returns_empty(self) -> None:
        assert strip_html(None) == ""

    def test_nested_html(self) -> None:
        assert strip_html("<div><span>text</span></div>") == "text"

    def test_li_to_dash(self) -> None:
        result = strip_html("<ul><li>item1</li><li>item2</li></ul>")
        assert "- item1" in result
        assert "- item2" in result

    def test_consecutive_newlines_collapsed(self) -> None:
        result = strip_html("<p></p><p></p><p></p><p>text</p>")
        # 3+ newlines should be collapsed to 2
        assert "\n\n\n" not in result


# ============================================================
# truncate_field
# ============================================================


class TestTruncateField:
    """Tests for the truncate_field() helper."""

    def test_short_text_untouched(self) -> None:
        result = truncate_field("short", max_len=300)
        assert result == "short"

    def test_long_text_truncated_with_ellipsis(self) -> None:
        long_text = "a" * 400
        result = truncate_field(long_text, max_len=300)
        assert result.endswith("...")
        # The visible part should be 300 chars + "..."
        assert len(result) == 303

    def test_html_stripped_before_truncation(self) -> None:
        html = "<b>" + "x" * 10 + "</b>"
        result = truncate_field(html, max_len=300)
        assert "<b>" not in result
        assert result == "x" * 10

    def test_none_returns_empty(self) -> None:
        assert truncate_field(None) == ""

    def test_empty_returns_empty(self) -> None:
        assert truncate_field("") == ""

    def test_pipe_escaped_in_result(self) -> None:
        result = truncate_field("foo|bar", max_len=300)
        assert result == "foo\\|bar"

    def test_exact_length_no_truncation(self) -> None:
        text = "a" * 300
        result = truncate_field(text, max_len=300)
        assert "..." not in result
        assert len(result) == 300


# ============================================================
# page_info
# ============================================================


class TestPageInfo:
    """Tests for the page_info() pagination helper."""

    def test_showing_all(self) -> None:
        result = page_info(count=5, limit=10, offset=0)
        assert "5 resultados" in result
        assert "Mostrando todos" in result

    def test_with_pagination(self) -> None:
        result = page_info(count=10, limit=10, offset=10, total=50)
        assert "10 resultados" in result
        assert "Pagina 2/5" in result
        assert "total: 50" in result

    def test_zero_count(self) -> None:
        result = page_info(count=0, limit=10, offset=0)
        assert "0 resultados" in result
        assert "Mostrando todos" in result

    def test_first_page(self) -> None:
        result = page_info(count=10, limit=10, offset=0, total=30)
        assert "Pagina 1/3" in result

    def test_total_equals_count(self) -> None:
        # total == count means no pagination needed
        result = page_info(count=5, limit=10, offset=0, total=5)
        assert "Mostrando todos" in result


# ============================================================
# to_paged_response
# ============================================================


class TestToPagedResponse:
    """Tests for the to_paged_response() pagination wrapper."""

    def test_list_data(self) -> None:
        items = [{"id": 1}, {"id": 2}]
        result = to_paged_response(items, offset=0, limit=10)
        assert result["data"] == items
        assert result["total"] == 2
        assert result["offset"] == 0
        assert result["limit"] == 10
        assert result["has_more"] is False

    def test_dict_data_with_totalcount(self) -> None:
        data = {"data": [{"id": 1}], "totalcount": 50}
        result = to_paged_response(data, offset=0, limit=10)
        assert result["data"] == [{"id": 1}]
        assert result["total"] == 50
        assert result["has_more"] is False  # len(items)=1 < limit=10

    def test_has_more_true(self) -> None:
        items = [{"id": i} for i in range(10)]
        result = to_paged_response(items, offset=0, limit=10)
        assert result["has_more"] is True  # len(items)==10 >= limit==10

    def test_has_more_false(self) -> None:
        items = [{"id": i} for i in range(5)]
        result = to_paged_response(items, offset=0, limit=10)
        assert result["has_more"] is False

    def test_empty_list(self) -> None:
        result = to_paged_response([], offset=0, limit=10)
        assert result["data"] == []
        assert result["total"] == 0
        assert result["has_more"] is False

    def test_non_list_non_dict_returns_empty(self) -> None:
        result = to_paged_response("not a list or dict", offset=0, limit=10)
        assert result["data"] == []


# ============================================================
# check_response_size
# ============================================================


class TestCheckResponseSize:
    """Tests for the check_response_size() helper."""

    def test_small_ok(self) -> None:
        result = check_response_size("small text")
        assert result["exceeded"] is False
        assert result["size"] > 0

    def test_over_400kb_exceeds(self) -> None:
        large_text = "x" * (401 * 1024)
        result = check_response_size(large_text)
        assert result["exceeded"] is True
        assert "excede" in result["message"]

    def test_exactly_at_limit(self) -> None:
        # 400 * 1024 bytes = 409600 bytes
        text = "x" * (400 * 1024)
        result = check_response_size(text)
        assert result["exceeded"] is False

    def test_custom_max_bytes(self) -> None:
        result = check_response_size("hello", max_bytes=3)
        assert result["exceeded"] is True


# ============================================================
# remove_heavy_fields
# ============================================================


class TestRemoveHeavyFields:
    """Tests for the remove_heavy_fields() helper."""

    def test_removes_links(self) -> None:
        data = {"id": 1, "links": [1, 2], "_links": {"self": "/"}, "completename": "Root"}
        result = remove_heavy_fields(data, mode="list")
        assert "links" not in result
        assert "_links" not in result
        assert "completename" not in result
        assert result["id"] == 1

    def test_list_mode_removes_content_description(self) -> None:
        data = {"id": 1, "content": "long text", "description": "desc", "comment": "c"}
        result = remove_heavy_fields(data, mode="list")
        assert "content" not in result
        assert "description" not in result
        assert "comment" not in result

    def test_detail_mode_keeps_content_description(self) -> None:
        data = {"id": 1, "content": "long text", "description": "desc"}
        result = remove_heavy_fields(data, mode="detail")
        assert "content" in result
        assert "description" in result

    def test_removes_underscore_prefixed_except_id(self) -> None:
        data = {"_id": 1, "_internal": "secret", "name": "test"}
        result = remove_heavy_fields(data, mode="list")
        assert "_id" in result
        assert "_internal" not in result

    def test_non_dict_returns_as_is(self) -> None:
        assert remove_heavy_fields("not a dict") == "not a dict"
        assert remove_heavy_fields(42) == 42
        assert remove_heavy_fields(None) is None

    def test_removes_href(self) -> None:
        data = {"id": 1, "href": "https://example.com"}
        result = remove_heavy_fields(data, mode="list")
        assert "href" not in result


# ============================================================
# fmt_date
# ============================================================


class TestFmtDate:
    """Tests for the fmt_date() ISO date formatter."""

    def test_iso_date_formatted(self) -> None:
        result = fmt_date("2024-03-15T14:30:00")
        assert result == "15/03/2024 14:30"

    def test_none_returns_na(self) -> None:
        assert fmt_date(None) == "N/A"

    def test_empty_returns_na(self) -> None:
        assert fmt_date("") == "N/A"

    def test_invalid_returns_original(self) -> None:
        assert fmt_date("not-a-date") == "not-a-date"

    def test_iso_with_z_suffix(self) -> None:
        result = fmt_date("2024-01-01T00:00:00Z")
        assert "01/01/2024" in result

    def test_iso_with_timezone(self) -> None:
        result = fmt_date("2024-06-15T10:00:00+03:00")
        assert "15/06/2024" in result


# ============================================================
# fmt_status
# ============================================================


class TestFmtStatus:
    """Tests for the fmt_status() ticket status formatter."""

    def test_status_1_novo(self) -> None:
        assert fmt_status(1) == "Novo"

    def test_status_6_fechado(self) -> None:
        assert fmt_status(6) == "Fechado"

    def test_status_99_desconhecido(self) -> None:
        assert fmt_status(99) == "Desconhecido (99)"

    def test_none_returns_na(self) -> None:
        assert fmt_status(None) == "N/A"

    def test_all_known_statuses(self) -> None:
        expected = {
            1: "Novo",
            2: "Atribuido",
            3: "Planejado",
            4: "Pendente",
            5: "Solucionado",
            6: "Fechado",
        }
        for code, label in expected.items():
            assert fmt_status(code) == label


# ============================================================
# fmt_priority
# ============================================================


class TestFmtPriority:
    """Tests for the fmt_priority() ticket priority formatter."""

    def test_priority_4_alta(self) -> None:
        assert fmt_priority(4) == "Alta"

    def test_none_returns_na(self) -> None:
        assert fmt_priority(None) == "N/A"

    def test_unknown_priority(self) -> None:
        assert fmt_priority(99) == "Desconhecida (99)"

    def test_all_known_priorities(self) -> None:
        expected = {
            1: "Muito baixa",
            2: "Baixa",
            3: "Media",
            4: "Alta",
            5: "Muito alta",
            6: "Maior",
        }
        for code, label in expected.items():
            assert fmt_priority(code) == label


# ============================================================
# fmt_type
# ============================================================


class TestFmtType:
    """Tests for the fmt_type() ticket type formatter."""

    def test_type_1_incidente(self) -> None:
        assert fmt_type(1) == "Incidente"

    def test_type_2_requisicao(self) -> None:
        assert fmt_type(2) == "Requisicao"

    def test_none_returns_na(self) -> None:
        assert fmt_type(None) == "N/A"

    def test_unknown_type(self) -> None:
        assert fmt_type(99) == "Desconhecido (99)"
