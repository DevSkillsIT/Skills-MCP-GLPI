"""Generic parameterized hybrid search — faithful port of the reference db.ts.

ONE query shape, parameterized by a SourceConfig (table + column expressions),
so the public MCP carries no source-specific SQL. Identical algorithm to the
reference:
  - semantic CTE: ROW_NUMBER() OVER (ORDER BY embedding <=> qvec) LIMIT 50
  - keyword CTE:  ROW_NUMBER() OVER (ORDER BY ts_rank_cd(fts, plainto_tsquery(
                  'portuguese_unaccent', q)) DESC) LIMIT 50
  - fused: SUM(1.0 / (k + rank)), k=60
  - similarity = 1 - (embedding <=> qvec); stable tiebreak by id (+ optional boost)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from .registry import SourceConfig
from .rrf import Hit

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

Mode = Literal["hybrid", "semantic", "keyword"]
RRF_K = 60
_CTE_LIMIT = 50
_TSCONFIG = "portuguese_unaccent"


def _vec_literal(qvec: list[float]) -> str:
    """pgvector text literal '[v1,v2,...]' (cast to ::halfvec in SQL)."""
    return "[" + ",".join(repr(float(x)) for x in qvec) + "]"


async def hybrid_search(
    pool: AsyncConnectionPool,
    src: SourceConfig,
    *,
    query: str,
    qvec: list[float] | None,
    limit: int,
    mode: Mode,
    rrf_k: int = RRF_K,
) -> list[Hit]:
    """Run hybrid/semantic/keyword search for one source. Returns ordered Hits."""
    effective_mode: Mode = mode
    if mode in ("hybrid", "semantic") and qvec is None:
        # No vector available -> keyword (hybrid degrades; semantic empty per ref,
        # but here we prefer keyword so the source still contributes).
        effective_mode = "keyword"

    t = src.table
    idx = src.id_expr
    title = src.title_expr
    url = src.url_expr
    ctx = src.context_expr
    emb = src.embedding_col
    fts = src.fts_col
    extra = f" {src.extra_filter} " if src.extra_filter else " "
    boost = f"{src.boost_order}, " if src.boost_order else ""

    if effective_mode == "keyword":
        sql = f"""
            SELECT {idx} AS id, {title} AS title, {ctx} AS context, {url} AS url,
                   ts_rank_cd({fts}, plainto_tsquery('{_TSCONFIG}', %(q)s)) AS score,
                   NULL::float8 AS similarity
            FROM {t} t
            WHERE {fts} @@ plainto_tsquery('{_TSCONFIG}', %(q)s){extra}
            ORDER BY score DESC, {boost}{idx}
            LIMIT %(lim)s;
        """
        params: dict[str, Any] = {"q": query, "lim": limit}
    elif effective_mode == "semantic":
        vec = _vec_literal(qvec)  # type: ignore[arg-type]
        sql = f"""
            SELECT {idx} AS id, {title} AS title, {ctx} AS context, {url} AS url,
                   1.0 - ({emb} <=> %(vec)s::halfvec) AS score,
                   1.0 - ({emb} <=> %(vec)s::halfvec) AS similarity
            FROM {t} t
            WHERE {emb} IS NOT NULL{extra}
            ORDER BY {emb} <=> %(vec)s::halfvec, {boost}{idx}
            LIMIT %(lim)s;
        """
        params = {"vec": vec, "lim": limit}
    else:  # hybrid
        vec = _vec_literal(qvec)  # type: ignore[arg-type]
        sql = f"""
            WITH semantic AS (
                SELECT {idx} AS id,
                       ROW_NUMBER() OVER (ORDER BY {emb} <=> %(vec)s::halfvec) AS rank
                FROM {t} t
                WHERE {emb} IS NOT NULL{extra}
                ORDER BY {emb} <=> %(vec)s::halfvec
                LIMIT {_CTE_LIMIT}
            ),
            keyword AS (
                SELECT {idx} AS id,
                       ROW_NUMBER() OVER (
                           ORDER BY ts_rank_cd({fts}, plainto_tsquery('{_TSCONFIG}', %(q)s)) DESC
                       ) AS rank
                FROM {t} t
                WHERE {fts} @@ plainto_tsquery('{_TSCONFIG}', %(q)s){extra}
                LIMIT {_CTE_LIMIT}
            ),
            fused AS (
                SELECT id, SUM(1.0 / (%(k)s + rank)) AS rrf_score
                FROM (SELECT id, rank FROM semantic UNION ALL SELECT id, rank FROM keyword) u
                GROUP BY id
            )
            SELECT {idx} AS id, {title} AS title, {ctx} AS context, {url} AS url,
                   f.rrf_score AS score,
                   1.0 - ({emb} <=> %(vec)s::halfvec) AS similarity
            FROM fused f
            JOIN {t} t ON ({idx}) = f.id
            ORDER BY f.rrf_score DESC, {boost}{idx}
            LIMIT %(lim)s;
        """
        params = {"vec": vec, "q": query, "k": rrf_k, "lim": limit}

    async with pool.connection() as conn:
        cur = await conn.execute(sql, params)
        rows = await cur.fetchall()

    return [
        Hit(
            id=str(r["id"]),
            title=r["title"] or "",
            url=r["url"] or "",
            context=r["context"],
            similarity=(float(r["similarity"]) if r["similarity"] is not None else None),
        )
        for r in rows
    ]


async def distinct_embedding_models(pool: AsyncConnectionPool, src: SourceConfig) -> list[str | None]:
    """Distinct embedding_model values for a source (feeds index-compat)."""
    sql = (
        f"SELECT DISTINCT {src.embedding_model_col} AS m "
        f"FROM {src.table} t WHERE {src.embedding_col} IS NOT NULL"
    )
    async with pool.connection() as conn:
        cur = await conn.execute(sql)
        rows = await cur.fetchall()
    return [r["m"] for r in rows]
