"""Unit tests for the pure kb_search modules (rrf, index_compat, registry, fmt)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.services.kb_search.index_compat import check_index_compatibility, models_match
from src.services.kb_search.registry import SourceConfig
from src.services.kb_search.rrf import (
    Hit,
    SourceResults,
    UnifiedHit,
    cross_source_rrf,
    dedup_by_title,
)
from src.services.kb_search.service import _display_title, format_markdown


class TestDedupByTitle:
    def test_collapses_accent_and_case_variants(self) -> None:
        hits = [
            Hit(id="1", title="Serviço de Configuração", url="u1"),
            Hit(id="2", title="servico de configuracao", url="u2"),
            Hit(id="3", title="Outro assunto", url="u3"),
        ]
        assert [h.id for h in dedup_by_title(hits)] == ["1", "3"]


class TestCrossSourceRRF:
    def test_official_wins_equal_rank_and_weight(self) -> None:
        help_src = SourceResults("HELP", True, [Hit(id="h1", title="A", url="u")], weight=1.0)
        comm_src = SourceResults("COMUNIDADE", False, [Hit(id="c1", title="B", url="u")], weight=1.0)
        fused = cross_source_rrf([help_src, comm_src])
        assert fused[0].id == "h1"

    def test_weight_boosts_source(self) -> None:
        # Both rank 1, but weighted source must come first.
        light = SourceResults("A", False, [Hit(id="a1", title="A", url="u")], weight=0.5)
        heavy = SourceResults("B", False, [Hit(id="b1", title="B", url="u")], weight=2.0)
        fused = cross_source_rrf([light, heavy])
        assert fused[0].id == "b1"
        assert fused[0].rrf_score > fused[1].rrf_score

    def test_rank_one_beats_rank_two(self) -> None:
        src = SourceResults("S", True, [Hit(id="1", title="A", url="u"), Hit(id="2", title="B", url="u")])
        fused = cross_source_rrf([src])
        assert [h.id for h in fused] == ["1", "2"]
        assert fused[0].rrf_score == 1.0 / 61


class TestCanonicalDedup:
    def test_collapses_cross_source_by_canonical_id(self) -> None:
        s1 = SourceResults("HELP", True, [Hit(id="h1", title="A", url="u", canonical_id="DOC-9")])
        s2 = SourceResults("COMUNIDADE", False, [Hit(id="c1", title="A2", url="u", canonical_id="DOC-9")])
        fused = cross_source_rrf([s1, s2])
        assert len(fused) == 1  # same canonical_id collapses to the best-ranked
        assert fused[0].id == "h1"

    def test_null_canonical_not_collapsed(self) -> None:
        s1 = SourceResults("A", False, [Hit(id="1", title="x", url="u", canonical_id=None)])
        s2 = SourceResults("B", False, [Hit(id="2", title="y", url="u", canonical_id=None)])
        assert len(cross_source_rrf([s1, s2])) == 2


class TestModelsMatch:
    def test_exact(self) -> None:
        assert models_match("/model", "/model", "vllm") is True

    def test_cross_family_rejected(self) -> None:
        assert models_match("/model", "text-embedding-3-large", "openai") is False

    def test_none_provider_always_true(self) -> None:
        assert models_match("anything", "other", "none") is True


class TestCheckIndexCompatibility:
    def test_empty_source_compatible(self) -> None:
        assert check_index_compatibility([], "vllm", "/model").compatible is True

    def test_mismatch_incompatible(self) -> None:
        r = check_index_compatibility(["text-embedding-3-large"], "vllm", "/model")
        assert r.compatible is False and r.reason is not None


class TestRegistryValidate:
    def _src(self, **over: object) -> SourceConfig:
        base: dict[str, object] = dict(
            name="x", label="X", is_official=False, dsn="d", relation="kb_search"
        )
        base.update(over)
        return SourceConfig(**base)  # type: ignore[arg-type]

    def test_valid_relation(self) -> None:
        self._src()  # constructs without error
        self._src(relation="public.kb_search_help")

    def test_unsafe_relation_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._src(relation="kb_search; DROP TABLE x")

    def test_nonpositive_weight_rejected(self) -> None:
        with pytest.raises(ValidationError):
            self._src(weight=0.0)


class TestFormatAndDisplayTitle:
    def test_empty(self) -> None:
        assert "Nenhum" in format_markdown([])

    def test_weak_title_uses_body_snippet(self) -> None:
        h = UnifiedHit(
            source="CHAMADOS", is_official=False, id="1", title="Sankhya",
            context="Sistemas", url="u", source_rank=1, rrf_score=0.5,
            similarity=0.7, body="nota fiscal nao emite por erro de imposto",
        )
        assert "nota fiscal" in _display_title(h)

    def test_strong_title_kept(self) -> None:
        h = UnifiedHit(
            source="HELP", is_official=True, id="1",
            title="Como configurar o boleto no financeiro", context=None, url="u",
            source_rank=1, rrf_score=0.5, similarity=0.8, body="x",
        )
        assert _display_title(h) == "Como configurar o boleto no financeiro"

    def test_table_renders(self) -> None:
        h = UnifiedHit(
            source="HELP", is_official=True, id="42", title="Titulo grande aqui ok",
            context="Ctx", url="http://x", source_rank=1, rrf_score=0.5, similarity=0.812,
        )
        md = format_markdown([h])
        assert "| HELP |" in md and "Sim" in md and "0.812" in md and "http://x" in md
