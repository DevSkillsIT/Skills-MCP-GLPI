"""
Unit tests for SearchOptionsCache.

Covers the resolution cascade, the own-table tie-break, cache behaviour and
graceful degradation when listSearchOptions is unavailable.
"""

from unittest.mock import AsyncMock, patch

import pytest

from src.models.exceptions import ValidationError
from src.services.search_options import SearchOptionsCache


# Trimmed shape of a real /listSearchOptions/Ticket payload. Note the two
# entries carrying the SQL column "name": id 1 belongs to the ticket itself,
# id 4 arrives through the requester join.
TICKET_OPTIONS = {
    "common": "Caracteristicas",
    "1": {
        "name": "Titulo",
        "table": "glpi_tickets",
        "field": "name",
        "datatype": "itemlink",
        "uid": "Ticket.name",
        "available_searchtypes": ["contains", "equals"],
    },
    "4": {
        "name": "Requerente",
        "table": "glpi_users",
        "field": "name",
        "datatype": "dropdown",
        "uid": "Ticket.Ticket_User.User.name",
    },
    "12": {
        "name": "Status",
        "table": "glpi_tickets",
        "field": "status",
        "datatype": "specific",
        "uid": "Ticket.status",
    },
    "80": {
        "name": "Entidade",
        "table": "glpi_entities",
        "field": "completename",
        "datatype": "dropdown",
        "uid": "Ticket.Entity.completename",
    },
}


@pytest.fixture
def cache():
    return SearchOptionsCache()


def _patched_get(payload):
    """Patch the module-level glpi_client used by SearchOptionsCache."""
    return patch(
        "src.services.search_options.glpi_client.get",
        new=AsyncMock(return_value=payload),
    )


class TestResolutionCascade:
    async def test_numeric_int_passes_through_without_api_call(self, cache):
        with _patched_get(TICKET_OPTIONS) as mocked:
            assert await cache.resolve("Ticket", 12) == 12
            mocked.assert_not_called()

    async def test_numeric_string_passes_through(self, cache):
        assert await cache.resolve("Ticket", "12") == 12

    async def test_explicit_uid(self, cache):
        with _patched_get(TICKET_OPTIONS):
            assert await cache.resolve("Ticket", "Ticket.status") == 12

    async def test_canonical_own_table_uid_is_locale_independent(self, cache):
        # "status" becomes "Ticket.status" before the localized label is tried.
        with _patched_get(TICKET_OPTIONS):
            assert await cache.resolve("Ticket", "status") == 12

    async def test_translated_label(self, cache):
        with _patched_get(TICKET_OPTIONS):
            assert await cache.resolve("Ticket", "Requerente") == 4
            assert await cache.resolve("Ticket", "requerente") == 4

    async def test_raw_sql_column_fallback(self, cache):
        with _patched_get(TICKET_OPTIONS):
            assert await cache.resolve("Ticket", "completename") == 80

    async def test_unknown_reference_returns_none(self, cache):
        with _patched_get(TICKET_OPTIONS):
            assert await cache.resolve("Ticket", "campo_inexistente") is None

    async def test_bool_is_never_treated_as_field_id(self, cache):
        assert await cache.resolve("Ticket", True) is None

    @pytest.mark.parametrize("empty", [None, "", "   "])
    async def test_empty_references(self, cache, empty):
        assert await cache.resolve("Ticket", empty) is None


class TestOwnTableTieBreak:
    async def test_own_column_wins_over_joined_column(self, cache):
        """`name` must reach the ticket title (1), never the requester (4).

        This is the defect the tie-break exists to prevent: without it, a text
        filter on tickets would silently match user names instead of titles.
        """
        with _patched_get(TICKET_OPTIONS):
            assert await cache.resolve("Ticket", "name") == 1

    async def test_joined_column_still_reachable_by_label(self, cache):
        with _patched_get(TICKET_OPTIONS):
            assert await cache.resolve("Ticket", "Requerente") == 4


class TestCaching:
    async def test_catalogue_fetched_once_across_lookups(self, cache):
        with _patched_get(TICKET_OPTIONS) as mocked:
            await cache.resolve("Ticket", "status")
            await cache.resolve("Ticket", "name")
            await cache.resolve("Ticket", "Requerente")
            assert mocked.call_count == 1

    async def test_invalidate_forces_refetch(self, cache):
        with _patched_get(TICKET_OPTIONS) as mocked:
            await cache.resolve("Ticket", "status")
            cache.invalidate("Ticket")
            await cache.resolve("Ticket", "status")
            assert mocked.call_count == 2

    async def test_expired_entry_is_refetched(self, cache):
        with _patched_get(TICKET_OPTIONS) as mocked:
            await cache.resolve("Ticket", "status")
            catalogue = cache._cache["Ticket"]
            catalogue.fetched_at -= cache._TTL_SECONDS + 1
            await cache.resolve("Ticket", "status")
            assert mocked.call_count == 2

    async def test_distinct_itemtypes_cached_separately(self, cache):
        with _patched_get(TICKET_OPTIONS) as mocked:
            await cache.resolve("Ticket", "status")
            await cache.resolve("Computer", "status")
            assert mocked.call_count == 2


