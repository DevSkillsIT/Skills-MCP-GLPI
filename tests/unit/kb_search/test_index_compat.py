"""Unit tests: per-source embedding-model compatibility guardrail (pure)."""

from __future__ import annotations

from src.services.kb_search.index_compat import check_index_compatibility, models_match


class TestModelsMatch:
    def test_exact(self) -> None:
        assert models_match("/model", "/model", "vllm") is True

    def test_substring(self) -> None:
        assert models_match("qwen3-embedding-4b", "qwen3", "vllm") is True

    def test_cross_family_rejected(self) -> None:
        assert models_match("/model", "text-embedding-3-large", "openai") is False
        assert models_match("text-embedding-3-large", "/model", "vllm") is False

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
        assert r.reason is not None and "keyword" in r.reason

    def test_none_provider_compatible(self) -> None:
        assert check_index_compatibility(["/model"], "none", "x").compatible is True

    def test_ignores_null_models(self) -> None:
        assert check_index_compatibility([None, "/model"], "vllm", "/model").compatible is True
