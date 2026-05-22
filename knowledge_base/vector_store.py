"""PostgreSQL + pgvector access layer for the tickets KB.

Mirrors the reference ``db.py``: an async psycopg pool with the vector type
registered, plus the upsert/gate helpers the ingestion uses. The hash gate
(``get_ticket_hash`` + metadata-only vs full upsert) is what makes the ETL
incremental — unchanged tickets are never re-embedded.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import structlog
from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .settings import PgSettings, get_settings
from .ticket_document import TicketDocument

log = structlog.get_logger(__name__)

_SCHEMA_FILE = Path(__file__).with_name("schema.sql")

_pool: AsyncConnectionPool[Any] | None = None


async def _on_connect(conn: AsyncConnection) -> None:
    await register_vector_async(conn)


async def get_pool(settings: PgSettings | None = None) -> AsyncConnectionPool[Any]:
    global _pool  # noqa: PLW0603 - module-level lazy singleton is intentional
    if _pool is None:
        cfg = settings or get_settings().pg
        pool = AsyncConnectionPool(
            conninfo=cfg.dsn,
            min_size=1,
            max_size=4,
            kwargs={"row_factory": dict_row},
            configure=_on_connect,
            open=False,
        )
        await pool.open()
        _pool = pool
        log.info("db.pool_opened", host=cfg.host, db=cfg.db)
    return _pool


async def close_pool() -> None:
    global _pool  # noqa: PLW0603 - module-level lazy singleton is intentional
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def acquire():
    pool = await get_pool()
    async with pool.connection() as conn:
        yield conn


async def apply_schema() -> None:
    """Run schema.sql (idempotent). Extensions must already be installed."""
    sql = _SCHEMA_FILE.read_text(encoding="utf-8")
    async with acquire() as conn:
        await conn.execute(sql)  # type: ignore[arg-type]
    log.info("db.schema_applied")


# ---------------------------------------------------------------------
# tickets
# ---------------------------------------------------------------------
async def get_ticket_hash(source: str, ticket_id: int) -> str | None:
    async with acquire() as conn:
        cur = await conn.execute(
            "SELECT body_hash FROM tickets WHERE source = %s AND id = %s",
            (source, ticket_id),
        )
        row = cast("dict[str, Any] | None", await cur.fetchone())
        return row["body_hash"] if row else None


def _common_params(doc: TicketDocument) -> dict[str, Any]:
    return {
        "id": doc.id,
        "source": doc.source,
        "titulo": doc.titulo,
        "tipo": doc.tipo,
        "status": doc.status,
        "categoria": doc.categoria,
        "prioridade": doc.prioridade,
        "origem": doc.origem,
        "entidade": doc.entidade,
        "metadata": json.dumps(doc.metadata, ensure_ascii=False, default=str),
        "source_date": doc.source_date,
        "date_mod": doc.date_mod,
    }


async def upsert_metadata(doc: TicketDocument) -> None:
    """Hash unchanged: refresh filter columns + metadata, leave body/embedding."""
    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE tickets SET
                titulo = %(titulo)s, tipo = %(tipo)s, status = %(status)s,
                categoria = %(categoria)s, prioridade = %(prioridade)s,
                origem = %(origem)s, entidade = %(entidade)s,
                metadata = %(metadata)s::jsonb,
                source_date = %(source_date)s, date_mod = %(date_mod)s,
                synced_at = now()
            WHERE source = %(source)s AND id = %(id)s
            """,
            _common_params(doc),
        )


