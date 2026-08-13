# Changelog

All notable changes to **Skills MCP GLPI** are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

Knowledge-base release: the ticket KB stopped answering with the *form* and started
answering with the *fix*.

The corpus that motivated it is form-driven. Every ticket opened through Formcreator
carried the same scaffolding, so the indexed text was mostly the form and not the
problem, and the ticket titles are the form names — **78 distinct titles across 2,532
tickets**, so a title identifies a form, not an issue. Two consequences followed, both
of the "plausible, well-formed, wrong" kind: resolved tickets never surfaced in a
cross-source search, and the ones that did surface were indistinguishable from each
other.

The other half of the release is what the search *returns*. A solved-ticket KB whose
results omit the resolution forces the caller to open every hit to learn what was
actually done, which is the whole question.

Measured on the reference corpus (2,532 tickets, 2,531 embedded):

| | Before | After |
|---|---|---|
| Indexed body carrying form boilerplate | 50.0% | 0% |
| Tickets with a usable resolution indexed | 66% | 91.4% |
| Queries returning a ticket in the top 5 of `source=all` | 0 of 14 | 14 of 14 |

### Added

- **`problem_solution` embedding strategy** (`KB_EMBED_STRATEGY` / `embed_strategy`).
  The vector covers problem **and** resolution, so a ticket is findable by the fix and
  not only by the symptom, while the displayed body stays the problem alone — otherwise
  every result row would print the resolution twice.
  - `knowledge_base/ticket_document.py::build_document`
- **`embed_text`**, separate from `body_text`: what gets vectorized may legitimately be
  more than what gets displayed. Transient — it is folded into `body_hash` and never
  stored as a column.
- **`description_labels`** — the form field holding the free-text problem, named
  differently per instance (`Descrição`, `Por favor, descreva o problema`, …).
- **`include_followups`** (default `true`) — folds technician follow-ups into the
  indexed resolution.
- **`redact_literals`** — exact secret values to strip from indexed text; see *Security*.
- **`solution` in the search contract queries.** All three SELECT shapes (keyword,
  semantic, hybrid) now return it, capped at `SOLUTION_SNIPPET = 640`.
  - `src/services/kb_search/hybrid_query.py`
- **`solutions_expected`** per registry source. Only sources where every item is a solved
  case say "(resolvido, sem descricao da solucao)" when the resolution is missing;
  documentation and forum sources show `—`, because for them an absent solution field is
  normal rather than a gap.
  - `src/services/kb_search/registry.py`, `::rrf.py`
- **`vector_store.has_embedding`** — lets the incremental gate tell "unchanged and
  indexed" from "unchanged but never embedded".
- **Templated systemd units** `glpi-kb-ingest@.service` / `glpi-kb-ingest@.timer`, one
  enabled instance per GLPI (`systemctl enable --now glpi-kb-ingest@<instance>.timer`).
  Daily at 05:00, `Persistent=true`, randomized delay, and a `flock` shared with the
  Sankhya ETLs that contend for the same embedding endpoint.
- **Two diagnostic log events**: `redact.harvested` (how many secret values were
  configured vs. discovered) and `normalize.repeated_resolution_text` (resolution lines
  repeating across ≥ 20 tickets — boilerplate the denylist does not know about yet).

### Changed

- **Form problem extraction rewritten.** It matched one literal label (`"Descrição :"`)
  and silently mis-extracted the rest of the corpus. Now: configured labels, then a
  regex family for per-instance wordings, then a structural fallback. A purely
  structured form — no free-text field at all — keeps **every** answer instead of
  promoting one, because there the answers are the content. The Formcreator header
  (`Dados do formulário<FormName>`) and up to three stacked greetings are removed, and
  an attachment field is never promoted (`Nenhum documento anexado` is long enough to
  win on length alone).
  - `knowledge_base/ticket_document.py::extract_problem`
