"""Unit tests: Markdown formatting + weak-title display fallback (pure)."""

from __future__ import annotations

from src.services.kb_search.hybrid_query import SOLUTION_SNIPPET
from src.services.kb_search.rrf import UnifiedHit
from src.services.kb_search.service import (
    _SOLUTION_MAX,
    _display_title,
    _format_solution,
    format_markdown,
)


def _hit(**over: object) -> UnifiedHit:
    base: dict[str, object] = dict(
        source="HELP", is_official=True, id="1", title="Titulo bem grande aqui",
        context="Ctx", url="http://x", source_rank=1, rrf_score=0.5, similarity=0.812,
    )
    base.update(over)
    return UnifiedHit(**base)  # type: ignore[arg-type]


class TestSolutionCell:
    def test_short_solution_is_untouched(self) -> None:
        assert _format_solution("Trocado o cabo.") == "Trocado o cabo."

    def test_db_truncation_is_marked_even_when_collapsing_shrinks_it(self) -> None:
        """The DB caps the column; collapsing whitespace can bring a value that
        WAS cut back under the display cap, hiding the truncation."""
        cut = ("palavra   \n\n   " * 80)[:SOLUTION_SNIPPET]
        assert len(" ".join(cut.split())) < _SOLUTION_MAX  # collapse hides the cut
        assert _format_solution(cut).endswith("…")

    def test_no_false_ellipsis_on_a_complete_solution(self) -> None:
        """Complete and within the display cap — nothing was cut anywhere."""
        assert not _format_solution("x" * (_SOLUTION_MAX - 1)).endswith("…")

    def test_ellipsis_when_the_display_cap_is_what_cuts(self) -> None:
        """Fetched whole but longer than the cell allows: still a cut."""
        assert _format_solution("x" * (_SOLUTION_MAX + 10)).endswith("…")

    def test_missing_solution_only_claims_solved_for_ticket_sources(self) -> None:
        """Documentation and forum items have no solution by nature; labelling
        them "solved without a description" is false."""
        ticket = format_markdown([_hit(source="CHAMADOS", solution="", solutions_expected=True)])
        doc = format_markdown([_hit(source="HELP", solution="", solutions_expected=False)])
        assert "resolvido" in ticket
        assert "resolvido" not in doc


class TestFormatMarkdown:
    def test_empty(self) -> None:
        assert "Nenhum" in format_markdown([])

    def test_table_renders(self) -> None:
        md = format_markdown([_hit()])
        assert "| HELP |" in md and "Sim" in md and "0.812" in md and "http://x" in md

    def test_keyword_score_is_dash(self) -> None:
        md = format_markdown([_hit(is_official=False, similarity=None)])
        assert "Nao" in md and "—" in md

    def test_pipe_escaped(self) -> None:
        md = format_markdown([_hit(title="a | b")])
        assert "a \\| b" in md

    def test_rank_column_reflects_order(self) -> None:
        # "#" column makes the RRF order unambiguous even when the displayed
        # similarity is non-monotonic across rows.
        a = _hit(id="A", similarity=0.40)
        b = _hit(id="B", similarity=0.90)
        md = format_markdown([a, b])  # input order = RRF order
        assert "| # |" in md  # header
        lines = [ln for ln in md.splitlines() if ln.startswith("| ") and "http" in ln]
        assert lines[0].startswith("| 1 |") and "| A |" in lines[0]
        assert lines[1].startswith("| 2 |") and "| B |" in lines[1]


class TestDisplayTitle:
    def test_weak_title_uses_body_snippet(self) -> None:
        h = _hit(title="Sankhya", body="nota fiscal nao emite por erro de imposto")
        assert "nota fiscal" in _display_title(h)

    def test_strong_title_kept(self) -> None:
        h = _hit(title="Como configurar o boleto no financeiro", body="x")
        assert _display_title(h) == "Como configurar o boleto no financeiro"

    def test_weak_title_no_body_kept_as_is(self) -> None:
        h = _hit(title="GLPI", body="")
        assert _display_title(h) == "GLPI"
