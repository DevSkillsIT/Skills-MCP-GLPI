"""
Free-text search: words, not literal substrings.

Every case here failed on the live reference instance before the change, in the
same shape: each word alone returned rows, the natural phrase returned zero, and
the caller was told "nenhum resultado" as if that described the data.
"""

import pytest

from src.handlers import _normalize_argument_aliases
from src.utils.text_search import (
    build_text_criteria,
    describe_stage,
    plan_stages,
    run_text_search,
    score_by_coverage,
    significant_terms,
    split_terms,
)


def _leaves(criteria):
    """Flatten a criteria tree down to its leaf criteria."""
    for crit in criteria or []:
        nested = crit.get("criteria")
        if nested:
            yield from _leaves(nested)
        else:
            yield crit


class TestTokenisation:
    def test_a_phrase_becomes_one_term_per_word(self):
        terms, quoted = split_terms("Telefonica Vivo")
        assert terms == ["Telefonica", "Vivo"]
        assert quoted == []

    def test_quoted_run_stays_one_term(self):
        terms, quoted = split_terms('"Telefonica Brasil" internet')
        assert "Telefonica Brasil" in terms
        assert quoted == ["Telefonica Brasil"]

    def test_punctuation_glued_to_a_word_is_stripped(self):
        """'impressora,' searched literally matches nothing."""
        terms, _ = split_terms("impressora, sem toner")
        assert "impressora" in terms

    def test_connectors_are_dropped(self):
        """'problema com impressora' must not fail on 'com'."""
        assert "com" not in significant_terms(["problema", "com", "impressora"])

    def test_a_query_of_only_connectors_still_searches(self):
        """Dropping every term would match the whole table."""
        assert significant_terms(["de", "para"]) == ["de", "para"]

    def test_term_count_is_capped(self):
        terms, _ = split_terms(" ".join(f"palavra{i}" for i in range(30)))
        assert len(terms) <= 6


class TestCriteriaShape:
    def test_each_term_gets_its_own_group_joined_by_and(self):
        criteria = build_text_criteria([1, 16], ["Telefonica", "Vivo"], mode="all")
        assert len(criteria) == 2
        assert criteria[1]["link"] == "AND"
        # Inside a group the columns are alternatives.
        assert [c.get("link") for c in criteria[0]["criteria"]] == [None, "OR"]

    def test_every_term_is_searched_in_every_field(self):
        criteria = build_text_criteria([1, 16], ["a", "b"], mode="all")
        pairs = {(c["field"], c["value"]) for c in _leaves(criteria)}
        assert pairs == {(1, "a"), (16, "a"), (1, "b"), (16, "b")}

    def test_any_mode_is_a_single_or_group(self):
        criteria = build_text_criteria([1, 16], ["a", "b"], mode="any")
        assert len(criteria) == 1
        links = [c.get("link") for c in criteria[0]["criteria"]]
        assert links[0] is None and set(links[1:]) == {"OR"}

    def test_nesting_never_exceeds_two_levels(self):
        """Depth two is the shape proven against the live API."""

        def depth(node, level=1):
            nested = node.get("criteria")
            if not nested:
                return level
            return max(depth(child, level + 1) for child in nested)

        criteria = build_text_criteria([1, 16, 5], ["a", "b", "c"], mode="all")
        assert max(depth(group) for group in criteria) == 2

    def test_no_fields_yields_no_criteria(self):
        assert build_text_criteria([], ["a"], mode="all") == []


class TestEscalationPlan:
    def test_single_word_costs_one_request(self):
        """phrase, all and any would be identical -- paying three is waste."""
        stages, _ = plan_stages("impressora")
        assert [name for name, _ in stages] == ["phrase"]

    def test_multi_word_escalates_from_precise_to_loose(self):
        stages, _ = plan_stages("impressora nao imprime")
        assert [name for name, _ in stages] == ["phrase", "all", "any"]

    def test_a_fully_quoted_query_is_never_widened(self):
        """Quoting is an explicit request for the literal string."""
        stages, _ = plan_stages('"Telefonica Brasil"')
        assert [name for name, _ in stages] == ["phrase"]

    def test_empty_query_plans_nothing(self):
        assert plan_stages("   ") == ([], [])


