"""
Tests for asset and admin query sorting (SPEC: Fase 1b — capability density).

Sorting reached the ticket surface first; assets and admin resources still
returned whatever order GLPI happened to pick, so "computers by last update"
or "users by creation date" were impossible to ask for. Three groups here:

  A. Assets — sorting on the listing and text-search paths, plus the new
     assigned_user filter (name or id, same contract as the ticket actors).
  B. Admin — sorting across users, groups, entities and locations, which are
     searched by two different layers and must agree on the field table.
  C. Backward compatibility — a call without the new parameters must produce
     the exact request it produced before sorting existed.
"""

import pytest
from unittest.mock import AsyncMock, patch

from src.services.admin_service import ADMIN_SORT_FIELDS, admin_service
from src.services.asset_service import ASSET_FIELD, asset_service
from src.tools.admin import admin_tools


@pytest.fixture(autouse=True)
def _no_live_catalogue():
    """Keep field reconciliation out of these tests.

    The user paths now reconcile USER_FIELD against the instance catalogue
    before searching, which costs a client call. With the client mocked, that
    call would consume the mock and the assertions would inspect the
    reconciliation request instead of the search request.
    """
    from src.services.admin_service import reset_user_field_sync

    reset_user_field_sync()
    with patch(
        "src.services.search_options.search_options_cache.get_catalogue",
        new=AsyncMock(side_effect=RuntimeError("catalogue unavailable in tests")),
    ):
        yield
    reset_user_field_sync()


def _search_mock():
    return AsyncMock(return_value={"data": []})


def _get_mock(payload=None):
    """Mock for the plain item endpoints, which return a list or a dict."""
    return AsyncMock(return_value=payload if payload is not None else [])


def _kwargs_of(mock):
    call = mock.await_args
    assert call is not None, "mock was never awaited"
    return call.kwargs


def _criteria_of(mock):
    return _kwargs_of(mock)["criteria"]


def _params_of(mock, call_index=0):
    """Read the params dict of a positional client.get(endpoint, params, ...)."""
    calls = mock.await_args_list
    assert calls, "mock was never awaited"
    return calls[call_index].args[1]


def _field_criterion(criteria, field_id):
    return next(c for c in criteria if c.get("field") == field_id)


# ==========================================================================
# A. Assets
# ==========================================================================

class TestAssetSorting:
    async def test_sort_by_friendly_name(self):
        mock = _search_mock()
        with patch("src.services.asset_service.glpi_client.search", mock):
            await asset_service.list_assets(entity_id=1, sort_by="serial")

        assert _kwargs_of(mock)["sort"] == ASSET_FIELD["serial"]

    async def test_sort_by_numeric_id(self):
        """A caller that already knows the GLPI field id may pass it raw."""
        mock = _search_mock()
        with patch("src.services.asset_service.glpi_client.search", mock):
            await asset_service.list_assets(entity_id=1, sort_by=19)

        assert _kwargs_of(mock)["sort"] == 19

    async def test_numeric_string_sort_is_treated_as_id(self):
        mock = _search_mock()
        with patch("src.services.asset_service.glpi_client.search", mock):
            await asset_service.list_assets(entity_id=1, sort_by="19")

        assert _kwargs_of(mock)["sort"] == 19

    async def test_unknown_sort_field_falls_back_to_name(self):
        """An unusable sort key must never fail the whole listing."""
        mock = _search_mock()
        with patch("src.services.asset_service.glpi_client.search", mock):
            await asset_service.list_assets(entity_id=1, sort_by="campo_inexistente")

        assert _kwargs_of(mock)["sort"] == ASSET_FIELD["name"]

    async def test_order_desc_is_normalised_to_upper_case(self):
        mock = _search_mock()
        with patch("src.services.asset_service.glpi_client.search", mock):
            await asset_service.list_assets(entity_id=1, sort_by="name", order="desc")

        assert _kwargs_of(mock)["order"] == "DESC"

    async def test_order_defaults_to_ascending(self):
        mock = _search_mock()
        with patch("src.services.asset_service.glpi_client.search", mock):
            await asset_service.list_assets(entity_id=1, sort_by="name")

        assert _kwargs_of(mock)["order"] == "ASC"

    async def test_invalid_order_falls_back_to_ascending(self):
        mock = _search_mock()
        with patch("src.services.asset_service.glpi_client.search", mock):
            await asset_service.list_assets(entity_id=1, sort_by="name", order="sideways")

        assert _kwargs_of(mock)["order"] == "ASC"

    async def test_order_alone_sorts_by_name(self):
        """Asking only for a direction still implies the default column."""
        mock = _search_mock()
        with patch("src.services.asset_service.glpi_client.search", mock):
            await asset_service.list_assets(entity_id=1, order="desc")

        kwargs = _kwargs_of(mock)
        assert kwargs["sort"] == ASSET_FIELD["name"]
        assert kwargs["order"] == "DESC"

    async def test_sorting_also_applies_to_text_search(self):
        mock = _search_mock()
        with patch("src.services.asset_service.glpi_client.search", mock):
            await asset_service.search_assets(query="notebook", sort_by="date_mod", order="desc")

        kwargs = _kwargs_of(mock)
        assert kwargs["sort"] == ASSET_FIELD["date_mod"]
        assert kwargs["order"] == "DESC"

    async def test_unfiltered_listing_sorts_on_the_plain_endpoint(self):
        """Without criteria the listing uses /apirest.php/{type}, which also
        understands sort/order — the caller must not lose ordering there."""
        mock = _get_mock([])
        with patch("src.services.asset_service.glpi_client.get", mock):
            await asset_service.list_assets(sort_by="name", order="desc")

        params = _params_of(mock)
        assert params["sort"] == ASSET_FIELD["name"]
        assert params["order"] == "DESC"


