<div align="center">

# 🚀 Skills MCP GLPI v2.1

### 14 Production-Grade Tools with 70-85% Token Efficiency and Enterprise-Grade Safety

[![MCP Protocol](https://img.shields.io/badge/MCP-2024--11--05-blue)](https://modelcontextprotocol.io/)
[![Python](https://img.shields.io/badge/Python-3.11+-green)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-teal)](https://fastapi.tiangolo.com/)
[![Pydantic](https://img.shields.io/badge/Pydantic-v2-purple)](https://docs.pydantic.dev/)
[![Transport](https://img.shields.io/badge/Transport-Streamable%20HTTP-orange)](https://modelcontextprotocol.io/docs/concepts/transports)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Production%20Ready-brightgreen)](https://github.com/DevSkillsIT/mcp-glpi)

**Connect Claude Code, Gemini CLI, ChatGPT, VS Code Copilot, and Cursor to your GLPI instance**

[Why v2.0](#-why-v20) • [14 Tools](#-14-tools) • [Quick Start](#-quick-start) • [Resources](#-mcp-resources) • [Support](#-support)

</div>

---

## 📖 About The Project

**Skills MCP GLPI v2.1** is a production-ready Model Context Protocol (MCP) server for GLPI (IT Service Management) with a revolutionary token-optimization architecture. Built by **Skills IT**, this MCP consolidates 68 specialized tools into 14 enterprise-grade tools with Markdown responses, tool annotations, and MCP resources.

Compatible with **GLPI 10.x** (legacy API v1) and **GLPI 11.x** (current stable).

**What's new in 2.1** (April 2026): 14 bug fixes covering ticket stats aggregation, user/admin search, knowledge base integration, computer details enrichment (OS/disks/CPU/memory/network/software), webhook string IDs, entity root id=0, localhost rate-limit bypass, and a critical fix to the success formatter that was silently masking failed delete operations. See [CHANGELOG.md](./CHANGELOG.md) for the full list.

### 🌟 Why v2.0?

The v1.0 approach (68 tools, raw JSON responses) caused **token explosion** — typical GLPI queries consumed 50-100K tokens with limited reusability. v2.0 fixes this with a consolidated, Markdown-first design:

| Aspect | v1.0 | v2.0 |
|--------|------|------|
| **Tools** | 68 fragmented | **14 consolidated** ✨ |
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
- **14 production tools** organized by domain (Tickets, Assets, Admin, Webhooks, Bridge)
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

### 4. **MCP Resources & Prompts**
- **4 MCP Resources:** Entity list, ticket statuses, categories, priorities
- **15 MCP Prompts:** 7 for IT managers, 8 for support analysts
- Enables advanced workflows without heavy tool definitions

### 5. **Server-Side LLM Instructions**
LLM receives usage guide automatically on initialization, ensuring optimal tool usage patterns.

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
│  │  │   14 Tools   │ │ 4 Resources  │ │  15 Prompts     │   │ │
│  │  │ (Markdown)   │ │ (Static URIs)│ │ (Parameterized) │   │ │
│  │  └──────────────┘ └──────────────┘ └──────────────────┘   │ │
│  │  ┌───────────────┬──────────────┬──────────────────────┐   │ │
│  │  │ HTML Stripper │ Field Filter │ Rate Limiter (10/50)│   │ │
│  │  └───────────────┴──────────────┴──────────────────────┘   │ │
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

## 🧰 14 Tools (v2.0)

### 🎫 Tickets (3 tools)

| Tool | Description |
|------|-------------|
| `glpi_search_helpdesk_tickets` | Search tickets/incidents/requests by status, priority, entity, category |
| `glpi_manage_ticket_operations` | CRUD: get/create/update/delete/assign/close/resolve/add_followup/get_followups/get_history/get_stats |
| `glpi_manage_ticket_ai_analysis` | AI analysis: trigger/get_result/publish |

### 💻 Assets (2 tools)

| Tool | Description |
|------|-------------|
| `glpi_search_asset_inventory` | Search computers/monitors/software/devices/reservations by type, entity, status |
| `glpi_manage_asset_operations` | CRUD + reservations: get/get_details (enriched with OS/disks/CPU/mem/net/software)/create/update/delete/get_reservations/create_reservation |

### 👥 Admin (2 tools)

| Tool | Description |
|------|-------------|
| `glpi_search_admin_resources` | Search users/groups/entities/locations by name, type, status |
| `glpi_manage_admin_resources` | CRUD: get/create/update/delete for users, groups, entities, locations |

### 🔗 Webhooks (2 tools)

| Tool | Description |
|------|-------------|
| `glpi_search_webhook_integrations` | List/filter webhooks, delivery history, statistics |
| `glpi_manage_webhook_integrations` | CRUD + control: get/create/update/delete/test/trigger/enable/disable/retry |

### 🌉 Bridge (5 tools)

| Tool | Description |
|------|-------------|
| `glpi_list_available_resources` | List 4 MCP resources with URIs |
| `glpi_read_resource_by_uri` | Read resource content (entities, statuses, categories, priorities) |
| `glpi_list_available_prompts` | List 15 professional MCP prompts |
| `glpi_get_prompt_template` | Execute specific prompt with arguments |
| `glpi_search_knowledge_articles` | Search knowledge base |

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

## 🔄 Migration from v1.0

v2.0 consolidates 68 tools into 14. If upgrading from v1.0:

**Before (v1.0):**
```
68 tools: glpi_list_tickets, glpi_get_ticket, glpi_get_ticket_by_id,
glpi_get_ticket_by_number, glpi_create_ticket, glpi_update_ticket,
glpi_delete_ticket, glpi_assign_ticket, glpi_close_ticket, ...
```

**After (v2.0):**
```
14 tools: glpi_search_helpdesk_tickets, glpi_manage_ticket_operations,
glpi_manage_ticket_ai_analysis, glpi_search_asset_inventory,
glpi_manage_asset_operations, glpi_search_admin_resources, ...
```

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

| Variable | Required | Description |
|----------|----------|-------------|
| `GLPI_BASE_URL` | Yes | GLPI server URL |
| `GLPI_APP_TOKEN` | Yes | GLPI App Token |
| `MCP_PORT` | No | Server port (default: 8824) |
| `MCP_HOST` | No | Server host (default: 0.0.0.0) |
| `MCP_SAFETY_GUARD` | No | Enable delete protection (default: true) |
| `MCP_SAFETY_TOKEN` | Conditional | Confirmation token if Safety Guard enabled |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | No | Rate limiting (default: 500) |
| `LOG_LEVEL` | No | Logging level (default: INFO) |

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

**Test Coverage:** 323 automated tests covering unit, integration, contract, and E2E scenarios.

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

**Version:** 2.1.0 | **Last Updated:** April 2026

🇧🇷 **Proudly Made in Brazil**

[⬆ Back to Top](#-skills-mcp-glpi-v21)

</div>
