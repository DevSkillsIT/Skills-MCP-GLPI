# Changelog

All notable changes to **Skills MCP GLPI** are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.1.0] — 2026-04-23

Full CRUD validation round on the Skills instance (GLPI 11.0.6 / REST API v1) exposed 14 bugs across schema drift, formatter logic and authentication plumbing. This release fixes all of them and adds enrichment to `get_details` for computers.

### Added

- **`get_computer_details` enriched response** — returns the asset plus sub-items: operating systems, disks, processors, memories, network interfaces and installed software (capped at 25 entries). Each sub-query is wrapped so a partial failure does not abort the whole lookup.
  - `src/tools/assets.py::get_computer_details`
  - `src/formatters/glpi_formatters.py::format_computer_details_enriched`
- **`get_ticket_stats` real aggregation** — replaces the `TODO: implementar filtros` stub. Issues one `totalcount` query per status code (1..6) and returns `total_tickets`, `open_tickets`, `closed_tickets` plus the full `by_status` breakdown. Accepts `entity_id`, `date_from`, `date_to`.
  - `src/services/ticket_service.py::get_ticket_stats`
- **Admin `update` / `delete` for groups and locations** — the consolidated tool now delegates to `admin_service.update_group / delete_group / update_location / delete_location` instead of rejecting the action.
  - `src/tools/consolidated_admin.py::_manage_group`, `_manage_location`
  - `src/services/admin_service.py::update_location`, `delete_location` (new)
- **Knowledge article search** — `bridge_tools.search_knowledge` now queries `/search/KnowbaseItem` (fields 1=title, 4=answer) instead of returning an empty stub.
  - `src/tools/bridge_tools.py::search_knowledge`
- **MCP resources for dynamic data** — `glpi://entities` and `glpi://ticket-categories` fetch items through `glpi_client` (which handles auth via `SessionManager` context vars) instead of crashing with `'NoneType' object has no attribute 'get_items'`.
  - `src/resources.py::_fetch_items`
- **Prompts catalog wired** — `BridgeTools` is now constructed with `PROMPTS_CATALOG` and routes `glpi_get_prompt_template` through `prompt_handler.get_prompt` so the prompt bodies actually run. 15 prompts are exposed.
  - `src/tools/bridge_tools.py`
- **Localhost rate-limit bypass** — `127.0.0.1` / `::1` callers skip the per-minute quota, which unblocks parallel LLM requests from local MCP clients.
  - `src/auth/session_manager.py::_check_rate_limit`
- **Schema / implementation sync**:
  - `glpi_manage_ticket_operations` schema gained `threshold`, `max_results` (for `find_similar`) and `date_from`, `date_to` (for `get_stats`).
  - `glpi_manage_ticket_ai_analysis` schema gained `job_id` and `response`, so `get_result` and `publish` are actually callable through the MCP interface.
  - `glpi_manage_webhook_integrations` / `glpi_search_webhook_integrations` schema now declares `webhook_id` as **string** (GLPI 11 uses opaque hashes, e.g. `2b27acbaca81c9e9...`). `event_type` enum was corrected to dot notation (`ticket.created`, ...).
- **`CHANGELOG.md`** (this file).

### Changed

- **`find_similar` parameter contract** — the tool now requires `ticket_id` and accepts optional `threshold`/`max_results`. The unused `query` parameter advertised in the schema was removed (the code had been using `ticket_id` all along).
- **`close ticket` accepts `solution`** in addition to the legacy `resolution` parameter. Previously a call passing `solution` would fail with `"resolution is required"` because the schema exposes `solution` while the code only read `resolution`.
- **`format_operation_success` now distinguishes success from MCP error envelopes** — deletes that returned `isError=true` or `success=false` were being rendered as "Operacao … realizada com sucesso" even though nothing happened. The formatter now emits `Operacao … FALHOU: <reason>` when the call failed.
- **List formatters (`users`, `groups`, `entities`, `locations`)** now accept both the flat list shape (`[{...}]`) and the paginated wrapper shape (`{users: [...], pagination: {...}}`) produced by `admin_tools`.
- **`manage_admin entities get`** accepts `resource_id=0` via the new `validate_non_negative_int` helper (GLPI root entity is id 0).
- **`search_admin resource=users` with query** fans the search term across `name / firstname / realname / email` using **OR** instead of AND (see `admin.search_users::match_mode="any"`). Previously the AND intersection matched zero users.
- **`get_ticket_by_number`** tries a direct `/Ticket/{id}` lookup first for numeric inputs, then falls back to a name-contains search. Previously only the title search was attempted, so numeric IDs always missed.
- **`delete_group` defaults to `purge=true`** — GLPI's soft delete left groups visible via `get_group`, which silently invalidated previous acceptance tests.
- **`resources/read` JSON-RPC method** no longer passes a `session` argument to `read_resource` (delegated to `glpi_client` via context vars).