async def upsert_full(
    doc: TicketDocument,
    *,
    embedding: list[float] | None,
    embedding_model: str | None,
) -> None:
    """New/changed ticket: write body, hash and embedding (may be NULL)."""
    params = _common_params(doc)
    params.update(
        body_text=doc.body_text,
        solution_text=doc.solution_text,
        body_hash=doc.body_hash,
        embedding=embedding,
        embedding_model=embedding_model,
    )
    async with acquire() as conn:
        await conn.execute(
            """
            INSERT INTO tickets (
                id, source, titulo, tipo, status, categoria, prioridade,
                origem, entidade, metadata, body_text, solution_text, body_hash,
                embedding, embedding_model, source_date, date_mod,
                indexed_at, synced_at
            ) VALUES (
                %(id)s, %(source)s, %(titulo)s, %(tipo)s, %(status)s,
                %(categoria)s, %(prioridade)s, %(origem)s, %(entidade)s,
                %(metadata)s::jsonb, %(body_text)s, %(solution_text)s, %(body_hash)s,
                %(embedding)s, %(embedding_model)s, %(source_date)s, %(date_mod)s,
                now(), now()
            )
            ON CONFLICT (source, id) DO UPDATE SET
                titulo = EXCLUDED.titulo, tipo = EXCLUDED.tipo,
                status = EXCLUDED.status, categoria = EXCLUDED.categoria,
                prioridade = EXCLUDED.prioridade, origem = EXCLUDED.origem,
                entidade = EXCLUDED.entidade, metadata = EXCLUDED.metadata,
                body_text = EXCLUDED.body_text,
                solution_text = EXCLUDED.solution_text,
                body_hash = EXCLUDED.body_hash,
                embedding = EXCLUDED.embedding,
                embedding_model = EXCLUDED.embedding_model,
                source_date = EXCLUDED.source_date, date_mod = EXCLUDED.date_mod,
                indexed_at = now(), synced_at = now()
            """,
            params,
        )


async def purge_aged(source: str, max_age_months: int) -> int:
    """Delete tickets whose open date fell outside the recency window.

    Keeps the KB fresh: a solution from years ago is more likely wrong than
    helpful, so it is removed rather than left to surface in search.
    """
    async with acquire() as conn:
        cur = await conn.execute(
            """
            DELETE FROM tickets
            WHERE source = %s
              AND source_date IS NOT NULL
              AND source_date < (now() - make_interval(months => %s))
            """,
            (source, max_age_months),
        )
        return cur.rowcount


async def delete_orphans(source: str, active_ids: Sequence[int]) -> int:
    """Delete tickets in this source that are no longer in the active set."""
    if not active_ids:
        return 0
    async with acquire() as conn:
        cur = await conn.execute(
            "DELETE FROM tickets WHERE source = %s AND id <> ALL(%s)",
            (source, list(active_ids)),
        )
        return cur.rowcount


# ---------------------------------------------------------------------
# sync_state
# ---------------------------------------------------------------------
async def begin_sync() -> None:
    async with acquire() as conn:
        await conn.execute(
            "UPDATE sync_state SET last_status = 'running', last_error = NULL WHERE id = 1"
        )


async def finish_sync(
    *,
    status: str,
    ticket_count: int,
    changed_count: int,
    duration_sec: int,
    error: str | None = None,
) -> None:
    error_count_expr = "0" if status == "ok" else "error_count + 1"
    async with acquire() as conn:
        await conn.execute(
            f"""
            UPDATE sync_state SET
                last_sync_at = now(), last_status = %s,
                last_ticket_count = %s, last_changed_count = %s,
                last_duration_sec = %s, last_error = %s,
                error_count = {error_count_expr}
            WHERE id = 1
            """,  # noqa: S608 - error_count_expr is a static literal, not user input
            (status, ticket_count, changed_count, duration_sec, error),
        )


async def get_sync_state() -> dict[str, Any] | None:
    async with acquire() as conn:
        cur = await conn.execute("SELECT * FROM sync_state WHERE id = 1")
        return cast("dict[str, Any] | None", await cur.fetchone())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


__all__: Sequence[str] = (
    "acquire",
    "apply_schema",
    "begin_sync",
    "close_pool",
    "delete_orphans",
    "finish_sync",
    "get_pool",
    "get_sync_state",
    "get_ticket_hash",
    "purge_aged",
    "upsert_full",
    "upsert_metadata",
    "utcnow",
)
