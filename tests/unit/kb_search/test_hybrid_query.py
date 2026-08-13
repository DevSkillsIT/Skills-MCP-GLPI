"""Unit tests: pure SQL builder (modes, filters, injection-safety)."""

from __future__ import annotations

from src.services.kb_search.hybrid_query import (
    SearchFilters,
    build_search_sql,
    effective_mode,
)


class TestEffectiveMode:
    def test_hybrid_without_vec_degrades(self) -> None:
        assert effective_mode("hybrid", has_vec=False) == "keyword"

    def test_semantic_without_vec_degrades(self) -> None:
        assert effective_mode("semantic", has_vec=False) == "keyword"

    def test_keyword_stays(self) -> None:
        assert effective_mode("keyword", has_vec=True) == "keyword"

    def test_hybrid_with_vec(self) -> None:
        assert effective_mode("hybrid", has_vec=True) == "hybrid"


def _build(**over: object):
    kw: dict = dict(
        mode="keyword", query="q", vec_literal=None, limit=5, filters=SearchFilters()
    )
    kw.update(over)
    return build_search_sql("kb_search", **kw)  # type: ignore[arg-type]


class TestBuildSearchSql:
    def test_keyword_binds_query_no_vec(self) -> None:
        sql, p = _build()
        assert "plainto_tsquery" in sql and "active" in sql
        assert p["q"] == "q" and p["lim"] == 5 and "vec" not in p

    def test_hybrid_has_both_ctes(self) -> None:
        sql, p = _build(mode="hybrid", vec_literal="[0.1,0.2]")
        assert "WITH semantic" in sql and "keyword AS" in sql and "rrf_score" in sql
        assert p["vec"] == "[0.1,0.2]" and p["k"] == 60

    def test_hybrid_without_vec_falls_to_keyword(self) -> None:
        sql, p = _build(mode="hybrid", vec_literal=None)
        assert "WITH semantic" not in sql and "vec" not in p

    def test_tenant_filter_bound_not_interpolated(self) -> None:
        sql, p = _build(filters=SearchFilters(tenant="ACME"))
        assert "tenant = %(tenant)s" in sql and p["tenant"] == "ACME"
        assert "ACME" not in sql  # value bound, never interpolated

    def test_lang_filter_bound(self) -> None:
        sql, p = _build(filters=SearchFilters(lang="pt-BR"))
        assert "lang = %(lang)s" in sql and p["lang"] == "pt-BR"

    def test_private_excluded_by_default(self) -> None:
        sql, _ = _build()
        assert "visibility <> 'private'" in sql

    def test_private_included_when_flagged(self) -> None:
        sql, _ = _build(filters=SearchFilters(include_private=True))
        assert "visibility <> 'private'" not in sql

    def test_relation_interpolated(self) -> None:
        sql, _ = build_search_sql(
            "kb_search_help", mode="hybrid", query="q", vec_literal="[0.1]",
            limit=5, filters=SearchFilters(),
        )
        assert "FROM kb_search_help" in sql
