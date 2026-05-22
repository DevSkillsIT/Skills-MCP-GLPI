"""Unit tests: tool handler graceful behavior when KB is not configured."""

from __future__ import annotations

import pytest

from src.services.kb_search import handler as h


@pytest.mark.asyncio
async def test_missing_config_returns_message(monkeypatch: pytest.MonkeyPatch) -> None:
    # Reset the lazy singleton and force "no config".
    h._service = None
    h._init_error = None
    monkeypatch.setattr(h, "_kb_config", lambda: None)

    result = await h.search_knowledge_unified(query="qualquer coisa")
    assert isinstance(result, str)
    assert "indispon" in result.lower()  # "indisponivel ... config"


@pytest.mark.asyncio
async def test_empty_sources_treated_as_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    h._service = None
    h._init_error = None
    monkeypatch.setattr(h, "_kb_config", lambda: {"embedding": {"provider": "none"}, "sources": []})

    result = await h.search_knowledge_unified(query="x")
    assert "indispon" in result.lower()


@pytest.mark.asyncio
async def test_short_query_rejected_when_service_available(monkeypatch: pytest.MonkeyPatch) -> None:
    # With a working service, a 1-char query must be rejected (schema says min 2).
    monkeypatch.setattr(h, "_service_or_error", lambda: object())
    result = await h.search_knowledge_unified(query="a")
    assert "2 caracteres" in result
