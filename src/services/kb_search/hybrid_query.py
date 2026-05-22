"""Fixed hybrid search over the kb_search contract — faithful RRF port.

ONE query shape for every source (all expose the contract columns). Identical
algorithm to the reference: semantic CTE (ROW_NUMBER over embedding <=> qvec) +
keyword CTE (ts_rank_cd over a portuguese_unaccent FTS), fused by SUM(1/(k+rank)),
k=60. Enterprise filters: always ``active``; optional tenant / lang; private
visibility excluded unless explicitly included.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from .rrf import Hit

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

Mode = Literal["hybrid", "semantic", "keyword"]
RRF_K = 60
_CTE_LIMIT = 50
_TSCONFIG = "portuguese_unaccent"
_BODY_SNIPPET = 240


@dataclass(slots=True)
class SearchFilters:
    tenant: str | None = None
    lang: str | None = None
    include_private: bool = False


def _vec_literal(qvec: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in qvec) + "]"


def _where(filters: SearchFilters, params: dict[str, Any]) -> str:
    """Build the shared filter clause (bind params added to `params`)."""
    clauses = ["active"]
    if not filters.include_private:
        clauses.append("visibility <> 'private'")
    if filters.tenant:
        clauses.append("(tenant IS NULL OR tenant = %(tenant)s)")
        params["tenant"] = filters.tenant
    if filters.lang:
        clauses.append("(lang IS NULL OR lang = %(lang)s)")
        params["lang"] = filters.lang
    return " AND ".join(clauses)


async def hybrid_search(
    pool: AsyncConnectionPool,
    relation: str,
    *,
    query: str,
    qvec: list[float] | None,
    limit: int,
    mode: Mode,
    filters: SearchFilters | None = None,
    rrf_k: int = RRF_K,
) -> list[Hit]:
    """Run hybrid/semantic/keyword search over a kb_search-contract relation."""
    filters = filters or SearchFilters()
    eff: Mode = "keyword" if (mode in ("hybrid", "semantic") and qvec is None) else mode

    params: dict[str, Any] = {"lim": limit}
    where = _where(filters, params)
    r = relation  # validated by SourceConfig._validate

    if eff == "keyword":
        params["q"] = query
        sql = f"""
            SELECT id, title, context, url, canonical_id,
                   left(body, {_BODY_SNIPPET}) AS body,
                   ts_rank_cd(fts, plainto_tsquery('{_TSCONFIG}', %(q)s)) AS score,
                   NULL::float8 AS similarity
            FROM {r}
            WHERE fts @@ plainto_tsquery('{_TSCONFIG}', %(q)s) AND {where}
            ORDER BY score DESC, id
            LIMIT %(lim)s;
        """  # noqa: S608 - relation validated; values bound
    elif eff == "semantic":
        params["vec"] = _vec_literal(qvec)  # type: ignore[arg-type]
        sql = f"""
            SELECT id, title, context, url, canonical_id,
                   left(body, {_BODY_SNIPPET}) AS body,
                   1.0 - (embedding <=> %(vec)s::halfvec) AS score,
                   1.0 - (embedding <=> %(vec)s::halfvec) AS similarity
            FROM {r}
            WHERE embedding IS NOT NULL AND {where}
            ORDER BY embedding <=> %(vec)s::halfvec, id
            LIMIT %(lim)s;
        """  # noqa: S608
    else:  # hybrid
        params["vec"] = _vec_literal(qvec)  # type: ignore[arg-type]
        params["q"] = query
        params["k"] = rrf_k
        sql = f"""
            WITH semantic AS (
                SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> %(vec)s::halfvec) AS rank
                FROM {r}
                WHERE embedding IS NOT NULL AND {where}
                ORDER BY embedding <=> %(vec)s::halfvec
                LIMIT {_CTE_LIMIT}
            ),
            keyword AS (
                SELECT id, ROW_NUMBER() OVER (
                    ORDER BY ts_rank_cd(fts, plainto_tsquery('{_TSCONFIG}', %(q)s)) DESC
                ) AS rank
                FROM {r}
                WHERE fts @@ plainto_tsquery('{_TSCONFIG}', %(q)s) AND {where}
                LIMIT {_CTE_LIMIT}
            ),
            fused AS (
                SELECT id, SUM(1.0 / (%(k)s + rank)) AS rrf_score
                FROM (SELECT id, rank FROM semantic UNION ALL SELECT id, rank FROM keyword) u
                GROUP BY id
            )
            SELECT t.id, t.title, t.context, t.url, t.canonical_id,
                   left(t.body, {_BODY_SNIPPET}) AS body,
                   f.rrf_score AS score,
                   1.0 - (t.embedding <=> %(vec)s::halfvec) AS similarity
            FROM fused f
            JOIN {r} t ON t.id = f.id
            ORDER BY f.rrf_score DESC, t.id
            LIMIT %(lim)s;
        """  # noqa: S608

    async with pool.connection() as conn:
        cur = await conn.execute(sql, params)
        rows = await cur.fetchall()

    return [
        Hit(
            id=str(row["id"]),
            title=row["title"] or "",
            url=row["url"] or "",
            context=row["context"],
            similarity=(float(row["similarity"]) if row["similarity"] is not None else None),
            canonical_id=row.get("canonical_id"),
            body=row.get("body") or "",
        )
        for row in rows
    ]


async def distinct_embedding_models(pool: AsyncConnectionPool, relation: str) -> list[str | None]:
    """Distinct embedding_model values among embedded rows (feeds index-compat)."""
    sql = f"SELECT DISTINCT embedding_model AS m FROM {relation} WHERE embedding IS NOT NULL"  # noqa: S608
    async with pool.connection() as conn:
        cur = await conn.execute(sql)
        rows = await cur.fetchall()
    return [row["m"] for row in rows]
