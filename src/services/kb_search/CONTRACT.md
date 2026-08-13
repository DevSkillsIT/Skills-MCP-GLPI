# `kb_search` contract — the shape every KB source exposes

Any vectorized source the GLPI MCP searches must expose a **relation** (table or
read-only view) presenting these columns. The search engine queries ONLY these
names, so adding a source = create the relation + one registry entry. No
source-specific SQL lives in the MCP.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | `text` | Stable id within the source. |
| `title` | `text` | Display title. |
| `body` | `text` | The problem text: displayed, full-text searchable, and the basis of the vector. A source MAY embed more than it exposes here (the GLPI tickets ETL can vectorize problem + resolution while `body` stays the problem alone, so a result row does not print the resolution twice). |
| `solution` | `text` NULL | Resolution/answer, for ticket/Q&A sources. NULL if N/A. For structured/multi-part solutions, flatten to text or use `metadata`. |
| `url` | `text` NULL | Link back to the canonical item. |
| `context` | `text` NULL | Human context (breadcrumb, category, space). |
| `tags` | `text[]` NULL | Labels / keywords. |
| `lang` | `text` NULL | BCP-47-ish (`pt-BR`); enables multilingual filtering. |
| `tenant` | `text` NULL | Multi-tenant scoping (e.g. GLPI entity / client). |
| `visibility` | `text` | `public` \| `internal` \| `private`. Default search excludes `private`. |
| `canonical_id` | `text` NULL | Cross-source dedup key: hits sharing it collapse to the best-ranked. |
| `source_date` | `timestamptz` NULL | Creation/open date (recency). |
| `updated_at` | `timestamptz` NULL | Last change (freshness). |
| `active` | `boolean` | Searchable now (folds outdated/draft/status gates). |
| `embedding` | `halfvec(2560)` NULL | Query-time cosine. NULL rows still found via FTS. |
| `fts` | `tsvector` | Full-text, built with `portuguese_unaccent`. |
| `embedding_model` | `text` NULL | Model that produced `embedding`; drives per-source index-compat. |
| `metadata` | `jsonb` | Source-specific extras (votes, answered flag, …). |

## Deduplication (`canonical_id`)
If a row's `canonical_id` is non-null, it is a cross-source dedup key: when
multiple sources return rows sharing the same `canonical_id`, only the
best-ranked (highest RRF) is kept and the rest are collapsed. Use it when a row
mirrors content in another source (e.g. an official doc reposted to the forum).
Leave it NULL if the row is unique to its source. Within a single source,
repost-prone titles can also be collapsed via the registry `dedup` flag.

## Rules
- All sources in one deployment SHOULD share the same embedding model/dimension
  (cross-model cosine is invalid). A source whose `embedding_model` mismatches the
  configured provider degrades to keyword **only for itself**; others stay hybrid.
- Sources we build: the ETL writes a table with these columns directly.
- Foreign sources (not ours): expose a read-only `kb_search*` **view** mapping
  their columns to this contract (NULL where a field is absent). The view's DDL
  belongs to the source's OWN repo, not here (e.g. the Sankhya views live at
  `sankhya_ajuda/sql/kb_search_views.sql`).

## Config (centralized — no per-module files)
The source registry lives in the MCP's CENTRAL config: a `knowledge_base`
section in the per-instance JSON (`GLPI_MCP_CONFIG`), or the `KNOWLEDGE_BASE`
env (JSON string) for the `.env` fallback. Validated by Pydantic at load.
Shape: `{"embedding": {provider,base_url,api_key,model,dimensions}, "sources": [...]}`.
Per source — required: `name`, `label`, `relation`, `dsn`. Optional: `enabled`
(default `true`; set `false` to disable a source without removing it),
`is_official`, `weight` (RRF boost), `dedup`, `solutions_expected`, `lang`,
`description`.
Full example: `knowledge_base.example.json`.
- `weight` boosts a source in cross-source RRF (`rrf = weight / (k + rank)`).
  **RRF scores are compressed** (rank-1 ≈ 0.0164, rank-10 ≈ 0.0143), so even a
  small weight has outsized effect: `1.1` lets a source's top results outrank
  another source's #1. Defaults: official docs `1.1`, tickets `1.0`, forum `0.95`.
  Tune to taste; `1.0` everywhere = neutral RRF.
- `dedup` collapses repost-prone titles within the source (forum), off for tickets.
- `solutions_expected` (default `false`) declares that **every** item in this source
  is a solved case, i.e. a ticket KB. It changes only how an empty `solution` is
  rendered: such a source shows "(resolvido, sem descricao da solucao)" — the fix
  was never written down — while documentation and forum sources show `—`, because
  for them having no solution field is normal, not a gap. Set it on ticket sources.

## What the search reads
The engine SELECTs `solution` alongside `body` in all three query shapes (keyword,
semantic, hybrid), truncated to `SOLUTION_SNIPPET` (640 chars) — just above the
formatter's display cap, so truncation happens once, where an ellipsis can mark it.
A source that has no resolution concept simply exposes `solution` as NULL.

