"""
Unit tests for the shared search-criteria helpers.

These rules used to live in two copies (tickets and assets). The tests exist to
keep the single definition honest, since a silent divergence here shows up as a
filter matching the wrong rows rather than as an error.
"""

import pytest

from src.utils.search_criteria import (
    actor_criterion,
    as_field_id,
    normalize_order,
    resolve_sort_field,
)


class TestAsFieldId:
    @pytest.mark.parametrize("value,expected", [(42, 42), (0, 0), (-1, -1)])
    def test_integers_pass_through(self, value, expected):
        assert as_field_id(value) == expected

    @pytest.mark.parametrize("value,expected", [("42", 42), (" 42 ", 42), ("-7", -7)])
    def test_numeric_strings_are_ids(self, value, expected):
        assert as_field_id(value) == expected

    @pytest.mark.parametrize("value", ["Joao", "", "  ", "42a", "4.2", None])
    def test_non_numeric_values_are_not_ids(self, value):
        assert as_field_id(value) is None

    @pytest.mark.parametrize("value", [True, False])
    def test_booleans_are_never_ids(self, value):
        """bool subclasses int — accepting it would filter on id 0 or 1."""
        assert as_field_id(value) is None


class TestActorCriterion:
    def test_id_matches_exactly(self):
        assert actor_criterion(5, 42) == {
            "field": 5,
            "searchtype": "equals",
            "value": 42,
        }

    def test_name_matches_loosely(self):
        assert actor_criterion(5, "Joao") == {
            "field": 5,
            "searchtype": "contains",
            "value": "Joao",
        }

    def test_name_is_trimmed(self):
        assert actor_criterion(8, "  Infraestrutura  ")["value"] == "Infraestrutura"

    def test_numeric_string_is_treated_as_id(self):
        assert actor_criterion(5, "42")["searchtype"] == "equals"


class TestResolveSortField:
    FIELDS = {"name": 1, "status": 12, "date": 15}

    def test_none_returns_default(self):
        assert resolve_sort_field(None, self.FIELDS, 19) == 19

    def test_friendly_name_resolves(self):
        assert resolve_sort_field("status", self.FIELDS, 19) == 12

    def test_name_is_case_insensitive(self):
        assert resolve_sort_field("STATUS", self.FIELDS, 19) == 12

    def test_numeric_id_passes_through(self):
        assert resolve_sort_field(15, self.FIELDS, 19) == 15

    def test_unknown_name_falls_back_instead_of_failing(self):
        """Sorting is a preference — never worth losing the whole result."""
        assert resolve_sort_field("nao_existe", self.FIELDS, 19) == 19


class TestNormalizeOrder:
    @pytest.mark.parametrize("value", ["asc", "ASC", " Asc "])
    def test_ascending_variants(self, value):
        assert normalize_order(value) == "ASC"

    @pytest.mark.parametrize("value", [None, "", "sideways", "descending"])
    def test_invalid_values_use_the_default(self, value):
        assert normalize_order(value) == "DESC"

    def test_explicit_default_is_respected(self):
        assert normalize_order(None, default="ASC") == "ASC"


class TestUserFieldSingleSource:
    """The user search must request and read the same columns.

    When forcedisplay and the response parser kept independent field lists,
    they drifted: the request asked for one column and the parser read another.
    Nothing about the response looks wrong in that state — every field comes
    back populated, just carrying the neighbouring column's content.
    """

    def test_forcedisplay_matches_the_parsed_fields(self):
        from src.services.admin_service import USER_FIELD
        from src.tools.admin import _user_forcedisplay

        # Read at call time, never frozen at import: reconciliation rewrites
        # USER_FIELD in place, and a snapshot would drift from the parser.
        assert set(_user_forcedisplay()) == set(USER_FIELD.values())

    def test_field_ids_are_unique(self):
        """Two keys sharing an id would silently return duplicated content."""
        from src.services.admin_service import USER_FIELD

        assert len(set(USER_FIELD.values())) == len(USER_FIELD)

    def test_sort_fields_are_derived_from_the_same_map(self):
        from src.services.admin_service import ADMIN_SORT_FIELDS, USER_FIELD

        for key, field_id in ADMIN_SORT_FIELDS["users"].items():
            assert field_id == USER_FIELD[key]
