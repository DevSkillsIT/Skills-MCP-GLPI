"""Config-driven source registry + per-DSN connection pools.

A source is a registry entry (no source-specific SQL in code): table + column
expressions + optional filter/boost, plus a DSN resolved from an env var so
secrets stay out of the structural config. Structure lives in a JSON file
(KB_SEARCH_SOURCES, default sources.json next to this module); DSNs and the
embedding config live in .env (KB_SEARCH_ENV / process env).

This keeps the public GLPI MCP generic: connecting another KB = one registry
entry + one DSN env var.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# psycopg / pgvector are imported lazily inside PoolManager so that importing
# this module (and thus registering the tool) never requires the DB drivers —
# the GLPI MCP starts even when the optional kb_search deps are absent.

Provider = Literal["vllm", "openai", "none"]

_MODULE_DIR = Path(__file__).parent
# Only safe SQL identifier/expression chars (config is operator-controlled, but
# validate anyway to refuse anything that could break out of the query shape).
_SAFE_EXPR = re.compile(r"^[A-Za-z0-9_.,'|()\[\]<>= :*+\-/%?&]*$")


class RegistryError(RuntimeError):
    """Invalid source registry configuration."""


@dataclass(slots=True)
class SourceConfig:
    name: str
    label: str
    is_official: bool
    dsn: str
    table: str
    id_expr: str
    title_expr: str
    url_expr: str
    context_expr: str
    embedding_col: str = "embedding"
    fts_col: str = "fts"
    embedding_model_col: str = "embedding_model"
    extra_filter: str = ""  # e.g. "AND status = 'PUBLISHED'"
    boost_order: str = ""  # e.g. "has_accepted_answer DESC, replies_count DESC"
    dedup: bool = False

    def _validate(self) -> None:
        for fieldname in (
            "table", "id_expr", "title_expr", "url_expr", "context_expr",
            "embedding_col", "fts_col", "embedding_model_col", "extra_filter", "boost_order",
        ):
            value = getattr(self, fieldname)
            if value and not _SAFE_EXPR.match(value):
                raise RegistryError(f"source '{self.name}': unsafe SQL in {fieldname!r}: {value!r}")


@dataclass(slots=True)
class EmbeddingConfig:
    provider: Provider = "vllm"
    base_url: str = ""
    api_key: str = ""
    model: str = "/model"
    dimensions: int = 2560
    timeout: float = 60.0


@dataclass(slots=True)
class Registry:
    embedding: EmbeddingConfig
    sources: list[SourceConfig] = field(default_factory=list)


def _sources_path() -> Path:
    return Path(os.environ.get("KB_SEARCH_SOURCES", str(_MODULE_DIR / "sources.json")))


def load_registry() -> Registry:
    """Load the source registry from JSON; resolve DSNs and embedding from env."""
    path = _sources_path()
    if not path.exists():
        raise RegistryError(f"sources file not found: {path}")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

    emb_raw = data.get("embedding", {})
    provider_raw = os.environ.get("EMBEDDING_PROVIDER", emb_raw.get("provider", "vllm"))
    provider: Provider = provider_raw if provider_raw in ("vllm", "openai", "none") else "vllm"
    if provider == "openai":
        embedding = EmbeddingConfig(
            provider="openai",
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            model=os.environ.get("OPENAI_MODEL", "text-embedding-3-large"),
            dimensions=int(os.environ.get("OPENAI_DIMENSIONS", "2560")),
        )
    else:
        embedding = EmbeddingConfig(
            provider=provider,
            base_url=os.environ.get("VLLM_BASE_URL", ""),
            api_key=os.environ.get("VLLM_API_KEY", ""),
            model=os.environ.get("VLLM_MODEL", "/model"),
            dimensions=int(os.environ.get("VLLM_DIMENSIONS", "2560")),
        )

    sources: list[SourceConfig] = []
    for raw in data.get("sources", []):
        if not raw.get("enabled", True):
            continue
        dsn_env = raw["dsn_env"]
        dsn = os.environ.get(dsn_env, "")
        if not dsn:
            raise RegistryError(f"source '{raw['name']}': DSN env {dsn_env} is not set")
        src = SourceConfig(
            name=raw["name"],
            label=raw["label"],
            is_official=bool(raw.get("is_official", False)),
            dsn=dsn,
            table=raw["table"],
            id_expr=raw["id_expr"],
            title_expr=raw["title_expr"],
            url_expr=raw["url_expr"],
            context_expr=raw["context_expr"],
            embedding_col=raw.get("embedding_col", "embedding"),
            fts_col=raw.get("fts_col", "fts"),
            embedding_model_col=raw.get("embedding_model_col", "embedding_model"),
            extra_filter=raw.get("extra_filter", ""),
            boost_order=raw.get("boost_order", ""),
            dedup=bool(raw.get("dedup", False)),
        )
        src._validate()
        sources.append(src)
    if not sources:
        raise RegistryError("no enabled sources in registry")
    return Registry(embedding=embedding, sources=sources)


class PoolManager:
    """Lazy async pool per distinct DSN (sources in the same DB share a pool).

    psycopg/pgvector are imported here (not at module load) so the tool can be
    registered without the optional DB drivers installed."""

    def __init__(self) -> None:
        self._pools: dict[str, Any] = {}

    async def get(self, dsn: str) -> Any:
        pool = self._pools.get(dsn)
        if pool is None:
            from psycopg.rows import dict_row
            from psycopg_pool import AsyncConnectionPool

            pool = AsyncConnectionPool(
                conninfo=dsn,
                min_size=1,
                max_size=4,
                kwargs={"row_factory": dict_row},
                configure=_register_vector,
                open=False,
            )
            await pool.open()
            self._pools[dsn] = pool
        return pool

    async def close_all(self) -> None:
        for pool in self._pools.values():
            await pool.close()
        self._pools.clear()


async def _register_vector(conn: Any) -> None:
    try:
        from pgvector.psycopg import register_vector_async
    except ImportError:  # pragma: no cover - dependency guard
        return
    await register_vector_async(conn)
