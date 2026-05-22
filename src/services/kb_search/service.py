"""Unified knowledge-base search orchestrator (enterprise contract).

Embed the query ONCE; per-source index-compat + health (an incompatible or
broken source degrades to keyword / drops out, others stay hybrid); run each
source's fixed contract query; fuse with weighted cross-source RRF + canonical
dedup; render Markdown. Supports tenant / lang / visibility filtering.
"""

from __future__ import annotations

import asyncio
import logging

from .embedding import EmbeddingError, QueryEmbedder
from .hybrid_query import SearchFilters, distinct_embedding_models, hybrid_search
from .index_compat import check_index_compatibility
from .registry import PoolManager, Registry, SourceConfig, load_registry
from .rrf import Hit, SourceResults, UnifiedHit, cross_source_rrf, dedup_by_title

log = logging.getLogger(__name__)

_FETCH_PER_SOURCE = 20
_TITLE_MAX = 90
_CONTEXT_MAX = 70
_WEAK_TITLE_LEN = 14  # below this, fall back to a body snippet for display


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
        # source name -> usable for hybrid (compatible + healthy). Lazy.
        self._ready: dict[str, bool] | None = None

    @classmethod
    def from_config(cls, kb_config: dict) -> KbSearchService:
        """Build from the central Settings knowledge_base section (validated)."""
        return cls(load_registry(kb_config))

    async def _ensure_ready(self) -> dict[str, bool]:
        """Per source: True if it can serve hybrid (healthy + index-compatible);
        False means keyword-only; missing means it dropped out (unhealthy)."""
        if self._ready is not None:
            return self._ready
        ready: dict[str, bool] = {}
        provider = self._reg.embedding.provider
        model = self._reg.embedding.model
        for src in self._reg.sources:
            err = await self._pools.health_check(src)
            if err is not None:
                log.error("kb_search source '%s' unhealthy, skipping: %s", src.name, err)
                continue  # drop out entirely
            if provider == "none":
                ready[src.name] = False
                continue
            try:
                pool = await self._pools.get(src.dsn)
                models = await distinct_embedding_models(pool, src.relation)
                ready[src.name] = check_index_compatibility(models, provider, model).compatible
            except Exception as exc:  # noqa: BLE001 - probe failed -> keyword
                log.warning("kb_search compat probe failed for '%s': %s", src.name, exc)
                ready[src.name] = False
        self._ready = ready
        return ready

    def _select(self, source: str) -> list[SourceConfig]:
        if source == "all":
            return list(self._reg.sources)
        return [s for s in self._reg.sources if s.name == source]

    async def search(
        self,
        *,
        query: str,
        source: str = "all",
        limit: int = 15,
        tenant: str | None = None,
        lang: str | None = None,
        include_private: bool = False,
    ) -> list[UnifiedHit]:
        selected = self._select(source)
        if not selected:
            return []

        qvec: list[float] | None = None
        if self._reg.embedding.provider != "none":
            try:
                qvec = await self._embedder.embed(query)
            except EmbeddingError:
                qvec = None

        ready = await self._ensure_ready()
        usable = [s for s in selected if s.name in ready]  # drop unhealthy
        if not usable:
            return []
        filters = SearchFilters(tenant=tenant, lang=lang, include_private=include_private)
        per_source = limit if len(usable) == 1 else _FETCH_PER_SOURCE

        async def run(src: SourceConfig) -> SourceResults:
            mode = "hybrid" if (qvec is not None and ready.get(src.name)) else "keyword"
            try:
                pool = await self._pools.get(src.dsn)
                hits: list[Hit] = await hybrid_search(
                    pool, src.relation, query=query, qvec=qvec, limit=per_source,
                    mode=mode, filters=filters,
                )
            except Exception as exc:  # noqa: BLE001 - one source must not crash the whole search
                # Mid-session failure (DB down, view dropped). Degrade THIS source
                # to keyword; if that also fails, drop it and keep the others.
                log.warning("kb_search source '%s' failed (%s); degrading to keyword", src.name, exc)
                try:
                    pool = await self._pools.get(src.dsn)
                    hits = await hybrid_search(
                        pool, src.relation, query=query, qvec=None, limit=per_source,
                        mode="keyword", filters=filters,
                    )
                except Exception as exc2:  # noqa: BLE001 - drop this source from the fusion
                    log.error("kb_search source '%s' unavailable: %s", src.name, exc2)
                    hits = []
            if src.dedup:
                hits = dedup_by_title(hits)
            return SourceResults(name=src.label, is_official=src.is_official, hits=hits, weight=src.weight)

        results = await asyncio.gather(*(run(s) for s in usable))
        return cross_source_rrf(list(results))[:limit]

    async def close(self) -> None:
        await self._pools.close_all()


def _display_title(hit: UnifiedHit) -> str:
    """Weak/boilerplate titles (common on form-opened tickets) are replaced by a
    body snippet so the result row is legible without opening the item."""
    title = (hit.title or "").strip()
    if len(title) < _WEAK_TITLE_LEN and hit.body:
        snippet = hit.body.strip().split("\n", 1)[0]
        if snippet:
            return f"{title} — {snippet}" if title else snippet
    return title


def format_markdown(hits: list[UnifiedHit]) -> str:
    if not hits:
        return "Nenhum resultado encontrado."
    headers = ["Fonte", "Oficial", "ID", "Titulo", "Contexto", "Score", "URL"]
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for h in hits:
        oficial = "Sim" if h.is_official else "Nao"
        titulo = _escape(_truncate(_display_title(h), _TITLE_MAX))
        contexto = _escape(_truncate(h.context, _CONTEXT_MAX)) if h.context else "—"
        score = f"{h.similarity:.3f}" if h.similarity is not None else "—"
        lines.append(
            f"| {h.source} | {oficial} | {_escape(h.id)} | {titulo} | {contexto} | {score} | {_escape(h.url)} |"
        )
    return "\n".join(lines)