@pytest.mark.asyncio
class TestEscalationRun:
    async def test_stops_at_the_first_stage_that_answers(self):
        calls = []

        async def execute(groups, fetch):
            calls.append(groups)
            return ([{"1": "Telefonica Brasil - VIVO"}], 1)

        rows, _total, stage, _terms = await run_text_search(
            "Telefonica Vivo", [1], execute, limit=5
        )
        assert stage == "phrase" and len(rows) == 1 and len(calls) == 1

    async def test_widens_only_after_the_precise_stages_come_back_empty(self):
        seen = []

        async def execute(groups, fetch):
            seen.append(len(groups))
            if len(seen) < 3:
                return ([], 0)
            return ([{"1": "Dell Latitude"}], 1)

        rows, _total, stage, _terms = await run_text_search(
            "Notebook Dell", [1], execute, limit=5
        )
        assert stage == "any" and rows

    async def test_widened_results_are_ranked_by_how_many_terms_match(self):
        async def execute(groups, fetch):
            if fetch <= 2:  # the strict stages
                return ([], 0)
            return (
                [
                    {"1": "Dell apenas"},
                    {"1": "Notebook Dell completo"},
                    {"1": "Notebook apenas"},
                ],
                3,
            )

        rows, _total, stage, _terms = await run_text_search(
            "Notebook Dell", [1], execute, limit=2
        )
        assert stage == "any"
        assert rows[0]["1"] == "Notebook Dell completo"
        assert len(rows) == 2

    async def test_widened_total_is_dropped_rather_than_overstated(self):
        """Over-fetching then ranking makes the server's total describe more
        rows than were kept; reporting it promises a page ranking consumed."""

        async def execute(groups, fetch):
            if fetch <= 1:
                return ([], 0)
            return ([{"1": f"row {i}"} for i in range(6)], 99)

        _rows, total, stage, _terms = await run_text_search(
            "Notebook Dell", [1], execute, limit=1
        )
        assert stage == "any" and total is None

    async def test_coverage_score_counts_distinct_terms(self):
        row = {"1": "Notebook Dell Latitude", "2": "serial"}
        assert score_by_coverage(row, ["notebook", "dell"]) == 2
        assert score_by_coverage(row, ["notebook", "acer"]) == 1


class TestStageReporting:
    def test_an_exact_phrase_match_is_not_announced(self):
        assert describe_stage("phrase", ["impressora"]) is None

    def test_a_widened_hit_says_so(self):
        assert "ampliada" in describe_stage("all", ["a", "b"])
        assert "ampliada" in describe_stage("any", ["a", "b"])

    def test_an_empty_result_never_claims_items_were_returned(self):
        """The success wording next to an empty table states a falsehood."""
        message = describe_stage("any", ["a", "b"], found=False)
        assert "esgotada" in message
        assert "exibindo" not in message


class TestArgumentAliases:
    """Four sibling tools named the same parameter four different ways."""

    ITIL = {"properties": {"record_type": {}, "query": {}, "limit": {}}}
    ADMIN = {"properties": {"resource": {}, "query": {}, "limit": {}}}
    ASSETS = {"properties": {"asset_type": {}, "query": {}}}
    CRITERIA = {"properties": {"itemtype": {}, "limit": {}}}

    def test_the_admin_spelling_reaches_the_itil_tool(self):
        out = _normalize_argument_aliases("itil", {"resource": "suppliers"}, self.ITIL)
        assert out == {"record_type": "suppliers"}

    def test_the_itil_spelling_reaches_the_admin_tool(self):
        """This one raised TypeError and surfaced as a tool failure."""
        out = _normalize_argument_aliases("admin", {"record_type": "users"}, self.ADMIN)
        assert out == {"resource": "users"}

    def test_it_reaches_assets_and_free_criteria_too(self):
        assert _normalize_argument_aliases(
            "assets", {"record_type": "Computer"}, self.ASSETS
        ) == {"asset_type": "Computer"}
        assert _normalize_argument_aliases(
            "criteria", {"record_type": "Ticket"}, self.CRITERIA
        ) == {"itemtype": "Ticket"}

    def test_free_text_synonyms_are_normalised(self):
        out = _normalize_argument_aliases("itil", {"search": "vivo"}, self.ITIL)
        assert out == {"query": "vivo"}

    def test_the_canonical_name_always_wins(self):
        out = _normalize_argument_aliases(
            "itil", {"record_type": "problems", "resource": "users"}, self.ITIL
        )
        assert out["record_type"] == "problems"

    def test_an_unrelated_argument_is_untouched(self):
        args = {"record_type": "suppliers", "entity_id": 3}
        assert _normalize_argument_aliases("itil", args, self.ITIL) == args

    def test_a_tool_declaring_none_of_the_group_is_left_alone(self):
        schema = {"properties": {"webhook_id": {}}}
        args = {"resource": "users"}
        assert _normalize_argument_aliases("webhooks", args, schema) == args

    def test_name_is_not_treated_as_free_text(self):
        """On manage_* tools `name` is a value being written, not a search."""
        schema = {"properties": {"name": {}, "record_type": {}}}
        args = {"name": "Novo fornecedor"}
        assert _normalize_argument_aliases("manage", args, schema) == args
