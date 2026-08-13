# GLPI MCP Server — Referência de Tools

> 17 ferramentas consolidadas organizadas em 7 domínios
> (18 quando `ENABLE_AI_ANALYSIS=true` — ver 1.3)
>
> **Versão:** 2.2.0 (Agosto 2026) · **GLPI:** 10.x e 11.x

## Sumário

| # | Tool | Domínio | Tipo |
|---|------|---------|------|
| 1 | `glpi_search_helpdesk_tickets` | Tickets | Leitura |
| 2 | `glpi_manage_ticket_operations` | Tickets | Escrita |
| 3 | `glpi_manage_ticket_ai_analysis` | Tickets | Escrita — **desativada por padrão** |
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
| 15 | `glpi_search_knowledge_unified` | Conhecimento | Leitura |
| 16 | `glpi_search_itil_records` | ITIL | Leitura |
| 17 | `glpi_manage_itil_records` | ITIL | Escrita |
| 18 | `glpi_search_records_by_criteria` | Consulta livre | Leitura |

### Como escolher a tool

| A pergunta é sobre… | Use |
|---------------------|-----|
| Chamados / incidentes / requisições | `glpi_search_helpdesk_tickets`, `glpi_manage_ticket_operations` |
| Problemas, mudanças (RFC), projetos, contratos, fornecedores | `glpi_search_itil_records`, `glpi_manage_itil_records` |
| Equipamentos, inventário, reservas | `glpi_search_asset_inventory`, `glpi_manage_asset_operations` |
| Usuários, grupos, entidades, localizações | `glpi_search_admin_resources`, `glpi_manage_admin_resources` |
| Algo que não cabe nos filtros prontos, contagem barata ou descoberta de campos | `glpi_search_records_by_criteria` |

> **Convenção:** `glpi_search_*` é sempre somente leitura; `glpi_manage_*` executa escrita.
> As tools específicas são preferíveis à consulta livre — elas já trazem colunas
> formatadas e nomes resolvidos. Use `glpi_search_records_by_criteria` como escape hatch.

---

## 1. TICKETS

### 1.1 `glpi_search_helpdesk_tickets`

Busca e listagem de chamados, tickets e incidentes no GLPI.

**Quando usar:** Para consultar chamados abertos, pendentes ou fechados de um cliente.

| Parâmetro | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `status` | string | Não | `new`, `assigned`, `planned`, `pending`, `solved`, `closed` |
| `priority` | integer | Não | Prioridade: 1 (muito baixa) a 5 (muito alta), 6 (maior) |
| `urgency` | integer | Não | **Eixo distinto de prioridade** — 1 a 5. No GLPI a prioridade é derivada de urgência + impacto |
| `query` | string | Não | Busca textual em **título e conteúdo** (mín. 2 caracteres) |
| `date_after` | string | Não | Criado a partir de. Aceita `YYYY-MM-DD`, `DD/MM/YYYY`, ISO com hora ou `hoje`/`ontem`/`amanha` |
| `date_before` | string | Não | Criado até. Mesmos formatos |
| `assigned_tech` | string | Não | Técnico atribuído — **nome** (parcial) ou ID numérico |
| `assigned_group` | string | Não | Grupo técnico atribuído — **nome** (parcial) ou ID numérico |
| `requester` | string | Não | Solicitante que abriu — **nome** (parcial) ou ID numérico |
| `category` | string | Não | Categoria ITIL — **nome** (parcial) ou ID numérico |
| `open_only` | boolean | Não | Somente chamados em aberto (exclui solucionados e fechados). Ignorado quando `status` é informado |
| `sort_by` | string | Não | `date`, `date_mod`, `priority`, `urgency`, `status`, `name`, `category`, `solvedate`, `closedate`. Padrão: `date_mod` |
| `order` | string | Não | `asc` ou `desc` (padrão: `desc`) |
| `entity_id` | integer | Não | **Opcional** — o token já fixa o tenant. Use só para uma sub-entidade |
| `entity_name` | string | Não | **Opcional** — nome de uma sub-entidade, resolvido automaticamente |
| `limit` | integer | Não | Resultados por página (padrão: 10, máx: 50) |
| `offset` | integer | Não | Offset para paginação (padrão: 0) |

> **Filtros combinam.** `query` roda em conjunto com `status`, `priority`, datas e os
> filtros de ator — a busca textual não descarta os demais critérios.

