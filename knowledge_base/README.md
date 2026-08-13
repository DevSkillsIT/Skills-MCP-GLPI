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
ticket_document.py   clean HTML, translate codes, extract the form's problem,
                     redact credentials, build body / solution / embed text
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
| `ticket_document.py` | HTML cleaning, code→label translation, form problem extraction, credential redaction, `body_text` / `solution_text` / `embed_text` + content hash. |
| `embedder.py` | Async embedding client, `vllm`\|`openai`, retries + dimension check. |
| `vector_store.py` | psycopg pool, schema apply, hash-gated upsert, recency purge, `sync_state`. |
| `schema.sql` | `tickets` table (`halfvec(2560)`, FTS, HNSW + GIN) + `sync_state`. |
| `ingest_tickets.py` | Orchestrator CLI: extract → normalize → gate → embed → upsert. |

## Configuration (centralized — no per-module .env)

Config comes from the MCP's central config, ONE place:

- **Multi-instance (recommended):** the `knowledge_base.ingestion` section of the
  per-instance JSON (`GLPI_MCP_CONFIG`), sharing `knowledge_base.embedding` with
  search. Example shape: `knowledge_base.ingestion = {pg:{host,port,db,user,
  password}, source_label, ssh_host, remote_db_config, ticket_statuses,
  max_age_months, embed_strategy, description_labels, include_followups,
  redact_literals}`.
- **Community / standalone fallback:** the SINGLE root `.env` (`.base-code/.env`,
  shared with the MCP) using the env vars below — never a per-module .env.

```dotenv
# --- root .env fallback (community) ---
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
KB_EMBED_STRATEGY=full         # full | form_description | problem_solution
KB_INCLUDE_FOLLOWUPS=true      # fold technician follow-ups into the resolution
# List-valued settings are parsed as JSON arrays with DOUBLE quotes, not as a
# comma-separated string — anything else fails at startup with a SettingsError.
# Unset = built-in defaults.
KB_DESCRIPTION_LABELS=["Descrição","Por favor, descreva o problema"]
KB_REDACT_LITERALS=[]          # exact secret values to strip everywhere (see "Credential redaction")
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
- **`form_description`** — only the form's free-text problem field. Right for
  form-driven instances where one form title can cover a large share of tickets,
  making titles boilerplate noise.
- **`problem_solution`** — problem **and** resolution. Same displayed body as
  `form_description`, but the vector also covers what the technician did, so a
  ticket is findable by the fix and not only by the symptom.

Which field holds the problem is instance-specific: forms name it `Descrição`,
`Por favor, descreva o problema`, and so on. `description_labels` configures
that; when no configured label matches, a label in the same family is used, and
a purely structured form (no free-text field at all) keeps every answer instead
of promoting one. The Formcreator header and leading greetings are always
stripped, and attachment fields are never promoted.

`include_followups` (default true) folds technician follow-ups into
`solution_text`: GLPI keeps the fix in a follow-up rather than a formal solution
on a large share of tickets. Boilerplate lines (GLPI's own workflow messages,
sign-offs, bare acknowledgements) are dropped; the ingest logs any text
repeating across many tickets as a candidate for that list.

In all modes the **solution** is stored separately (`solution_text`) and surfaced
on hit. Whether it is *embedded* depends on the strategy: `full` and
`form_description` vectorize the problem only, `problem_solution` vectorizes both.
What gets vectorized is `embed_text`, which is deliberately separate from the
displayed `body_text`; it is transient (folded into `body_hash`, never stored as
a column). FTS is weighted regardless: description = `A`, solution = `B`,
title + category = `D`, so `ts_rank` favors the real problem text over repetitive
form labels.

## Credential redaction

Users and technicians paste passwords into tickets. A KB makes that text
semantically discoverable, so credentials are stripped **before indexing** — the
value never reaches the vector, the FTS index or a rendered result. Redaction
happens at the single point where raw GLPI text enters the document, which also
covers `metadata` (it keeps follow-ups and solutions verbatim). The label is kept
so a reader knows something was removed: `[credencial removida]`.

Four mechanisms, because no single one is enough:

1. **Labelled** — `Senha: X`, `password=X`, same line only.
2. **Proximity** — real tickets write it as prose ("Resetei sua senha para: X").
   Anchored on the *value* looking like a credential (≥ 6 chars, letter **and**
   digit), so "a senha do usuário expirou" is untouched.
3. **Known literals** (`redact_literals`) — a shared password often sits on a line
   of its own with no label near it; only knowing the value catches that.
   Replacement is word-bounded so a literal inside a longer word is not corrupted.
4. **Standalone line** — handover blocks put the password lines away from any
   label. Requires a symbol and forbids a dot, keeping hostnames, versions, IPs
   and e-mails out.

**Corpus harvesting.** The same password appears labelled in one ticket and bare
in another, which no per-ticket rule can see. The ingest runs `harvest_secrets`
over the whole extraction *before* building documents and applies the union as
literals — the corpus becomes its own denylist. This runs before any `--limit`
slice, so a partial run redacts identically to a full one. The `redact.harvested`
log line reports how many values were configured versus discovered.

Because a harvested value is applied to **every** ticket, a false positive erases
a word corpus-wide (`Senha - Padrão` once promoted `Padrão` and mutilated 61
tickets). Only values that look like a credential on their own may travel: letters
and digits, not money, no `XXXX`-style runs. Values failing that gate are still
redacted where they were actually seen.

> Redaction is **near-idempotent, not idempotent**: a second pass can redact more.
> The pipeline always starts from raw GLPI text, so this does not arise in
> practice — but do not rely on `redact(redact(x)) == redact(x)`.

## Scheduling (incremental sync)

The pipeline is incremental (hash gate), so run it on a timer to keep the KB
fresh. `knowledge_base/deploy/` ships a **templated** systemd pair — one enabled
instance per GLPI, since a deployment serves several:

```bash
sudo cp knowledge_base/deploy/glpi-kb-ingest@.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
# %i is the instance directory name; it selects that instance's GLPI_MCP_CONFIG
sudo systemctl enable --now glpi-kb-ingest@<instance>.timer

