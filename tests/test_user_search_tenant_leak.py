"""
Regression: user search must not leak across tenants.

The user search combines text conditions with OR (match_mode="any") and the
entity filter with AND. Flat, GLPI evaluates that left to right with no
precedence, so "login OR firstname OR realname AND entity" applied the entity
only to the last term — a search restricted to one client returned users from
other clients, with no sign that anything was wrong.

This server is multi-tenant: that is cross-client exposure, not a loose filter.
The text conditions therefore travel as a nested group, so the entity filter
constrains the whole match.
"""

from unittest.mock import AsyncMock, patch

from src.services.admin_service import USER_FIELD
from src.tools.admin import admin_tools

ENTITY_FIELD = 80


def _params_of(mock):
    call = mock.await_args
    assert call is not None, "search was never awaited"
    # admin_tools calls glpi_client.get(endpoint, params, use_cache=False)
    return call.args[1] if len(call.args) > 1 else call.kwargs["params"]


def _get_mock():
    return AsyncMock(return_value={"data": [], "totalcount": 0})


class TestEntityConstrainsTheWholeMatch:
    async def test_text_conditions_are_grouped_when_matching_any(self):
        mock = _get_mock()
        with patch("src.services.glpi_client.glpi_client.get", mock):
            await admin_tools.search_users(
                name="joao", firstname="joao", entity_id=3, match_mode="any"
            )

        params = _params_of(mock)
        # The group exists...
        assert "criteria[0][criteria][0][field]" in params
        # ...and the entity sits outside it, joined by AND.
        assert params["criteria[1][field]"] == ENTITY_FIELD
        assert params["criteria[1][link]"] == "AND"

    async def test_or_never_appears_at_the_top_level(self):
        """An OR at the top level is what let the entity filter slip."""
        mock = _get_mock()
        with patch("src.services.glpi_client.glpi_client.get", mock):
            await admin_tools.search_users(
                name="joao", realname="joao", entity_id=3, match_mode="any"
            )

        params = _params_of(mock)
        top_level_links = [
            value
            for key, value in params.items()
            if key.startswith("criteria[") and key.endswith("][link]")
            and "][criteria][" not in key
        ]
        assert "OR" not in top_level_links

    async def test_or_is_preserved_inside_the_group(self):
        mock = _get_mock()
        with patch("src.services.glpi_client.glpi_client.get", mock):
            await admin_tools.search_users(
                name="joao", realname="joao", match_mode="any"
            )

        params = _params_of(mock)
        assert params["criteria[0][criteria][1][link]"] == "OR"

    async def test_match_all_keeps_and_between_text_conditions(self):
        mock = _get_mock()
        with patch("src.services.glpi_client.glpi_client.get", mock):
            await admin_tools.search_users(
                name="joao", realname="silva", match_mode="all"
            )

        params = _params_of(mock)
        assert params["criteria[0][criteria][1][link]"] == "AND"


class TestSingleConditionStaysFlat:
    async def test_one_text_condition_needs_no_group(self):
        """A lone condition has nothing to group with — keep the request simple."""
        mock = _get_mock()
        with patch("src.services.glpi_client.glpi_client.get", mock):
            await admin_tools.search_users(name="joao", entity_id=3)

        params = _params_of(mock)
        assert params["criteria[0][field]"] == USER_FIELD["name"]
        assert params["criteria[1][field]"] == ENTITY_FIELD
        assert params["criteria[1][link]"] == "AND"

    async def test_entity_only_search_is_unchanged(self):
        mock = _get_mock()
        with patch("src.services.glpi_client.glpi_client.get", mock):
            await admin_tools.search_users(entity_id=3)

        params = _params_of(mock)
        assert params["criteria[0][field]"] == ENTITY_FIELD
