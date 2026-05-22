"""Unified knowledge-base search orchestrator.

Faithful port of the reference ``search-unified.ts`` runUnifiedSearch, made
multi-source and multi-DB: embed the query ONCE, per-source index-compat
(incompatible source degrades to keyword only for itself), run each source's
hybrid search, fuse with cross-source RRF, render Markdown.
"""

from __future__ import annotations

import asyncio

from .embedding import EmbeddingError, QueryEmbedder
from .hybrid_query import distinct_embedding_models, hybrid_search
from .index_compat import check_index_compatibility
from .registry import PoolManager, Registry, SourceConfig, load_registry
from .rrf import Hit, SourceResults, UnifiedHit, cross_source_rrf, dedup_by_title

# Candidates fetched per source before cross-source fusion when source='all'.
_FETCH_PER_SOURCE = 20

_TITLE_MAX = 90
_CONTEXT_MAX = 70


def _truncate(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


class KbSearchService:
    def __init__(self, registry: Registry) -> None:
        self._reg = registry
        self._pools = PoolManager()
        self._embedder = QueryEmbedder(
            provider=registry.embedding.provider,
            base_url=registry.embedding.base_url,
            api_key=registry.embedding.api_key,
            model=registry.embedding.model,
            dimensions=registry.embedding.dimensions,
            timeout=registry.embedding.timeout,
        )
        # source name -> compatible (lazy, computed once).
        self._compat: dict[str, bool] | None = None

    @classmethod
    def from_env(cls) -> KbSearchService:
        return cls(load_registry())

    async def _ensure_compat(self) -> dict[str, bool]:
        if self._compat is not None:
            return self._compat
        compat: dict[str, bool] = {}
        provider = self._reg.embedding.provider
        model = self._reg.embedding.model
        for src in self._reg.sources:
            if provider == "none":
                compat[src.name] = False
                continue
            try:
                pool = await self._pools.get(src.dsn)
                models = await distinct_embedding_models(pool, src)
                compat[src.name] = check_index_compatibility(models, provider, model).compatible
            except Exception:  # noqa: BLE001 - any probe failure -> degrade to keyword
                compat[src.name] = False
        self._compat = compat
        return compat

    def _select(self, source: str) -> list[SourceConfig]:
        if source == "all":
            return list(self._reg.sources)
        return [s for s in self._reg.sources if s.name == source]

    async def search(self, *, query: str, source: str = "all", limit: int = 15) -> list[UnifiedHit]:
        selected = self._select(source)
        if not selected:
            return []

        # Embed once. provider=none or failure -> keyword for all sources.
        qvec: list[float] | None = None
        if self._reg.embedding.provider != "none":
            try:
                qvec = await self._embedder.embed(query)
            except EmbeddingError:
                qvec = None

        compat = await self._ensure_compat()
        per_source = limit if len(selected) == 1 else _FETCH_PER_SOURCE

        async def run(src: SourceConfig) -> SourceResults:
            # Per-source mode: hybrid only if we have a vector AND the source is
            # index-compatible; otherwise keyword (the source still contributes).
            mode = "hybrid" if (qvec is not None and compat.get(src.name)) else "keyword"
            pool = await self._pools.get(src.dsn)
            hits: list[Hit] = await hybrid_search(
                pool, src, query=query, qvec=qvec, limit=per_source, mode=mode
            )
            if src.dedup:
                hits = dedup_by_title(hits)
            return SourceResults(name=src.label, is_official=src.is_official, hits=hits)

        results = await asyncio.gather(*(run(s) for s in selected))
        fused = cross_source_rrf(list(results))
        return fused[:limit]

    async def close(self) -> None:
        await self._pools.close_all()


def format_markdown(hits: list[UnifiedHit]) -> str:
    if not hits:
        return "Nenhum resultado encontrado."
    headers = ["Fonte", "Oficial", "ID", "Titulo", "Contexto", "Score", "URL"]
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for h in hits:
        oficial = "Sim" if h.is_official else "Nao"
        titulo = _escape(_truncate(h.title, _TITLE_MAX))
        contexto = _escape(_truncate(h.context, _CONTEXT_MAX)) if h.context else "—"
        score = f"{h.similarity:.3f}" if h.similarity is not None else "—"
        lines.append(
            f"| {h.source} | {oficial} | {_escape(h.id)} | {titulo} | {contexto} | {score} | {_escape(h.url)} |"
        )
    return "\n".join(lines)
