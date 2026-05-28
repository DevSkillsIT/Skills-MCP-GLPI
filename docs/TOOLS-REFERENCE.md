# GLPI MCP Server — Referência de Tools

> 14 ferramentas consolidadas organizadas em 6 domínios
>
> **Versão:** 2.1.0 (April 2026) · **GLPI:** 10.x e 11.x

## Sumário

| # | Tool | Domínio | Tipo |
|---|------|---------|------|
| 1 | `glpi_search_helpdesk_tickets` | Tickets | Leitura |
| 2 | `glpi_manage_ticket_operations` | Tickets | Escrita |
| 3 | `glpi_manage_ticket_ai_analysis` | Tickets | Escrita |
| 4 | `glpi_search_asset_inventory` | Ativos | Leitura |
| 5 | `glpi_manage_asset_operations` | Ativos | Escrita |
| 6 | `glpi_search_admin_resources` | Admin | Leitura |
| 7 | `glpi_manage_admin_resources` | Admin | Escrita |
| 8 | `glpi_search_webhook_integrations` | Webhooks | Leitura |
| 9 | `glpi_manage_webhook_integrations` | Webhooks | Escrita |
| 10 | `glpi_list_available_resources` | Bridge | Leitura |
| 11 | `glpi_read_resource_by_uri` | Bridge | Leitura |
| 12 | `glpi_list_available_prompts` | Bridge | Leitura |
| 13 | `glpi_get_prompt_template` | Bridge | Leitura |
| 14 | `glpi_search_knowledge_articles` | Conhecimento | Leitura |

---

## 1. TICKETS

### 1.1 `glpi_search_helpdesk_tickets`

Busca e listagem de chamados, tickets e incidentes no GLPI.

**Quando usar:** Para consultar chamados abertos, pendentes ou fechados de um cliente.

| Parâmetro | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `status` | string | Não | Filtro: `new`, `processing`, `pending`, `solved`, `closed` |
| `priority` | integer | Não | Prioridade: 1 (muito baixa) a 5 (muito alta) |
| `entity_id` | integer | Não | ID da entidade/cliente no GLPI |
| `entity_name` | string | Não | Nome da entidade (alternativa ao ID) |
| `query` | string | Não | Busca textual no título/conteúdo (mín. 2 caracteres) |
| `limit` | integer | Não | Resultados por página (padrão: 10, máx: 50) |
| `offset` | integer | Não | Offset para paginação (padrão: 0) |

**Exemplo:**
```
"Listar chamados abertos da entidade Skills IT"
→ Tool: glpi_search_helpdesk_tickets
→ Params: { "status": "new", "entity_name": "Skills IT", "limit": 20 }
```

```
"Buscar chamados sobre impressora"
→ Tool: glpi_search_helpdesk_tickets
→ Params: { "query": "impressora" }
```

---

### 1.2 `glpi_manage_ticket_operations`

Operações completas de gestão de chamados: criar, atualizar, atribuir, resolver, fechar.

**Quando usar:** Para qualquer operação que modifique chamados no GLPI.

| Parâmetro | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `action` | string | **Sim** | Ação: ver abaixo |
| `ticket_id` | integer | Condicional | ID do chamado (obrigatório para maioria das ações) |
| `title` | string | Condicional | Título (obrigatório para `create`) |
| `description` | string | Condicional | Descrição do problema (obrigatório para `create`) |
| `content` | string | Condicional | Conteúdo do acompanhamento (para `add_followup`) |
| `status` | string | Não | Status: `new`, `processing`, `pending`, `solved`, `closed` |
| `priority` | integer | Não | Prioridade 1-5 |
| `entity_id` | integer | Não | ID da entidade |
| `entity_name` | string | Não | Nome da entidade |
| `user_id` | integer | Condicional | ID do técnico (para `assign`) |
| `solution` | string | Condicional | Solução técnica (para `resolve`/`close`) |
| `ticket_number` | string | Não | Número do chamado (para `get_by_number`) |
| `threshold` | number | Não | Similaridade 0.0–1.0 para `find_similar` (padrão: 0.3) |
| `max_results` | integer | Não | Máx. tickets similares em `find_similar` (padrão: 10, máx: 50) |
| `date_from` | string | Não | Data inicial YYYY-MM-DD para `get_stats` |
| `date_to` | string | Não | Data final YYYY-MM-DD para `get_stats` |
| `is_private` | boolean | Não | Acompanhamento privado (padrão: false) |

