"""
Tests for the ticket query surface (SPEC: Fase 1 — capability density).

Two groups:

  A. Regression — the text-search branch silently dropped every filter other
     than the query itself. Asking for "open tickets mentioning printer"
     returned tickets in any status, with no warning. Reproduced here at both
     layers: the consolidated tool and the service.

  B. New filters — assigned tech, assigned group, requester, category,
     urgency, open_only, plus caller-controlled sorting.
"""

from unittest.mock import AsyncMock, patch


from src.services.ticket_service import TICKET_FIELD, ticket_service


def _search_mock():
    return AsyncMock(return_value={"data": []})


def _kwargs_of(mock):
    call = mock.await_args
    assert call is not None, "mock was never awaited"
    return call.kwargs


def _criteria_of(mock):
    return _kwargs_of(mock)["criteria"]


def _flat(criteria):
    """Yield every leaf criterion, descending into nested groups."""
    for crit in criteria:
        nested = crit.get("criteria")
        if nested:
            yield from _flat(nested)
        else:
            yield crit


def _field_values(criteria, field_id):
    return [c["value"] for c in _flat(criteria) if c.get("field") == field_id]


# ==========================================================================
# A. Regression: filters dropped on the text-search branch
# ==========================================================================

class TestTextSearchKeepsFilters:
    async def test_status_survives_text_search(self):
        """Reproduces the drop: query + status must still filter by status."""
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.search_tickets(query="impressora", status="new")

        assert _field_values(_criteria_of(mock), TICKET_FIELD["status"]) == [1]

    async def test_priority_survives_text_search(self):
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.search_tickets(query="impressora", priority=5)

        assert _field_values(_criteria_of(mock), TICKET_FIELD["priority"]) == [5]

    async def test_date_range_survives_text_search(self):
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.search_tickets(
                query="impressora",
                date_created_after="2026-08-01",
                date_created_before="2026-08-10",
            )

        criteria = _criteria_of(mock)
        assert _field_values(criteria, TICKET_FIELD["date"]) == [
            "2026-08-01",
            "2026-08-10",
        ]

    async def test_query_criterion_still_present_alongside_filters(self):
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.search_tickets(query="impressora", status="new")

        assert _field_values(_criteria_of(mock), TICKET_FIELD["name"]) == ["impressora"]

    async def test_text_search_also_covers_the_description(self):
        """A term that only appears in the body must still be found.

        The criterion used to cover the title alone while the tool advertised
        "title and content": searching for an error message — the main use
        case — returned "nothing found" as if it were a fact.
        """
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.search_tickets(query="paletizado")

        assert _field_values(_criteria_of(mock), TICKET_FIELD["content"]) == ["paletizado"]

    async def test_title_and_description_are_joined_by_or(self):
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.search_tickets(query="impressora")

        group = _criteria_of(mock)[0]["criteria"]
        assert group[0].get("link") in (None, "")
        assert group[1]["link"] == "OR"

    async def test_text_group_is_nested_so_filters_still_narrow(self):
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.search_tickets(query="impressora", status="new")

        criteria = _criteria_of(mock)
        assert "criteria" in criteria[0]
        assert "OR" not in [c.get("link") for c in criteria[1:]]


class TestConsolidatedToolForwardsFilters:
    """The tool layer must forward filters into the text-search branch too."""

    async def test_tool_forwards_status_on_query_branch(self):
        service_mock = AsyncMock(return_value=[])
        with patch(
            "src.tools.consolidated_tickets.ticket_service.search_tickets",
            service_mock,
        ):
            from src.tools.consolidated_tickets import search_tickets

            await search_tickets(query="impressora", status="new")

        assert _kwargs_of(service_mock).get("status") == "new"

    async def test_tool_forwards_priority_and_dates_on_query_branch(self):
        service_mock = AsyncMock(return_value=[])
        with patch(
            "src.tools.consolidated_tickets.ticket_service.search_tickets",
            service_mock,
        ):
            from src.tools.consolidated_tickets import search_tickets

            await search_tickets(
                query="impressora",
                priority=4,
                date_after="2026-08-01",
                date_before="2026-08-10",
            )

        kwargs = _kwargs_of(service_mock)
        assert kwargs.get("priority") == 4
        # The tool normalises a bare date into a full timestamp range.
        assert kwargs.get("date_created_after") == "2026-08-01 00:00:00"
        assert str(kwargs.get("date_created_before")).startswith("2026-08-10")


# ==========================================================================
# B. New filters
# ==========================================================================

class TestActorFilters:
    async def test_assigned_tech_by_id_uses_equals(self):
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.list_tickets(assigned_tech=42)

        crit = next(
            c for c in _criteria_of(mock) if c["field"] == TICKET_FIELD["tech_assign"]
        )
        assert crit["searchtype"] == "equals"
        assert crit["value"] == 42

    async def test_assigned_tech_by_name_uses_contains(self):
        """Names are matched loosely — the column renders the display name."""
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.list_tickets(assigned_tech="Joao")

        crit = next(
            c for c in _criteria_of(mock) if c["field"] == TICKET_FIELD["tech_assign"]
        )
        assert crit["searchtype"] == "contains"
        assert crit["value"] == "Joao"

    async def test_assigned_group_filter(self):
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.list_tickets(assigned_group="Infraestrutura")

        crit = next(
            c for c in _criteria_of(mock) if c["field"] == TICKET_FIELD["group_assign"]
        )
        assert crit["searchtype"] == "contains"
        assert crit["value"] == "Infraestrutura"

    async def test_requester_filter(self):
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.list_tickets(requester=7)

        assert _field_values(_criteria_of(mock), TICKET_FIELD["requester"]) == [7]

    async def test_numeric_string_is_treated_as_id(self):
        """A loose agent may send "42" instead of 42."""
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.list_tickets(assigned_tech="42")

        crit = next(
            c for c in _criteria_of(mock) if c["field"] == TICKET_FIELD["tech_assign"]
        )
        assert crit["searchtype"] == "equals"
        assert crit["value"] == 42


