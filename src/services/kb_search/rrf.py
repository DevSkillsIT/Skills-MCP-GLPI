"""Pure RRF (Reciprocal Rank Fusion) helpers for cross-source search.

Faithful port of the reference ``search/rrf.ts``. No DB, no I/O — fully
unit-testable. Two operations:
  1. dedup_by_title   — collapse near-duplicate hits by normalized title.
  2. cross_source_rrf — fuse N already-ranked source lists by array position.

Why position, not score: intra-source scores (hybrid RRF, cosine, ts_rank_cd)
are incomparable across corpora. The only comparable unit is 1-indexed array
position within each source list (sourceRank), which feeds the RRF formula.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# RRF constant — matches the intra-source k used by the hybrid query layer.
DEFAULT_K = 60


@dataclass(slots=True)
class Hit:
    """One intra-source result (already ordered best-first by the DB layer)."""

    id: str
    title: str
    url: str
    context: str | None = None
    similarity: float | None = None
    extra: dict = field(default_factory=dict)


@dataclass(slots=True)
class SourceResults:
    """A source's ordered hits plus its display metadata."""

    name: str  # e.g. "chamados", "help", "comunidade"
    is_official: bool
    hits: list[Hit]


@dataclass(slots=True)
class UnifiedHit:
    source: str
    is_official: bool
    id: str
    title: str
    context: str | None
    url: str
    source_rank: int
    rrf_score: float
    similarity: float | None


def _normalize_title(title: str) -> str:
    """NFD-decompose, strip combining diacritics, lowercase, collapse
    non-alphanumeric runs to a single space, trim (mirrors reference C6)."""
    nfd = unicodedata.normalize("NFD", title)
    no_marks = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", no_marks.lower()).strip()


def dedup_by_title(hits: list[Hit]) -> list[Hit]:
    """Keep only the first occurrence of each normalized title (best rank).
    Apply only to sources prone to reposts (e.g. community); NOT to tickets,
    whose titles are boilerplate and would wrongly collapse distinct records."""
    seen: set[str] = set()
    out: list[Hit] = []
    for hit in hits:
        key = _normalize_title(hit.title)
        if key not in seen:
            seen.add(key)
            out.append(hit)
    return out


def cross_source_rrf(sources: list[SourceResults], k: int = DEFAULT_K) -> list[UnifiedHit]:
    """Fuse N ranked source lists via cross-source RRF.

    sourceRank = 1-indexed array position within each source (NOT raw score).
    rrf_score  = 1 / (k + sourceRank).
    Tiebreak (deterministic): higher rrf_score first; then official sources
    before non-official; then id ascending.
    """
    unified: list[UnifiedHit] = []
    for src in sources:
        for i, hit in enumerate(src.hits):
            rank = i + 1
            unified.append(
                UnifiedHit(
                    source=src.name,
                    is_official=src.is_official,
                    id=str(hit.id),
                    title=hit.title,
                    context=hit.context,
                    url=hit.url,
                    source_rank=rank,
                    rrf_score=1.0 / (k + rank),
                    similarity=hit.similarity,
                )
            )

    unified.sort(key=lambda u: (-u.rrf_score, 0 if u.is_official else 1, u.id))
    return unified
