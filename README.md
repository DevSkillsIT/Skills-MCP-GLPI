<div align="center">

# 🚀 Skills MCP GLPI

### The Most Complete GLPI MCP Server with 66 Tools, Smart Search v2.0, and Safety Guard

[![MCP Protocol](https://img.shields.io/badge/MCP-2024--11--05-blue)](https://modelcontextprotocol.io/)
[![Python](https://img.shields.io/badge/Python-3.11+-green)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-teal)](https://fastapi.tiangolo.com/)
[![Pydantic](https://img.shields.io/badge/Pydantic-v2-purple)](https://docs.pydantic.dev/)
[![Transport](https://img.shields.io/badge/Transport-Streamable%20HTTP-orange)](https://modelcontextprotocol.io/docs/concepts/transports)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Production%20Ready-brightgreen)](https://github.com/DevSkillsIT/mcp-glpi)

**Connect Claude Code, Gemini CLI, ChatGPT, VS Code Copilot, and Cursor to your GLPI instance**

[Features](#-key-features) • [Installation](#-installation) • [66 Tools](#-66-tools) • [Quick Start](#-quick-start) • [Support](#-support)

</div>

---

## 📖 About The Project

**Skills MCP GLPI** is a production-ready Model Context Protocol (MCP) server that provides comprehensive integration with GLPI (IT Service Management). Built by **Skills IT**, a Managed Service Provider (MSP) from Brazil, this MCP addresses real-world needs that other GLPI integrations don't cover.

### 🌟 Why This MCP?

While other GLPI MCPs exist (PyPI, npm), **none offer complete coverage**:

| Feature | Other MCPs | Skills MCP GLPI |
|---------|------------|-----------------|
| **Tools** | 10-20 | **66 tools** ✨ |
| **Reservations** | ❌ Not supported | ✅ Complete system |
| **User Creation with Password** | ❌ Not supported | ✅ Fully supported |
| **Webhooks** | ❌ Not supported | ✅ 12 tools |
| **Safety Guard** | ❌ Doesn't exist | ✅ Delete protection |
| **Smart Search** | ❌ Basic | ✅ Fallback for deleted users |
| **Enriched Data** | ❌ Basic | ✅ Memory, CPU, AnyDesk in list_computers |
| **Performance** | Synchronous | ✅ 100% async/await |
| **Validation** | Basic | ✅ Pydantic v2 |

---

## 🎯 Key Features

### 1. 🔐 Complete Reservations System
List reservable items, check availability, create/cancel reservations with full GLPI integration.

### 2. 👤 User Creation with Password
The **only MCP** that allows setting passwords when creating users (not available in other GLPI MCPs).

### 3. 🔗 Native Webhooks
Complete webhook management for GLPI 10.x with 12 dedicated tools.

### 4. 🛡️ Safety Guard
Protection against accidental deletions with confirmation tokens and mandatory reasons.

### 5. 🔍 Smart Search v2.0
Intelligent search with automatic fallback to deleted users (LDAP/AD synchronization scenarios).

**The Problem:** When users are synced from Active Directory and then removed from AD, GLPI deletes them. Computers remain associated with non-existent user IDs, breaking searches.

**The Solution:** Smart Search implements 3-level fallback:
- **Level 1:** Search by Name, Serial, or main fields
- **Level 2:** Search by Username (JOIN with `glpi_users`)
- **Level 3:** Search in deleted users table (`glpi_users_deleted`)

### 6. 📊 Enriched Data
The `list_computers` tool returns complete data without additional calls:

| Field | Description |
|-------|-------------|
| `memory_info` | Installed RAM amount |
| `cpu_info` | CPU model and specifications |
| `anydesk_id` | AnyDesk ID for remote access |
| `teamviewer_id` | TeamViewer ID (if available) |
| `contact` | Associated contact name |
| `user_info` | Responsible user data |
| `os_info` | Installed operating system |

**Recommendation:** Use `list_computers` for overview with enriched data, use `get_computer_details` only for granular details of a specific computer.

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
> 📞 **WhatsApp/Phone:** +55 63 3224-4925 - Brazil
> 🌐 **Website:** skillsit.com.br 📧 **Email:** contato@skillsit.com.br
>
> *"Transforming infrastructure into intelligence"*

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
│                      Skills MCP GLPI Server                      │
│                         localhost:8824                           │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                      FastAPI App                           │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │ │
│  │  │ Tickets  │ │  Assets  │ │  Admin   │ │ Webhooks │      │ │
│  │  │(18 tools)│ │(20 tools)│ │(13 tools)│ │(12 tools)│      │ │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘      │ │
│  │  ┌─────────────────────────────────────────────────────┐  │ │
│  │  │ Session Manager │ Safety Guard │ Rate Limiter       │  │ │
│  │  └─────────────────────────────────────────────────────┘  │ │
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
- GLPI 10.x with REST API enabled
- GLPI App Token and User Token

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

Before using the MCP, configure your GLPI instance:

1. **Enable REST API:**
   - Menu: Setup > General > API
   - Check "Enable REST API"

2. **Create App Token:**
   - Menu: Setup > General > API > API Clients
   - Click "Add", activate and copy the **App Token**

3. **Get User Token:**
   - Menu: Administration > Users > your user
   - Tab "Remote access keys" > Generate **User Token**

### Environment Setup

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your credentials
nano .env
```

```bash
# .env

# Required
GLPI_BASE_URL=https://your-glpi-server.com
GLPI_APP_TOKEN=your_app_token_here

# Server
MCP_PORT=8824
MCP_HOST=0.0.0.0

# Safety Guard (delete protection)
MCP_SAFETY_GUARD=true
MCP_SAFETY_TOKEN=secure_token_min_8_chars

# Optional
RATE_LIMIT_REQUESTS_PER_MINUTE=500
LOG_LEVEL=INFO
```

### Start the Server

```bash
# Development (with reload)
python -m uvicorn src.main:app --host 0.0.0.0 --port 8824 --reload

# Production (with PM2)
pm2 start ecosystem.config.cjs
pm2 save
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

### Connect to Gemini CLI

Edit `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "glpi": {
      "httpUrl": "http://localhost:8824/mcp",
      "headers": {
        "X-GLPI-User-Token": "your_user_token_here"
      },
      "timeout": 30000
    }
  }
}
```

> **Note:** Gemini CLI uses `httpUrl` instead of `url`.

### Test Connection

```bash
# Health check
curl http://localhost:8824/health

# List available tools
curl -X POST http://localhost:8824/mcp \
  -H "Content-Type: application/json" \
  -H "X-GLPI-User-Token: your_token_here" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

---

## 🧰 66 Tools

### 🎫 Tickets (18 tools)

| Tool | Description |
|------|-------------|
| `list_tickets` | List tickets with advanced filters (status, entity_id, entity_name) |
| `get_ticket` | Complete ticket details by ID |
| `get_ticket_by_number` | Find ticket by number (not ID) |
| `create_ticket` | Create new ticket with validation |
| `update_ticket` | Update ticket fields |
| `delete_ticket` | ⚠️ Delete ticket (protected by Safety Guard) |
| `assign_ticket` | Assign technician to ticket |
| `close_ticket` | Close ticket with solution |
| `resolve_ticket` | Resolve ticket (awaiting user validation) |
| `search_tickets` | Search text in title, description and content |
| `search_similar_tickets` | Find similar tickets by title/description |
| `add_ticket_followup` | Add public followup |
| `post_private_note` | Add private note (visible only to technicians) |
| `get_ticket_followups` | List all ticket followups |
| `get_ticket_history` | Complete change history |
| `get_ticket_stats` | Ticket statistics by entity |
| `find_similar_tickets` | Search similar tickets using similarity algorithms |

### 💻 Assets (20 tools)

| Tool | Description |
|------|-------------|
| `list_assets` | List assets with filters (type, entity) |
| `get_asset` | Details of specific asset |
| `create_asset` | Create new asset |
| `update_asset` | Update existing asset |
| `delete_asset` | ⚠️ Delete asset (protected) |
| `search_assets` | 🔍 **Smart Search v2.0** - Search by name, serial or user |
| `list_computers` | 📊 List computers with **enriched data** |
| `get_computer_details` | Granular details of ONE computer |
| `list_monitors` | List monitors |
| `get_monitor` | Monitor details |
| `list_software` | List installed software |
| `get_software` | Software details |
| `list_devices` | List devices (NetworkEquipment, Phone, Peripheral) |
| `get_device` | Device details |
| `get_asset_stats` | Asset statistics by entity |
| `list_reservable_items` | Items available for reservation |
| `list_reservations` | List existing reservations |
| `create_reservation` | Create equipment reservation |
| `update_reservation` | Update reservation |
| `get_asset_reservations` | Reservations of specific asset |

### 👥 Admin/Users (13 tools)

| Tool | Description |
|------|-------------|
| `list_users` | List users with filters |
| `get_user` | User details |
| `create_user` | ✨ Create user **WITH PASSWORD** |
| `update_user` | Update user data |
| `delete_user` | ⚠️ Delete user (protected) |
| `search_users` | 🔍 **Smart Search** in 20+ fields with fallback |
| `list_groups` | List groups |
| `get_group` | Group details |
| `create_group` | Create new group |
| `list_entities` | List entities/companies |
| `get_entity` | Entity details |
| `list_locations` | List locations |
| `get_location` | Location details |

### 🔗 Webhooks (12 tools)

| Tool | Description |
|------|-------------|
| `list_webhooks` | List configured webhooks |
| `get_webhook` | Webhook details |
| `create_webhook` | Create webhook |
| `update_webhook` | Update webhook |
| `delete_webhook` | ⚠️ Delete webhook (protected) |
| `enable_webhook` | Activate webhook |
| `disable_webhook` | Deactivate webhook |
| `test_webhook` | Test webhook |
| `get_webhook_deliveries` | Delivery history |
| `get_webhook_stats` | Webhook statistics |
| `retry_failed_deliveries` | Retry failed deliveries |
| `trigger_webhook` | Manually trigger webhook |

### 🤖 AI/Analysis (3 tools)

| Tool | Description |
|------|-------------|
| `trigger_ai_analysis` | Trigger AI analysis on ticket |
| `get_ai_analysis_result` | Get analysis result |
| `publish_ai_response` | Publish AI response to ticket |

---

## 💡 Usage Examples

> **Tip:** Mention "GLPI" at the beginning of prompts to avoid confusion with other MCPs.

### Ticket Management

```
GLPI, list all open tickets
GLPI, create a ticket: "Computer won't start" with high urgency
GLPI, add followup to ticket 123: "Waiting for parts"
GLPI, close ticket 123 with solution: "Power supply replaced"
```

### Asset Management

```
GLPI, list all computers
GLPI, search equipment for user "John Smith"
GLPI, find computer with serial ABC123
GLPI, show asset statistics
```

### Reservations System

```
GLPI, what equipment is available for reservation?
GLPI, reserve the projector for tomorrow 2pm to 4pm
GLPI, cancel my reservation
```

### User Management

```
GLPI, create user: name "Mary Johnson", login "mary.johnson", password "Initial@2025"
GLPI, search users from finance department
GLPI, list support groups
```

---

## 🛡️ Safety Guard

Protection against accidental destructive operations.

### Protected Operations

| Operation | Protection |
|-----------|-----------|
| `delete_ticket` | Token + Reason required |
| `delete_asset` | Token + Reason required |
| `delete_user` | Token + Reason required |
| `delete_webhook` | Token + Reason required |

### How It Works

When Safety Guard is **enabled**, delete operations require:
- `confirmationToken` - Token configured on server
- `reason` - Deletion reason (minimum 10 characters)

```json
{
  "name": "delete_ticket",
  "arguments": {
    "ticket_id": 123,
    "confirmationToken": "your_secure_token",
    "reason": "Duplicate ticket, created by mistake by user"
  }
}
```

### Disable (development only)

```bash
# .env
MCP_SAFETY_GUARD=false
```

> ⚠️ **Never disable in production!**

---

## ⚙️ Configuration

### Per-User Authentication

Each user must configure their own `X-GLPI-User-Token`:

1. Access GLPI with your credentials
2. Go to **Preferences** (top right corner)
3. In **Personal access token**, click **Regenerate**
4. Copy the generated token

> **Benefits:** Proper user auditing, respects individual permissions, no credential sharing.

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GLPI_BASE_URL` | ✅ Yes | - | GLPI server URL |
| `GLPI_APP_TOKEN` | ✅ Yes | - | GLPI App Token |
| `MCP_PORT` | No | 8824 | Server port |
| `MCP_HOST` | No | 0.0.0.0 | Server host |
| `MCP_SAFETY_GUARD` | No | true | Enable delete protection |
| `MCP_SAFETY_TOKEN` | If Safety Guard enabled | - | Confirmation token (min 8 chars) |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | No | 500 | Rate limiting |
| `LOG_LEVEL` | No | INFO | Logging level |

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check (no auth required) |
| `/mcp` | POST | MCP JSON-RPC endpoint (requires auth) |

### Required Headers

```
Content-Type: application/json
X-GLPI-User-Token: your_user_token_here
```

---

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=src --cov-report=html

# Specific test
pytest tests/test_models.py -v
```

### Test Coverage

The project maintains high test coverage:
- Models and validation: 95%+
- Services: 85%+
- Handlers: 80%+

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

## 📋 Requirements

| Component | Version |
|-----------|---------|
| Python | 3.11+ |
| GLPI | 10.x |
| FastAPI | 0.104+ |
| Pydantic | 2.x |
| MCP Protocol | 2024-11-05 |

---

## 🤝 Contributing

Contributions are welcome! Here's how you can help:

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'feat: add amazing feature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

### Commit Standards

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add new feature
fix: correct bug
docs: update documentation
refactor: improve code structure
test: add tests
chore: update dependencies
```

---

## 📚 Useful Links

- [GLPI Project](https://glpi-project.org/) - Official GLPI website
- [GLPI API Documentation](https://glpi-project.org/DOC/API/) - REST API documentation
- [MCP Specification](https://modelcontextprotocol.io/) - Model Context Protocol specification
- [Skills IT Website](https://skillsit.com.br/) - Our company website

---

## 📞 Support

### Bug Reports
Found a bug? Please [open an issue](https://github.com/DevSkillsIT/mcp-glpi/issues) with:
- Description of the problem
- Steps to reproduce
- Expected vs actual behavior
- Environment details (Python version, GLPI version, OS)

### Discussions
Have questions or ideas? Join our [GitHub Discussions](https://github.com/DevSkillsIT/mcp-glpi/discussions)

### Email
Technical support: contato@skillsit.com.br

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

<div align="center">

**Made with ❤️ by Skills IT - Soluções em TI - BRAZIL**

*We are an MSP empowering other MSPs with intelligent automation.*

**Version:** 1.1.0 | **Last Updated:** December 2025

🇧🇷 **Proudly Made in Brazil**

[⬆ Back to Top](#-skills-mcp-glpi)

</div>