class TestGracefulDegradation:
    async def test_api_failure_falls_back_to_legacy_id(self, cache):
        with patch(
            "src.services.search_options.glpi_client.get",
            new=AsyncMock(side_effect=RuntimeError("GLPI down")),
        ):
            # "entity" on Ticket is a proven production id.
            assert await cache.resolve("Ticket", "entity") == 80

    async def test_api_failure_without_legacy_entry_returns_none(self, cache):
        with patch(
            "src.services.search_options.glpi_client.get",
            new=AsyncMock(side_effect=RuntimeError("GLPI down")),
        ):
            # Never guess a number for a reference we have not proven.
            assert await cache.resolve("Ticket", "urgency") is None

    async def test_malformed_payload_is_rejected(self, cache):
        with _patched_get(["not", "a", "dict"]):
            assert await cache.resolve("Ticket", "status") is None

    async def test_empty_catalogue_is_rejected(self, cache):
        with _patched_get({"common": "only metadata"}):
            assert await cache.resolve("Ticket", "status") is None

    async def test_non_dict_entries_are_skipped(self, cache):
        payload = dict(TICKET_OPTIONS)
        payload["99"] = "garbage"
        with _patched_get(payload):
            assert await cache.resolve("Ticket", "status") == 12


class TestResolveOrRaise:
    async def test_returns_id_when_resolvable(self, cache):
        with _patched_get(TICKET_OPTIONS):
            assert await cache.resolve_or_raise("Ticket", "status") == 12

    async def test_raises_with_actionable_message(self, cache):
        with _patched_get(TICKET_OPTIONS):
            with pytest.raises(ValidationError) as exc:
                await cache.resolve_or_raise("Ticket", "campo_inexistente")
            assert "campo_inexistente" in str(exc.value)


class TestDiscovery:
    async def test_available_fields_maps_labels_to_ids(self, cache):
        with _patched_get(TICKET_OPTIONS):
            fields = await cache.available_fields("Ticket")
            assert fields["Status"] == 12
            assert fields["Titulo"] == 1

    async def test_available_fields_empty_on_failure(self, cache):
        with patch(
            "src.services.search_options.glpi_client.get",
            new=AsyncMock(side_effect=RuntimeError("GLPI down")),
        ):
            assert await cache.available_fields("Ticket") == {}


# A live instance returns several options named "Status": the ticket's own
# column plus approval and solution statuses reached through joins.
HOMONYM_CATALOGUE = {
    "12": {"name": "Status", "table": "glpi_tickets", "field": "status", "uid": "Ticket.status"},
    "55": {"name": "Status", "table": "glpi_ticketvalidations", "field": "status", "uid": "Ticket.TicketValidation.status"},
    "202": {"name": "Status", "table": "glpi_itilsolutions", "field": "status", "uid": "Ticket.ITILSolution.status"},
    "1": {"name": "Titulo", "table": "glpi_tickets", "field": "name", "uid": "Ticket.name"},
}


class TestDiscoveryHandlesHomonyms:
    """Discovery must never advertise an id that resolution would not pick."""

    async def test_own_column_keeps_the_bare_label(self, cache):
        with _patched_get(HOMONYM_CATALOGUE):
            fields = await cache.available_fields("Ticket")

        assert fields["Status"] == 12

    async def test_resolution_agrees_with_discovery(self, cache):
        """The contract that matters: what is listed is what gets used."""
        with _patched_get(HOMONYM_CATALOGUE):
            fields = await cache.available_fields("Ticket")
            resolved = await cache.resolve("Ticket", "status")

        assert fields["Status"] == resolved

    async def test_homonyms_are_kept_but_qualified(self, cache):
        with _patched_get(HOMONYM_CATALOGUE):
            fields = await cache.available_fields("Ticket")

        # Nothing is silently dropped...
        assert sorted(fields.values()) == [1, 12, 55, 202]
        # ...and the extra ones say where they come from.
        qualified = [k for k in fields if k.startswith("Status ")]
        assert len(qualified) == 2

    async def test_no_label_is_lost_to_overwriting(self, cache):
        with _patched_get(HOMONYM_CATALOGUE):
            fields = await cache.available_fields("Ticket")

        assert len(fields) == len(HOMONYM_CATALOGUE)
