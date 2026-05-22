"""Unit tests for the pure kb_search modules (rrf + index_compat)."""

from __future__ import annotations

import pytest

from src.services.kb_search.index_compat import check_index_compatibility, models_match
from src.services.kb_search.registry import RegistryError, SourceConfig
from src.services.kb_search.rrf import (
    Hit,
    SourceResults,
    UnifiedHit,
    cross_source_rrf,
    dedup_by_title,
)
from src.services.kb_search.service import format_markdown


class TestDedupByTitle:
    def test_collapses_accent_and_case_variants(self) -> None:
        hits = [
            Hit(id="1", title="Serviço de Configuração", url="u1"),
            Hit(id="2", title="servico de configuracao", url="u2"),
            Hit(id="3", title="Outro assunto", url="u3"),
        ]
        out = dedup_by_title(hits)
        assert [h.id for h in out] == ["1", "3"]  # first kept, dup dropped

    def test_preserves_order(self) -> None:
        hits = [Hit(id="a", title="X", url="u"), Hit(id="b", title="Y", url="u")]
        assert [h.id for h in dedup_by_title(hits)] == ["a", "b"]


class TestCrossSourceRRF:
    def test_rank_one_beats_rank_two_across_sources(self) -> None:
        help_src = SourceResults("help", True, [Hit(id="h1", title="A", url="u", similarity=0.9)])
        comm_src = SourceResults("comunidade", False, [Hit(id="c1", title="B", url="u", similarity=0.5)])
        fused = cross_source_rrf([help_src, comm_src])
        # both are rank 1 -> equal rrf; official (help) wins the tiebreak.
        assert fused[0].id == "h1"
        assert fused[0].rrf_score == fused[1].rrf_score

    def test_higher_rank_higher_score(self) -> None:
        src = SourceResults("s", True, [Hit(id="1", title="A", url="u"), Hit(id="2", title="B", url="u")])
        fused = cross_source_rrf([src])
        assert fused[0].id == "1"  # rank 1 > rank 2
        assert fused[0].rrf_score > fused[1].rrf_score
        assert fused[0].rrf_score == 1.0 / (60 + 1)

    def test_source_rank_is_position_not_score(self) -> None:
        # A low-similarity hit ranked first in its source still gets rank-1 rrf.
        src = SourceResults("s", False, [Hit(id="1", title="A", url="u", similarity=0.1)])
        fused = cross_source_rrf([src])
        assert fused[0].source_rank == 1
        assert fused[0].rrf_score == 1.0 / 61


class TestModelsMatch:
    def test_exact(self) -> None:
        assert models_match("/model", "/model", "vllm") is True

    def test_substring(self) -> None:
        assert models_match("qwen3-embedding-4b", "qwen3", "vllm") is True

    def test_cross_family_rejected(self) -> None:
        assert models_match("/model", "text-embedding-3-large", "openai") is False

    def test_none_provider_always_true(self) -> None:
        assert models_match("anything", "other", "none") is True


class TestCheckIndexCompatibility:
    def test_empty_source_compatible(self) -> None:
        assert check_index_compatibility([], "vllm", "/model").compatible is True

    def test_matching_compatible(self) -> None:
        assert check_index_compatibility(["/model"], "vllm", "/model").compatible is True

    def test_mismatch_incompatible_with_reason(self) -> None:
        r = check_index_compatibility(["text-embedding-3-large"], "vllm", "/model")
        assert r.compatible is False
        assert r.reason is not None and "degrades to keyword" in r.reason

    def test_none_provider_compatible(self) -> None:
        assert check_index_compatibility(["/model"], "none", "x").compatible is True


class TestFormatMarkdown:
    def test_empty(self) -> None:
        assert "Nenhum" in format_markdown([])

    def test_table_renders_hit(self) -> None:
        h = UnifiedHit(
            source="HELP", is_official=True, id="1", title="Titulo X",
            context="Categoria Y", url="http://x", source_rank=1,
            rrf_score=0.5, similarity=0.812,
        )
        md = format_markdown([h])
        assert "| HELP |" in md and "Sim" in md and "0.812" in md and "http://x" in md

    def test_keyword_score_is_dash(self) -> None:
        h = UnifiedHit(
            source="CHAMADOS", is_official=False, id="2", title="T", context=None,
            url="u", source_rank=1, rrf_score=0.5, similarity=None,
        )
        md = format_markdown([h])
        assert "Nao" in md and "—" in md


def _src(**over: object) -> SourceConfig:
    base: dict[str, object] = dict(
        name="x", label="X", is_official=False, dsn="d", table="tickets",
        id_expr="t.id", title_expr="t.titulo",
        url_expr="'/front/ticket.form.php?id=' || t.id::text", context_expr="t.categoria",
    )
    base.update(over)
    return SourceConfig(**base)  # type: ignore[arg-type]


class TestRegistryValidate:
    def test_safe_expr_ok(self) -> None:
        _src()._validate()  # must not raise

    def test_semicolon_rejected(self) -> None:
        with pytest.raises(RegistryError):
            _src(id_expr="t.id; DROP TABLE x")._validate()

    def test_subquery_context_allowed(self) -> None:
        _src(context_expr="(SELECT s.name FROM community_spaces s WHERE s.id = t.space_id)")._validate()
