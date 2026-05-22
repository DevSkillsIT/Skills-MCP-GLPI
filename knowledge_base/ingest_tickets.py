"""Ingestion orchestrator: GLPI tickets -> pgvector knowledge base.

Mirrors the reference indexer lifecycle (extract -> clean -> hash gate ->
embed -> upsert) for GLPI tickets. Extraction runs remotely over SSH so the
GLPI database password never leaves the GLPI host: a small remote script reads
the credentials from GLPI's ``config_db.php``, runs ``mysql``, and streams the
JSONL back over stdout.

Usage (from the knowledge_base/ directory, with .env populated):
    python -m knowledge_base.ingest_tickets --dry-run
    python -m knowledge_base.ingest_tickets
    python -m knowledge_base.ingest_tickets --max-age-months 12 --provider openai
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import structlog

from . import vector_store as store
from .embedder import (
    EmbeddingClient,
    EmbeddingError,
    EmbeddingTooLongError,
    NullEmbeddingClient,
    build_embedding_client,
)
from .settings import Provider, Settings, get_settings
from .ticket_document import TicketDocument, build_document

log = structlog.get_logger(__name__)

_SQL_FILE = Path(__file__).with_name("extract_tickets.sql")

# Remote extraction: parse GLPI DB creds from config_db.php, write a 600 my.cnf,
# run mysql, clean up. The SQL is appended as a heredoc by the caller.
_REMOTE_SCRIPT_TMPL = r"""
set -euo pipefail
CFG="{cfg}"
[ -f "$CFG" ] || {{ echo "config_db.php not found: $CFG" >&2; exit 3; }}
H=$(grep -oP "dbhost\s*=\s*'\K[^']+" "$CFG" | head -1 || true)
PORTCFG=$(grep -oP "dbport\s*=\s*'\K[^']+" "$CFG" | head -1 || true)
U=$(grep -oP "dbuser\s*=\s*'\K[^']+" "$CFG" | head -1 || true)
P=$(grep -oP "dbpassword\s*=\s*'\K[^']+" "$CFG" | head -1 || true)
D=$(grep -oP "dbdefault\s*=\s*'\K[^']+" "$CFG" | head -1 || true)
# Port can live in a separate $dbport field or inline as host:port; the
# explicit field wins, then an inline colon, then the MySQL default.
HOST="${{H%%:*}}"
INLINE_PORT="${{H##*:}}"
PORT="${{PORTCFG:-}}"
[ -z "$PORT" ] && [ "$INLINE_PORT" != "$H" ] && PORT="$INLINE_PORT"
[ -z "$PORT" ] && PORT=3306
# 'localhost' makes the mysql client use the unix socket and ignore the port;
# force TCP to 127.0.0.1 so we hit the GLPI mysqld on its real port.
[ "$HOST" = "localhost" ] && HOST=127.0.0.1
# Password goes through MYSQL_PWD, NOT a my.cnf: GLPI passwords routinely
# contain '#', which an option file would treat as a comment and silently
# truncate. MYSQL_PWD is read verbatim and never appears on the command line.
export MYSQL_PWD="$P"
mysql --protocol=TCP -h"$HOST" -P"$PORT" -u"$U" --skip-column-names --raw "$D"
"""


def _render_sql(max_age_months: int, statuses: list[int]) -> str:
    sql = _SQL_FILE.read_text(encoding="utf-8")
    status_list = ",".join(str(s) for s in statuses)
    return sql.replace("__MAX_AGE_MONTHS__", str(max_age_months)).replace(
        "__STATUS_LIST__", status_list
    )


def extract_remote(ssh_host: str, cfg_path: str, sql: str) -> list[dict]:
    """Run the extraction on the GLPI host via SSH; return parsed JSON rows."""
    remote_script = _REMOTE_SCRIPT_TMPL.format(cfg=cfg_path) + "\n" + sql + "\n"
    log.info("extract.start", ssh_host=ssh_host)
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", ssh_host, "bash -s"],
        input=remote_script,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"remote extraction failed (rc={proc.returncode}): {proc.stderr.strip()[:500]}"
        )
    rows: list[dict] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            log.warning("extract.bad_line", error=str(exc), preview=line[:120])
    log.info("extract.done", rows=len(rows))
    return rows


async def _preflight(embedder: EmbeddingClient, settings: Settings) -> None:
    """Verify the embedding endpoint is reachable and returns the expected
    dimension before the bulk loop — fail fast instead of mid-run."""
    dims = settings.openai.dimensions if settings.provider == "openai" else settings.vllm.dimensions
    vec = await embedder.embed("teste de conectividade")
    if len(vec) != dims:
        raise EmbeddingError(f"preflight: endpoint returned {len(vec)} dims, expected {dims}")
    log.info("preflight.ok", provider=settings.provider, dims=dims)


async def _index_one(
    doc: TicketDocument, embedder: EmbeddingClient, model: str | None, embeddings_enabled: bool
) -> str:
    """Hash gate + embed + upsert one ticket. Returns the mode taken."""
    existing = await store.get_ticket_hash(doc.source, doc.id)
    if existing == doc.body_hash:
        await store.upsert_metadata(doc)
        return "unchanged"

    if not embeddings_enabled or not doc.body_text.strip():
        # Embeddings off (provider=none) or no problem text to embed. Keep the
        # row (solution + FTS still useful); skip the vector.
        await store.upsert_full(doc, embedding=None, embedding_model=None)
        return "no-embed"

    try:
        vector = await embedder.embed(doc.body_text)
    except EmbeddingTooLongError as exc:
        # Keep the text (FTS still finds it); skip the vector.
        log.warning("index.too_long", id=doc.id, error=str(exc)[:160])
        await store.upsert_full(doc, embedding=None, embedding_model=None)
        return "no-embed"
    except EmbeddingError:
        log.error("index.embed_failed", id=doc.id)
        raise

    await store.upsert_full(doc, embedding=vector, embedding_model=model)
    return "new"


async def run(
    *,
    dry_run: bool,
    max_age_months: int,
    provider: Provider | None,
    limit: int | None,
) -> int:
    settings = get_settings()
    if provider:
        settings.provider = provider
    source = settings.kb.source_label
    statuses = settings.kb.status_list
    strategy = settings.kb.embed_strategy
    active_provider = settings.provider
    model = settings.openai.model if active_provider == "openai" else settings.vllm.model

    if not settings.kb.ssh_host:
        raise RuntimeError("KB_SSH_HOST not set (configure the GLPI SSH alias in .env)")

    sql = _render_sql(max_age_months, statuses)
    rows = extract_remote(settings.kb.ssh_host, settings.kb.remote_db_config, sql)
    if limit:
        rows = rows[:limit]

    docs = [build_document(r, source=source, embed_strategy=strategy) for r in rows]
    log.info(
        "normalize.done",
        tickets=len(docs),
        strategy=strategy,
        with_solution=sum(1 for d in docs if d.solution_text),
        empty_problem=sum(1 for d in docs if not d.body_text.strip()),
        avg_chars=(sum(len(d.body_text) for d in docs) // len(docs)) if docs else 0,
    )

    if dry_run:
        sample = docs[0] if docs else None
        log.info(
            "dry_run.ok",
            tickets=len(docs),
            provider=active_provider,
            model=model,
            sample_id=sample.id if sample else None,
            sample_chars=len(sample.body_text) if sample else 0,
        )
        return 0

    started = time.monotonic()
    counters = {"new": 0, "unchanged": 0, "no-embed": 0}
    await store.apply_schema()
    await store.begin_sync()
    embedder = build_embedding_client(settings)
    embeddings_enabled = not isinstance(embedder, NullEmbeddingClient)
    try:
        async with embedder:
            if embeddings_enabled:
                await _preflight(embedder, settings)
            for doc in docs:
                mode = await _index_one(doc, embedder, model, embeddings_enabled)
                counters[mode] += 1
        purged = await store.purge_aged(source, max_age_months)
        # Orphan cleanup only on a FULL run — with --limit the active set is
        # partial and would otherwise delete every other row.
        orphans = (
            await store.delete_orphans(source, [d.id for d in docs])
            if limit is None
            else 0
        )
        duration = int(time.monotonic() - started)
        changed = counters["new"] + counters["no-embed"]
        await store.finish_sync(
            status="ok",
            ticket_count=len(docs),
            changed_count=changed,
            duration_sec=duration,
        )
        log.info(
            "ingest.ok",
            **counters,
            purged_aged=purged,
            orphans_deleted=orphans,
            duration_sec=duration,
        )
    except Exception as exc:  # noqa: BLE001 - record failure in sync_state, then re-raise
        await store.finish_sync(
            status="error",
            ticket_count=len(docs),
            changed_count=0,
            duration_sec=int(time.monotonic() - started),
            error=str(exc)[:500],
        )
        log.error("ingest.failed", error=str(exc))
        raise
    finally:
        await store.close_pool()
    return 0


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Ingest GLPI tickets into the pgvector KB.")
    parser.add_argument("--dry-run", action="store_true", help="Extract + normalize only; no DB writes, no embeddings.")
    parser.add_argument("--max-age-months", type=int, default=settings.kb.max_age_months, help="Recency window in months.")
    parser.add_argument("--provider", choices=["vllm", "openai", "none"], default=None, help="Override embedding provider.")
    parser.add_argument("--limit", type=int, default=None, help="Cap the number of tickets (testing).")
    args = parser.parse_args(argv)

    try:
        return asyncio.run(
            run(
                dry_run=args.dry_run,
                max_age_months=args.max_age_months,
                provider=args.provider,
                limit=args.limit,
            )
        )
    except (RuntimeError, EmbeddingError, subprocess.SubprocessError) as exc:
        print(f"ingest failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