class TestAssignedUserFilter:
    async def test_assigned_user_by_id_uses_equals(self):
        mock = _search_mock()
        with patch("src.services.asset_service.glpi_client.search", mock):
            await asset_service.list_assets(assigned_user=42)

        crit = _field_criterion(_criteria_of(mock), ASSET_FIELD["user"])
        assert crit["searchtype"] == "equals"
        assert crit["value"] == 42

    async def test_assigned_user_by_name_uses_contains(self):
        """The user column renders a display name, so names match loosely."""
        mock = _search_mock()
        with patch("src.services.asset_service.glpi_client.search", mock):
            await asset_service.list_assets(assigned_user="Joao")

        crit = _field_criterion(_criteria_of(mock), ASSET_FIELD["user"])
        assert crit["searchtype"] == "contains"
        assert crit["value"] == "Joao"

    async def test_numeric_string_is_treated_as_id(self):
        """A loose agent may send "42" instead of 42."""
        mock = _search_mock()
        with patch("src.services.asset_service.glpi_client.search", mock):
            await asset_service.list_assets(assigned_user="42")

        crit = _field_criterion(_criteria_of(mock), ASSET_FIELD["user"])
        assert crit["searchtype"] == "equals"
        assert crit["value"] == 42

    async def test_assigned_user_wins_over_legacy_user_id(self):
        """Only one criterion on the user column, or the two would AND out."""
        mock = _search_mock()
        with patch("src.services.asset_service.glpi_client.search", mock):
            await asset_service.list_assets(assigned_user="Joao", user_id=7)

        user_criteria = [
            c for c in _criteria_of(mock) if c.get("field") == ASSET_FIELD["user"]
        ]
        assert len(user_criteria) == 1
        assert user_criteria[0]["value"] == "Joao"

    async def test_legacy_user_id_still_filters_when_assigned_user_absent(self):
        mock = _search_mock()
        with patch("src.services.asset_service.glpi_client.search", mock):
            await asset_service.list_assets(user_id=7)

        crit = _field_criterion(_criteria_of(mock), ASSET_FIELD["user"])
        assert crit["searchtype"] == "equals"
        assert crit["value"] == 7