class TestCategoryAndUrgency:
    async def test_category_by_name(self):
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.list_tickets(category="Rede")

        crit = next(
            c for c in _criteria_of(mock) if c["field"] == TICKET_FIELD["category"]
        )
        assert crit["searchtype"] == "contains"
        assert crit["value"] == "Rede"

    async def test_urgency_is_distinct_from_priority(self):
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.list_tickets(urgency=5, priority=3)

        criteria = _criteria_of(mock)
        assert _field_values(criteria, TICKET_FIELD["urgency"]) == [5]
        assert _field_values(criteria, TICKET_FIELD["priority"]) == [3]


class TestOpenOnly:
    async def test_open_only_enumerates_the_open_statuses(self):
        """Open must list the open codes, never a range comparison.

        Measured on a live instance, an ordering operator on the status column
        behaves as equality: bounding at 4 returned only the pending tickets
        and hid the new, assigned and planned ones — answering "3 open" where
        there were 7, with no warning. Enumerating is the only correct form.
        """
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.list_tickets(open_only=True)

        status_criteria = [
            c for c in _flat(_criteria_of(mock)) if c["field"] == TICKET_FIELD["status"]
        ]
        assert [c["value"] for c in status_criteria] == [1, 2, 3, 4]
        assert all(c["searchtype"] == "equals" for c in status_criteria)

    async def test_open_statuses_travel_as_one_group(self):
        """Grouped, so a filter added afterwards still narrows the result."""
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.list_tickets(open_only=True, priority=5)

        criteria = _criteria_of(mock)
        assert "criteria" in criteria[0]
        # The OR only exists inside the group.
        assert "OR" not in [c.get("link") for c in criteria[1:]]

    async def test_open_only_never_uses_an_ordering_operator(self):
        """Guards the exact defect: lessthan on status acts as equality."""
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.list_tickets(open_only=True)

        operators = {c["searchtype"] for c in _flat(_criteria_of(mock))}
        assert not operators & {"lessthan", "morethan"}

    async def test_explicit_status_wins_over_open_only(self):
        """An explicit status is more specific — it must not be overridden."""
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.list_tickets(status="closed", open_only=True)

        status_criteria = [
            c for c in _criteria_of(mock) if c["field"] == TICKET_FIELD["status"]
        ]
        assert len(status_criteria) == 1
        assert status_criteria[0]["searchtype"] == "equals"
        assert status_criteria[0]["value"] == 6

    async def test_open_only_false_adds_nothing(self):
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.list_tickets(open_only=False)

        assert _field_values(_criteria_of(mock), TICKET_FIELD["status"]) == []


class TestSorting:
    async def test_default_sort_is_last_update_desc(self):
        """Existing behaviour must not change when the caller says nothing."""
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.list_tickets()

        assert _kwargs_of(mock)["sort"] == TICKET_FIELD["date_mod"]
        assert _kwargs_of(mock)["order"] == "DESC"

    async def test_sort_by_friendly_name(self):
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.list_tickets(sort_by="priority", order="asc")

        assert _kwargs_of(mock)["sort"] == TICKET_FIELD["priority"]
        assert _kwargs_of(mock)["order"] == "ASC"

    async def test_sort_by_numeric_id(self):
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.list_tickets(sort_by=15)

        assert _kwargs_of(mock)["sort"] == 15

    async def test_unknown_sort_field_falls_back_to_default(self):
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.list_tickets(sort_by="campo_inexistente")

        assert _kwargs_of(mock)["sort"] == TICKET_FIELD["date_mod"]

    async def test_sorting_also_applies_to_text_search(self):
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.search_tickets(query="impressora", sort_by="date", order="asc")

        assert _kwargs_of(mock)["sort"] == TICKET_FIELD["date"]
        assert _kwargs_of(mock)["order"] == "ASC"


class TestBackwardCompatibility:
    async def test_legacy_call_shape_unchanged(self):
        """The pre-existing parameter set must produce the same criteria."""
        mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", mock):
            await ticket_service.list_tickets(
                status="pending", priority=4, entity_id=0, limit=10
            )

        criteria = _criteria_of(mock)
        assert _field_values(criteria, TICKET_FIELD["status"]) == [4]
        assert _field_values(criteria, TICKET_FIELD["priority"]) == [4]
        assert _field_values(criteria, TICKET_FIELD["entities_id"]) == [0]
        assert len(criteria) == 3

    async def test_no_filters_still_uses_search_api(self):
        """An unfiltered listing still goes through /search.

        The lighter getAllItems endpoint returns raw ids for requester and
        category, so the listing would come back pruned. /search with
        expand_dropdowns resolves those names in the same round-trip.
        """
        search_mock = _search_mock()
        with patch("src.services.ticket_service.glpi_client.search", search_mock):
            await ticket_service.list_tickets(limit=5)

        search_mock.assert_awaited_once()
        assert _criteria_of(search_mock) == []
