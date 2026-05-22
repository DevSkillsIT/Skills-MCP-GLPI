"""Unit tests: cross-source RRF fusion, weighting, dedup (pure)."""

from __future__ import annotations

from src.services.kb_search.rrf import (
    Hit,
    SourceResults,
    cross_source_rrf,
    dedup_by_title,
)


class TestDedupByTitle:
    def test_collapses_accent_and_case_variants(self) -> None:
        hits = [
            Hit(id="1", title="Serviço de Configuração", url="u1"),
            Hit(id="2", title="servico de configuracao", url="u2"),
            Hit(id="3", title="Outro assunto", url="u3"),
        ]
        assert [h.id for h in dedup_by_title(hits)] == ["1", "3"]

    def test_preserves_order_and_keeps_first(self) -> None:
        hits = [Hit(id="a", title="X", url="u"), Hit(id="b", title="Y", url="u")]
        assert [h.id for h in dedup_by_title(hits)] == ["a", "b"]

    def test_empty(self) -> None:
        assert dedup_by_title([]) == []


class TestCrossSourceRRF:
    def test_official_wins_equal_rank_and_weight(self) -> None:
        h = SourceResults("HELP", True, [Hit(id="h1", title="A", url="u")], weight=1.0)
        c = SourceResults("COMUNIDADE", False, [Hit(id="c1", title="B", url="u")], weight=1.0)
        assert cross_source_rrf([h, c])[0].id == "h1"

    def test_weight_boosts_source(self) -> None:
        light = SourceResults("A", False, [Hit(id="a1", title="A", url="u")], weight=0.5)
        heavy = SourceResults("B", False, [Hit(id="b1", title="B", url="u")], weight=2.0)
        fused = cross_source_rrf([light, heavy])
        assert fused[0].id == "b1" and fused[0].rrf_score > fused[1].rrf_score

    def test_rank_one_beats_rank_two(self) -> None:
        src = SourceResults("S", True, [Hit(id="1", title="A", url="u"), Hit(id="2", title="B", url="u")])
        fused = cross_source_rrf([src])
        assert [h.id for h in fused] == ["1", "2"]
        assert fused[0].rrf_score == 1.0 / 61

    def test_source_rank_is_position_not_similarity(self) -> None:
        src = SourceResults("s", False, [Hit(id="1", title="A", url="u", similarity=0.05)])
        fused = cross_source_rrf([src])
        assert fused[0].source_rank == 1 and fused[0].rrf_score == 1.0 / 61

    def test_empty_sources(self) -> None:
        assert cross_source_rrf([]) == []


class TestCanonicalDedup:
    def test_collapses_cross_source_by_canonical_id(self) -> None:
        s1 = SourceResults("HELP", True, [Hit(id="h1", title="A", url="u", canonical_id="DOC-9")])
        s2 = SourceResults("COMUNIDADE", False, [Hit(id="c1", title="A2", url="u", canonical_id="DOC-9")])
        fused = cross_source_rrf([s1, s2])
        assert len(fused) == 1 and fused[0].id == "h1"

    def test_null_canonical_not_collapsed(self) -> None:
        s1 = SourceResults("A", False, [Hit(id="1", title="x", url="u")])
        s2 = SourceResults("B", False, [Hit(id="2", title="y", url="u")])
        assert len(cross_source_rrf([s1, s2])) == 2

    def test_distinct_canonical_kept(self) -> None:
        s1 = SourceResults("A", True, [Hit(id="1", title="x", url="u", canonical_id="K1")])
        s2 = SourceResults("B", False, [Hit(id="2", title="y", url="u", canonical_id="K2")])
        assert len(cross_source_rrf([s1, s2])) == 2
