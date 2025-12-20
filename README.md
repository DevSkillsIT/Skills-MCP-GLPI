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
> 📞 **WhatsApp/Phone:** +55 63 3224-4925 - Brazil 🇧🇷
> 🌐 **Website:** [skillsit.com.br](https://skillsit.com.br)
> 📧 **Email:** contato@skillsit.com.br
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

## 📋 MCP Prompts

### O que são MCP Prompts?

**MCP Prompts** são templates de conversação reutilizáveis que orquestram múltiplas chamadas de ferramentas em workflows guiados. Pense neles como "atalhos inteligentes" que executam sequências complexas de 5-7 passos automaticamente.

**Benefícios:**
- ⚡ **Produtividade**: Economize 80% do tempo em tarefas repetitivas
- 🎯 **Consistência**: Workflows padronizados com melhores práticas embutidas
- 📊 **Insights**: Relatórios prontos para reuniões e decisões executivas
- 🚀 **Adoção**: Use prompts naturais sem precisar conhecer comandos técnicos

### Categorias de Prompts

| Categoria | Prompts | Público-Alvo | Foco |
|-----------|---------|--------------|------|
| **Gestão de TI** | 7 prompts | Gestores, Coordenadores | Métricas, SLA, ROI, Produtividade |
| **Suporte Técnico** | 8 prompts | Analistas, Técnicos | Atendimento, Troubleshooting, Documentação |
| **Total** | **15 prompts** | - | Cobertura completa de operações MSP |

---

## 🎯 Prompts para Gestores de TI (7)

### 1. `glpi_sla_performance` - Relatório de Desempenho de SLA

**Descrição:** Dashboard completo de performance de SLA mensal com tempo médio de resposta e resolução.

**Quando Usar:**
- Reuniões de status semanal/mensal com diretoria
- Relatórios executivos para clientes MSP
- Validação de compliance contratual
- Análise de tendências de atendimento

**Argumentos:**
- `entity_name` (opcional): Filtrar por nome do cliente MSP
- `period_days` (opcional): Janela temporal em dias (padrão: 30)

**O Que Este Prompt Faz:**
1. Busca estatísticas de tickets do período especificado
2. Calcula tempos médios de resposta e resolução
3. Analisa taxa de cumprimento de SLA (%)
4. Identifica tickets em atraso e causas
5. Gera análise executiva com recomendações
6. Formata relatório em versão compacta (WhatsApp/Teams) e detalhada (reuniões)

**Exemplo de Uso:**
```
GLPI, use o prompt glpi_sla_performance para análise dos últimos 30 dias
```

**Output Esperado:**
```
📊 SLA Performance - Últimos 30 dias
Todos os clientes

✅ Tickets Resolvidos: 142
⏱️ Tempo Médio Resposta: 2.3 horas
🔧 Tempo Médio Resolução: 18.5 horas
📈 Taxa de Cumprimento SLA: 92%

⚠️ Tickets em Atraso: 8
```

---

### 2. `glpi_ticket_trends` - Análise de Tendências de Tickets

**Descrição:** Analisa tendências de tickets por categoria identificando aumento ou redução de demandas.

**Quando Usar:**
- Planejamento de capacidade de equipe
- Identificação de padrões sazonais
- Priorização de treinamentos técnicos
- Justificativa de contratações

**Argumentos:**
- `entity_name` (opcional): Filtrar por cliente específico
- `period_days` (opcional): Período de análise (padrão: 30)

**O Que Este Prompt Faz:**
1. Lista todos os tickets do período (limite: 500)
2. Agrupa tickets por categoria (itilcategories_id)
3. Calcula distribuição percentual
4. Identifica top 5 categorias mais demandadas
5. Compara com período anterior (se disponível)
6. Gera análise de crescimento/redução

**Exemplo de Uso:**
```
GLPI, mostre as tendências de tickets dos últimos 60 dias do cliente Acme Corp
```

**Output Esperado:**
```
📊 Tendências de Tickets - 60 dias
Cliente: Acme Corp

🔝 Top 5 Categorias:
1. Problemas de VPN: 34 tickets
2. Senha bloqueada: 28 tickets
3. Email não sincroniza: 22 tickets
4. Lentidão de sistema: 18 tickets
5. Impressora offline: 15 tickets
```

---

### 3. `glpi_asset_roi` - Análise de ROI de Ativos

**Descrição:** Calcula ROI de ativos por cliente analisando custo versus utilização.

**Quando Usar:**
- Justificativa de renovação de hardware
- Planejamento de orçamento anual
- Identificação de ativos subutilizados
- Relatórios de TCO (Total Cost of Ownership)

**Argumentos:**
- `entity_name` (obrigatório): Nome do cliente/entidade

**O Que Este Prompt Faz:**
1. Resolve entity_name para entity_id
2. Busca estatísticas de ativos da entidade
3. Calcula quantidade por tipo (computadores, monitores, dispositivos)
4. Estima custos totais e médios
5. Calcula taxa de utilização
6. Identifica ativos subutilizados (potencial de remanejamento)
7. Gera recomendações de otimização

**Exemplo de Uso:**
```
GLPI, calcule o ROI de ativos do cliente TechStart
```

**Output Esperado:**
```
💰 ROI de Ativos - TechStart

💻 Computadores: 45
🖥️ Monitores: 52
📱 Dispositivos: 23

📊 Utilização Média: 78%
💵 Custo Total Estimado: R$ 142.500,00
```

---

### 4. `glpi_technician_productivity` - Produtividade de Técnicos

**Descrição:** Mede produtividade individual de técnicos através de tickets resolvidos e tempo médio de resolução.

**Quando Usar:**
- Avaliações de desempenho
- Distribuição de bônus/comissões
- Identificação de necessidade de treinamento
- Balanceamento de carga de trabalho

**Argumentos:**
- `period_days` (opcional): Período de análise (padrão: 30)

**O Que Este Prompt Faz:**
1. Lista todos os usuários com flag is_technician
2. Calcula tickets resolvidos por técnico
3. Calcula tempo médio de resolução por técnico
4. Analisa índice de satisfação (se disponível)
5. Gera ranking de produtividade
6. Calcula médias consolidadas da equipe

**Exemplo de Uso:**
```
GLPI, mostre a produtividade dos técnicos dos últimos 30 dias
```

**Output Esperado:**
```
👷 Produtividade de Técnicos - 30 dias

Total de Técnicos: 8

🏆 Top 3 Produtivos:
1. Carlos Silva - 45 tickets (3.5h média)
2. Ana Santos - 38 tickets (4.1h média)
3. Pedro Costa - 32 tickets (4.8h média)

⏱️ Tempo Médio de Resolução: 4.2 horas
```

---

### 5. `glpi_cost_per_ticket` - Custo Médio por Ticket

**Descrição:** Calcula custo médio por ticket baseado em tempo técnico versus resultado.

**Quando Usar:**
- Precificação de contratos MSP
- Análise de rentabilidade por cliente
- Justificativa de reajustes contratuais
- Otimização de processos de atendimento

**Argumentos:**
- `entity_name` (opcional): Filtrar por cliente específico
- `period_days` (opcional): Período de análise (padrão: 30)

**O Que Este Prompt Faz:**
1. Calcula tempo médio de atendimento
2. Aplica custo/hora padrão do técnico (configurável)
3. Calcula custo médio por ticket
4. Totaliza custo do período
5. Distribui custos por tipo de ticket (incidente, requisição, problema)
6. Gera análise de rentabilidade

**Exemplo de Uso:**
```
GLPI, calcule o custo por ticket do cliente FinanceCorp nos últimos 60 dias
```

**Output Esperado:**
```
💰 Custo por Ticket - 60 dias
Cliente: FinanceCorp

📊 Custo Médio: R$ 85,00
⏱️ Tempo Médio: 3.2 horas
👷 Custo/Hora Técnico: R$ 26,50

Total Período: R$ 12.750,00 (150 tickets)
```

---

### 6. `glpi_recurring_problems` - Identificação de Problemas Recorrentes

**Descrição:** Identifica problemas recorrentes para ação preventiva e criação de base de conhecimento.

**Quando Usar:**
- Planejamento de ações preventivas
- Criação de artigos de base de conhecimento
- Identificação de necessidade de treinamento de usuários
- Priorização de projetos de melhoria

**Argumentos:**
- `entity_name` (opcional): Filtrar por cliente
- `min_occurrences` (opcional): Número mínimo de ocorrências (padrão: 3)

**O Que Este Prompt Faz:**
1. Agrupa tickets por descrição/categoria similar
2. Conta ocorrências de cada problema
3. Filtra problemas acima do threshold de ocorrências
4. Analisa impacto de cada problema recorrente
5. Gera recomendações de ação (KB, treinamento, automação)
6. Prioriza ações por impacto vs esforço

**Exemplo de Uso:**
```
GLPI, identifique problemas recorrentes com no mínimo 5 ocorrências
```

**Output Esperado:**
```
🔁 Problemas Recorrentes
Min. 5 ocorrências

⚠️ Top 5 Problemas:
1. Falha de VPN (8x) - Impacto: Alto
2. Impressora offline (6x) - Impacto: Médio
3. Senha expirada (5x) - Impacto: Baixo
4. Lentidão sistema (5x) - Impacto: Alto
5. Email não sincroniza (5x) - Impacto: Médio

💡 Ação: Criar KB e plano preventivo
```

---

### 7. `glpi_client_satisfaction` - Indicadores de Satisfação do Cliente

**Descrição:** Relatório consolidado de indicadores de satisfação do cliente (NPS, CSAT, SLA Compliance).

**Quando Usar:**
- Reuniões de QBR (Quarterly Business Review)
- Relatórios mensais para stakeholders
- Identificação de riscos de churn
- Demonstração de valor entregue

**Argumentos:**
- `entity_name` (opcional): Filtrar por cliente
- `period_days` (opcional): Período de análise (padrão: 30)

**O Que Este Prompt Faz:**
1. Calcula NPS (Net Promoter Score) baseado em feedbacks
2. Calcula CSAT (Customer Satisfaction Score)
3. Verifica compliance de SLA (%)
4. Analisa First Call Resolution (FCR)
5. Identifica pontos positivos e de melhoria
6. Compara com período anterior (tendência)

**Exemplo de Uso:**
```
GLPI, gere relatório de satisfação do cliente GlobalTech
```

**Output Esperado:**
```
😊 Satisfação do Cliente - 30 dias
Cliente: GlobalTech

⭐ NPS: 72 (Promotores)
📊 CSAT: 4.3/5
⏱️ SLA Cumprido: 94%

👍 Pontos Positivos: Rapidez no atendimento
👎 Melhorar: Comunicação proativa
```

---

## 🔧 Prompts para Analistas de Suporte (8)

### 1. `glpi_ticket_summary` - Resumo Rápido de Ticket

**Descrição:** Resumo compacto de ticket formatado para WhatsApp/Teams (máximo 10 linhas).

**Quando Usar:**
- Resposta rápida a clientes via WhatsApp
- Atualização de status em canais do Teams/Slack
- Consultas rápidas durante atendimento telefônico
- Compartilhamento de contexto entre técnicos

**Argumentos:**
- `ticket_id` (obrigatório): ID numérico do ticket

**O Que Este Prompt Faz:**
1. Busca dados completos do ticket por ID
2. Extrai informações essenciais (título, status, prioridade, solicitante)
3. Formata data de abertura
4. Trunca descrição em 200 caracteres
5. Formata em versão compacta (WhatsApp) e detalhada (email)

**Exemplo de Uso:**
```
GLPI, resuma o ticket 4582 para WhatsApp
```

**Output Esperado:**
```
🎫 Ticket #4582
Notebook não liga após atualização

📅 Aberto: 10/12/2025 14:32
👤 Solicitante: João Silva (Financeiro)
🔴 Prioridade: Alta
📊 Status: Em andamento

📝 Resumo:
Usuário relatou que após atualização do Windows,
notebook não liga mais. LED de energia acende...
```

---

### 2. `glpi_user_ticket_history` - Histórico de Tickets do Usuário

**Descrição:** Histórico completo de tickets abertos por um usuário específico.

**Quando Usar:**
- Identificação de usuários problemáticos (muitos tickets)
- Análise de padrão de comportamento
- Contexto antes de atender novo ticket do usuário
- Identificação de necessidade de treinamento

**Argumentos:**
- `username` (obrigatório): Nome ou login do usuário

**O Que Este Prompt Faz:**
1. Busca usuário por nome (Smart Search com fallback para deletados)
2. Lista todos os tickets vinculados ao usuário
3. Calcula estatísticas (total, abertos, resolvidos, fechados)
4. Calcula tempo médio de resolução dos tickets do usuário
5. Identifica categorias mais frequentes
6. Lista últimos 10 tickets com detalhes

**Exemplo de Uso:**
```
GLPI, mostre histórico de tickets da Maria Santos
```

**Output Esperado:**
```
👤 Histórico de Tickets - Maria Santos

📊 Total de Tickets: 12
📈 Abertos: 2
✅ Resolvidos: 8
❌ Fechados: 2

🔝 Últimos 3:
1. #345 - Senha bloqueada (Resolvido) - 10/12
2. #338 - Email não envia (Em andamento) - 08/12
3. #322 - VPN não conecta (Fechado) - 05/12
```

---

### 3. `glpi_asset_lookup` - Busca Rápida de Ativo

**Descrição:** Busca rápida de ativo por nome, serial ou usuário usando Smart Search v2.0.

**Quando Usar:**
- Durante atendimento telefônico (busca rápida)
- Validação de configuração de equipamento
- Localização de ativo para manutenção
- Verificação de especificações técnicas

**Argumentos:**
- `search_term` (obrigatório): Nome, serial, ou usuário do equipamento

**O Que Este Prompt Faz:**
1. Executa Smart Search v2.0 (busca em nome, serial, contact, users_id)
2. Fallback automático para usuários deletados (sync AD/LDAP)
3. Retorna primeiro resultado mais relevante
4. Exibe dados essenciais (serial, usuário, local, status)
5. Mostra especificações técnicas (CPU, RAM, SO)
6. Formata versão compacta e detalhada

**Exemplo de Uso:**
```
GLPI, busque computador do usuário Carlos Oliveira
```

**Output Esperado:**
```
💻 Ativo Encontrado
NOTEBOOK-DEV-042

🏷️ Serial: ABC12345XYZ
👤 Usuário: Carlos Oliveira
📍 Local: TI - Desenvolvimento
📊 Status: Em uso

🔧 Specs:
• CPU: Intel Core i7-10750H
• RAM: 16 GB
• SO: Windows 11 Pro
```

---

### 4. `glpi_onboarding_checklist` - Checklist de Onboarding

**Descrição:** Checklist completo para onboarding de novo colaborador com todas as etapas de TI.

**Quando Usar:**
- Admissão de novo colaborador
- Padronização do processo de onboarding
- Garantia de não esquecer nenhuma etapa
- Documentação do processo de setup

**Argumentos:**
- `username` (obrigatório): Nome do novo colaborador
- `entity_name` (obrigatório): Nome da empresa/cliente

**O Que Este Prompt Faz:**
1. Gera checklist padronizado de onboarding de TI
2. Inclui criação de acessos (AD, email, VPN)
3. Lista configuração de equipamento
4. Detalha entrega de hardware
5. Inclui treinamento inicial obrigatório
6. Gera template de email de login para novo usuário

**Exemplo de Uso:**
```
GLPI, crie checklist de onboarding para Rafael Costa na empresa TechStart
```

**Output Esperado:**
```
✅ Checklist Onboarding
Rafael Costa - TechStart

□ Criar usuário no Active Directory
□ Criar conta de email (rafael.costa@techstart.com)
□ Configurar acesso VPN
□ Adicionar aos grupos necessários
□ Entregar equipamento (Notebook + Monitor)
□ Configurar estação de trabalho
□ Treinamento inicial (2h)
□ Teste de acesso aos sistemas
```

---

### 5. `glpi_incident_investigation` - Template de Investigação de Incidente (RCA)

**Descrição:** Template estruturado de RCA (Root Cause Analysis) para investigação profunda de incidentes.

**Quando Usar:**
- Incidentes de alto impacto
- Problemas recorrentes sem causa identificada
- Análise post-mortem
- Documentação de lições aprendidas

**Argumentos:**
- `ticket_id` (obrigatório): ID do ticket de incidente

**O Que Este Prompt Faz:**
1. Busca detalhes completos do ticket
2. Gera template de RCA estruturado
3. Inclui análise de impacto
4. Cria timeline do incidente
5. Aplica método dos 5 Porquês (Ishikawa)
6. Gera seção de ações preventivas
7. Documenta lições aprendidas

**Exemplo de Uso:**
```
GLPI, crie RCA para investigação do ticket 8745
```

**Output Esperado:**
```
🔍 RCA - Ticket #8745
Servidor de email inoperante por 4 horas

📝 Próximos passos:
1. Coletar evidências (logs, prints, testemunhos)
2. Identificar causa raiz (diagrama Ishikawa)
3. Documentar resolução aplicada
4. Implementar ações preventivas

Timeline:
• 14:30 - Incidente detectado
• 14:35 - Equipe acionada
• 15:20 - Causa identificada
• 18:15 - Serviço restaurado
```

---

### 6. `glpi_change_management` - Checklist de Gestão de Mudança (RFC)

**Descrição:** Checklist completo de RFC (Request for Change) para mudanças planejadas.

**Quando Usar:**
- Mudanças de infraestrutura
- Atualizações de sistemas críticos
- Migrações de ambiente
- Implementação de novos serviços

**Argumentos:**
- `change_description` (obrigatório): Descrição da mudança planejada

**O Que Este Prompt Faz:**
1. Gera template de RFC completo
2. Inclui análise de riscos (probabilidade vs impacto)
3. Cria cronograma de implementação
4. Detalha plano de backup
5. Gera plano de rollback (contingência)
6. Inclui checklist de comunicação
7. Define critérios de sucesso

**Exemplo de Uso:**
```
GLPI, crie RFC para migração do servidor de arquivos para novo storage
```

**Output Esperado:**
```
📋 RFC - Gestão de Mudança
Migração servidor de arquivos para novo storage

✅ Checklist:
□ Aprovar mudança (CAB)
□ Planejar implementação (domingo 22h)
□ Notificar stakeholders (48h antes)
□ Backup completo de segurança
□ Executar migração (janela de 4h)
□ Validar integridade dos dados
□ Documentar processo no GLPI
```

---

### 7. `glpi_hardware_request` - Template de Solicitação de Hardware

**Descrição:** Template padronizado para solicitação e aprovação de hardware.

**Quando Usar:**
- Solicitação de novo equipamento
- Substituição de hardware defeituoso
- Upgrade de configuração
- Padronização de processo de compras

**Argumentos:**
- `user_name` (obrigatório): Nome do usuário solicitante
- `hardware_type` (obrigatório): Tipo de hardware (Notebook, Desktop, Monitor, etc.)

**O Que Este Prompt Faz:**
1. Gera template de solicitação formal
2. Inclui especificações técnicas mínimas
3. Lista periféricos necessários
4. Cria workflow de aprovações (gestor, financeiro, TI)
5. Gera template de cotação (3 fornecedores)
6. Inclui checklist de configuração
7. Documenta termo de responsabilidade

**Exemplo de Uso:**
```
GLPI, crie solicitação de Notebook para Ana Paula (Financeiro)
```

**Output Esperado:**
```
🖥️ Solicitação de Hardware
Tipo: Notebook
Usuário: Ana Paula (Financeiro)

📋 Checklist:
□ Aprovar solicitação (gestor financeiro)
□ Verificar orçamento disponível
□ Cotação (3 fornecedores)
□ Compra/Reserva
□ Configurar equipamento (Win 11 + Office)
□ Entregar ao usuário com termo assinado
```

---

### 8. `glpi_knowledge_base_search` - Busca em Base de Conhecimento

**Descrição:** Busca inteligente em base de conhecimento com sugestões de artigos relacionados.

**Quando Usar:**
- Resolução de problemas conhecidos
- Treinamento de novos técnicos
- Compartilhamento de soluções
- Redução de tempo de resolução (First Call Resolution)

**Argumentos:**
- `search_query` (obrigatório): Termo de busca ou descrição do problema

**O Que Este Prompt Faz:**
1. Busca artigos na base de conhecimento do GLPI
2. Ordena por relevância e popularidade
3. Exibe estatísticas de cada artigo (visualizações, % útil)
4. Mostra resumo de cada solução
5. Sugere artigos relacionados
6. Lista artigos mais populares gerais

**Exemplo de Uso:**
```
GLPI, busque na base de conhecimento: VPN não conecta
```

**Output Esperado:**
```
📚 Busca em Base de Conhecimento
Termo: "VPN não conecta"

📄 Artigos Encontrados:
1. Resolver erro de VPN "Conexão recusada"
   (245 visualizações, 92% útil)

2. Configurar VPN no Windows 11
   (189 visualizações, 88% útil)

3. Troubleshooting VPN - Checklist completo
   (156 visualizações, 85% útil)

💡 Dica: Use palavras-chave específicas
```

---

## 🚀 Como Usar os Prompts

### No Claude Code

```bash
# Adicionar MCP GLPI
claude mcp add --transport http glpi http://localhost:8824/mcp

# Usar prompts em conversação natural
Claude, use o prompt glpi_sla_performance para análise dos últimos 30 dias
Claude, crie checklist de onboarding para João Silva na empresa TechStart
Claude, busque histórico de tickets da Maria Santos
```

### No Claude Desktop

Edite `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "glpi": {
      "type": "streamable-http",
      "url": "http://localhost:8824/mcp",
      "headers": {
        "X-GLPI-User-Token": "your_token_here"
      }
    }
  }
}
```

### No Gemini CLI

Edite `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "glpi": {
      "httpUrl": "http://localhost:8824/mcp",
      "headers": {
        "X-GLPI-User-Token": "your_token_here"
      },
      "timeout": 30000
    }
  }
}
```

---

## 💡 Casos de Uso Práticos

### Para Gestores de TI

**Reunião Mensal com Diretoria:**
```
Claude, use glpi_sla_performance para relatório mensal
Claude, depois mostre glpi_client_satisfaction de todos os clientes
Claude, finalize com glpi_cost_per_ticket dos últimos 30 dias
```

**Planejamento Trimestral:**
```
Claude, execute glpi_ticket_trends dos últimos 90 dias
Claude, depois identifique glpi_recurring_problems com mínimo 5 ocorrências
Claude, finalize com glpi_technician_productivity para avaliação de equipe
```

### Para Analistas de Suporte

**Atendimento Rápido (WhatsApp/Teams):**
```
GLPI, resuma ticket 4582 para WhatsApp
GLPI, busque computador do usuário Carlos Silva
GLPI, mostre histórico de tickets da Ana Paula
```

**Onboarding de Colaborador:**
```
GLPI, crie checklist completo de onboarding para Rafael Costa na empresa TechStart
```

**Investigação de Incidente:**
```
GLPI, crie RCA para investigação do ticket 8745
GLPI, depois busque glpi_knowledge_base_search: servidor de email inoperante
```

**Planejamento de Mudança:**
```
GLPI, crie RFC para migração do Exchange Server 2016 para Microsoft 365
```

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
