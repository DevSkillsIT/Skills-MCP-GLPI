"""
Tests for the advanced search tool (free criteria, cheap count, field discovery).

The capability already existed in the client and was simply unreachable. These
tests pin the contract that makes it safe to expose: field names resolve
through the live catalogue, an unknown field fails with an actionable message
instead of querying the wrong column, and counting never pulls rows.
"""

from unittest.mock import AsyncMock, patch

import pytest

from src.models.exceptions import ValidationError
from src.tools.consolidated_search import format_search_records, search_records

TICKET_OPTIONS = {
    "1": {"name": "Titulo", "table": "glpi_tickets", "field": "name", "uid": "Ticket.name"},
    "12": {"name": "Status", "table": "glpi_tickets", "field": "status", "uid": "Ticket.status"},
    "15": {"name": "Data de abertura", "table": "glpi_tickets", "field": "date", "uid": "Ticket.date"},
}


def _catalogue():
    return patch(
        "src.services.search_options.glpi_client.get",
        new=AsyncMock(return_value=TICKET_OPTIONS),
    )


@pytest.fixture(autouse=True)
def _fresh_catalogue():
    from src.services.search_options import search_options_cache

    search_options_cache.invalidate()
    yield
    search_options_cache.invalidate()


class TestFieldResolution:
    async def test_field_name_is_resolved_to_its_id(self):
        search = AsyncMock(return_value={"data": [], "totalcount": 0})
        with _catalogue(), patch("src.tools.consolidated_search.glpi_client.search", search):
            await search_records(
                itemtype="Ticket",
                criteria=[{"field": "status", "searchtype": "equals", "value": 1}],
            )

        assert search.await_args.kwargs["criteria"][0]["field"] == 12

    async def test_numeric_field_passes_through(self):
        search = AsyncMock(return_value={"data": [], "totalcount": 0})
        with _catalogue(), patch("src.tools.consolidated_search.glpi_client.search", search):
            await search_records(
                itemtype="Ticket",
                criteria=[{"field": 12, "searchtype": "equals", "value": 1}],
            )

        assert search.await_args.kwargs["criteria"][0]["field"] == 12

    async def test_unknown_field_fails_with_guidance(self):
        with _catalogue():
            with pytest.raises(ValidationError) as exc:
                await search_records(
                    itemtype="Ticket",
                    criteria=[{"field": "campo_que_nao_existe", "value": 1}],
                )

        message = str(exc.value)
        assert "campo_que_nao_existe" in message
        assert "scope=fields" in message


class TestCriteriaValidation:
    async def test_invalid_operator_is_rejected(self):
        with _catalogue():
            with pytest.raises(ValidationError) as exc:
                await search_records(
                    itemtype="Ticket",
                    criteria=[{"field": "status", "searchtype": "aproximadamente", "value": 1}],
                )
        assert "aproximadamente" in str(exc.value)

    async def test_invalid_link_is_rejected(self):
        with _catalogue():
            with pytest.raises(ValidationError):
                await search_records(
                    itemtype="Ticket",
                    criteria=[
                        {"field": "status", "searchtype": "equals", "value": 1},
                        {"field": "name", "searchtype": "contains", "value": "x", "link": "TALVEZ"},
                    ],
                )

    async def test_criterion_without_field_is_rejected(self):
        with _catalogue():
            with pytest.raises(ValidationError):
                await search_records(itemtype="Ticket", criteria=[{"value": 1}])

    async def test_subsequent_criteria_default_to_and(self):
        search = AsyncMock(return_value={"data": [], "totalcount": 0})
        with _catalogue(), patch("src.tools.consolidated_search.glpi_client.search", search):
            await search_records(
                itemtype="Ticket",
                criteria=[
                    {"field": "status", "searchtype": "equals", "value": 1},
                    {"field": "name", "searchtype": "contains", "value": "x"},
                ],
            )

        assert search.await_args.kwargs["criteria"][1]["link"] == "AND"

    async def test_or_is_preserved(self):
        search = AsyncMock(return_value={"data": [], "totalcount": 0})
        with _catalogue(), patch("src.tools.consolidated_search.glpi_client.search", search):
            await search_records(
                itemtype="Ticket",
                criteria=[
                    {"field": "status", "searchtype": "equals", "value": 1},
                    {"field": "status", "searchtype": "equals", "value": 2, "link": "or"},
                ],
            )

        assert search.await_args.kwargs["criteria"][1]["link"] == "OR"

    async def test_too_many_criteria_is_rejected(self):
        with _catalogue():
            with pytest.raises(ValidationError):
                await search_records(
                    itemtype="Ticket",
                    criteria=[{"field": "status", "value": i} for i in range(20)],
                )