class TestConsolidatedAssetToolForwards:
    """The tool layer must forward the new parameters to the service."""

    async def test_tool_forwards_sorting_on_listing_branch(self):
        tool_mock = AsyncMock(return_value=[])
        with patch("src.tools.consolidated_assets.asset_tools.list_assets", tool_mock):
            from src.tools.consolidated_assets import search_assets

            await search_assets(sort_by="date_mod", order="desc")

        kwargs = _kwargs_of(tool_mock)
        assert kwargs.get("sort_by") == "date_mod"
        assert kwargs.get("order") == "desc"

    async def test_tool_forwards_assigned_user_on_listing_branch(self):
        tool_mock = AsyncMock(return_value=[])
        with patch("src.tools.consolidated_assets.asset_tools.list_assets", tool_mock):
            from src.tools.consolidated_assets import search_assets

            await search_assets(assigned_user="Joao")

        assert _kwargs_of(tool_mock).get("assigned_user") == "Joao"

    async def test_tool_forwards_assigned_user_on_computers_scope(self):
        tool_mock = AsyncMock(return_value=[])
        with patch("src.tools.consolidated_assets.asset_tools.list_computers", tool_mock):
            from src.tools.consolidated_assets import search_assets

            await search_assets(scope="computers", assigned_user=42, sort_by="name")

        kwargs = _kwargs_of(tool_mock)
        assert kwargs.get("assigned_user") == 42
        assert kwargs.get("sort_by") == "name"

    async def test_tool_forwards_sorting_on_query_branch(self):
        tool_mock = AsyncMock(return_value=[])
        with patch("src.tools.consolidated_assets.asset_tools.search_assets", tool_mock):
            from src.tools.consolidated_assets import search_assets

            await search_assets(query="notebook", sort_by="serial", order="asc")

        kwargs = _kwargs_of(tool_mock)
        assert kwargs.get("sort_by") == "serial"
        assert kwargs.get("order") == "asc"

    async def test_software_scope_does_not_receive_assigned_user(self):
        """Software has no responsible-user column; the criterion would be
        rejected by GLPI, so the filter must not reach that branch."""
        tool_mock = AsyncMock(return_value=[])
        with patch("src.tools.consolidated_assets.asset_tools.list_software", tool_mock):
            from src.tools.consolidated_assets import search_assets

            await search_assets(scope="software", assigned_user="Joao", sort_by="name")

        kwargs = _kwargs_of(tool_mock)
        assert "assigned_user" not in kwargs
        assert kwargs.get("sort_by") == "name"


# ==========================================================================
# B. Admin resources
# ==========================================================================

class TestAdminUserSorting:
    async def test_users_sort_by_friendly_name(self):
        mock = _get_mock({"data": [{"2": "1", "1": "user"}], "totalcount": 1})
        with patch("src.services.glpi_client.glpi_client.get", mock):
            await admin_tools.search_users(name="ana", sort_by="email", order="desc")

        params = _params_of(mock)
        assert params["sort"] == ADMIN_SORT_FIELDS["users"]["email"]
        assert params["order"] == "DESC"

    async def test_users_sort_by_numeric_id(self):
        mock = _get_mock({"data": [{"2": "1", "1": "user"}], "totalcount": 1})
        with patch("src.services.glpi_client.glpi_client.get", mock):
            await admin_tools.search_users(name="ana", sort_by=34)

        assert _params_of(mock)["sort"] == 34

    async def test_users_unknown_sort_field_falls_back_to_name(self):
        mock = _get_mock({"data": [{"2": "1", "1": "user"}], "totalcount": 1})
        with patch("src.services.glpi_client.glpi_client.get", mock):
            await admin_tools.search_users(name="ana", sort_by="campo_inexistente")

        assert _params_of(mock)["sort"] == ADMIN_SORT_FIELDS["users"]["name"]


class TestAdminResourceSorting:
    async def test_groups_sort_by_friendly_name(self):
        mock = _get_mock([])
        with patch("src.services.admin_service.glpi_client.get", mock):
            await admin_service.list_groups(sort_by="date_mod", order="desc")

        params = _params_of(mock)
        assert params["sort"] == ADMIN_SORT_FIELDS["groups"]["date_mod"]
        assert params["order"] == "DESC"

    async def test_entities_sort_by_friendly_name(self):
        mock = _get_mock([])
        with patch("src.services.admin_service.glpi_client.get", mock):
            await admin_service.list_entities(sort_by="name", order="asc")

        params = _params_of(mock)
        assert params["sort"] == ADMIN_SORT_FIELDS["entities"]["name"]
        assert params["order"] == "ASC"

    async def test_locations_sort_by_numeric_id(self):
        mock = _get_mock([])
        with patch("src.services.admin_service.glpi_client.get", mock):
            await admin_service.list_locations(sort_by=16)

        assert _params_of(mock)["sort"] == 16

    async def test_unknown_sort_field_falls_back_to_name(self):
        """last_login only exists for users — asking a group for it must not
        raise, it must sort by name instead."""
        mock = _get_mock([])
        with patch("src.services.admin_service.glpi_client.get", mock):
            await admin_service.list_groups(sort_by="last_login")

        assert _params_of(mock)["sort"] == ADMIN_SORT_FIELDS["groups"]["name"]