**Exemplos:**
```
"Listar chamados abertos"
→ Tool: glpi_search_helpdesk_tickets
→ Params: { "open_only": true, "limit": 20 }
```

```
"Buscar chamados sobre impressora que ainda estão abertos"
→ Params: { "query": "impressora", "open_only": true }
```

```
"Chamados do grupo Infraestrutura"
→ Params: { "assigned_group": "Infraestrutura" }
```

```
"O que está atribuído ao João?"
→ Params: { "assigned_tech": "João", "open_only": true }
```

```
"Chamados urgentes da categoria Rede"
→ Params: { "urgency": 5, "category": "Rede" }
```

```
"Chamados mais antigos primeiro"
→ Params: { "sort_by": "date", "order": "asc" }
```

```
"Chamados abertos hoje pelo solicitante Maria"
→ Params: { "requester": "Maria", "date_after": "hoje", "date_before": "hoje" }
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
| `date_from` | string | Não | Data inicial para `get_stats` (`YYYY-MM-DD`, `DD/MM/YYYY`, `hoje`/`ontem`/`amanha`) |
| `date_to` | string | Não | Data final para `get_stats` |
| `is_private` | boolean | Não | Acompanhamento ou tarefa visível só para técnicos (padrão: false) |
| `actiontime` | integer | Não | Duração prevista da tarefa em **segundos** (`add_task`). Ex.: 3600 = 1 hora |
| `task_category_id` | integer | Não | ID da categoria da tarefa (`add_task`) |
| `approver` | string | Condicional | Aprovador (`request_validation`) — **nome/login** ou ID. Nome ambíguo é recusado com a lista de candidatos |
| `validation_id` | integer | Não | ID da aprovação (`answer_validation`). Se omitido e houver **uma única** pendente, é resolvida automaticamente |
| `validation_status` | string | Condicional | `aprovado` ou `recusado` (`answer_validation`) |
| `comment` | string | Condicional | Comentário da aprovação — **obrigatório ao recusar** |
| `group` | string | Condicional | Grupo/equipe (`assign_group`) — **nome** ou ID. Nome ambíguo é recusado com a lista de candidatos |
| `group_type` | string | Não | Papel do grupo: `assigned` (padrão), `requester`, `observer` |
| `linked_ticket_id` | integer | Condicional | Outro chamado a vincular (`link_tickets`) |
| `link_type` | string | Não | `link` (padrão), `duplicate`, `son`, `parent` |
| `file_path` | string | Condicional | Caminho do arquivo **no servidor** (`add_document`). Limite 25 MB |
| `file_base64` | string | Condicional | Conteúdo do arquivo em base64 (alternativa a `file_path`). Exige `file_name` |
| `file_name` | string | Condicional | Nome com extensão (obrigatório com `file_base64`) — a extensão define o MIME type |
| `document_title` | string | Não | Título do documento no GLPI (padrão: o nome do arquivo) |
| `limit` | integer | Não | Máx. de eventos em `get_timeline` (padrão: 100, mantém os mais recentes) |
| `confirmation_token` | string | Condicional | Exigido em operações destrutivas quando o safety guard está ativo |
| `reason` | string | Condicional | Motivo da operação destrutiva (mín. 10 caracteres) com safety guard ativo |

**Ações disponíveis:**

*Consulta*

| Action | Descrição | Parâmetros obrigatórios |
|--------|-----------|------------------------|
| `get` | Consultar detalhes de um chamado | `ticket_id` |
| `get_by_number` | Buscar chamado pelo número | `ticket_number` |
| `get_followups` | Listar acompanhamentos | `ticket_id` |
| `get_history` | Histórico de alterações | `ticket_id` |
| `get_timeline` | **Linha do tempo unificada**: acompanhamentos + tarefas + soluções + aprovações em ordem cronológica | `ticket_id` (+ `limit` opcional) |
| `get_tasks` | Listar tarefas do chamado | `ticket_id` |
| `get_validations` | Listar aprovações do chamado | `ticket_id` |
| `get_stats` | Estatísticas agregadas por status (`by_status`: new/assigned/planned/pending/solved/closed). Filtros opcionais: `entity_id`, `date_from`, `date_to` | nenhum |
| `find_similar` | Encontrar chamados similares por conteúdo do ticket de referência | `ticket_id` (+ `threshold`, `max_results` opcionais) |

*Escrita*

| Action | Descrição | Parâmetros obrigatórios |
|--------|-----------|------------------------|
| `create` | Abrir novo chamado | `title`, `description` |
| `update` | Atualizar dados do chamado | `ticket_id` + campos a alterar |
| `delete` | Excluir chamado | `ticket_id` |
| `assign` | Atribuir **técnico** ao chamado | `ticket_id`, `user_id` |
| `assign_group` | Atribuir **grupo/equipe** ao chamado | `ticket_id`, `group` (+ `group_type` opcional) |
| `close` | Fechar chamado com solução | `ticket_id`, `solution` |
| `resolve` | Resolver chamado | `ticket_id`, `solution` |
| `add_followup` | Adicionar acompanhamento | `ticket_id`, `content` |
| `add_task` | Adicionar tarefa (com duração prevista) | `ticket_id`, `content` (+ `actiontime`, `task_category_id`, `is_private`) |
| `add_document` | Anexar arquivo ao chamado | `ticket_id` + (`file_path` **ou** `file_base64` + `file_name`) |
| `link_tickets` | Vincular dois chamados | `ticket_id`, `linked_ticket_id` (+ `link_type`) |
| `request_validation` | Pedir aprovação a um usuário | `ticket_id`, `approver` |
| `answer_validation` | Aprovar ou recusar uma aprovação | `ticket_id`, `validation_status` (+ `comment` se recusar) |

**Exemplos:**

```
"Abrir chamado para o usuário João sobre problema de VPN"
→ action: "create"
→ Params: {
    "action": "create",
    "title": "Problema de conexão VPN - João Silva",
    "description": "Usuário João Silva não consegue conectar na VPN desde hoje às 9h.",
    "priority": 3
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

```
"Linha do tempo completa do chamado 542"
→ action: "get_timeline"
→ Params: { "action": "get_timeline", "ticket_id": 542, "limit": 100 }
→ Retorna acompanhamentos, tarefas, soluções e aprovações intercalados em ordem
   cronológica — o histórico que antes exigia 4 chamadas separadas.
```

```
"Atribuir o chamado 542 para o grupo Infraestrutura"
→ action: "assign_group"
→ Params: {
    "action": "assign_group",
    "ticket_id": 542,
    "group": "Infraestrutura"
  }
→ group_type controla o papel: "assigned" (padrão), "requester" ou "observer".
```

```
"Registrar tarefa de 2 horas no chamado 542"
→ action: "add_task"
→ Params: {
    "action": "add_task",
    "ticket_id": 542,
    "content": "Substituição do switch de borda e testes de link.",
    "actiontime": 7200,
    "is_private": false
  }
```

```
"Pedir aprovação da gerente para o chamado 542"
→ action: "request_validation"
→ Params: { "action": "request_validation", "ticket_id": 542, "approver": "Maria" }
→ Nome ambíguo é recusado com a lista de candidatos, em vez de escolher um.
```

```
"Recusar a aprovação pendente do chamado 542"
→ action: "answer_validation"
→ Params: {
    "action": "answer_validation",
    "ticket_id": 542,
    "validation_status": "recusado",
    "comment": "Janela de manutenção não aprovada para esta semana."
  }
→ Com uma única aprovação pendente, validation_id é opcional.
```

```
"Marcar o chamado 543 como duplicado do 542"
→ action: "link_tickets"
→ Params: {
    "action": "link_tickets",
    "ticket_id": 543,
    "linked_ticket_id": 542,
    "link_type": "duplicate"
  }
```

```
"Anexar o log ao chamado 542"
→ action: "add_document"
→ Params: {
    "action": "add_document",
    "ticket_id": 542,
    "file_path": "/var/log/exemplo/coleta.txt",
    "document_title": "Log da coleta"
  }
→ Sem caminho no servidor: file_base64 + file_name (a extensão define o MIME type).
```

---

### 1.3 `glpi_manage_ticket_ai_analysis`

> ⚠️ **Desativada por padrão — não aparece em `tools/list`.**
> Ative com `ENABLE_AI_ANALYSIS=true` **somente** depois de existir um agente de IA
> real por trás. Hoje o `AIIntegrationService` é um job store em memória que nunca
> chama o GLPI: `trigger` responde "disparada com sucesso" para qualquer `ticket_id`
> (inclusive um que não existe) e `publish` responde "realizada com sucesso" sem
> escrever nada no chamado. Auditoria de 12/08/2026.

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
| `assigned_user` | string | Não | Responsável pelo ativo — **nome** (parcial) ou ID numérico. Não se aplica a `scope=software` |
| `status` | string | Não | Situação do ativo (`states_id`) — ID numérico do estado |
| `location_id` | integer | Não | ID da localização |
| `manufacturer_id` | integer | Não | ID do fabricante |
| `user_id` | integer | Não | ID do usuário vinculado. Prefira `assigned_user`, que também aceita nome |
| `sort_by` | string | Não | `name`, `id`, `serial`, `location`, `manufacturer`, `model`, `status`, `user`, `date_mod` |
| `order` | string | Não | `asc` ou `desc`. Sem `sort_by`, aplica a direção ao nome do ativo |
| `entity_id` | integer | Não | **Opcional** — o token já fixa o tenant. Use só para uma sub-entidade |
| `entity_name` | string | Não | **Opcional** — nome de uma sub-entidade |
| `limit` | integer | Não | Resultados (padrão: 10, máx: 50) |
| `offset` | integer | Não | Offset paginação |

> **Filtros combinam com a busca textual.** `query` roda em conjunto com fabricante,
> localização e situação — o texto não anula os demais critérios.

**Exemplos:**
```
"Listar todos os computadores da empresa"
→ Params: { "scope": "computers", "limit": 50 }

"Buscar equipamento pelo serial ABC123"
→ Params: { "query": "ABC123" }

"Quais equipamentos estão com o João?"
→ Params: { "assigned_user": "João" }

"Notebooks Dell em estoque"
→ Params: { "scope": "computers", "manufacturer_id": 12, "status": "3" }

"Equipamentos em ordem alfabética"
→ Params: { "scope": "computers", "sort_by": "name", "order": "asc" }

"Equipamentos alterados recentemente"
→ Params: { "sort_by": "date_mod", "order": "desc" }

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
| `query` | string | Não | Busca por nome, sobrenome, email ou login (aplica-se a `users`) |
| `sort_by` | string | Não | `name`, `id`, `email`, `firstname`, `realname`, `comment`, `entity`, `location`, `date_mod`, `date_creation`, `last_login`. Campo que o recurso não possui cai no nome |
| `order` | string | Não | `asc` ou `desc`. Sem `sort_by`, aplica a direção ao nome do recurso |
| `entity_id` | integer | Não | **Opcional** — filtrar por uma sub-entidade |
| `entity_name` | string | Não | **Opcional** — filtrar pelo nome de uma sub-entidade |
| `limit` | integer | Não | Resultados (padrão: 10, máx: 50) |
| `offset` | integer | Não | Offset paginação |

> **O filtro de entidade vale para todos os recursos**, inclusive `groups` e `locations` —
> a listagem passa pelo endpoint de busca, que respeita critérios.

**Exemplos:**
```
"Listar todos os técnicos"
→ Params: { "resource": "users", "limit": 50 }

"Buscar usuário pelo email joao@empresa.com"
→ Params: { "resource": "users", "query": "joao@empresa.com" }

"Usuários cadastrados recentemente"
→ Params: { "resource": "users", "sort_by": "date_creation", "order": "desc" }

"Quem entrou por último?"
→ Params: { "resource": "users", "sort_by": "last_login", "order": "desc" }

"Listar entidades/clientes cadastrados"
→ Params: { "resource": "entities" }

"Grupos de uma sub-entidade específica, em ordem alfabética"
→ Params: { "resource": "groups", "entity_id": 4, "sort_by": "name", "order": "asc" }
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
> ℹ️ **Nota arquitetural:** os webhooks são gravados no **backend nativo do GLPI 11**
> (`/apirest.php/Webhook`), e não em memória do processo MCP. Eles persistem a
> reinícios do servidor e aparecem na própria interface do GLPI. Em instâncias onde
> o endpoint não está disponível, a tool responde com um aviso explícito em vez de
> criar um registro fantasma.

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
"Gerar relatório de SLA dos últimos 60 dias para a Acme Corp"
→ Params: {
    "name": "glpi_sla_performance",
    "arguments": { "entity_name": "Acme Corp", "period_days": 60 }
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

### 6.2 `glpi_search_knowledge_unified`

Base de conhecimento unificada: busca **semântica (pgvector) + textual** em chamados
resolvidos, artigos de ajuda e posts de comunidade, com ranking RRF que mistura as
fontes e rotula cada item.

**Diferença para 6.1:** `glpi_search_knowledge_articles` consulta apenas os artigos
nativos via REST. Esta tool cruza também o histórico de chamados já resolvidos.

| Parâmetro | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `query` | string | **Sim** | Dúvida, erro ou sintoma (mín. 2 caracteres) |
| `source` | string | Não | `all` (padrão, todas com RRF), `chamados`, `help`, `comunidade` |
| `limit` | integer | Não | Resultados (padrão: 15, máx: 50) |
| `tenant` | string | Não | Restringe a uma entidade/cliente. Itens globais sempre aparecem |

**Saída** — tabela Markdown com as colunas:

| Coluna | Conteúdo |
|--------|----------|
| `#` | Posição final no ranking RRF — **esta** é a ordem autoritativa |
| `Fonte` / `Oficial` | Rótulo da origem e se é conteúdo oficial |
| `ID` | Identificador do item dentro da fonte |
| `Titulo` | Título do item. Quando o título **se repete** no conjunto de resultados (típico de instâncias com formulário, onde o título é o nome do formulário), vem acompanhado de um trecho do problema para diferenciar as linhas |
| `Solucao` | A resolução aplicada. Em fontes de chamados, quando não há resolução registrada, exibe `(resolvido, sem descricao da solucao)` — todo item indexado já está resolvido, então o que falta é o registro do que foi feito, não a solução. Documentação e fórum exibem `—` |
| `Contexto` | Categoria / breadcrumb |
| `Sim.` | Similaridade vetorial bruta da fonte — **informativa**, não é a chave de ordenação e não é comparável entre fontes |
| `URL` | Link para o item |

> A coluna `Solucao` evita o passo mais caro do fluxo: sem ela é preciso abrir
> cada resultado só para descobrir o que foi feito. Textos longos são cortados e
> o corte é marcado com reticências.

**Exemplos:**
```
"Já resolvemos algo parecido com 'erro 0x80070005'?"
→ Params: { "query": "erro 0x80070005", "source": "chamados" }

"Como configurar VPN — qualquer fonte"
→ Params: { "query": "configurar VPN", "limit": 10 }
```

---

## 7. ITIL (Problemas, Mudanças, Projetos, Contratos, Fornecedores)

Os registros ITIL que ficam **além do chamado comum**. Ambas as tools cobrem os mesmos
cinco tipos, selecionados por `record_type`.

| `record_type` | O que é |
|---------------|---------|
| `problems` | Problemas / análise de causa raiz |
| `changes` | Mudanças / RFC |
| `projects` | Projetos |
| `contracts` | Contratos |
| `suppliers` | Fornecedores |

### 7.1 `glpi_search_itil_records`

Busca e listagem dos registros ITIL. **Somente leitura.**

| Parâmetro | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `record_type` | string | **Sim** | `problems`, `changes`, `projects`, `contracts`, `suppliers` |
| `query` | string | Não | Busca textual no título/nome (mín. 2 caracteres) |
| `status` | string | Não | Situação. Problemas/mudanças: nome do status. Projetos/contratos: o estado. Fornecedores: ativo ou inativo |
| `priority` | integer | Não | 1 (muito baixa) a 6 (maior). Não se aplica a contratos e fornecedores |
| `urgency` | integer | Não | 1 a 5. Apenas problemas e mudanças |
| `category` | string | Não | Categoria ITIL ou tipo — **nome** ou ID numérico |
| `date_from` | string | Não | Início do período (`AAAA-MM-DD`, `DD/MM/AAAA`, `hoje`, `ontem`) |
| `date_to` | string | Não | Fim do período |
| `date_field` | string | Não | Coluna de data do período. Padrão: abertura (problemas/mudanças/projetos), início de vigência (contratos), cadastro (fornecedores) |
| `sort_by` | string | Não | Campo de ordenação (nome ou ID). Campo desconhecido cai no padrão do tipo |
| `order` | string | Não | `asc` ou `desc` (padrão: `desc`) |
| `entity_id` / `entity_name` | — | Não | **Opcional** — só para sub-entidade |
| `limit` | integer | Não | Resultados (padrão: 10, máx: 50) |
| `offset` | integer | Não | Offset paginação |
| `count_only` | boolean | Não | Retorna **apenas o total**, sem trazer os registros — consulta barata para perguntas de volume |

**Exemplos:**
```
"Quais problemas estão abertos?"
→ Params: { "record_type": "problems", "status": "new" }

"Mudanças planejadas para este mês"
→ Params: {
    "record_type": "changes",
    "date_from": "2026-08-01",
    "date_to": "2026-08-31"
  }

"Contratos vencendo — ordenados pelo fim da vigência"
→ Params: { "record_type": "contracts", "sort_by": "end_date", "order": "asc" }

"Quantos fornecedores temos cadastrados?" (sem listar)
→ Params: { "record_type": "suppliers", "count_only": true }
```

---

### 7.2 `glpi_manage_itil_records`

Operações sobre **um** registro ITIL.

| Action | Descrição | Parâmetros obrigatórios |
|--------|-----------|------------------------|
| `get` | Consultar detalhes | `record_id` |
| `create` | Cadastrar | `name` |
| `update` | Alterar | `record_id` + campos |
| `delete` | Excluir | `record_id` |
| `add_followup` | Comentar | `record_id`, `followup_content` |
| `get_followups` | Listar comentários | `record_id` |
| `link_ticket` | Vincular chamado (só `problems` e `changes`) | `record_id`, `ticket_id` |

**Parâmetros comuns:** `record_type` (**obrigatório**), `action` (**obrigatório**),
`record_id`, `name`, `content`, `comment`, `status`, `entity_id` / `entity_name`.

**Parâmetros por tipo:**

| Escopo | Parâmetros |
|--------|-----------|
| Problemas e mudanças | `priority` (1–6), `urgency` (1–5), `impact` (1–5), `category_id`, `ticket_id` |
| Projetos | `state_id`, `begin_date`, `end_date`, `manager_id`, `percent_done` (0–100), `code` |
| Contratos | `state_id`, `begin_date`, `duration` (meses), `periodicity` (meses), `num`. O GLPI calcula o fim a partir do início + duração |
| Fornecedores | `is_active`, `email`, `phone`, `website` |

**Outros:** `followup_content` e `is_private` (comentário), `fields` (objeto
chave-valor para colunas não cobertas acima), `purge` (padrão `false` = lixeira),
`confirmation_token` e `reason` (exclusão com safety guard ativo).

**Exemplos:**
```
"Abrir um problema a partir de chamados repetidos de lentidão"
→ Params: {
    "record_type": "problems",
    "action": "create",
    "name": "Lentidão recorrente na rede do 2º andar",
    "content": "5 chamados nas últimas 2 semanas com o mesmo sintoma.",
    "priority": 4,
    "urgency": 4
  }

"Vincular o chamado 542 ao problema 8"
→ Params: {
    "record_type": "problems",
    "action": "link_ticket",
    "record_id": 8,
    "ticket_id": 542
  }

"Cadastrar contrato de suporte de 12 meses"
→ Params: {
    "record_type": "contracts",
    "action": "create",
    "name": "Suporte Anual - Acme Corp",
    "num": "CT-2026-014",
    "begin_date": "2026-09-01",
    "duration": 12,
    "periodicity": 12
  }

"Cadastrar fornecedor"
→ Params: {
    "record_type": "suppliers",
    "action": "create",
    "name": "Acme Distribuidora",
    "email": "contato@exemplo.com",
    "phone": "+55 00 0000-0000"
  }

"Atualizar o andamento do projeto 3"
→ Params: {
    "record_type": "projects",
    "action": "update",
    "record_id": 3,
    "percent_done": 60
  }
```

---

## 8. CONSULTA LIVRE

### 8.1 `glpi_search_records_by_criteria`

Consulta por critérios livres em **qualquer itemtype** do GLPI, quando a pergunta não
cabe nos filtros prontos das outras tools.

> **Ferramenta de apoio.** Prefira as tools específicas quando elas atenderem — elas já
> trazem colunas formatadas e nomes resolvidos. Use esta como escape hatch, para contar
> sem paginar ou para descobrir quais campos existem.

| Parâmetro | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `itemtype` | string | **Sim** | `Ticket`, `Computer`, `User`, `Problem`, `Change`, `Contract`, `Supplier`, `Software`, `Monitor`, `Printer`, `KnowbaseItem`, … |
| `scope` | string | Não | `search` (padrão, traz os registros), `count` (só o total), `fields` (lista os campos disponíveis) |
| `criteria` | array | Não | Lista de condições — ver estrutura abaixo |
| `fields` | array | Não | Colunas a retornar, por **nome** ou ID. Campo desconhecido é ignorado com aviso |
| `sort_by` | string | Não | Campo de ordenação, por nome ou ID |
| `order` | string | Não | `asc` ou `desc` |
| `limit` | integer | Não | Resultados (padrão: 10, máx: 50) |
| `offset` | integer | Não | Offset paginação |
| `field_filter` | string | Não | Com `scope=fields`: filtra os campos por um trecho do nome (ex.: `data`, `status`) |

**Estrutura de cada item de `criteria`:**

| Chave | Descrição |
|-------|-----------|
| `field` | **Nome do campo** (ex.: `status`, `name`) ou ID numérico |
| `searchtype` | `contains`, `equals`, `notequals`, `lessthan`, `morethan`, `under`, `empty` |
| `value` | Valor a comparar |
| `link` | `AND` ou `OR` — aplicado a partir da **segunda** condição |

**Os três escopos:**

```
# 1. scope=fields — descobrir o que dá para filtrar
"Quais campos de data existem em Ticket?"
→ Params: { "itemtype": "Ticket", "scope": "fields", "field_filter": "data" }
→ Rótulos repetidos são desambiguados pela tabela de origem
   (ex.: "Nome" vs "Nome (users)"), então o id anunciado é o que a busca usa.

# 2. scope=count — sonda barata, sem paginar
"Quantos computadores existem no total?"
→ Params: { "itemtype": "Computer", "scope": "count" }

# 3. scope=search — os registros
"Chamados com 'backup' no título abertos depois de julho"
→ Params: {
    "itemtype": "Ticket",
    "scope": "search",
    "criteria": [
      { "field": "name", "searchtype": "contains", "value": "backup" },
      { "field": "date", "searchtype": "morethan", "value": "2026-07-01", "link": "AND" }
    ],
    "fields": ["id", "name", "status", "date"],
    "sort_by": "date",
    "order": "desc"
  }
```

> **Campos por nome, não por id.** O nome é resolvido contra o catálogo de search
> options da **sua** instância, então o mesmo parâmetro funciona em instâncias que
> numeram os campos de forma diferente. IDs numéricos continuam aceitos.

---

## Anotações MCP

Todas as tools incluem anotações que indicam ao LLM o tipo de operação:

| Tool | ReadOnly | Destructive | Idempotent |
|------|:--------:|:-----------:|:----------:|
| Tools `search_*` | Sim | Nao | Sim |
| Tools `manage_*` | Nao | Sim | Nao |
| Tools `list_*`/`read_*` | Sim | Nao | Sim |
| `search_knowledge_articles` | Sim | Nao | Sim |

---

## Garantias de escrita

### Idempotência

Operações de criação passam por um guarda de idempotência: **repetir exatamente a
mesma chamada não cria um segundo registro**. A chave é o próprio conteúdo da chamada,
então uma retentativa do cliente (ou um clique duplo do LLM) recebe de volta o
resultado da primeira execução, marcado com `replayed: true`, sem tocar no GLPI.

Cobre as ações do tipo criação: `create`, `add_followup`, `add_task`, `add_document`,
`link_tickets`, `request_validation` e `create_reservation`.

O armazenamento padrão é **SQLite persistente** (`var/idempotency/store.sqlite3`), o
que mantém a garantia entre reinícios e entre workers do mesmo servidor. Um backend
apenas em memória também está disponível. Se o armazenamento falhar, a operação **não
é bloqueada** — ela executa normalmente e o modo degradado é registrado no log.

### Retentativas e escrita

A camada de requisição faz retentativa com espera exponencial e jitter, e respeita o
`Retry-After` quando o GLPI responde `429`. A regra que importa:

> **Escrita nunca é repetida depois que o servidor respondeu.** O GLPI pode ter
> aplicado a escrita antes de falhar, e uma retentativa criaria um segundo chamado ou
> um acompanhamento duplicado. Só são repetidas as falhas comprovadamente **anteriores**
> ao envio (conexão recusada, timeout de conexão) e o `429`, em que o servidor recusou
> sem processar. Timeout de leitura/escrita e erro `5xx` só são repetidos em `GET`.

### Política de escrita

Cada operação de escrita tem uma variável de ambiente própria, além de um interruptor
global de somente-leitura. Ver [Guia Rápido](./QUICK-START.md#política-de-escrita)
para a lista de variáveis e os padrões.
