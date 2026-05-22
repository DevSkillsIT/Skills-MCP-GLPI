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
    assert "message" in result
    assert "indispon" in result["message"].lower()  # "indisponivel ... config"


@pytest.mark.asyncio
async def test_empty_sources_treated_as_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    h._service = None
    h._init_error = None
    monkeypatch.setattr(h, "_kb_config", lambda: {"embedding": {"provider": "none"}, "sources": []})

    result = await h.search_knowledge_unified(query="x")
    assert "indispon" in result["message"].lower()
