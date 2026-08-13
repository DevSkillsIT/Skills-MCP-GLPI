<div align="center">

# 🚀 Skills MCP GLPI v2.2

### 18 Production-Grade Tools with 70-85% Token Efficiency and Enterprise-Grade Safety

[![MCP Protocol](https://img.shields.io/badge/MCP-2024--11--05-blue)](https://modelcontextprotocol.io/)
[![Python](https://img.shields.io/badge/Python-3.11+-green)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-teal)](https://fastapi.tiangolo.com/)
[![Pydantic](https://img.shields.io/badge/Pydantic-v2-purple)](https://docs.pydantic.dev/)
[![Transport](https://img.shields.io/badge/Transport-Streamable%20HTTP-orange)](https://modelcontextprotocol.io/docs/concepts/transports)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Production%20Ready-brightgreen)](https://github.com/DevSkillsIT/mcp-glpi)

**Connect Claude Code, Gemini CLI, ChatGPT, VS Code Copilot, and Cursor to your GLPI instance**

[Why v2.0](#-why-v20) • [18 Tools](#-18-tools) • [Quick Start](#-quick-start) • [Resources](#-mcp-resources) • [Support](#-support)

</div>

---

## 📖 About The Project

**Skills MCP GLPI v2.2** is a production-ready Model Context Protocol (MCP) server for GLPI (IT Service Management) with a revolutionary token-optimization architecture. Built by **Skills IT**, this MCP consolidates 68 specialized tools into 18 enterprise-grade tools with Markdown responses, tool annotations, and MCP resources.

Compatible with **GLPI 10.x** (legacy API v1) and **GLPI 11.x** (current stable).

**What's new in 2.2** (August 2026):

- **ITIL beyond the ticket** — problems, changes, projects, contracts and suppliers are now first-class, through `glpi_search_itil_records` and `glpi_manage_itil_records`.
- **Free-criteria search** — `glpi_search_records_by_criteria` queries any itemtype, counts without paginating, and discovers which fields your instance actually exposes.
- **Filters people actually ask for** — assigned technician, assigned group, requester and category, each accepting a **name** instead of forcing an id lookup first; plus urgency as its own axis, `open_only`, and caller-controlled sorting.
- **9 new ITIL actions on tickets** — unified timeline, tasks, approvals, group assignment, ticket linking and file attachments.
- **Correctness fixes for answers that looked right and were not** — text search silently discarding the other filters, entity filters that never applied, and pagination reporting totals it never had. See [CHANGELOG.md](./CHANGELOG.md).

### 🌟 Why v2.0?

The v1.0 approach (68 tools, raw JSON responses) caused **token explosion** — typical GLPI queries consumed 50-100K tokens with limited reusability. v2.0 fixes this with a consolidated, Markdown-first design:

| Aspect | v1.0 | v2.2 |
|--------|------|------|
| **Tools** | 68 fragmented | **18 consolidated** ✨ |
| **Response Format** | Raw JSON (verbose) | **Markdown (compact)** ✨ |
| **Token Efficiency** | ~100K per operation | **15-30K per operation** ✨ |
| **Tool Annotations** | None | **Read-only & destructive hints** ✨ |
| **MCP Resources** | 0 | **4 static resources** ✨ |
| **MCP Prompts** | 15 templates | **15 professional prompts** ✨ |
| **Response Limits** | default=50, max=1000 | **default=10, max=50** ✨ |
| **Estimated Savings** | — | **70-85% token reduction** ✨ |

---

## 🎯 Key Improvements

### 1. **Consolidated Toolkit**
- **18 production tools** organized by domain (Tickets, ITIL, Assets, Admin, Webhooks, Knowledge, Bridge)
- **search_* + manage_*** pattern: Clear separation of read-only vs mutation operations
- Each tool handles 4-8 related operations, reducing context overhead

### 2. **Token Efficiency (70-85% Reduction)**
Markdown-formatted responses instead of JSON reduce token consumption dramatically:
- **Before:** `{"user":{"id":1,"name":"John","email":"john@example.com","created":"2025-01-22T10:30:00Z"}}`
- **After:** `👤 **John** (john@example.com) — Created Jan 22, 2025`

### 3. **Enterprise Safety**
- Tool annotations for LLM safety (readOnlyHint, destructiveHint)
- Aggressive rate limits (default=10, max=50 per request)
- HTML stripping from GLPI TinyMCE fields
- Automatic internal field filtering
- **Idempotent creates** — repeating the same create does not create it twice
- **Per-operation write policy** plus a global read-only switch

### 4. **MCP Resources & Prompts**
- **4 MCP Resources:** Entity list, ticket statuses, categories, priorities
- **15 MCP Prompts:** 7 for IT managers, 8 for support analysts
- Enables advanced workflows without heavy tool definitions

### 5. **Server-Side LLM Instructions**
LLM receives usage guide automatically on initialization, ensuring optimal tool usage patterns.

### 6. **Resilient Request Path**
Every GLPI call goes through one point that applies timeout, retry with exponential
backoff and jitter, honours `Retry-After` on `429`, and re-authenticates on `401`.

> **Writes are never replayed once the server has answered.** GLPI may have applied the
> write before failing, so a retry would create a second ticket or a duplicate
> followup. Only failures that provably happened *before* the request left the client
> (connection refused, connect timeout) and explicit throttling (`429`, where the
> server refused without processing) are repeated.

### 7. **Instance-Aware Field Resolution**
Field names are resolved against your instance's own search-option catalogue and
cached, so the same parameter works across installs that number fields differently.
Static field maps are reconciled with the live catalogue at startup, and never block a
search if the catalogue is unavailable.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│         Claude / ChatGPT / Gemini / Copilot / Cursor            │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ MCP Protocol (HTTP JSON-RPC)
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Skills MCP GLPI v2.0 Server                   │
│                         localhost:8824                           │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    FastAPI + Formatters                    │ │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐   │ │
│  │  │   18 Tools   │ │ 4 Resources  │ │  15 Prompts     │   │ │
│  │  │ (Markdown)   │ │ (Static URIs)│ │ (Parameterized) │   │ │
│  │  └──────────────┘ └──────────────┘ └──────────────────┘   │ │
│  │  ┌───────────────┬──────────────┬──────────────────────┐   │ │
│  │  │ HTML Stripper │ Field Filter │ Rate Limiter (10/50)│   │ │
│  │  ├───────────────┴──────────────┴──────────────────────┤   │ │
│  │  │ Write Policy · Idempotency · Retry (writes-safe)    │   │ │
│  │  └─────────────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ GLPI REST API v1
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                         GLPI Server                              │
│                   https://your-glpi-server.com                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11 or higher
- GLPI 10.x or 11.x with REST API enabled
- GLPI App Token and User Token (Personal Access Token)

### Installation

```bash
# Clone the repository
git clone https://github.com/DevSkillsIT/mcp-glpi.git
cd mcp-glpi

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### GLPI Configuration

1. **Enable REST API:** Setup > General > API — Check "Enable REST API"
2. **Create App Token:** Setup > General > API > API Clients — Add and copy token
3. **Get User Token:** Administration > Users > your user > Remote access keys — Generate token

### Environment Setup

```bash
cp .env.example .env
nano .env
```

```bash
# .env
GLPI_BASE_URL=https://your-glpi-server.com
GLPI_APP_TOKEN=your_app_token_here
MCP_PORT=8824
MCP_HOST=0.0.0.0
MCP_SAFETY_GUARD=true
MCP_SAFETY_TOKEN=secure_token_min_8_chars
RATE_LIMIT_REQUESTS_PER_MINUTE=500
LOG_LEVEL=INFO
```

### Start the Server

```bash
# Development
python -m uvicorn src.main:app --host 0.0.0.0 --port 8824 --reload

# Production (with PM2)
pm2 start ecosystem.config.cjs
```

### Connect to Claude Code

Edit `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "glpi": {
      "type": "streamable-http",
      "url": "http://localhost:8824/mcp",
      "headers": {
        "X-GLPI-User-Token": "your_user_token_here"
      }
    }
  }
}
```

### Test Connection

```bash
curl http://localhost:8824/health
```

---

## 🧰 18 Tools

### 🎫 Tickets (3 tools)

| Tool | Description |
|------|-------------|
| `glpi_search_helpdesk_tickets` | Search tickets/incidents/requests. Filters: status, priority, **urgency**, **assigned_tech**, **assigned_group**, **requester**, **category** (each by **name** or id), **open_only**, date range, **sort_by/order** |
| `glpi_manage_ticket_operations` | 22 actions — get/get_by_number/create/update/delete/assign/**assign_group**/close/resolve/add_followup/**add_task**/**add_document**/**link_tickets**/**request_validation**/**answer_validation**/**get_timeline**/**get_tasks**/**get_validations**/get_followups/get_history/get_stats/find_similar |
| `glpi_manage_ticket_ai_analysis` | AI analysis: trigger/get_result/publish. **Off by default** — the service behind it is an in-memory stub with no GLPI-side agent, so it would report success without doing anything. Enable with `ENABLE_AI_ANALYSIS=true` once a real agent is wired in. |

### 🧩 ITIL (2 tools) — *new in 2.2*

| Tool | Description |
|------|-------------|
| `glpi_search_itil_records` | Search **problems, changes, projects, contracts and suppliers** (`record_type`). Filters: query, status, priority, urgency, category, entity, date range + `date_field`, sort, and **`count_only`** for a cheap total |
| `glpi_manage_itil_records` | CRUD + `add_followup`/`get_followups`/`link_ticket` across the same five record types |

### 🔍 Free-Criteria Search (1 tool) — *new in 2.2*

| Tool | Description |
|------|-------------|
| `glpi_search_records_by_criteria` | Query **any itemtype** with combined AND/OR criteria. `scope=search` returns rows, `scope=count` returns only the total (cheap probe), `scope=fields` discovers the filterable fields. Fields are given **by name**, not by id |

### 💻 Assets (2 tools)

| Tool | Description |
|------|-------------|
| `glpi_search_asset_inventory` | Search computers/monitors/software/devices/reservations. Filters: **assigned_user** (name or id), **status**, **location_id**, **manufacturer_id**, plus **sort_by/order** |
| `glpi_manage_asset_operations` | CRUD + reservations: get/get_details (enriched with OS/disks/CPU/mem/net/software)/create/update/delete/get_reservations/create_reservation |

### 👥 Admin (2 tools)

| Tool | Description |
|------|-------------|
| `glpi_search_admin_resources` | Search users/groups/entities/locations by name and entity, with **sort_by/order** |
| `glpi_manage_admin_resources` | CRUD: get/create/update/delete for users, groups, entities, locations |

### 🔗 Webhooks (2 tools)

| Tool | Description |
|------|-------------|
| `glpi_search_webhook_integrations` | List/filter webhooks, delivery history, statistics |
| `glpi_manage_webhook_integrations` | CRUD + control: get/create/update/delete/test/trigger/enable/disable/retry |

### 📚 Knowledge (2 tools)

| Tool | Description |
|------|-------------|
| `glpi_search_knowledge_articles` | Search the native GLPI knowledge base via REST |
| `glpi_search_knowledge_unified` | Semantic (pgvector) + full-text search across resolved tickets, help articles and community posts, merged with RRF ranking. Each hit carries **the resolution that was applied**, so the caller does not have to open every result to learn what was done |

### 🌉 Bridge (4 tools)

| Tool | Description |
|------|-------------|
| `glpi_list_available_resources` | List 4 MCP resources with URIs |
| `glpi_read_resource_by_uri` | Read resource content (entities, statuses, categories, priorities) |
| `glpi_list_available_prompts` | List 15 professional MCP prompts |
| `glpi_get_prompt_template` | Execute specific prompt with arguments |

---

## ✨ What the New Capabilities Look Like

**The whole ticket history in one call** — followups, tasks, solutions and approvals
interleaved chronologically, instead of four separate lookups:

```json
{ "action": "get_timeline", "ticket_id": 542, "limit": 100 }
```

**Assign to a group, by name** — no id lookup, and an ambiguous name is refused with
the candidate list rather than guessed:

```json
{ "action": "assign_group", "ticket_id": 542, "group": "Infrastructure" }
```

**Ask the questions people actually ask** — filters take names, and text search
combines with the other filters instead of replacing them:

```json
{ "assigned_tech": "John", "open_only": true }
{ "query": "printer", "open_only": true, "urgency": 4 }
{ "sort_by": "date", "order": "asc" }
```

**ITIL records beyond the ticket** — contracts expiring soonest first:

```json
{ "record_type": "contracts", "sort_by": "end_date", "order": "asc" }
```

**Count without paginating** — a cheap probe before deciding to fetch rows:

```json
{ "record_type": "suppliers", "count_only": true }
{ "itemtype": "Computer", "scope": "count" }
```

**Discover the fields your instance exposes** — repeated labels are disambiguated by
their source table, so the advertised id is the one the search will use:

```json
{ "itemtype": "Ticket", "scope": "fields", "field_filter": "date" }
```

**Then query anything with them:**

```json
{
  "itemtype": "Ticket",
  "scope": "search",
  "criteria": [
    { "field": "name", "searchtype": "contains", "value": "backup" },
    { "field": "date", "searchtype": "morethan", "value": "2026-07-01", "link": "AND" }
  ],
  "fields": ["id", "name", "status", "date"],
  "sort_by": "date", "order": "desc"
}
```

---

## 📦 MCP Resources (4 Static URIs)

Access reference data via MCP resource protocol:

| Resource | URI | Content |
|----------|-----|---------|
| **Entities** | `glpi://entities` | Client/company list with IDs |
| **Ticket Status** | `glpi://ticket-status` | Status code mapping (new, assigned, waiting, solved, closed) |
| **Categories** | `glpi://ticket-categories` | Category tree (Hardware, Software, Network, etc.) |
| **Priorities** | `glpi://priorities` | Priority levels (Very Low to Very High) |

**Usage:** Instead of searching for entity IDs, use `glpi://entities` resource to find correct ID.

---

## 📋 MCP Prompts (15 Templates)

### IT Manager Prompts (7)

1. `glpi_sla_performance` — Monthly SLA dashboard with response times and compliance
2. `glpi_ticket_trends` — Analyze ticket patterns by category over time
3. `glpi_asset_roi` — ROI analysis of assets per client
4. `glpi_technician_productivity` — Team productivity metrics and rankings
5. `glpi_cost_per_ticket` — Cost analysis and rentability reports
6. `glpi_recurring_problems` — Identify recurring issues for preventive action
7. `glpi_client_satisfaction` — NPS, CSAT, and SLA compliance scorecard

### Support Analyst Prompts (8)

1. `glpi_ticket_summary` — Quick ticket summary for WhatsApp/Teams
2. `glpi_user_ticket_history` — User's complete ticket history and patterns
3. `glpi_asset_lookup` — Rapid asset search by name, serial, or user
4. `glpi_onboarding_checklist` — New employee IT onboarding checklist
5. `glpi_incident_investigation` — RCA (Root Cause Analysis) template
6. `glpi_change_management` — Change request (RFC) workflow checklist
7. `glpi_hardware_request` — Hardware request with approval workflow
8. `glpi_knowledge_base_search` — Intelligent knowledge base lookup

---

## 💡 Usage Examples

```bash
# Search for tickets
GLPI, list all open tickets with high priority

# Quick asset lookup
GLPI, search equipment for user John Smith

# Get resource data
Use the glpi://entities resource to find entity IDs

# Execute prompt
GLPI, use glpi_sla_performance for last 30 days analysis
```

---

## ⚠️ Known Limitations & Security Notes

Read this before trusting any protection described further down. **Implemented is
not the same as active** — two of the safeguards below are opt-in and do nothing
until configured.

### The confirmation guard is opt-in and OFF by default

Destructive operations (deleting tickets, assets, users, groups, locations,
webhooks and ITIL records) are wired to a confirmation guard that demands a token
and a written reason. It only runs when `MCP_SAFETY_GUARD=true`.

**With the variable unset — the default — a delete call reaches GLPI with no
confirmation at all.** Verified against a live instance: a delete for a
non-existent id returned "not found" from GLPI, meaning the request went through.
If the id had existed, the record would be gone.

The write policy (`GLPI_READ_ONLY`, `GLPI_ALLOW_<OPERATION>`) is independent and
always active, and every delete operation defaults to disabled there. That is the
protection you actually get out of the box; the guard adds the human challenge on
top of it.

### Knowledge base search does not derive the tenant from the token

`glpi_search_knowledge_unified` filters by client only when the caller passes
`tenant`. It is not inferred from the user token, unlike every other tool, where
the token fixes the scope.

If a single vector store holds documents ingested from more than one client, a
caller can read solutions belonging to another client. Either keep one store per
client, or always pass `tenant`. This is a design gap, not a bug report — it has
not been reproduced against a multi-client store.

### Search options are cached per process, not per user

Field labels come from whichever session populates the cache first, and last for
an hour. Two users on different languages or profiles can therefore see the same
label set. Only labels are shared — never record data — but resolution by
translated label may behave inconsistently across users. Resolution by canonical
name and by numeric id is unaffected.

### Never put a user token in the server configuration

`GLPI_USER_TOKEN` exists as a development fallback. Setting it in a deployment
that serves real users makes the server accept calls **without** any identity,
using that person's permissions and recording their name as the author of every
write. It defeats both the isolation between clients and the audit trail. Pass
the token per call, via the `X-GLPI-User-Token` header.

---

## 🛡️ Enterprise Features

### Tool Annotations

All tools include safety hints for LLM reasoning:

```json
{
  "name": "glpi_manage_ticket_operations",
  "readOnlyHint": "Use search_* tools for read-only lookups",
  "destructiveHint": "delete operation requires confirmationToken"
}
```

### Aggressive Rate Limiting

- **Default:** 10 results per request
- **Maximum:** 50 results per request
- Prevents context overflow and token waste

### HTML Stripping

GLPI TinyMCE fields automatically converted to plain text:

```
Before:  "<p>Issue started <b>yesterday</b> morning</p>"
After:   "Issue started yesterday morning"
```

### Field Filtering

Internal GLPI fields automatically removed:

```
Removed: _links, links, completename, etc.
Kept:    user-facing fields only
```

---

## 🔄 Migration

### From v2.1 to v2.2

**No breaking changes.** Every v2.1 call keeps working. What changed is additive:

- Three new tools (`glpi_search_itil_records`, `glpi_manage_itil_records`,
  `glpi_search_records_by_criteria`).
- New optional parameters on the existing search tools; omitting them preserves the
  previous behaviour.
- Nine new actions on `glpi_manage_ticket_operations`.

Two behavioural corrections are worth knowing, because the previous answers were
plausible and wrong:

- **Text search now respects the other filters.** A call combining `query` with
  `status`, `priority` or a date range previously returned results ignoring those
  filters. The same call now returns fewer, correct rows.
- **`query` searches title *and* content.** It previously matched the title only, so
  searching for an error message returned "none found" as if that were a fact.

### From v1.0

v2.x consolidates 68 fragmented tools into 18:

**Key Changes:**
- Use `glpi_search_*` for read-only operations (searches, lists, lookups)
- Use `glpi_manage_*` for mutations (create, update, delete, assign)
- Response format is Markdown instead of JSON
- Limits are aggressive (default=10, max=50) to prevent token waste
- Tool annotations guide LLM for optimal usage

---

> 💼 **Need Help with GLPI or AI?**
>
> **Skills IT - Technology Solutions** specializes in IT infrastructure and has deep expertise in **GLPI IT Service Management**. Our team has expertise in **Artificial Intelligence** and **Model Context Protocol (MCP)**, offering complete solutions for automation and system integration.
>
> **Our Services:**
> - ✅ GLPI consulting and implementation
> - ✅ Custom MCP development for your infrastructure
> - ✅ AI integration with corporate systems
> - ✅ Ticket and asset management automation
> - ✅ Specialized training and support
>
> 📞 **WhatsApp/Phone:** +55 63 3224-4925 - Brazil 🇧🇷
> 🌐 **Website:** [skillsit.com.br](https://skillsit.com.br)
> 📧 **Email:** contato@skillsit.com.br
>
> *"Transforming infrastructure into intelligence"*

---

## ⚙️ Configuration

### Per-User Authentication

Each user configures their own `X-GLPI-User-Token`:

1. Access GLPI with your credentials
2. Go to **Preferences** (top right corner)
3. In **Personal access token**, click **Regenerate**
4. Copy the generated token

### Environment Variables

**Core**

| Variable | Required | Description |
|----------|----------|-------------|
| `GLPI_BASE_URL` | Yes | GLPI server URL |
| `GLPI_APP_TOKEN` | Yes | GLPI App Token |
| `MCP_PORT` | No | Server port (default: 8824) |
| `MCP_HOST` | No | Server host (default: 0.0.0.0) |
| `MCP_SAFETY_GUARD` | No | Enable delete protection (default: false) |
| `MCP_SAFETY_TOKEN` | Conditional | Confirmation token if Safety Guard enabled |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | No | Rate limiting (default: 60) |
| `LOG_LEVEL` | No | Logging level (default: INFO) |

**Request resilience**

| Variable | Default | Description |
|----------|---------|-------------|
| `CONNECTION_TIMEOUT` | `30` | Connection timeout (seconds) |
| `REQUEST_TIMEOUT` | `60` | Request timeout (seconds) |
| `GLPI_MAX_RETRIES` | `2` | Retries only — 2 means up to 3 calls in total |
| `GLPI_RETRY_BACKOFF_BASE` | `1.5` | Exponential backoff base |
| `GLPI_RETRY_BACKOFF_CAP` | `20.0` | Backoff ceiling (seconds) |
| `MAX_CONNECTIONS` | `20` | Pool size |
| `MAX_KEEPALIVE_CONNECTIONS` | `10` | Keep-alive connections |

**Write policy** — reads are never affected.

| Variable | Default | Description |
|----------|---------|-------------|
| `GLPI_READ_ONLY` | `false` | Global read-only mode: blocks **every** write |
| `GLPI_ALLOW_<OPERATION>` | see below | One switch per write operation |

The per-operation name is `GLPI_ALLOW_` + the operation uppercased with `.` replaced by
`_` (e.g. `ticket.create` → `GLPI_ALLOW_TICKET_CREATE`). Non-destructive operations
default to **enabled**; every delete operation defaults to **disabled** and must be
turned on explicitly: `GLPI_ALLOW_TICKET_DELETE`, `GLPI_ALLOW_ASSET_DELETE`,
`GLPI_ALLOW_USER_DELETE`, `GLPI_ALLOW_GROUP_DELETE`, `GLPI_ALLOW_LOCATION_DELETE`,
`GLPI_ALLOW_WEBHOOK_DELETE`, `GLPI_ALLOW_PROBLEM_DELETE`, `GLPI_ALLOW_CHANGE_DELETE`,
`GLPI_ALLOW_PROJECT_DELETE`, `GLPI_ALLOW_CONTRACT_DELETE`, `GLPI_ALLOW_SUPPLIER_DELETE`.
A blocked write returns an error naming the variable to set — never a silent success.
Values are read at startup; changing them needs a restart.

ITIL deletion is gated **per record type**: allowing a problem to be deleted is a
different decision from allowing a contract to be, since contracts carry commercial
data maintained outside the service desk. Creating, updating, commenting and linking
ITIL records share one gate each, since the blast radius is the same across types.

The gate covers every tool whose annotations mark it destructive — tickets, assets,
admin resources, webhooks and ITIL. A test asserts that mapping against the live tool
catalogue, so a tool added later cannot quietly ship without a gate.

**Idempotency**

| Variable | Default | Description |
|----------|---------|-------------|
| `GLPI_IDEMPOTENCY_ENABLED` | `true` | Enable the idempotency guard |
| `GLPI_IDEMPOTENCY_BACKEND` | `sqlite` | `sqlite`, `memory` or `none` |
| `GLPI_IDEMPOTENCY_DB_PATH` | `var/idempotency/store.sqlite3` | SQLite database path |
| `GLPI_IDEMPOTENCY_NAMESPACE` | `default` | Isolates instances sharing a database |
| `GLPI_IDEMPOTENCY_TTL_SECONDS` | `86400` | Record retention in the store (24 h) |
| `GLPI_IDEMPOTENCY_LEASE_SECONDS` | `60` | Lease held by an in-flight execution |
| `GLPI_IDEMPOTENCY_WAIT_TIMEOUT` | `30` | Max wait for a concurrent execution |
| `GLPI_IDEMPOTENCY_POLL_INTERVAL` | `0.25` | Lease polling interval |
| `GLPI_IDEMPOTENCY_PURGE_INTERVAL` | `300` | Expired-record cleanup interval |

Repeating the same create returns the first result flagged `replayed: true` without
touching GLPI. The guard window at tool dispatch is **120 seconds** — deliberately
short, so a client or model retry is absorbed while a legitimately identical followup
later still goes through. If the store fails, the operation is **not** blocked: it runs
and the degraded mode is logged.

### Knowledge base (optional)

`glpi_search_knowledge_unified` is the only tool backed by a vector store instead of
the GLPI REST API. Without a `knowledge_base` section configured it degrades
politely — the tool reports that the KB is not configured; nothing else is affected.

Two halves, sharing one `knowledge_base.embedding` block:

- **Search** (`knowledge_base.sources`) — the source registry read by the MCP. Every
  source exposes the same fixed column contract, so adding one is a registry entry plus
  a relation, with no source-specific SQL in the MCP. See
  [`src/services/kb_search/CONTRACT.md`](src/services/kb_search/CONTRACT.md).
- **Ingestion** (`knowledge_base.ingestion`) — the ETL that turns a GLPI instance's own
  resolved tickets into that store. See
  [`knowledge_base/README.md`](knowledge_base/README.md).

Ingestion knobs worth knowing (full list in the `knowledge_base` README):

| Setting | Default | Description |
|---------|---------|-------------|
| `embed_strategy` | `full` | `full` (title + category + description), `form_description` (only the form's free-text problem — right when titles are form names and therefore boilerplate), `problem_solution` (problem **and** resolution, so a ticket is findable by the fix and not only by the symptom) |
| `description_labels` | built-in list | Which form field holds the free-text problem; instances name it differently. A JSON array, not a comma-separated string |
| `include_followups` | `true` | Fold technician follow-ups into the indexed resolution — GLPI keeps the fix in a follow-up on most tickets, so leaving this off discards it |
| `redact_literals` | `[]` | Exact secret values to strip from indexed text, on top of the pattern-based redaction that always runs |

Credentials pasted into tickets are **redacted before indexing**, so they never reach
the vector, the full-text index or a rendered result. Values found anywhere in the
batch are stripped everywhere in it. This is on by default and not configurable off;
`redact_literals` only adds values the patterns cannot infer.

Per-source display: set `solutions_expected: true` on ticket sources. It is what makes
a missing resolution read as "(resolvido, sem descricao da solucao)" — the fix was
never written down — instead of the `—` shown by documentation and forum sources,
where having no solution field is normal.

**Deployment.** The ETL is incremental and meant to run on a timer.
`knowledge_base/deploy/` ships a templated systemd pair, enabled once per instance:

```bash
sudo cp knowledge_base/deploy/glpi-kb-ingest@.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now glpi-kb-ingest@<instance>.timer
```

It runs daily at 05:00 under a `flock` shared with the other ETLs that contend for the
same embedding endpoint. Search works against whatever is already indexed, so a missed
run degrades freshness, not availability.

---

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=src --cov-report=html

# Specific test file
pytest tests/test_models.py -v
```

**Test Coverage:** 1,333 automated tests (plus 12 skipped) covering unit, integration,
contract and E2E scenarios.

Among them is a **contract test on description quality**: tool and prompt descriptions
are the retrieval surface that MCP hubs index and match semantically, so a thin
description makes a working tool unreachable — it simply never gets picked. The test
fails the build on descriptions that are too short or that open with a generic verb.

### Live smoke test

The suite mocks GLPI's responses, so it cannot observe GLPI's own semantics. Two real
defects only surfaced against a live instance: the ordering operator on status
behaving as equality (hiding assigned tickets from the "open" filter), and the plain
listing endpoint silently ignoring criteria (returning every entity's groups when one
entity was asked for).

```bash
# Read-only by default; the port is the first argument (default 8826)
GLPI_TOKEN=<user token> ./scripts/smoke_live.sh 8826

# Including the write cycle, against a disposable test ticket
GLPI_TOKEN=<token> SMOKE_WRITE=1 SMOKE_TICKET_ID=<id> ./scripts/smoke_live.sh 8826
```

> ⚠️ **The token always comes from the environment.** Never write it into the script or
> add it to the server's `.env`: there it becomes a fallback, and the server starts
> accepting **unauthenticated** calls under that identity — breaking tenant isolation
> and record authorship in GLPI.

---

## 🔧 Maintenance

### PM2 Commands

```bash
pm2 status mcp-glpi      # Status
pm2 logs mcp-glpi        # Real-time logs
pm2 restart mcp-glpi     # Restart
pm2 monit                # Monitoring
```

### Update

```bash
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
pm2 restart mcp-glpi
```

---

## 📚 Useful Links

- [GLPI Project](https://glpi-project.org/) — Official GLPI website
- [GLPI API Documentation](https://glpi-project.org/DOC/API/) — REST API docs
- [MCP Specification](https://modelcontextprotocol.io/) — MCP protocol spec
- [Skills IT Website](https://skillsit.com.br/) — Our company website

---

## 📋 Requirements

| Component | Version |
|-----------|---------|
| Python | 3.11+ |
| GLPI | 10.x, 11.x |
| FastAPI | 0.104+ |
| Pydantic | 2.x |
| MCP Protocol | 2024-11-05 |

---

## 🤝 Contributing

Contributions are welcome! Fork the repository, create a feature branch, and open a Pull Request with conventional commit messages.

---

## 📞 Support

### Bug Reports
[Open an issue](https://github.com/DevSkillsIT/mcp-glpi/issues) with reproduction steps and environment details.

### Email
Technical support: contato@skillsit.com.br

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">

**Made with ❤️ by Skills IT - Soluções em TI - BRAZIL**

*We are an MSP empowering other MSPs with intelligent automation.*

**Version:** 2.2.0 | **Last Updated:** August 2026

🇧🇷 **Proudly Made in Brazil**

[⬆ Back to Top](#-skills-mcp-glpi-v22)

</div>