- **Resolution assembled from follow-ups, not only formal solutions.** GLPI stores the
  fix in a follow-up on most tickets. Boilerplate is filtered **per line**, not per
  follow-up, so a genuine fix wrapped in a signature block survives while the signature
  does not. Length is deliberately not a filter: on this corpus `normalizado` (11 chars)
  *is* the resolution, while the single largest noise source was GLPI's own auto-generated
  `Solução aprovada`.
- **Weak-title detection is now about repetition, not length.** A title that repeats
  within one result set is non-distinguishing whatever its length; the old `< 14 chars`
  rule let a long generic form name through and returned N identical-looking rows. Weak
  titles are backed by a body snippet.
  - `src/services/kb_search/service.py::_display_title`
- **Display caps sized from the measured corpus, not guessed.** `_SOLUTION_MAX = 600`
  — on the reference corpus resolution length is p50=156, p75=378, p90=902, so 600
  returns **84.6%** of resolutions complete, where a 220-char cap would have truncated
  roughly a third of them and the resolution *is* the answer. `_TITLE_MAX = 160`, since
  the title cell now carries the distinguishing snippet. Truncation is marked with an
  ellipsis.
- **`body_hash` now covers `embed_text`** as well as body and solution. Changing
  `embed_strategy` alters only what is vectorized, so without this the gate reported
  "unchanged" and every vector stayed stale.
- **RRF weights of the ticket instances set to `1.0`** (neutral fusion).
- **Non-templated deploy units removed**, replaced by the templated pair above.

### Fixed

- **A row could stay permanently vectorless.** When the hash matched, the pipeline
  refreshed metadata and moved on — but a row indexed while `provider=none`, or after an
  embedding failure, carries no vector, and the hash never changes on its own. It stayed
  invisible to semantic search forever. The unchanged path now re-embeds rows whose
  `embedding IS NULL`.
  - `knowledge_base/ingest_tickets.py::_index_one`
- **The header dump logged at warning/error on every request**, including the token-less
  `initialize` handshake — 3,356 false `ERROR` lines in one log. It is a diagnostic, so
  it is now emitted at `DEBUG` and only when that level is enabled.
  - `src/main.py`

#### Audit of 2026-08-12 — seven ways a tool answered something that was not true

An external session asked for ticket 9449 with a token whose GLPI profile is
*Self-Service*. Every read came back `ERROR_RIGHT_MISSING`, which was correct. What the
caller reported was not: that the ticket did not exist, and that an AI analysis "was
triggered successfully". The token was the root cause; the audit that followed found
seven defects of one family — output a reader takes as fact when it is not.

- **`glpi_manage_ticket_ai_analysis` is no longer advertised.** `AIIntegrationService` is
  an in-memory job store that never calls GLPI, and `configure_agents()` has no caller,
  so `_agents_configured` is permanently `False`. In that state `action=trigger` answered
  *"analise disparada com sucesso"* for **any** `ticket_id` — verified live against
  ticket `99999999`, which does not exist — and `action=publish` answered *"realizada com
  sucesso"* without writing a byte to the ticket, after which `get_result` reported
  `status: completed` carrying the invented payload. The tool is now gated behind
  `ENABLE_AI_ANALYSIS` (default off) and the `initialize` instructions describe the tools
  actually registered instead of a fixed roster. Handler and service are untouched, so
  wiring a real agent is a one-flag change.
  - `src/handlers.py::_register_tools`, `src/config/settings.py`
- **`get_by_number` turned "no permission" into "not found".** Any non-404 from the direct
  id lookup was logged as a warning and fell through to the title search, which finds
  nothing — so a ticket that exists and is merely out of reach was reported as
  nonexistent. Only a genuine 404 falls through now; everything else is re-raised.
  - `src/services/ticket_service.py::get_ticket_by_number`
