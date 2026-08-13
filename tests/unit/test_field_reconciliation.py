"""
Tests for reconciling static field maps against the live GLPI catalogue.

The static map is what production runs on and is known to work. Reconciliation
is a safety net against version, plugin and profile drift across the instances
we serve — so the bar is: it corrects what it can prove, leaves alone what it
cannot, and never breaks a search that would otherwise succeed.
"""

from unittest.mock import AsyncMock, patch

import pytest

from src.services.search_options import SearchOptionsCache


# Catalogue where the ticket status moved from 12 to 112 (the drift we are
# protecting against) while the title stayed put.
DRIFTED_CATALOGUE = {
    "1": {"name": "Titulo", "table": "glpi_tickets", "field": "name", "uid": "Ticket.name"},
    "112": {"name": "Status", "table": "glpi_tickets", "field": "status", "uid": "Ticket.status"},
    "4": {"name": "Requerente", "table": "glpi_users", "field": "name", "uid": "Ticket.Ticket_User.User.name"},
}

HINTS = {"name": "Ticket.name", "status": "Ticket.status"}


@pytest.fixture
def cache():
    return SearchOptionsCache()


def _patched_get(payload):
    return patch(
        "src.services.search_options.glpi_client.get",
        new=AsyncMock(return_value=payload),
    )


class TestCorrection:
    async def test_drifted_field_is_corrected_in_place(self, cache):
        field_map = {"name": 1, "status": 12, "requester": 4}

        with _patched_get(DRIFTED_CATALOGUE):
            report = await cache.reconcile("Ticket", field_map, HINTS)

        assert field_map["status"] == 112
        assert report["corrected"] == {"status": (12, 112)}

    async def test_matching_field_is_left_untouched(self, cache):
        field_map = {"name": 1, "status": 112}

        with _patched_get(DRIFTED_CATALOGUE):
            report = await cache.reconcile("Ticket", field_map, HINTS)

        assert field_map["name"] == 1
        assert "name" not in report["corrected"]

    async def test_report_is_empty_when_everything_matches(self, cache):
        field_map = {"name": 1}

        with _patched_get(DRIFTED_CATALOGUE):
            report = await cache.reconcile("Ticket", field_map, HINTS)

        assert report["corrected"] == {}
        assert report["missing"] == []


class TestJoinedFieldsAreOnlyChecked:
    async def test_joined_field_is_never_rewritten(self, cache):
        """Requester reaches the catalogue through a join.

        There is no locale-independent way to re-derive it, so replacing a
        working id with a guess would be worse than the drift itself.
        """
        field_map = {"requester": 4}

        with _patched_get(DRIFTED_CATALOGUE):
            report = await cache.reconcile("Ticket", field_map, HINTS)

        assert field_map["requester"] == 4
        assert report["corrected"] == {}

    async def test_absent_field_is_reported_but_kept(self, cache):
        field_map = {"sla_flag": 82}

        with _patched_get(DRIFTED_CATALOGUE):
            report = await cache.reconcile("Ticket", field_map, HINTS)

        assert field_map["sla_flag"] == 82  # untouched
        assert "sla_flag" in report["missing"]


class TestNeverBreaksTheCaller:
    async def test_unreachable_catalogue_leaves_map_intact(self, cache):
        field_map = {"name": 1, "status": 12}
        original = dict(field_map)

        with patch(
            "src.services.search_options.glpi_client.get",
            new=AsyncMock(side_effect=RuntimeError("GLPI down")),
        ):
            report = await cache.reconcile("Ticket", field_map, HINTS)

        assert field_map == original
        assert report["checked"] is False

    async def test_empty_catalogue_leaves_map_intact(self, cache):
        field_map = {"name": 1, "status": 12}
        original = dict(field_map)

        with _patched_get({"common": "metadata only"}):
            await cache.reconcile("Ticket", field_map, HINTS)

        assert field_map == original

    async def test_reconcile_without_hints_only_checks(self, cache):
        field_map = {"status": 12}

        with _patched_get(DRIFTED_CATALOGUE):
            report = await cache.reconcile("Ticket", field_map)

        assert field_map["status"] == 12
        assert "status" in report["missing"]


class TestTicketServiceIntegration:
    async def test_search_reconciles_once_across_calls(self):
        """The lazy pass must not add a lookup to every search."""
        import src.services.ticket_service as ts

        ts._field_sync_done = False
        search_mock = AsyncMock(return_value={"data": []})
        reconcile_mock = AsyncMock(return_value={"corrected": {}, "missing": [], "checked": True})

        with patch("src.services.ticket_service.glpi_client.search", search_mock), patch(
            "src.services.ticket_service.search_options_cache.reconcile", reconcile_mock
        ):
            await ts.ticket_service.list_tickets(status="new")
            await ts.ticket_service.list_tickets(status="closed")
            await ts.ticket_service.search_tickets(query="impressora")

        assert reconcile_mock.await_count == 1

    async def test_reconciliation_failure_does_not_break_search(self):
        import src.services.ticket_service as ts

        ts._field_sync_done = False
        search_mock = AsyncMock(return_value={"data": []})

        with patch("src.services.ticket_service.glpi_client.search", search_mock), patch(
            "src.services.ticket_service.search_options_cache.reconcile",
            new=AsyncMock(side_effect=RuntimeError("catalogue unavailable")),
        ):
            result = await ts.ticket_service.list_tickets(status="new")

        assert result == []
        search_mock.assert_awaited_once()