class TestConsolidatedAdminToolForwards:
    async def test_tool_forwards_sorting_for_users(self):
        tool_mock = AsyncMock(return_value={"users": []})
        with patch("src.tools.consolidated_admin.admin_tools.search_users", tool_mock):
            from src.tools.consolidated_admin import search_admin

            await search_admin(resource="users", query="ana", sort_by="realname", order="asc")

        kwargs = _kwargs_of(tool_mock)
        assert kwargs.get("sort_by") == "realname"
        assert kwargs.get("order") == "asc"

    async def test_tool_forwards_sorting_for_users_without_query(self):
        tool_mock = AsyncMock(return_value={"users": []})
        with patch("src.tools.consolidated_admin.admin_tools.search_users", tool_mock):
            from src.tools.consolidated_admin import search_admin

            await search_admin(resource="users", sort_by="name")

        assert _kwargs_of(tool_mock).get("sort_by") == "name"

    async def test_tool_forwards_sorting_for_groups(self):
        tool_mock = AsyncMock(return_value={"groups": []})
        with patch("src.tools.consolidated_admin.admin_tools.list_groups", tool_mock):
            from src.tools.consolidated_admin import search_admin

            await search_admin(resource="groups", sort_by="name", order="desc")

        kwargs = _kwargs_of(tool_mock)
        assert kwargs.get("sort_by") == "name"
        assert kwargs.get("order") == "desc"

    async def test_tool_forwards_sorting_for_entities(self):
        tool_mock = AsyncMock(return_value={"entities": []})
        with patch("src.tools.consolidated_admin.admin_tools.list_entities", tool_mock):
            from src.tools.consolidated_admin import search_admin

            await search_admin(resource="entities", sort_by="id")

        assert _kwargs_of(tool_mock).get("sort_by") == "id"

    async def test_tool_forwards_sorting_for_locations(self):
        tool_mock = AsyncMock(return_value={"locations": []})
        with patch("src.tools.consolidated_admin.admin_tools.list_locations", tool_mock):
            from src.tools.consolidated_admin import search_admin

            await search_admin(resource="locations", sort_by="comment", order="asc")

        kwargs = _kwargs_of(tool_mock)
        assert kwargs.get("sort_by") == "comment"
        assert kwargs.get("order") == "asc"


# ==========================================================================
# C. Backward compatibility
# ==========================================================================

class TestBackwardCompatibility:
    async def test_asset_listing_without_sort_sends_no_sort_params(self):
        """The pre-existing call shape must reach GLPI unchanged."""
        mock = _search_mock()
        with patch("src.services.asset_service.glpi_client.search", mock):
            await asset_service.list_assets(entity_id=1, limit=10)

        kwargs = _kwargs_of(mock)
        assert kwargs["sort"] is None
        assert kwargs["order"] is None

    async def test_asset_unfiltered_listing_params_unchanged(self):
        mock = _get_mock([])
        with patch("src.services.asset_service.glpi_client.get", mock):
            await asset_service.list_assets(limit=10)

        params = _params_of(mock)
        assert "sort" not in params
        assert "order" not in params

    async def test_asset_text_search_without_sort_sends_no_sort_params(self):
        mock = _search_mock()
        with patch("src.services.asset_service.glpi_client.search", mock):
            await asset_service.search_assets(query="notebook")

        kwargs = _kwargs_of(mock)
        assert kwargs["sort"] is None
        assert kwargs["order"] is None

    async def test_asset_legacy_filters_still_build_the_same_criteria(self):
        mock = _search_mock()
        with patch("src.services.asset_service.glpi_client.search", mock):
            await asset_service.list_assets(
                entity_id=1, location_id=2, manufacturer_id=3, status="4"
            )

        criteria = _criteria_of(mock)
        assert [c["field"] for c in criteria] == [
            ASSET_FIELD["entity"],
            ASSET_FIELD["location"],
            ASSET_FIELD["manufacturer"],
            ASSET_FIELD["status"],
        ]
        assert len(criteria) == 4

    async def test_user_search_without_sort_sends_no_sort_params(self):
        mock = _get_mock({"data": [{"2": "1", "1": "user"}], "totalcount": 1})
        with patch("src.services.glpi_client.glpi_client.get", mock):
            await admin_tools.search_users(name="ana")

        params = _params_of(mock)
        assert "sort" not in params
        assert "order" not in params

    async def test_admin_listing_without_sort_sends_no_sort_params(self):
        mock = _get_mock([])
        with patch("src.services.admin_service.glpi_client.get", mock):
            await admin_service.list_groups(entity_id=1)

        params = _params_of(mock)
        assert "sort" not in params
        assert "order" not in params