systemctl list-timers 'glpi-kb-ingest@*'
journalctl -u glpi-kb-ingest@<instance>.service -n 50
```

The timer runs daily at **05:00** with `Persistent=true` (catches up after
downtime) and a randomized delay so several instances do not start at the same
instant. The service wraps the run in a `flock` **shared with the Sankhya ETLs**,
which contend for the same embedding endpoint and Postgres; `-n` means a loser
skips its run rather than queueing, which is safe because the ingest is
incremental and the next run self-heals.

A plain cron entry works too, if systemd is not in play:

```cron
0 5 * * * cd /path/to/Skills-MCP-GLPI/<this-repo> && venv/bin/python -m knowledge_base.ingest_tickets >> /var/log/glpi_kb_sync.log 2>&1
```

## Incremental behavior

- Unchanged ticket (`body_hash` match) → metadata-only refresh, no re-embed —
  **unless** the stored row carries no vector (indexed while `provider=none`, or
  after an embedding failure), in which case it is embedded now. The hash never
  changes on its own, so without this the row would stay invisible to semantic
  search forever.
- New/changed ticket → embed + full upsert. `body_hash` covers `body_text`,
  `solution_text` **and** `embed_text`, so changing `embed_strategy` correctly
  forces reindexing instead of reporting "unchanged" with stale vectors.
- Body too long to embed → text kept (FTS still finds it), vector skipped.
- Tickets aged past `KB_MAX_AGE_MONTHS` are purged each run.
- Run stats recorded in `sync_state` for cron/alerting.

> **Privacy note:** follow-ups include private technician notes and real names.
> Fine for an internal IT KB; anonymize/filter before any external exposure.
