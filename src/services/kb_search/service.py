"""Unified knowledge-base search orchestrator (enterprise contract).

Embed the query ONCE; per-source index-compat + health (an incompatible or
broken source degrades to keyword / drops out, others stay hybrid); run each
source's fixed contract query; fuse with weighted cross-source RRF + canonical
dedup; render Markdown. Supports tenant / lang / visibility filtering.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Container

from .embedding import EmbeddingError, QueryEmbedder
from .hybrid_query import (
    SOLUTION_SNIPPET,
    SearchFilters,
    distinct_embedding_models,
    hybrid_search,
)
from .index_compat import check_index_compatibility
from .registry import PoolManager, Registry, SourceConfig, load_registry
from .rrf import Hit, SourceResults, UnifiedHit, cross_source_rrf, dedup_by_title

log = logging.getLogger(__name__)

_FETCH_PER_SOURCE = 20
# The title cell now carries the distinguishing payload (a problem snippet
# whenever the title repeats), so it needs more room than a bare label did.
_TITLE_MAX = 160
# Sized from the corpus, not guessed: with follow-ups folded in, resolution
# length is p50=156, p75=378, p90=902. 600 returns ~85% of resolutions complete;
# 220 would have truncated a third of them, and the resolution IS the answer.
_SOLUTION_MAX = 600
_CONTEXT_MAX = 70
# An empty cell would read as "not solved". For a ticket KB every item IS solved
# (the ETL only ingests solved/closed), so the honest statement is that the fix
# was never written down — not that there was none.
_NO_SOLUTION = "(resolvido, sem descricao da solucao)"
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
        # Recall scaling (v1.1.0): for source=all, each source contributes at least
        # `limit` candidates (floor 20) so cross-source RRF can fill the requested
        # limit with well-ranked results instead of padding with leftovers.
        per_source = limit if len(usable) == 1 else max(_FETCH_PER_SOURCE, limit)

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
            return SourceResults(
                name=src.label, is_official=src.is_official, hits=hits,
                weight=src.weight, solutions_expected=src.solutions_expected,
            )

        results = await asyncio.gather(*(run(s) for s in usable))
        return cross_source_rrf(list(results))[:limit]

    async def close(self) -> None:
        await self._pools.close_all()


def _display_title(hit: UnifiedHit, repeated: Container[str] = frozenset()) -> str:
    """Weak/boilerplate titles are replaced by a body snippet so the result row
    is legible without opening the item.

    "Weak" is NOT primarily about length. On form-driven GLPI instances the form
    label IS the title, so hundreds of unrelated tickets share one long, generic
    title ("Falha no Equipamento") — a length threshold lets
    those through and the caller gets N indistinguishable rows. A title that
    repeats WITHIN one result set is non-distinguishing by definition, whatever
    its length, so that is the signal we use; short titles stay covered too.
    """
    title = (hit.title or "").strip()
    is_weak = len(title) < _WEAK_TITLE_LEN or _title_key(title) in repeated
    if is_weak and hit.body:
        snippet = " ".join(hit.body.split())
        if snippet:
            return f"{title} — {snippet}" if title else snippet
    return title


def _format_solution(solution: str) -> str:
    """Collapse whitespace and cap the resolution, marking any cut with an
    ellipsis.

    The DB already caps the column at SOLUTION_SNIPPET, and collapsing runs of
    whitespace can bring a value that WAS cut back under the display cap — so
    the formatter alone cannot tell truncated from complete. Hitting the fetch
    cap is the signal, and it has to be read before collapsing.
    """
    was_cut_by_db = len(solution) >= SOLUTION_SNIPPET
    collapsed = " ".join(solution.split())
    out = _truncate(collapsed, _SOLUTION_MAX)
    if was_cut_by_db and not out.endswith("…"):
        out += "…"
    return out


def _absolute_url(url: str) -> str:
    """Turn a stored root-relative path into a URL the caller can open.

    @MX:NOTE: hits vindos de CHAMADOS guardam o caminho relativo do GLPI
    (`/front/ticket.form.php?id=9397`), enquanto HELP e COMUNIDADE ja guardam
    URL absoluta.
    @MX:REASON: a tabela misturava os dois formatos, e o caminho relativo nao e
    clicavel em lugar nenhum — nem no chat, nem depois de copiado. Prefixar no
    render (e nao no ETL) conserta tambem tudo o que ja foi indexado, sem
    reprocessar o corpus.
    """
    if not url or not url.startswith("/"):
        return url
    from src.config.settings import settings

    base = str(settings.glpi_base_url or "").rstrip("/")
    return f"{base}{url}" if base else url


def _title_key(title: str) -> str:
    return " ".join(title.split()).casefold()


def _repeated_titles(hits: list[UnifiedHit]) -> set[str]:
    """Titles carried by more than one hit in this result set."""
    counts = Counter(_title_key(h.title or "") for h in hits)
    return {key for key, n in counts.items() if key and n > 1}


def format_markdown(hits: list[UnifiedHit]) -> str:
    if not hits:
        return "Nenhum resultado encontrado."
    # "#" = posição final no ranking RRF (ordem autoritativa). "Sim." é a
    # similaridade vetorial bruta da fonte (informativa) — NÃO é a chave de
    # ordenação e é incomparável entre corpora; por isso pode não ser monotônica
    # ao longo das linhas. A coluna "#" deixa a ordem inequívoca para a LLM.
    repeated = _repeated_titles(hits)
    headers = ["#", "Fonte", "Oficial", "ID", "Titulo", "Solucao", "Contexto", "Sim.", "URL"]
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for pos, h in enumerate(hits, start=1):
        oficial = "Sim" if h.is_official else "Nao"
        titulo = _escape(_truncate(_display_title(h, repeated), _TITLE_MAX))
        # The resolution is the point of a solved-ticket KB: without it the
        # caller has to open every hit to learn what was actually done.
        if h.solution:
            solucao = _escape(_format_solution(h.solution))
        else:
            solucao = _NO_SOLUTION if h.solutions_expected else "—"
        contexto = _escape(_truncate(h.context, _CONTEXT_MAX)) if h.context else "—"
        score = f"{h.similarity:.3f}" if h.similarity is not None else "—"
        lines.append(
            f"| {pos} | {h.source} | {oficial} | {_escape(h.id)} | {titulo} | {solucao} "
            f"| {contexto} | {score} | {_escape(_absolute_url(h.url))} |"
        )
    return "\n".join(lines)
