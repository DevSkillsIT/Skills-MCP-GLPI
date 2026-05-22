"""Config-driven source registry + per-DSN connection pools.

With the kb_search contract (CONTRACT.md) every source exposes the SAME columns,
so a source is just: a relation name + a DSN + display metadata + an RRF weight.
No per-source SQL or column mapping. Structure lives in a JSON file
(KB_SEARCH_SOURCES, default sources.json); DSNs/embedding config live in env.

psycopg/pgvector are imported lazily so importing this module (and registering
the tool) never requires the DB drivers — the MCP starts without them.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Provider = Literal["vllm", "openai", "none"]

_MODULE_DIR = Path(__file__).parent
# A relation name: optional schema + identifier. No spaces/semicolons/etc.
_SAFE_RELATION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


class RegistryError(RuntimeError):
    """Invalid source registry configuration."""


@dataclass(slots=True)
class SourceConfig:
    name: str
    label: str
    is_official: bool
    dsn: str
    relation: str  # table/view exposing the kb_search contract
    weight: float = 1.0  # RRF boost (e.g. official sources > community)
    dedup: bool = False  # collapse repost-prone titles within the source

    def _validate(self) -> None:
        if not _SAFE_RELATION.match(self.relation):
            raise RegistryError(f"source '{self.name}': unsafe relation {self.relation!r}")
        if self.weight <= 0:
            raise RegistryError(f"source '{self.name}': weight must be > 0")


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


def _embedding_from_env(default_provider: str) -> EmbeddingConfig:
    raw = os.environ.get("EMBEDDING_PROVIDER", default_provider)
    provider: Provider = raw if raw in ("vllm", "openai", "none") else "vllm"
    if provider == "openai":
        return EmbeddingConfig(
            provider="openai",
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            model=os.environ.get("OPENAI_MODEL", "text-embedding-3-large"),
            dimensions=int(os.environ.get("OPENAI_DIMENSIONS", "2560")),
        )
    return EmbeddingConfig(
        provider=provider,
        base_url=os.environ.get("VLLM_BASE_URL", ""),
        api_key=os.environ.get("VLLM_API_KEY", ""),
        model=os.environ.get("VLLM_MODEL", "/model"),
        dimensions=int(os.environ.get("VLLM_DIMENSIONS", "2560")),
    )


def load_registry() -> Registry:
    path = _sources_path()
    if not path.exists():
        raise RegistryError(f"sources file not found: {path}")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

    embedding = _embedding_from_env(data.get("embedding", {}).get("provider", "vllm"))

    sources: list[SourceConfig] = []
    for raw in data.get("sources", []):
        if not raw.get("enabled", True):
            continue
        dsn = os.environ.get(raw["dsn_env"], "")
        if not dsn:
            raise RegistryError(f"source '{raw['name']}': DSN env {raw['dsn_env']} not set")
        src = SourceConfig(
            name=raw["name"],
            label=raw["label"],
            is_official=bool(raw.get("is_official", False)),
            dsn=dsn,
            relation=raw["relation"],
            weight=float(raw.get("weight", 1.0)),
            dedup=bool(raw.get("dedup", False)),
        )
        src._validate()
        sources.append(src)
    if not sources:
        raise RegistryError("no enabled sources in registry")
    return Registry(embedding=embedding, sources=sources)


class PoolManager:
    """Lazy async pool per distinct DSN (sources in the same DB share a pool)."""

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

    async def health_check(self, src: SourceConfig) -> str | None:
        """Probe the source relation (SELECT ... LIMIT 0). Returns an error
        string if the relation is missing/broken, else None."""
        try:
            pool = await self.get(src.dsn)
            async with pool.connection() as conn:
                await conn.execute(f"SELECT 1 FROM {src.relation} LIMIT 0")  # noqa: S608 - relation validated
            return None
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            return str(exc)[:200]

    async def close_all(self) -> None:
        for pool in self._pools.values():
            await pool.close()
        self._pools.clear()


async def _register_vector(conn: Any) -> None:
    try:
        from pgvector.psycopg import register_vector_async
    except ImportError:  # pragma: no cover
        return
    await register_vector_async(conn)