**Ações disponíveis:**

| Action | Descrição | Parâmetros obrigatórios |
|--------|-----------|------------------------|
| `get` | Consultar detalhes de um chamado | `ticket_id` |
| `get_by_number` | Buscar chamado pelo número | `ticket_number` |
| `create` | Abrir novo chamado | `title`, `description` |
| `update` | Atualizar dados do chamado | `ticket_id` + campos a alterar |
| `delete` | Excluir chamado | `ticket_id` |
| `assign` | Atribuir técnico ao chamado | `ticket_id`, `user_id` |
| `close` | Fechar chamado com solução | `ticket_id`, `solution` |
| `resolve` | Resolver chamado | `ticket_id`, `solution` |
| `add_followup` | Adicionar acompanhamento | `ticket_id`, `content` |
| `get_followups` | Listar acompanhamentos | `ticket_id` |
| `get_history` | Histórico de alterações | `ticket_id` |
| `get_stats` | Estatísticas agregadas por status (`by_status`: new/assigned/planned/pending/solved/closed). Filtros opcionais: `entity_id`, `date_from`, `date_to` | nenhum |
| `find_similar` | Encontrar chamados similares por conteúdo do ticket de referência | `ticket_id` (+ `threshold`, `max_results` opcionais) |

**Exemplos:**

```
"Abrir chamado para o usuário João sobre problema de VPN"
→ action: "create"
→ Params: {
    "action": "create",
    "title": "Problema de conexão VPN - João Silva",
    "description": "Usuário João Silva não consegue conectar na VPN desde hoje às 9h.",
    "priority": 3,
    "entity_name": "Skills IT"
  }
```

```
"Atribuir chamado 542 para o técnico ID 15"
→ action: "assign"
→ Params: { "action": "assign", "ticket_id": 542, "user_id": 15 }
```

```
"Adicionar acompanhamento no chamado 542"
→ action: "add_followup"
→ Params: {
    "action": "add_followup",
    "ticket_id": 542,
    "content": "Entrei em contato com o usuário. O problema ocorre apenas na rede Wi-Fi do escritório."
  }
```

```
"Resolver chamado 542"
→ action: "resolve"
→ Params: {
    "action": "resolve",
    "ticket_id": 542,
    "solution": "Reconfigurado cliente VPN FortiClient. Problema era certificado expirado."
  }
```

```
"Fechar chamado 542"
→ action: "close"
→ Params: {
    "action": "close",
    "ticket_id": 542,
    "solution": "Problema resolvido, usuário confirmou funcionamento."
  }
```

```
"Tickets similares ao 542"
→ action: "find_similar"
→ Params: {
    "action": "find_similar",
    "ticket_id": 542,
    "threshold": 0.3,
    "max_results": 5
  }
```

```
"Estatísticas de chamados de abril"
→ action: "get_stats"
→ Params: {
    "action": "get_stats",
    "date_from": "2026-04-01",
    "date_to": "2026-04-30"
  }
→ Retorna: total_tickets, open_tickets, closed_tickets, by_status { new, assigned, planned, pending, solved, closed }
```

---

### 1.3 `glpi_manage_ticket_ai_analysis`

Análise inteligente de chamados usando IA com categorização, priorização e sugestões automáticas.
Fluxo assíncrono: `trigger` retorna um `job_id` que deve ser usado em `get_result` e `publish`.

| Parâmetro | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `action` | string | **Sim** | `trigger` (disparar), `get_result` (consultar), `publish` (publicar) |
| `ticket_id` | integer | Condicional | Obrigatório para `trigger` |
| `job_id` | string | Condicional | ID do job retornado por `trigger` — obrigatório para `get_result` e `publish` |
| `response` | object | Condicional | Payload da resposta IA para `publish` |