class TestScopes:
    async def test_itemtype_is_required(self):
        with pytest.raises(ValidationError):
            await search_records(scope="search")

    async def test_invalid_scope_is_rejected(self):
        with pytest.raises(ValidationError):
            await search_records(itemtype="Ticket", scope="tudo")

    async def test_count_reads_total_without_pulling_rows(self):
        probe = AsyncMock(return_value={"totalcount": 4213, "data": []})
        with _catalogue(), patch("src.tools.consolidated_search.glpi_client.get", probe):
            out = await search_records(itemtype="Ticket", scope="count")

        assert out["total"] == 4213
        # The cheap probe asks for an empty window.
        assert probe.await_args.kwargs["params"]["range"] == "0-0"

    async def test_fields_scope_lists_the_catalogue(self):
        with _catalogue():
            out = await search_records(itemtype="Ticket", scope="fields")

        assert out["fields"]["Status"] == 12
        assert out["total"] == 3

    async def test_fields_scope_can_be_filtered(self):
        with _catalogue():
            out = await search_records(itemtype="Ticket", scope="fields", field_filter="stat")

        assert list(out["fields"]) == ["Status"]


class TestSearchScope:
    async def test_limit_is_capped(self):
        search = AsyncMock(return_value={"data": [], "totalcount": 0})
        with _catalogue(), patch("src.tools.consolidated_search.glpi_client.search", search):
            out = await search_records(itemtype="Ticket", limit=9999)

        assert out["limit"] == 50

    async def test_unknown_sort_field_is_ignored_not_fatal(self):
        search = AsyncMock(return_value={"data": [], "totalcount": 0})
        with _catalogue(), patch("src.tools.consolidated_search.glpi_client.search", search):
            await search_records(itemtype="Ticket", sort_by="campo_inexistente")

        assert search.await_args.kwargs["sort"] is None

    async def test_requested_columns_are_resolved(self):
        search = AsyncMock(return_value={"data": [], "totalcount": 0})
        with _catalogue(), patch("src.tools.consolidated_search.glpi_client.search", search):
            await search_records(itemtype="Ticket", fields=["status", "name"])

        assert search.await_args.kwargs["forcedisplay"] == [12, 1]


class TestFormatting:
    def test_count_renders_the_total(self):
        out = format_search_records(
            {"itemtype": "Ticket", "scope": "count", "total": 42, "criteria_count": 1}, {}
        )
        assert "42" in out and "Ticket" in out

    def test_fields_render_as_a_table(self):
        out = format_search_records(
            {"itemtype": "Ticket", "scope": "fields", "fields": {"Status": 12}}, {}
        )
        assert "| Campo | ID |" in out and "Status" in out

    def test_empty_search_is_explicit(self):
        out = format_search_records(
            {"itemtype": "Ticket", "scope": "search", "rows": []}, {}
        )
        assert "Nenhum registro" in out

    def test_rows_render_as_a_table(self):
        out = format_search_records(
            {
                "itemtype": "Ticket",
                "scope": "search",
                "rows": [{"1": "Impressora", "12": "Novo"}],
                "total": 1,
                "limit": 10,
                "offset": 0,
            },
            {},
        )
        assert "Impressora" in out and "|" in out