- **`glpi_search_records_by_criteria` returned raw search-option ids as column headers**
  — `| 2 | 1 | 12 | 19 | 4 |`, with `1` under status and `228` under requester. The
  catalogue that resolves field names on the way in now names them on the way out, and
  status / priority / urgency / impact / type are decoded for ITIL itemtypes
  (`expand_dropdowns` does not touch them: they are integers on the ticket's own table).
  - `src/tools/consolidated_search.py`
- **An id printed by one tool was rejected by the next.** The webhook listing prints
  `| ID | 4 |` while `webhook_id` was declared a string described as a *"hash
  alfanumerico"*, so `webhook_id=4` failed type validation and the caller concluded the
  webhook was gone. Unambiguous scalars are now coerced to the declared JSON type
  (int↔string, `"true"`→bool) before validation — which also absorbs the mirror-image
  slip, `ticket_id="9449"`. Genuinely ambiguous input still errors.
  - `src/handlers.py::_validate_arguments`
- **The user detail discarded three HTTP calls' worth of data.** `groups`, `profiles` and
  `entities` were fetched per user and the card printed only `| Grupos | 8 |` — a bare
  count that reads as "group 8" — while profiles and entities never appeared at all. All
  three are now resolved to names. Profile is the field that explains an
  `ERROR_RIGHT_MISSING`: paying for the call and dropping the answer left whoever
  diagnoses without the one thing that matters.
  - `src/services/admin_service.py::get_user`, `src/formatters/glpi_formatters.py`
- **The history was the last place still printing GLPI codes.** `Status | 1 | 2` instead
  of `Novo → Atribuido`, `0 → 11580` seconds instead of `0 → 3h 13min`, and `—` in the
  field column for link events, which makes the history look corrupt. Entries with no
  `id_search_option` are labelled from `itemtype_link` (namespace stripped, the `"0"`
  placeholder ignored).
  - `src/formatters/glpi_formatters.py::format_ticket_history`
- **Ticket hits in the unified KB carried a root-relative URL** (`/front/ticket.form.php?id=…`)
  while help and community hits carried absolute ones, so half the table was not
  clickable anywhere. Prefixed at render time rather than in the ETL, which also repairs
  everything already indexed.
  - `src/services/kb_search/service.py`
- **Filtering tickets by a person's name returned nothing.** `requester="Azeredo Da Silva
  Guimaraes Erica"` — the name exactly as the listing prints it — matched zero tickets and
  said so without an error. GLPI keeps a person in three columns (`name` = login,
  `firstname`, `realname`) and the Search API compares one of them at a time, so the
  displayed full name exists in none of them: `realname` holds "Azeredo Da Silva
  Guimaraes" and `firstname` holds "Erica". `requester` and `assigned_tech` now resolve
  through `/User` — tokenised, surname prepositions dropped, probed across all three
  columns, candidates ranked by how many tokens they cover — and filter by user id. Any
  fragment works (`guimar`, `Erica`, the login, the full displayed name); several matches
  become an OR group, because ambiguity in a *filter* should widen the result, not refuse
  the question.
  - `src/services/ticket_service.py::_find_users_by_any_name_part`, `::_person_criterion`

### Fixed — the sanitiser was corrupting the text it was meant to protect

- **`&quot;` in the ticket, for the customer to read.** `sanitize_string` ran `html.escape`
  on everything before sending it to GLPI, and GLPI escaped it again on save. A note
  saying `"cópia de 3"` was **stored and displayed** as `&quot;cópia de 3&quot;`. Escaping
  is the responsibility of whoever *renders*, never of whoever *writes* — doing it here
  guaranteed the double escape, and no prompt instruction could fix it because the damage
  happened after the model. `html.escape` is gone; quotes, `&` and accents now reach GLPI
  exactly as written. What leaves the sanitiser is the content, not its HTML
  representation.
- **Rich text stopped being flattened.** Every tag was stripped from every field, so
  `<p>` and `<strong>` — the format GLPI's own editor writes — vanished, while Markdown
  (`**negrito**`) survived only to render literally, because GLPI is not Markdown-aware.
  The GLPI rich-text fields (`description`, followup/task `content`, `solution`,
  `comment`) now accept HTML; scalar fields (name, status, asset type, URL) still drop
  tags, where a tag is only noise. The parameter descriptions say which is which, so the
  model stops reaching for Markdown.
- **Executable constructs are still removed, in rich text too**: `<script>`, `<style>`,
  `<iframe>`, `<object>`, `<embed>`, `<form>`, `on*=` handlers, and `javascript:` /
  `vbscript:` / `data:` URLs. A dangerous URL is **neutralised to `href="#"` rather than
  deleted** — removing the whole attribute left `<a ">` sitting in the middle of the note.
- **A note longer than 10,000 characters was silently cut.** That limit applied to a
  ticket description the same as to a status string, so a technical report or a pasted log
  lost its tail with a bare `... [truncated]` that never said how much was gone. Rich text
  now allows 200,000 characters (GLPI stores `content` as LONGTEXT), scalar fields keep
  10,000, and a cut states the count of discarded characters and is logged.
- **A quoted search query searched for the word `quot`.** `sanitize_search_query` escaped
  first and then filtered the string character by character against an allowlist: `&` and
  `;` were dropped from `&quot;` and the letters `q`,`u`,`o`,`t` stayed. Searching
  `"impressora HP"` searched `quot impressora HP quot`.
  - `src/utils/helpers.py::InputSanitizer`, plus `allow_html=True` at the rich-text call
    sites in `src/tools/{consolidated_tickets,tickets,consolidated_itil,assets,admin}.py`

### Changed — computer listing answers the hardware question

- **`glpi_search_asset_inventory` returns the basic hardware inline** for computers: type
  (Notebook/Desktop), CPU, RAM with module speed (`16 GB DDR4-2666`), disk (total, SSD or
  HDD, drive count) and usage of the main volume (`38% de 951.7 GB`). "List this person's
  computers" is always followed by "how much RAM, what disk, is it a laptop", and that
  needed a second tool per asset. All of it lives in columns of `Computer` itself, so it
  rides along in the listing request at **zero extra calls**. The drive kind is inferred
  from the drive MODEL, not from GLPI's "Disco rígido: Tipo", which collapses to one value
  and reports "HDD" for an HDD+SSD pair.
- **The listing stopped paying for data it threw away.** `list_assets` fired five requests
  *per computer* to build `cpu_info`/`memory_info`/`anydesk_id`, and the table printed none
  of them — while the tool description promised them and told the model not to call
  `get_computer_details`. CPU and memory now come from the search itself (two fewer calls
  per computer), and what is fetched is rendered.
- **The enrichment ran twice on every small listing.** It was invoked inside the pagination
  block and again on the common exit; when `totalcount <= limit` — the normal case — the
  first pass did not return early, so every computer was enriched twice, in silence.

### Fixed — asset listing (found while adding the hardware columns)

- **A listing with more results than the page size rendered as "Nenhum ativo
  encontrado".** `list_assets` returns a plain list when everything fits and
  `{"assets": [...], "pagination": {...}}` when it does not; the formatter only knew
  `data`/`items`. So the big inventories — the ones worth listing — reported an empty
  inventory. It now reads `assets` and takes the total from `pagination.total`, so the
  header says `Pagina 1/30 (total: 119)` instead of announcing a page as the whole.
  - `src/formatters/glpi_formatters.py::format_assets_list`

### Security

- **Credentials pasted into tickets are redacted before indexing.** A KB makes ticket
  text semantically discoverable, which raises the cost of leaving a password in it, so
  the secret never reaches the vector, the FTS index or a rendered result. Redaction is
  applied at the single point where raw GLPI text enters the document, which also covers
  `metadata` — it keeps follow-ups and solutions verbatim and had been leaking every
  individual password even when body and solution were clean.

  Four mechanisms, because no single one is enough:
  1. **Labelled** — `Senha: X`, `password=X`. Same-line only; crossing a newline
     swallowed the next line's first word.
  2. **Proximity** — anchored on the *value* looking like a credential (≥ 6 chars with a
     letter and a digit) inside a short window after the label, because real tickets
     write it as prose. Rule 1 alone left 65 in the index. Prose such as
     "a senha do usuário expirou" is untouched, since no nearby token has a digit.
  3. **Known literals** (`redact_literals`) — a shared password often sits on a line of
     its own with no label anywhere near it. Only knowing the value catches that.
     Replacement is word-bounded, so a literal embedded in a longer word or number is
     not silently corrupted.
  4. **Standalone line** — handover blocks put the password two lines from any label.
     Requires a symbol and forbids a dot, which keeps hostnames, versions, IPs and
     e-mails out.

  **Corpus harvesting**: the same password appears labelled in one ticket and bare in
  another, and a per-ticket view cannot see that. `harvest_secrets` collects credential
  values across the whole extraction *before* any document is built, and applies the
  union as literals — the corpus becomes its own denylist. Harvesting runs before any
  `--limit` slice, so a partial run redacts identically to a full one.

  A harvested value is applied to **every** ticket, so a false positive erases a word
  corpus-wide: `Senha - Padrão` once promoted `Padrão` to a global literal and mutilated
  61 tickets. Only values that look like a credential on their own may travel (letters
  **and** digits, not money, no `XXXX`-style placeholder runs); values failing that gate
  are still redacted where they were actually seen.

### Tests

- 475 unit tests pass (`pytest tests/unit/`).
- `tests/test_audit_2026_08_regression.py` — 52 tests pinning each finding of the
  2026-08-12 audit, including the two that only fail against the old code by *not*
  raising: a 403 from the id lookup must reach the caller, and it must not be followed by
  a second lookup. Both sides of `ENABLE_AI_ANALYSIS` are covered — a gate that hides but
  cannot reappear is a removal in disguise, and it would only surface the day a real AI
  agent exists.
- Full suite: 1,478 passed, 12 skipped.

---

## [2.2.0] — 2026-08-10

Capability, correctness and resilience release. Three themes: reaching the ITIL records
that live beyond the ticket, search tools that can answer the questions an MSP actually
asks, and a request layer that survives an unhealthy GLPI. Much of it came out of a
comparative audit against the actively maintained GLPI MCP servers on GitHub, and out of
a smoke run against a live instance.

The consolidated catalogue grew from 15 to 18 tools. Adding a tool is not free — every
one costs context on every conversation — so the three additions each cover a domain the
existing tools could not reach at all, rather than splitting work they already did.

Most of the defects below share a shape worth naming: **they produced a plausible,
well-formed, wrong answer, with no error**. A filter that is silently discarded does not
look like a bug; it looks like a smaller result set. That is what makes them expensive.

### Added

#### New tools

- **`glpi_search_itil_records`** — problems, changes, projects, contracts and suppliers,
  selected by `record_type`. Filters: `query`, `status`, `priority`, `urgency`,
  `category`, entity, `date_from`/`date_to` with a selectable `date_field`, `sort_by`,
  `order`, `limit`, `offset`, and `count_only` for a cheap total that never fetches rows.
  - `src/tools/consolidated_itil.py`, `src/services/itil_service.py`
- **`glpi_manage_itil_records`** — `get`, `create`, `update`, `delete`, `add_followup`,
  `get_followups` and `link_ticket` over the same five record types.
  - `src/tools/consolidated_itil.py::manage_itil_records`
- **`glpi_search_records_by_criteria`** — free-criteria query over any itemtype, for the
  questions the specific tools do not cover. Three scopes: `search` (rows), `count` (only
  the total — a cheap probe before deciding to paginate) and `fields` (which fields this
  instance actually exposes). Fields are given **by name**, not by id.
  - `src/tools/consolidated_search.py`

#### New ticket actions

Nine additions to `glpi_manage_ticket_operations`, all in `src/tools/consolidated_tickets.py`:

- `get_timeline` — followups, tasks, solutions and approvals interleaved chronologically.
  Reconstructing this took four separate calls and a manual merge.
- `add_task` / `get_tasks` — tasks with a planned duration (`actiontime`, in seconds).
- `request_validation` / `answer_validation` / `get_validations` — the approval workflow.
  Refusing an approval requires a comment.
- `assign_group` — assign to a **group**, with a configurable role (`assigned`,
  `requester`, `observer`). Only technician assignment existed before.
- `link_tickets` — relate, duplicate or parent/child two tickets.
- `add_document` — attach a file, by server path or base64.

`approver` and `group` accept a name or an id; an ambiguous name is refused with the
candidate list rather than resolved by guessing.

#### New filters and sorting

- **Ticket filters**: `assigned_tech`, `assigned_group`, `requester` and `category` — each
  accepting a **name** (partial match) or a numeric id — plus `urgency` (a distinct axis
  from priority in GLPI) and `open_only`.
  - `src/services/ticket_service.py::_actor_criterion`
- **Caller-controlled sorting** (`sort_by`, `order`) on tickets, assets and admin
  resources. Field names resolve through the central maps; an unknown name falls back to
  the previous default instead of failing the query — sorting is a presentation
  preference, and refusing the whole query over it trades a small annoyance for no result.
  - `src/utils/search_criteria.py::resolve_sort_field`, `::normalize_order`
- **Asset filters**: `assigned_user` (name or id), `status`, `location_id` and
  `manufacturer_id`.
- **Group column** in the ticket list. The group is filterable now, so the table has to
  show it — and actor names are resolved for it, instead of returning a raw id.
  - `src/formatters/glpi_formatters.py::format_tickets_list`

#### Infrastructure

- **Search option catalogue** — `/listSearchOptions/{itemtype}` cached per itemtype (1 h),
  with name-to-id resolution in cascade (explicit uid, canonical own-table uid, translated
  label, raw column). Own-table entries win collisions, so filtering a ticket by `name`
  reaches the title and not the requester's name.
  - `src/services/search_options.py`
- **Field map reconciliation** — the static field maps are checked against the live
  catalogue once per process. Columns on the item's own table are corrected when they
  drift; columns reached through joins are only checked for existence, because there is no
  locale-independent way to re-derive them and replacing a working id with a guess would
  be worse than the drift. Never blocks a search: on any failure the static map is kept.
  - `src/services/search_options.py::reconcile`
- **Shared criteria helpers** — one place for the name-or-id contract and for sorting, so
  the tools cannot drift apart on it.
  - `src/utils/search_criteria.py::as_field_id`, `::actor_criterion`
- **Nested criteria groups.** GLPI evaluates a flat criteria list left to right with no
  precedence between AND and OR, so `text OR text AND filter` did not narrow the result —
  it widened it, because the trailing AND bound only to the last OR term. A criterion
  carrying its own `criteria` list is emitted as a group, and the group as a whole is
  joined by its `link`.
  - `src/services/glpi_client.py::_emit_criteria`
- **Resilient request path** — a single point every GLPI call passes through:
  - request timeout, retry with exponential backoff and full jitter (so concurrent callers
    recovering from one outage do not resynchronise into a thundering herd);
  - `429` honouring `Retry-After` when the server sends a delay;
  - re-authentication on `401`, centralised (it was duplicated across the four verbs);
  - **writes are never replayed once the server has answered** — GLPI may have applied the
    write before failing, so a retry would create a second ticket or a duplicate followup.
    Only failures that provably happened before the request left the client (connection
    refused, connect timeout) and explicit throttling (`429`, where the server refused
    without processing) are repeated. Read/write timeouts and `5xx` are retried for `GET`
    only.
  - `src/auth/session_manager.py::_request`
  - New settings: `GLPI_MAX_RETRIES` (default 2), `GLPI_RETRY_BACKOFF_BASE` (1.5),
    `GLPI_RETRY_BACKOFF_CAP` (20.0).
- **Idempotency and write policy**, wired at the dispatch point rather than left as
  libraries the tools could forget to call:
  - Repeating an identical create does not create it twice. The key is the call payload
    itself; the replay returns the first result flagged `replayed: true` without touching
    GLPI. Covers `create`, `add_followup`, `add_task`, `add_document`, `link_tickets`,
    `request_validation`, `create_reservation`. Backed by persistent SQLite (surviving
    restarts and shared across workers) or memory. A store failure never blocks the
    operation — it runs, and the degraded mode is logged.
  - A global read-only switch (`GLPI_READ_ONLY`) and one variable per write operation
    (`GLPI_ALLOW_<OPERATION>`). Non-destructive operations default to enabled; every
    delete operation defaults to disabled. A blocked write returns an error naming the
    variable to set, never a silent success. Reads are never affected.
  - The gate covers every tool annotated as destructive — tickets, assets, admin,
    webhooks and ITIL. ITIL writes were initially left out of the dispatch map, so
    creating a problem or a contract escaped both the read-only mode and the replay
    protection; a test now asserts the map against the live tool catalogue so a tool
    added later cannot ship ungated. ITIL deletion is gated per record type.
  - The five ITIL delete operations were being registered with the confirmation guard
    at call time and unregistered afterwards, a transitional arrangement from when two
    workstreams shared the file. They are permanent registry entries now: a destructive
    operation must not depend on someone remembering to register it.
  - `src/security/idempotency.py`, `src/security/write_policy.py`
  - `src/handlers.py::handle_call_tool`, `::_resolve_write_operation`, `::_execute_guarded`
- **`scripts/smoke_live.sh`** — a smoke test against a real instance. The unit suite mocks
  GLPI's responses, so it cannot observe GLPI's own semantics; two of the defects below
  were visible only here. The token comes from the environment and must never be written
  into the script or the server's `.env`, where it would become a fallback and let the
  server accept unauthenticated calls under that identity.

### Fixed

Every item below returned a plausible answer and no error.

- **Text search silently dropped every other filter.** `search_tickets` accepted `status`,
  `priority` and the date range, validated them, and then built its criteria from the query
  and the entity alone. Asking for open tickets mentioning a keyword returned tickets in
  any status, with a well-formed answer and no warning. Listing and text search now build
  criteria through one shared function, so the two paths cannot diverge again.
  - `src/services/ticket_service.py::_build_ticket_criteria`
  - `src/tools/consolidated_tickets.py::search_tickets`
- **Same defect in the asset search.** A text query discarded manufacturer, location and
  status. The text terms now go as a *nested* group, so a filter added after them narrows
  the result instead of being absorbed into the OR chain.
  - `src/services/asset_service.py::search_assets`
- **The entity filter on groups and locations never worked.** Both listed through
  `/apirest.php/Group` and `/apirest.php/Location` — the `getAllItems` endpoint, which
  ignores `criteria[]` silently. Asking for one client's groups returned every client's
  groups. Confirmed live: filtering by entity 4 returned entity 1's groups. On a
  multi-tenant server this is cross-tenant exposure, not a loose filter. With a filter
  present, the lookup now goes through the Search API.
  - `src/services/admin_service.py::list_groups`, `::list_locations`
- **User search leaked across tenants.** The name terms were joined with OR and the entity
  with AND, ungrouped — so left-to-right evaluation applied the entity to the *last* term
  only. A search restricted to one client returned users from others. The text terms are
  now grouped, and the entity is applied to the group.
  - `src/tools/admin.py::search_users`
- **The root entity (id 0) was discarded for being falsy in Python.** A truthiness test
  cannot distinguish "no entity given" from "entity zero", and GLPI's root entity is 0.
  - `src/tools/admin.py`
- **`open_only` used an ordering operator on status.** Measured live, GLPI's operator
  behaves as equality here, so the filter returned 3 open tickets where there were 7 —
  hiding exactly the assigned ones. It now enumerates the open status codes as a nested
  OR group.
  - `src/services/ticket_service.py` (`_OPEN_STATUS_CODES`)
- **Text search covered only the title, while promising content.** Searching for an error
  message returned "none found" — presented as a fact about the instance rather than a
  limit of the query. It now searches title and content.
  - `src/services/ticket_service.py`
- **Read cache was global and the session swallowed authentication failures.** Resolving
  the session is what validates the caller's token; the cache key did not include the
  caller. An invalid token could be served data another user had already loaded. The
  session now fails instead of degrading, and the cache key carries the identity.
  - `src/auth/session_manager.py::_ensure_session`
- **User search requested one set of columns and read another**, so the location column
  rendered the "active" flag. Both sides now read the same field map.
  - `src/tools/admin.py::search_users`
- **Field discovery let the last repeated label overwrite the earlier ones**, advertising
  an id the search would not use. GLPI labels are not unique across joined tables — the
  item's own column now keeps the plain label and homonyms are qualified by their source
  table.
  - `src/services/search_options.py::available_fields`, `::_qualified_label`
- **Pagination claimed "showing all" without knowing the total.** A full page means the
  total is unknown and more probably exist; 3 of 9,270 tickets were announced as the
  complete list. Without a total, the header now states the uncertainty.
  - `src/formatters/markdown_helpers.py::page_info`
- **A truncated asset list rendered a ghost row and an inflated count.** The truncator
  appends a marker item, which the formatter drew as an asset (`N/A | — | —`) and counted:
  119 computers appeared as "6 resultados | Mostrando todos", and the warning the marker
  carried was dropped exactly when it mattered. Markers are now extracted, and a truncated
  list says so in the header rather than in a note the model can skip.
  - `src/formatters/glpi_formatters.py::format_assets_list`
- **`location_id` on create and `category_id` on update were accepted and never written.**
  "Open a ticket in room 12" produced a ticket with no location and reported success.
  Optional fields are now only sent when supplied, and a field that cannot be applied is
  refused instead of dropped.
  - `src/services/ticket_service.py::create_ticket`, `::update_ticket`
- **`solution` on update moved the ticket to solved with no solution recorded.** In GLPI a
  solution is its own record (`ITILSolution`), not a ticket column, so it could never be
  written this way. The parameter is now refused with a message pointing at `resolve` or
  `close`.
  - `src/services/ticket_service.py::update_ticket`
- **Group and location deletion bypassed the confirmation guard**, unlike every other
  destructive action. Both now go through it.
  - `src/tools/consolidated_admin.py`

### Changed

- Field ids are no longer written as bare numbers in ticket criteria, statistics or
  reports — all of them go through the central maps that reconciliation keeps aligned.
- Webhooks are persisted through the **native GLPI 11 backend** (`/apirest.php/Webhook`)
  instead of process memory, so they survive a restart and are visible in GLPI's own UI.
  Where the endpoint is unavailable, the tool warns explicitly rather than creating a
  phantom record.
  - `src/tools/webhooks.py`
- All 15 prompt descriptions were rewritten (see Tests, below).
- `GLPIClient._handle_response` removed. It carried a full HTTP status mapping, including
  rate limiting, and was never called — reading it suggested behaviour that did not exist.

### Tests

- **1,333 passing, 12 skipped** (was 572 passing with 5 failing at the start of this
  release; 694 at the mid-point).
- The 5 pre-existing failures were diagnosed individually rather than muted: three tests
  described contracts that had deliberately changed, one mocked a method the code no
  longer calls (so the call escaped to the network), and one fed the formatter raw data,
  measuring a table of dashes against a full JSON payload.
- **New contract test on description quality.** Tool and prompt descriptions are not
  documentation — they are the retrieval surface. Hubs that federate several MCP servers
  index them and pick a tool by semantic similarity against the user's phrasing, so a thin
  description makes a working tool unreachable: it simply never gets chosen. The test
  fails descriptions that are too short to carry context plus synonyms, or that open with
  a generic verb (embedding models weight the leading tokens, so the domain noun has to
  come first). All 15 prompt descriptions were rewritten to pass it.
  - `tests/contract/test_description_quality.py`
- Lint errors down from 85 to 8.

### Compatibility

- No breaking changes. Every v2.1 call keeps working; the new parameters are optional and
  omitting them preserves the previous behaviour.
- Two behavioural corrections change results for the better and are worth knowing before
  upgrading: text search now respects the other filters (fewer, correct rows), and `query`
  now matches content as well as the title (more rows, and no more false "none found").

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
