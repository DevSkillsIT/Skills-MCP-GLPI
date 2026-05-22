# knowledge_base — GLPI tickets as a vector knowledge base

Phase 1 of the GLPI MCP knowledge-base feature: an **optional, self-contained**
Python pipeline that turns a GLPI instance's own resolved tickets into a
PostgreSQL + pgvector store. The MCP (Phase 2) then answers from resolved-ticket
history through hybrid (vector + full-text) search.

It deliberately mirrors the proven `reference` ETL: same pgvector +
`portuguese_unaccent` FTS + `halfvec(2560)` shape, same incremental hash gate,
same OpenAI-compatible embedding client. Every KB in a deployment shares this
shape so the MCP can query them through one search path.

```
extract_tickets.sql  ──ssh──>  GLPI MySQL (remote, creds stay on host)
        │
        ▼
ticket_document.py   clean HTML, translate codes, build searchable body_text
        │
        ▼
embedder.py          vLLM (Qwen3-embedding-4b) | OpenAI (text-embedding-3-large)
        │
        ▼
vector_store.py      hash-gated upsert into pgvector + recency purge + sync_state
```

## Layout

| File | Role |
|------|------|
| `settings.py` | Env config: `PG_*`, embedding provider (`EMBEDDING_PROVIDER`), `KB_*` window/status. |
| `extract_tickets.sql` | GLPI extraction (recency + resolved-status filters; placeholders filled by the orchestrator). |
| `ticket_document.py` | HTML cleaning, code→label translation, `body_text` + content hash. |
| `embedder.py` | Async embedding client, `vllm`\|`openai`, retries + dimension check. |
| `vector_store.py` | psycopg pool, schema apply, hash-gated upsert, recency purge, `sync_state`. |
| `schema.sql` | `tickets` table (`halfvec(2560)`, FTS, HNSW + GIN) + `sync_state`. |
| `ingest_tickets.py` | Orchestrator CLI: extract → normalize → gate → embed → upsert. |

## Configuration (`.env`)

```dotenv
# pgvector target
PG_HOST=localhost
PG_PORT=5432
PG_DB=glpi_kb
PG_USER=glpi_kb
PG_PASSWORD=...

# embedding provider: vllm | openai | none (mutually exclusive, no auto-fallback)
EMBEDDING_PROVIDER=vllm
VLLM_BASE_URL=http://your-vllm-host:8090/v1
VLLM_MODEL=/model
VLLM_DIMENSIONS=2560
# OPENAI_API_KEY=...        # only if EMBEDDING_PROVIDER=openai
# OPENAI_MODEL=text-embedding-3-large
# OPENAI_DIMENSIONS=2560

# knowledge-base shaping
KB_MAX_AGE_MONTHS=18           # recency window (IT solutions age out)
KB_TICKET_STATUSES=5,6         # GLPI status codes: 5=Solucionado, 6=Fechado
KB_EMBED_STRATEGY=full         # full | form_description (see "Embedding strategy")
KB_SOURCE_LABEL=glpi           # label for this GLPI instance (e.g. a site name)
KB_SSH_HOST=your-glpi-ssh-alias  # ~/.ssh/config alias for the GLPI host (required)
KB_REMOTE_DB_CONFIG=/etc/glpi/config_db.php
```

## Database prerequisites

Run once as superuser on the target Postgres:

```sql
CREATE EXTENSION IF NOT EXISTS vector;     -- >= 0.7 for halfvec
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

`ingest_tickets` applies `schema.sql` itself (idempotent).

## Running

```bash
pip install -r knowledge_base/requirements.txt

# extract + normalize only — no DB, no embeddings (safe first check)
python -m knowledge_base.ingest_tickets --dry-run

# full incremental load
python -m knowledge_base.ingest_tickets

# overrides
python -m knowledge_base.ingest_tickets --max-age-months 12 --provider openai
```

## How extraction stays safe

`extract_tickets.sql` runs on the GLPI host over SSH. A small remote script
reads the DB credentials from GLPI's `config_db.php`, passes the password to
`mysql` via the `MYSQL_PWD` environment variable (never an option file — GLPI
passwords often contain `#`, which a `my.cnf` would treat as a comment and
truncate), and streams JSONL back — **the password never leaves the GLPI
server** and never appears in this repo, on a command line, or in logs.

> Hardening note: `MYSQL_PWD` is a pragmatic choice for controlled remote
> execution. A future hardening could use a dedicated read-only DB user and a
> short-lived restricted credentials file instead.

## Embedding strategy (`KB_EMBED_STRATEGY`)

Choose what gets embedded based on how the GLPI is used:

- **`full`** (default) — title + category + description. Right for GLPI
  instances where the ticket title is real signal (free-text tickets).
- **`form_description`** — only the form's `Descrição` field. Right for
  form-driven instances where one form title can cover a large share of tickets,
  making titles boilerplate noise. Forms without a `Descrição` field fall back
  to the full cleaned text (which is their real content).

In both modes the **solution** is stored separately (`solution_text`), surfaced
on hit, and **not** embedded. FTS is weighted regardless: description = `A`,
solution = `B`, title + category = `D`, so `ts_rank` favors the real problem
text over repetitive form labels.

## Scheduling (incremental sync)

The pipeline is incremental (hash gate), so run it on a timer to keep the KB
fresh. A cron entry (mirrors the reference KB's daily 03:00 sync):

```cron
0 3 * * * cd /path/to/Skills-MCP-GLPI/<this-repo> && .venv/bin/python -m knowledge_base.ingest_tickets >> /var/log/glpi_kb_sync.log 2>&1
```

A systemd service + timer is provided under `knowledge_base/deploy/`.

## Incremental behavior

- Unchanged ticket (`body_hash` match) → metadata-only refresh, no re-embed.
- New/changed ticket → embed + full upsert.
- Body too long to embed → text kept (FTS still finds it), vector skipped.
- Tickets aged past `KB_MAX_AGE_MONTHS` are purged each run.
- Run stats recorded in `sync_state` for cron/alerting.

> **Privacy note:** follow-ups include private technician notes and real names.
> Fine for an internal IT KB; anonymize/filter before any external exposure.
