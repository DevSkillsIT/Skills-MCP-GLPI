"""
Regression tests: asset text search must honour the same filters as listing.

The text-search branch used to forward only the query, the asset type and the
entity. Manufacturer, location, status and responsible user were accepted,
validated and then dropped — so searching "notebook" with a manufacturer filter
quietly returned every notebook. The response looks perfectly normal, which is
what makes this class of defect dangerous.

The second half covers the reason it could not be fixed by simply appending the
filters: GLPI evaluates criteria left to right with no precedence, so an AND
appended after an OR chain widens the result instead of narrowing it. The text
conditions therefore have to travel as a nested group.
"""

from unittest.mock import AsyncMock, patch

from src.services.asset_service import ASSET_FIELD, asset_service


def _search_mock():
    return AsyncMock(return_value={"data": []})


def _criteria_of(mock):
    call = mock.await_args
    assert call is not None, "search was never awaited"
    return call.kwargs["criteria"]


def _flat(criteria):
    """Yield every leaf criterion, descending into nested groups."""
    for crit in criteria:
        nested = crit.get("criteria")
        if nested:
            yield from _flat(nested)
        else:
            yield crit


def _fields(criteria):
    return [c["field"] for c in _flat(criteria)]


class TestFiltersSurviveTextSearch:
    async def test_manufacturer_is_applied(self):
        mock = _search_mock()
        with patch.object(asset_service, "client") as client:
            client.search = mock
            client.get = AsyncMock(return_value={"data": []})
            await asset_service.search_assets(query="notebook", manufacturer_id=7)

        assert ASSET_FIELD["manufacturer"] in _fields(_criteria_of(mock))

    async def test_location_is_applied(self):
        mock = _search_mock()
        with patch.object(asset_service, "client") as client:
            client.search = mock
            client.get = AsyncMock(return_value={"data": []})
            await asset_service.search_assets(query="notebook", location_id=3)

        assert ASSET_FIELD["location"] in _fields(_criteria_of(mock))

    async def test_status_is_applied(self):
        mock = _search_mock()
        with patch.object(asset_service, "client") as client:
            client.search = mock
            client.get = AsyncMock(return_value={"data": []})
            await asset_service.search_assets(query="notebook", status=2)

        assert ASSET_FIELD["status"] in _fields(_criteria_of(mock))

    async def test_responsible_user_accepts_a_name(self):
        mock = _search_mock()
        with patch.object(asset_service, "client") as client:
            client.search = mock
            client.get = AsyncMock(return_value={"data": []})
            await asset_service.search_assets(query="notebook", assigned_user="Joao")

        user_criteria = [
            c for c in _flat(_criteria_of(mock)) if c["field"] == ASSET_FIELD["user"]
        ]
        assert any(c["searchtype"] == "contains" and c["value"] == "Joao" for c in user_criteria)


class TestTextConditionsAreGrouped:
    async def test_text_conditions_travel_as_one_group(self):
        """Without the group, a later AND is swallowed by the OR chain."""
        mock = _search_mock()
        with patch.object(asset_service, "client") as client:
            client.search = mock
            client.get = AsyncMock(return_value={"data": []})
            await asset_service.search_assets(query="notebook", manufacturer_id=7)

        criteria = _criteria_of(mock)
        assert "criteria" in criteria[0], "as condicoes de texto devem ir aninhadas"
        # Every OR lives inside the group, never at the top level.
        top_level_links = [c.get("link") for c in criteria[1:]]
        assert "OR" not in top_level_links

    async def test_filter_is_joined_with_and(self):
        mock = _search_mock()
        with patch.object(asset_service, "client") as client:
            client.search = mock
            client.get = AsyncMock(return_value={"data": []})
            await asset_service.search_assets(query="notebook", manufacturer_id=7)

        manufacturer = next(
            c
            for c in _criteria_of(mock)[1:]
            if c.get("field") == ASSET_FIELD["manufacturer"]
        )
        assert manufacturer["link"] == "AND"

    async def test_plain_search_still_works_without_filters(self):
        mock = _search_mock()
        with patch.object(asset_service, "client") as client:
            client.search = mock
            client.get = AsyncMock(return_value={"data": []})
            await asset_service.search_assets(query="notebook")

        criteria = _criteria_of(mock)
        assert len(criteria) == 1  # only the text group
        assert ASSET_FIELD["name"] in _fields(criteria)


class TestCriteriaSerialisation:
    """The client must serialise a nested group the way the API expects."""

    def test_nested_group_becomes_indexed_subkeys(self):
        from src.services.glpi_client import _emit_criteria

        params: dict = {}
        _emit_criteria(
            params,
            [
                {"criteria": [
                    {"field": 1, "searchtype": "contains", "value": "x"},
                    {"link": "OR", "field": 5, "searchtype": "contains", "value": "x"},
                ]},
                {"link": "AND", "field": 23, "searchtype": "equals", "value": 7},
            ],
            "criteria",
        )

        assert params["criteria[0][criteria][0][field]"] == 1
        assert params["criteria[0][criteria][1][link]"] == "OR"
        assert params["criteria[0][criteria][1][field]"] == 5
        assert params["criteria[1][link]"] == "AND"
        assert params["criteria[1][field]"] == 23
        # The group itself carries no field of its own.
        assert "criteria[0][field]" not in params

    def test_flat_list_is_unchanged(self):
        """Existing callers pass flat lists and must keep working."""
        from src.services.glpi_client import _emit_criteria

        params: dict = {}
        _emit_criteria(
            params,
            [
                {"field": 12, "searchtype": "equals", "value": 1},
                {"link": "AND", "field": 80, "searchtype": "under", "value": 0},
            ],
            "criteria",
        )

        assert params["criteria[0][field]"] == 12
        assert params["criteria[1][field]"] == 80
        assert params["criteria[1][link]"] == "AND"


class TestPlainSearchParity:
    """Grouping changed how every asset search is serialised, not just the
    filtered one. This pins that an unfiltered text search still produces the
    same conditions it produced before — same fields, same operators, same OR.
    """

    async def test_unfiltered_search_keeps_the_same_conditions(self):
        mock = _search_mock()
        with patch.object(asset_service, "client") as client:
            client.search = mock
            client.get = AsyncMock(return_value={"data": []})
            await asset_service.search_assets(query="notebook")

        leaves = list(_flat(_criteria_of(mock)))
        # Name, serial and contact are still searched, all with contains.
        assert ASSET_FIELD["name"] in [c["field"] for c in leaves]
        assert ASSET_FIELD["serial"] in [c["field"] for c in leaves]
        assert all(c["searchtype"] == "contains" for c in leaves)
        assert all(c["value"] == "notebook" for c in leaves)

    async def test_conditions_after_the_first_are_still_or(self):
        mock = _search_mock()
        with patch.object(asset_service, "client") as client:
            client.search = mock
            client.get = AsyncMock(return_value={"data": []})
            await asset_service.search_assets(query="notebook")

        leaves = list(_flat(_criteria_of(mock)))
        assert leaves[0].get("link") in (None, "")
        assert all(c["link"] == "OR" for c in leaves[1:])

    async def test_numeric_query_still_matches_the_id(self):
        mock = _search_mock()
        with patch.object(asset_service, "client") as client:
            client.search = mock
            client.get = AsyncMock(return_value={"data": []})
            await asset_service.search_assets(query="4321")

        leaves = list(_flat(_criteria_of(mock)))
        assert any(
            c["field"] == ASSET_FIELD["id"] and c["searchtype"] == "equals"
            for c in leaves
        )