**Exemplo:**
```
"Analisar chamado 200 com IA"
→ Params: { "action": "trigger", "ticket_id": 200 }
→ Retorna: { "job_id": "ai_job_xxxxxx", "status": "processing" }

"Ver resultado da análise"
→ Params: { "action": "get_result", "job_id": "ai_job_xxxxxx" }

"Publicar resposta IA no ticket"
→ Params: {
    "action": "publish",
    "job_id": "ai_job_xxxxxx",
    "response": { "summary": "Recomendação: ...", "suggested_priority": 3 }
  }
```

---

## 2. ATIVOS

### 2.1 `glpi_search_asset_inventory`

Busca no inventário de equipamentos e ativos de TI.

| Parâmetro | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `scope` | string | Não | `all`, `computers`, `monitors`, `software`, `devices`, `reservations`, `reservable`, `stats` (padrão: `all`) |
| `asset_type` | string | Não | `Computer`, `Monitor`, `Printer`, `NetworkEquipment`, `Phone`, `Peripheral` |
| `query` | string | Não | Busca por nome, serial ou usuário vinculado |
| `entity_id` | integer | Não | ID da entidade |
| `entity_name` | string | Não | Nome da entidade |
| `limit` | integer | Não | Resultados (padrão: 10, máx: 50) |
| `offset` | integer | Não | Offset paginação |

**Exemplos:**
```
"Listar todos os computadores da empresa"
→ Params: { "scope": "computers", "limit": 50 }

"Buscar equipamento pelo serial ABC123"
→ Params: { "query": "ABC123" }

"Estatísticas do inventário"
→ Params: { "scope": "stats" }

"Equipamentos reserváveis"
→ Params: { "scope": "reservable" }
```

---

### 2.2 `glpi_manage_asset_operations`

Operações de gestão de ativos: cadastrar, detalhar, atualizar, excluir, reservas.

| Parâmetro | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `action` | string | **Sim** | Ver tabela abaixo |
| `asset_type` | string | Condicional | Tipo do ativo |
| `asset_id` | integer | Condicional | ID do ativo |
| `name` | string | Condicional | Nome do ativo (para `create`) |
| `serial_number` | string | Não | Número de série |

**Ações disponíveis:**

| Action | Descrição | Parâmetros obrigatórios |
|--------|-----------|------------------------|
| `get` | Consultar ativo (dados básicos) | `asset_id`, `asset_type` |
| `get_details` | Detalhes enriquecidos (**Computer**: OS + discos + CPU + memória + redes + software instalado) | `asset_id`, `asset_type` |
| `create` | Cadastrar novo ativo | `name`, `asset_type` |
| `update` | Atualizar ativo | `asset_id` + campos |
| `delete` | Excluir ativo | `asset_id` |
| `get_reservations` | Reservas do ativo | `asset_id` |
| `create_reservation` | Criar reserva | `asset_id`, `user_id`, `date_start`, `date_end` |
| `update_reservation` | Atualizar reserva | `reservation_id` |

**Exemplos:**
```
"Cadastrar computador Dell OptiPlex 7090"
→ Params: {
    "action": "create",
    "asset_type": "Computer",
    "name": "Dell OptiPlex 7090",
    "serial_number": "SN-2024-001"
  }

"Detalhes do computador ID 150"
→ Params: { "action": "get_details", "asset_id": 150, "asset_type": "Computer" }
→ Retorna o ativo + seções "Sistema Operacional", "Discos", "Processadores",
   "Memorias", "Redes" e "Software Instalado" (até 25 itens).
```

---

## 3. ADMIN

### 3.1 `glpi_search_admin_resources`

Busca de usuários, grupos, entidades e localizações.

| Parâmetro | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `resource` | string | Não | `users`, `groups`, `entities`, `locations` (padrão: `users`) |
| `query` | string | Não | Busca por nome, sobrenome, email ou login |
| `entity_id` | integer | Não | Filtrar por entidade |
| `entity_name` | string | Não | Filtrar por nome da entidade |
| `limit` | integer | Não | Resultados (padrão: 10, máx: 50) |
| `offset` | integer | Não | Offset paginação |

