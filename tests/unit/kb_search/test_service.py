"""Unit tests: service degradation (a broken source must not crash search)."""

from __future__ import annotations

import pytest

from src.services.kb_search import service as svc_mod
from src.services.kb_search.rrf import Hit


@pytest.mark.asyncio
async def test_broken_source_dropped_others_survive(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {
        "embedding": {"provider": "none"},
        "sources": [
            {"name": "ok", "label": "OK", "dsn": "d", "relation": "ok"},
            {"name": "broken", "label": "BROKEN", "dsn": "d", "relation": "broken"},
        ],
    }
    svc = svc_mod.KbSearchService.from_config(cfg)
    svc._ready = {"ok": True, "broken": True}  # bypass live health/compat probe

    async def fake_get(dsn: str) -> object:
        return object()

    async def fake_hybrid(pool, relation, **kw):  # noqa: ANN001, ANN003
        if relation == "broken":
            raise RuntimeError("db down mid-session")
        return [Hit(id="1", title="ok result", url="u", similarity=0.5)]

    monkeypatch.setattr(svc._pools, "get", fake_get)
    monkeypatch.setattr(svc_mod, "hybrid_search", fake_hybrid)

    hits = await svc.search(query="x", source="all", limit=5)
    assert len(hits) == 1
    assert hits[0].source == "OK"  # broken source dropped, search did not crash


@pytest.mark.asyncio
async def test_no_usable_sources_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {"embedding": {"provider": "none"},
           "sources": [{"name": "a", "label": "A", "dsn": "d", "relation": "kb_search"}]}
    svc = svc_mod.KbSearchService.from_config(cfg)
    svc._ready = {}  # nothing healthy
    assert await svc.search(query="x", source="all", limit=5) == []
