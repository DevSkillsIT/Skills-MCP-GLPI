"""Pure RRF (Reciprocal Rank Fusion) helpers for cross-source search.

Faithful port of the reference ``search/rrf.ts``, extended for the enterprise
kb_search contract: per-source weighting and cross-source dedup by
``canonical_id``. No DB, no I/O — fully unit-testable.

Why position, not score: intra-source scores are incomparable across corpora.
The comparable unit is 1-indexed array position within each source list
(sourceRank), which feeds the RRF formula, scaled by the source weight.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

DEFAULT_K = 60


@dataclass(slots=True)
class Hit:
    """One intra-source result (already ordered best-first by the DB layer)."""

    id: str
    title: str
    url: str
    context: str | None = None
    similarity: float | None = None
    canonical_id: str | None = None
    body: str = ""
    extra: dict = field(default_factory=dict)


@dataclass(slots=True)
class SourceResults:
    """A source's ordered hits plus display metadata and RRF weight."""

    name: str
    is_official: bool
    hits: list[Hit]
    weight: float = 1.0


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
    canonical_id: str | None = None
    body: str = ""


def _normalize_title(title: str) -> str:
    """NFD-decompose, strip diacritics, lowercase, collapse non-alphanumeric
    runs to a space, trim (mirrors reference C6)."""
    nfd = unicodedata.normalize("NFD", title)
    no_marks = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", no_marks.lower()).strip()


def dedup_by_title(hits: list[Hit]) -> list[Hit]:
    """Keep only the first occurrence of each normalized title (best rank).
    Apply only to repost-prone sources (e.g. community); NOT to tickets."""
    seen: set[str] = set()
    out: list[Hit] = []
    for hit in hits:
        key = _normalize_title(hit.title)
        if key not in seen:
            seen.add(key)
            out.append(hit)
    return out


def cross_source_rrf(sources: list[SourceResults], k: int = DEFAULT_K) -> list[UnifiedHit]:
    """Fuse N ranked source lists via weighted cross-source RRF, then collapse
    cross-source duplicates that share a non-null ``canonical_id``.

    sourceRank = 1-indexed array position within each source.
    rrf_score  = weight / (k + sourceRank).
    Tiebreak (v1.1.0 AD-C02 reversal, in order):
      1. rrf_score DESC      — RRF position is the backbone.
      2. similarity DESC     — at the same rrf position, the more semantically
                               similar result wins regardless of source (null
                               similarity = lowest, so degraded/keyword mode keeps
                               the v1.0 official-first behaviour via step 3).
      3. official first      — only when similarities tie or are both null.
      4. id ascending        — determinism within a source.
    Then cross-source duplicates sharing a non-null canonical_id collapse.
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
                    rrf_score=src.weight / (k + rank),
                    similarity=hit.similarity,
                    canonical_id=hit.canonical_id,
                    body=hit.body,
                )
            )

    unified.sort(
        key=lambda u: (
            -u.rrf_score,
            -(u.similarity if u.similarity is not None else float("-inf")),
            0 if u.is_official else 1,
            u.id,
        )
    )
    return _dedup_canonical(unified)


def _dedup_canonical(hits: list[UnifiedHit]) -> list[UnifiedHit]:
    """Drop later hits sharing a non-null canonical_id (input must be sorted by
    rank desc, so the first kept is the best-ranked representative)."""
    seen: set[str] = set()
    out: list[UnifiedHit] = []
    for h in hits:
        if h.canonical_id:
            if h.canonical_id in seen:
                continue
            seen.add(h.canonical_id)
        out.append(h)
    return out