**Exemplos:**
```
"Listar todos os técnicos"
→ Params: { "resource": "users", "limit": 50 }

"Buscar usuário pelo email joao@empresa.com"
→ Params: { "resource": "users", "query": "joao@empresa.com" }

"Listar entidades/clientes cadastrados"
→ Params: { "resource": "entities" }

"Listar grupos de suporte"
→ Params: { "resource": "groups" }
```

---

### 3.2 `glpi_manage_admin_resources`

Operações CRUD em recursos administrativos.

| Parâmetro | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `resource` | string | **Sim** | `users`, `groups`, `entities`, `locations` |
| `action` | string | **Sim** | `get`, `create`, `update`, `delete` (nota: `entities` só suporta `get`) |
| `resource_id` | integer | Condicional | ID do recurso (para get/update/delete). **Aceita 0 para `entities`** (root entity do GLPI) |
| `name` | string | Condicional | Nome/login (para create) |
| `email` | string | Não | Email do usuário |

**Matriz de suporte por `resource` × `action`:**

| Resource | get | create | update | delete |
|----------|:---:|:------:|:------:|:------:|
| `users` | ✅ | ✅ | ✅ | ✅ (soft delete por padrão, purge opcional) |
| `groups` | ✅ | ✅ | ✅ | ✅ (purge=true por padrão) |
| `locations` | ✅ | ✅ | ✅ | ✅ (purge=true por padrão) |
| `entities` | ✅ (id=0 permitido) | ❌ | ❌ | ❌ |

**Exemplos:**
```
"Detalhes do usuário ID 25"
→ Params: { "resource": "users", "action": "get", "resource_id": 25 }

"Detalhes da entidade raiz (MSP)"
→ Params: { "resource": "entities", "action": "get", "resource_id": 0 }

"Criar grupo N2-Infraestrutura"
→ Params: { "resource": "groups", "action": "create", "name": "N2-Infraestrutura" }

"Renomear location 508"
→ Params: { "resource": "locations", "action": "update", "resource_id": 508, "name": "Sede - 2º andar" }

"Remover grupo 68 definitivamente"
→ Params: { "resource": "groups", "action": "delete", "resource_id": 68 }
```

---

## 4. WEBHOOKS

### 4.1 `glpi_search_webhook_integrations`

Listagem e estatísticas de webhooks configurados.

| Parâmetro | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `scope` | string | Não | `list`, `stats`, `deliveries` (padrão: `list`) |
| `webhook_id` | string | Condicional | ID do webhook (**hash alfanumérico**, para `deliveries`) |
| `limit` | integer | Não | Resultados (padrão: 10, máx: 50) |
| `offset` | integer | Não | Offset paginação |

**Exemplos:**
```
"Listar webhooks configurados"
→ Params: { "scope": "list" }

"Estatísticas de entrega dos webhooks"
→ Params: { "scope": "stats" }

"Histórico de entregas do webhook 5"
→ Params: { "scope": "deliveries", "webhook_id": 5 }
```

---

### 4.2 `glpi_manage_webhook_integrations`

Gestão completa de webhooks e integrações.

| Parâmetro | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `action` | string | **Sim** | `get`, `create`, `update`, `delete`, `test`, `trigger`, `enable`, `disable`, `retry` |
| `webhook_id` | string | Condicional | ID do webhook (**hash alfanumérico**, ex: `2b27acbaca81c9e9694107d708d92dcf`) |
| `name` | string | Condicional | Nome (para `create`) |
| `url` | string | Condicional | URL callback HTTP(S) (para `create`) |
| `event_type` | string | Condicional | Tipo de evento (enum abaixo) |

**`event_type` — enum oficial (formato `recurso.acao`):**

- Tickets: `ticket.created`, `ticket.updated`, `ticket.deleted`, `ticket.assigned`
- Assets: `asset.created`, `asset.updated`, `asset.deleted`, `asset.reserved`
- Users: `user.created`, `user.updated`, `user.deleted`
- Groups: `group.created`, `group.updated`, `group.deleted`