### Fixed

- Computer `get_details` was returning "Ativo: Sem nome" with every field empty. Root cause: `response_truncator.truncate_json_response` rewrote sub-dicts larger than 1 000 chars into `"<Object with N keys - truncated>"`, destroying the `{asset, disks, ...}` shape expected by the formatter. The truncate call was removed from `get_computer_details` (the response interceptor in `handlers.py` already truncates the final Markdown).
- `search_users` backend was working (`found N ativos`) but the MCP output rendered "Nenhum usuário encontrado" because `format_users_list` only read `data["data"]` / `data["items"]`, not `data["users"]`.
- `knowledge_articles` empty result rendered as "Nenhum ticket encontrado" (the old fallback was `format_tickets_list`). A dedicated `format_knowledge_articles` formatter now produces "Nenhum artigo encontrado na base de conhecimento".

### Compatibility

- Tested against **GLPI 11.0.6**. Earlier GLPI 10.x installs remain compatible (legacy API v1 / `apirest.php`).
- No breaking changes to the 14 tool names or high-level shapes.
- **Breaking for direct callers of `webhook_tools`**: `webhook_id` is now `Optional[str]` everywhere. Callers that typed it as `int` must switch to string.

### Security & Safety

- `MCP_SAFETY_GUARD` remains opt-in (`false` by default). When enabled it gates every destructive action on a `confirmationToken` and a `reason` ≥ 10 chars. No change to this behaviour — documented for clarity.

### Commits in this release

```
14f15b6  fix(glpi-mcp): infra fixes - validators, rate limit, legacy proxies
7b67807  fix(glpi-mcp): ticket operations - stats, get_by_number, schema sync
863dc08  fix(glpi-mcp): admin resources - users search and entity root id
93a681b  fix(glpi-mcp): bridge tools - resources, prompts catalog, knowledge search
0d46c0b  fix(glpi-mcp): CRUD behaviour - close ticket, AI trigger, success masking
3a6286a  fix(glpi-mcp): admin update/delete for groups and locations
200e149  fix(glpi-mcp): webhooks accept string IDs, event_type enum, schema cleanup
7f3cb8b  fix(glpi-mcp): do not run response_truncator on enriched computer details
```

---

## [2.0.0] — 2026-03

### Changed

- Consolidated **68 fragmented tools into 14** (`search_*` / `manage_*` pattern).
- Response format switched from raw JSON to compact Markdown (70-85 % token reduction).
- Default result limit lowered from 50 to 10 (max 50, previously 1 000).
- Added tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`).
- Added 4 MCP resources (`glpi://entities`, `glpi://ticket-status`, `glpi://ticket-categories`, `glpi://priorities`).
- Added 15 native MCP prompts (7 IT manager + 8 support analyst).
- Added server-side LLM instructions via the `initialize` handler.

### Added

- Multi-tenant authentication (`X-GLPI-User-Token` header per request).
- HTML stripping for GLPI TinyMCE fields.
- Internal field filter (`_links`, `completename`, etc.).
- Per-user rate limiting (composite key of URL + app_token + user_token + IP).
- Prometheus metrics endpoint (`/metrics`) when `prometheus_client` is installed.

---

## Known limitations

These are not bugs, but things to be aware of:

- **Webhooks layer is a mock** — `WebhookTools.webhooks_storage = {}` is an in-process dict that does not persist across restarts and does not integrate with GLPI 11's native `glpi_webhooks` table. A future release will rewrite the webhook service on top of `/apirest.php/Webhook`.
- **Safety Guard is disabled by default** — set `MCP_SAFETY_GUARD=true` and `MCP_SAFETY_TOKEN=<secret>` in the environment to require `confirmationToken`/`reason` on every delete.
- **Rate limit default is 60/min per user** (500/min in the Skills JSON config). Localhost is always exempted.
- **Entity id=0 backend behaviour** depends on the GLPI instance — some installs return 404 for `/apirest.php/Entity/0` even though `id=0` is the conventional root entity. The MCP validator accepts 0; the GLPI server is the source of truth.
