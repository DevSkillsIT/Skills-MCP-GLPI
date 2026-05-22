"""Source registry (Pydantic-validated) + per-DSN connection pools.

Config is NOT read here from files/env — it is passed in as a dict from the
MCP's central Settings (the per-instance JSON `knowledge_base` section, or the
`KNOWLEDGE_BASE` env for the .env fallback). One config location, no scattered
per-module files.

Every source exposes the kb_search contract (CONTRACT.md), so a source is just:
relation + DSN + display metadata + RRF weight. psycopg/pgvector import lazily.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Provider = Literal["vllm", "openai", "none"]

# A relation: optional schema + identifier; no spaces/semicolons/etc.
_SAFE_RELATION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


class EmbeddingConfig(BaseModel):
    provider: Provider = "vllm"
    base_url: str = ""
    api_key: str = ""
    model: str = "/model"
    dimensions: int = 2560
    timeout: float = 60.0


class SourceConfig(BaseModel):
    name: str
    label: str
    is_official: bool = False
    dsn: str
    relation: str
    weight: float = 1.0
    dedup: bool = False

    @field_validator("relation")
    @classmethod
    def _safe_relation(cls, v: str) -> str:
        if not _SAFE_RELATION.match(v):
            raise ValueError(f"unsafe relation name: {v!r}")
        return v

    @field_validator("weight")
    @classmethod
    def _positive_weight(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("weight must be > 0")
        return v


class Registry(BaseModel):
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    sources: list[SourceConfig] = Field(default_factory=list)


def load_registry(kb_config: dict[str, Any]) -> Registry:
    """Validate the knowledge_base config dict into a Registry (fail-fast)."""
    return Registry.model_validate(kb_config or {})


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
        """Probe the source relation. Returns an error string if broken, else None."""
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
