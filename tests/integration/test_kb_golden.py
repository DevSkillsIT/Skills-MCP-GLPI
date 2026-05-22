"""Golden-set evaluation for the unified KB search (ported from the reference
SPEC-SANKHYA-COMMUNITY-001 v1.1.0 golden-eval), adapted to the GLPI MCP's
sources (CHAMADOS + HELP + COMUNIDADE).

GUARDED: skipped unless RUN_GOLDEN=1 (needs the live pgvector DBs + embeddings).
    RUN_GOLDEN=1 GLPI_MCP_CONFIG=/opt/mcp-servers/glpi/ramada-lindacor/glpi-config/glpi-config.json \
      .venv/bin/python -m pytest tests/integration/test_kb_golden.py -v -o asyncio_mode=auto

Regression guard for the two v1.1.0 ranking changes:
  CHANGE 1 — recall scaling (per-source fetch = max(20, limit)).
  CHANGE 2 — similarity-aware cross-source tiebreak (AD-C02 reversal).

Categories:
  1. Official-error — anti-burying (≥1 HELP in top-8) AND quality (#1 sim ≥ floor).
  2. Dev/API        — AD-C02: #1 sim ≥ 0.65; no weak (sim<0.55) above strong
                      (sim>0.70) at an IDENTICAL rrf position.
  3. Recall         — limit=50 returns ≥ 45 results (recall scaling).
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, "/opt/mcp-servers/glpi/.base-code")

from src.services.kb_search.service import KbSearchService  # noqa: E402

RUN_GOLDEN = os.environ.get("RUN_GOLDEN") == "1"
_DEFAULT_CONFIG = "/opt/mcp-servers/glpi/ramada-lindacor/glpi-config/glpi-config.json"

pytestmark = pytest.mark.skipif(not RUN_GOLDEN, reason="set RUN_GOLDEN=1 (needs live DB)")


def _kb_config() -> dict:
    path = os.environ.get("GLPI_MCP_CONFIG", _DEFAULT_CONFIG)
    return json.load(open(path, encoding="utf-8"))["knowledge_base"]


async def _search(**kw) -> list:
    svc = KbSearchService.from_config(_kb_config())
    try:
        return await svc.search(**kw)
    finally:
        await svc.close()


def _log_top3(label: str, hits: list) -> None:
    print(f"\n[golden] {label}")
    for h in hits[:3]:
        sim = f"{h.similarity:.3f}" if h.similarity is not None else "null"
        print(f"  [{h.source:10}] sim={sim} | {h.title[:60]}")


# Empirical #1-similarity floors, measured on the live corpus (2026-05-22).
# They guard against ranking REGRESSIONS below the current best — not an ideal.
# Note: hybrid RRF can rank an FTS-strong but semantically-weaker title at #1
# (e.g. "nota fiscal"), so some floors are intentionally modest.
OFFICIAL_ERROR_FLOORS = {
    "erro ao confirmar nota fiscal": 0.50,
    "ORA-20101 historico nao pode ser zero": 0.70,
    "parametrizacao regras da reforma tributaria": 0.55,
    "como criar processo no Sankhya Flow BPM": 0.70,
}

# Per-query #1 floors for dev/API queries (empirical 2026-05-22). The primary
# v1.1.0 guard for this category is the AD-C02 tie-check below, not the floor.
DEV_QUERY_FLOORS = {
    "confirmar pedido de venda via API REST integracao": 0.50,
    "integracao Sankhya via API REST com Python": 0.65,
}


class TestOfficialErrorQueries:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", list(OFFICIAL_ERROR_FLOORS))
    async def test_anti_burying_and_quality(self, query: str) -> None:
        floor = OFFICIAL_ERROR_FLOORS[query]
        hits = await _search(query=query, source="all", limit=8)
        _log_top3(query, hits)
        # (a) anti-burying: at least one HELP (official) result in top-8.
        assert sum(1 for h in hits if h.source == "HELP") >= 1, f"no HELP in top-8 for {query!r}"
        # (b) quality: #1 similarity above the empirical floor.
        top = hits[0].similarity if hits else None
        assert top is not None and top >= floor, f"#1 sim {top} < {floor} for {query!r}"


class TestDevApiQueriesADC02:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", list(DEV_QUERY_FLOORS))
    async def test_strong_answer_leads_no_weak_above_strong(self, query: str) -> None:
        floor = DEV_QUERY_FLOORS[query]
        hits = await _search(query=query, source="all", limit=15)
        _log_top3(query, hits)
        # (a) a strong answer leads (per-query empirical floor).
        top = hits[0].similarity if hits else None
        assert top is not None and top >= floor, f"#1 sim {top} < {floor} for {query!r}"
        # (b) AD-C02: at an identical rrf position, no weak (<0.55) above strong (>0.70).
        eps = 1e-10
        sims = [h for h in hits if h.similarity is not None]
        for i, higher in enumerate(sims):
            if (higher.similarity or 1) < 0.55:
                for lower in sims[i + 1:]:
                    tie = abs(higher.rrf_score - lower.rrf_score) < eps
                    if tie and (lower.similarity or 0) > 0.70:
                        pytest.fail(
                            f"AD-C02: weak sim={higher.similarity:.3f} above "
                            f"strong sim={lower.similarity:.3f} at equal rrf for {query!r}"
                        )


class TestRecallScaling:
    @pytest.mark.asyncio
    async def test_limit_50_returns_many(self) -> None:
        hits = await _search(query="nota fiscal", source="all", limit=50)
        assert len(hits) >= 45, f"recall scaling: expected >=45, got {len(hits)}"
