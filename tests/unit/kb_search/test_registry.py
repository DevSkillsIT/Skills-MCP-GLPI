"""Unit tests: Pydantic source registry validation + enabled toggle (pure)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.services.kb_search.registry import SourceConfig, load_registry


def _src(**over: object) -> SourceConfig:
    base: dict[str, object] = dict(
        name="x", label="X", dsn="d", relation="kb_search"
    )
    base.update(over)
    return SourceConfig(**base)  # type: ignore[arg-type]


class TestSourceConfigValidation:
    def test_valid(self) -> None:
        _src()
        _src(relation="public.kb_search_help")

    def test_unsafe_relation_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _src(relation="kb_search; DROP TABLE x")
        with pytest.raises(ValidationError):
            _src(relation="kb search")

    def test_nonpositive_weight_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _src(weight=0.0)
        with pytest.raises(ValidationError):
            _src(weight=-1.0)

    def test_defaults(self) -> None:
        s = _src()
        assert s.enabled is True and s.weight == 1.0 and s.dedup is False and s.is_official is False


class TestLoadRegistry:
    def _cfg(self) -> dict:
        return {
            "embedding": {"provider": "none"},
            "sources": [
                {"name": "a", "label": "A", "dsn": "d", "relation": "kb_search", "enabled": True},
                {"name": "b", "label": "B", "dsn": "d", "relation": "kb_search", "enabled": False},
                {"name": "c", "label": "C", "dsn": "d", "relation": "kb_search"},  # default on
            ],
        }

    def test_skips_disabled(self) -> None:
        reg = load_registry(self._cfg())
        assert [s.name for s in reg.sources] == ["a", "c"]

    def test_empty_config(self) -> None:
        reg = load_registry({})
        assert reg.sources == [] and reg.embedding.provider == "vllm"

    def test_invalid_source_fails_fast(self) -> None:
        with pytest.raises(ValidationError):
            load_registry({"sources": [{"name": "x", "label": "X", "dsn": "d", "relation": "x; DROP"}]})

    def test_embedding_parsed(self) -> None:
        reg = load_registry({"embedding": {"provider": "openai", "dimensions": 2560}, "sources": []})
        assert reg.embedding.provider == "openai" and reg.embedding.dimensions == 2560