> ⚠️ **Atenção:** Os nomes usam **ponto** (`.`), não underline. `ticket_created` é inválido.
>
> ⚠️ **Nota arquitetural:** A camada atual de webhooks do MCP usa storage in-memory (não sincroniza com a tabela `glpi_webhooks` nativa do GLPI 11). Webhooks não persistem após restart do servidor MCP.

**Exemplos:**
```
"Criar webhook para notificar o Teams quando um chamado for criado"
→ Params: {
    "action": "create",
    "name": "Teams - Novo Chamado",
    "url": "https://hooks.teams.com/webhook/xxx",
    "event_type": "ticket.created"
  }
→ Retorna: { "id": "2b27acbaca81c9e9694107d708d92dcf", ... }

"Testar conectividade do webhook"
→ Params: { "action": "test", "webhook_id": "2b27acbaca81c9e9694107d708d92dcf" }

"Desabilitar webhook"
→ Params: { "action": "disable", "webhook_id": "2b27acbaca81c9e9694107d708d92dcf" }
```

---

## 5. BRIDGE (Acesso a Resources e Prompts)

### 5.1 `glpi_list_available_resources`

Lista os resources MCP disponíveis para consulta. Sem parâmetros.

**Retorna:** Tabela com URIs, nomes e descrições dos 4 resources.

---

### 5.2 `glpi_read_resource_by_uri`

Lê o conteúdo de um resource MCP específico.

| Parâmetro | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `uri` | string | **Sim** | URI do resource |

**URIs disponíveis:**

| URI | Conteúdo |
|-----|----------|
| `glpi://entities` | Lista de entidades/clientes cadastrados |
| `glpi://ticket-status` | Mapa de códigos de status (1=Novo, 2=Atribuído...) |
| `glpi://ticket-categories` | Árvore de categorias de chamado |
| `glpi://priorities` | Níveis de prioridade (1=Muito baixa a 6=Maior) |

**Exemplo:**
```
"Quais são os status possíveis de um chamado?"
→ Params: { "uri": "glpi://ticket-status" }
```

---

### 5.3 `glpi_list_available_prompts`

Lista os 15 prompts profissionais disponíveis. Sem parâmetros.

**Retorna:** Tabela com nomes, descrições e públicos-alvo dos prompts.

---

### 5.4 `glpi_get_prompt_template`

Executa um prompt específico com argumentos customizados.

| Parâmetro | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `name` | string | **Sim** | Nome do prompt |
| `arguments` | object | Não | Argumentos chave-valor para o prompt |

**Exemplo:**
```
"Gerar relatório de SLA dos últimos 60 dias para Skills IT"
→ Params: {
    "name": "glpi_sla_performance",
    "arguments": { "entity_name": "Skills IT", "period_days": 60 }
  }
```

(Ver [Referência de Prompts](./PROMPTS-REFERENCE.md) para lista completa)

---

## 6. CONHECIMENTO

### 6.1 `glpi_search_knowledge_articles`

Busca na base de conhecimento e artigos técnicos.

| Parâmetro | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `query` | string | **Sim** | Texto de busca (mín. 2 caracteres) |
| `limit` | integer | Não | Resultados (padrão: 10, máx: 50) |

**Exemplos:**
```
"Buscar artigos sobre configuração de VPN"
→ Params: { "query": "configuração VPN", "limit": 10 }

"Buscar solução para erro de impressão"
→ Params: { "query": "erro impressão" }
```

---

## Anotações MCP

Todas as tools incluem anotações que indicam ao LLM o tipo de operação:

| Tool | ReadOnly | Destructive | Idempotent |
|------|:--------:|:-----------:|:----------:|
| Tools `search_*` | Sim | Nao | Sim |
| Tools `manage_*` | Nao | Sim | Nao |
| Tools `list_*`/`read_*` | Sim | Nao | Sim |
| `search_knowledge_articles` | Sim | Nao | Sim |
