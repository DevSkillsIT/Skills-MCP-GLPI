# GLPI MCP Server — Exemplos de Uso

> Cenários completos do dia a dia de suporte com as tools e prompts do MCP GLPI
>
> **Versão:** 2.1.0 (April 2026) · **Cobertura:** 14 tools × todas as actions

---

## Cenário 1: Triagem de Chamados do Dia

**Situação:** Início do turno, técnico precisa ver o que está pendente.

### Passo 1 — Ver chamados novos
```
Usuário: "Quais chamados novos temos hoje?"

Tool: glpi_search_ticket_requests
Params: { "status": "new", "limit": 20 }
```

### Passo 2 — Filtrar por prioridade alta
```
Usuário: "Algum chamado urgente?"

Tool: glpi_search_ticket_requests
Params: { "status": "new", "priority": 5, "limit": 10 }
```

### Passo 3 — Ver detalhes de um chamado específico
```
Usuário: "Me mostra o chamado 542"

Tool: glpi_manage_ticket_operations
Params: { "action": "get", "ticket_id": 542 }
```

### Passo 4 — Atribuir para si mesmo
```
Usuário: "Vou pegar esse chamado. Meu ID é 15."

Tool: glpi_manage_ticket_operations
Params: { "action": "assign", "ticket_id": 542, "user_id": 15 }
```

---

## Cenário 2: Abrir e Resolver um Chamado Completo

**Situação:** Usuário liga reportando que não consegue acessar o e-mail.

### Passo 1 — Abrir o chamado
```
Tool: glpi_manage_ticket_operations
Params: {
  "action": "create",
  "title": "Sem acesso ao e-mail - Maria Santos",
  "description": "Usuária Maria Santos (Financeiro) não consegue acessar o Outlook desde 8h. Erro: 'Não foi possível conectar ao servidor'. Outros usuários do setor estão normais.",
  "priority": 3,
  "entity_name": "Skills IT"
}
```

### Passo 2 — Buscar chamados similares (pelo ticket de referência)
```
Tool: glpi_manage_ticket_operations
Params: {
  "action": "find_similar",
  "ticket_id": 600,
  "threshold": 0.3,
  "max_results": 5
}
```
> ⚠️ Desde a v2.1 `find_similar` usa o conteúdo do `ticket_id` como referência
> (não aceita mais `query`).

### Passo 3 — Consultar base de conhecimento
```
Tool: glpi_search_knowledge_articles
Params: { "query": "Outlook não conecta servidor" }
```

### Passo 4 — Adicionar acompanhamento
```
Tool: glpi_manage_ticket_operations
Params: {
  "action": "add_followup",
  "ticket_id": 600,
  "content": "Verificado: perfil do Outlook corrompido. Recriando perfil e reconfigurando a conta Exchange."
}
```

### Passo 5 — Resolver o chamado
```
Tool: glpi_manage_ticket_operations
Params: {
  "action": "resolve",
  "ticket_id": 600,
  "solution": "Perfil do Outlook estava corrompido. Solução: 1) Removido perfil antigo via Painel de Controle > Mail. 2) Criado novo perfil. 3) Reconfigurada conta Exchange com autodiscover. 4) Testado envio/recebimento OK."
}
```

---

## Cenário 3: Inventário e Gestão de Ativos

**Situação:** Gestor precisa de um panorama do parque de TI.

### Passo 1 — Estatísticas gerais
```
Tool: glpi_search_asset_inventory
Params: { "scope": "stats" }
```

### Passo 2 — Listar computadores de uma entidade
```
Tool: glpi_search_asset_inventory
Params: { "scope": "computers", "entity_name": "Acme Corp", "limit": 50 }
```

### Passo 3 — Buscar equipamento pelo serial
```
Tool: glpi_search_asset_inventory
Params: { "query": "SN-2024-001" }
```

### Passo 4 — Cadastrar novo equipamento
```
Tool: glpi_manage_asset_operations
Params: {
  "action": "create",
  "asset_type": "Computer",
  "name": "NB-MKT-015 Dell Latitude 5540",
  "serial_number": "ABC123XYZ"
}
```

### Passo 5 — Análise de ROI do parque
```
Tool: glpi_get_prompt_template
Params: { "name": "glpi_asset_roi", "arguments": { "entity_name": "Acme Corp" } }
```

---

## Cenário 4: Relatórios Gerenciais (Reunião Mensal)

**Situação:** Gestor precisa preparar relatórios para reunião com diretoria.

### Relatório 1 — Performance de SLA
```
Tool: glpi_get_prompt_template
Params: {
  "name": "glpi_sla_performance",
  "arguments": { "entity_name": "Skills IT", "period_days": 30 }
}
```

### Relatório 2 — Produtividade da equipe
```
Tool: glpi_get_prompt_template
Params: {
  "name": "glpi_technician_productivity",
  "arguments": { "period_days": 30 }
}
```

### Relatório 3 — Tendências de chamados
```
Tool: glpi_get_prompt_template
Params: {
  "name": "glpi_ticket_trends",
  "arguments": { "period_days": 90 }
}
```

### Relatório 4 — Problemas recorrentes
```
Tool: glpi_get_prompt_template
Params: {
  "name": "glpi_recurring_problems",
  "arguments": { "min_occurrences": 3 }
}
```

### Relatório 5 — Satisfação do cliente
```
Tool: glpi_get_prompt_template
Params: {
  "name": "glpi_client_satisfaction",
  "arguments": { "period_days": 30 }
}
```

---

## Cenário 5: Onboarding de Novo Colaborador

**Situação:** RH informou que Ana Oliveira começa segunda-feira no setor Marketing.

### Passo 1 — Gerar checklist de onboarding
```
Tool: glpi_get_prompt_template
Params: {
  "name": "glpi_onboarding_checklist",
  "arguments": { "username": "Ana Oliveira", "entity_name": "Skills IT" }
}
```

### Passo 2 — Requisitar hardware
```
Tool: glpi_get_prompt_template
Params: {
  "name": "glpi_hardware_request",
  "arguments": { "user_name": "Ana Oliveira", "hardware_type": "Notebook Dell Latitude 5540 + Monitor 24pol" }
}
```

### Passo 3 — Abrir chamado de preparação
```
Tool: glpi_manage_ticket_operations
Params: {
  "action": "create",
  "title": "Onboarding TI - Ana Oliveira (Marketing) - Início 31/03",
  "description": "Preparação de estação de trabalho para nova colaboradora:\n- Notebook Dell Latitude 5540\n- Monitor 24 polegadas\n- Conta AD + email\n- Acesso VPN\n- Licenças: Office 365, Adobe Creative Cloud\n- Treinamento de segurança",
  "priority": 3,
  "entity_name": "Skills IT"
}
```

---

## Cenário 6: Gestão de Mudanças (RFC)

**Situação:** Planejamento de migração de servidores no fim de semana.

### Passo 1 — Gerar checklist de mudança
```
Tool: glpi_get_prompt_template
Params: {
  "name": "glpi_change_management",
  "arguments": {
    "change_description": "Migração do servidor de arquivos FileServer01 (Windows Server 2016) para novo hardware Dell PowerEdge R750 (Windows Server 2022). Inclui migração de dados (2TB), recriação de compartilhamentos e atualização de GPOs."
  }
}
```

### Passo 2 — Buscar incidentes relacionados
```
Tool: glpi_search_ticket_requests
Params: { "query": "FileServer01", "limit": 20 }
```

---

## Cenário 7: Investigação de Incidente Crítico

**Situação:** Sistema ERP ficou fora do ar por 2 horas.

### Passo 1 — Registrar incidente
```
Tool: glpi_manage_ticket_operations
Params: {
  "action": "create",
  "title": "CRÍTICO - ERP Protheus indisponível",
  "description": "Sistema ERP Protheus ficou indisponível das 14:00 às 16:00. Impacto: toda a operação de faturamento parada. Aproximadamente 50 usuários afetados.",
  "priority": 5,
  "entity_name": "Acme Corp"
}
```

### Passo 2 — Análise RCA
```
Tool: glpi_get_prompt_template
Params: {
  "name": "glpi_incident_investigation",
  "arguments": { "ticket_id": 601 }
}
```

### Passo 3 — Buscar incidentes similares passados (pelo ticket atual)
```
Tool: glpi_manage_ticket_operations
Params: { "action": "find_similar", "ticket_id": 601, "threshold": 0.25 }
```

---

## Cenário 8: Configuração de Webhooks

**Situação:** Integrar GLPI com Microsoft Teams para notificações automáticas.

### Passo 1 — Listar webhooks existentes
```
Tool: glpi_search_webhook_integrations
Params: { "scope": "list" }
```

### Passo 2 — Criar webhook para novos chamados
```
Tool: glpi_manage_webhook_integrations
Params: {
  "action": "create",
  "name": "Teams - Chamados Críticos",
  "url": "https://prod-XX.westus.logic.azure.com/workflows/...",
  "event_type": "ticket.created"
}
→ Retorna: { "id": "2b27acbaca81c9e9694107d708d92dcf", ... }
```
> ⚠️ `event_type` usa notação **com ponto** (`ticket.created`, `ticket.updated`,
> `ticket.deleted`, `ticket.assigned`, `asset.created`, `asset.updated`,
> `asset.deleted`, `asset.reserved`, `user.created`, `user.updated`,
> `user.deleted`, `group.created`, `group.updated`, `group.deleted`).

### Passo 3 — Testar conectividade
```
Tool: glpi_manage_webhook_integrations
Params: { "action": "test", "webhook_id": "2b27acbaca81c9e9694107d708d92dcf" }
```
> ⚠️ `webhook_id` é um **hash alfanumérico** (string), não um inteiro.

---

## Cenário 9: Consulta de Dados de Referência

**Situação:** Preciso saber os códigos usados pelo GLPI.

### Listar status de chamados
```
Tool: glpi_read_resource_by_uri
Params: { "uri": "glpi://ticket-status" }
```

### Listar prioridades
```
Tool: glpi_read_resource_by_uri
Params: { "uri": "glpi://priorities" }
```

### Listar entidades/clientes
```
Tool: glpi_read_resource_by_uri
Params: { "uri": "glpi://entities" }
```

### Listar categorias de chamado
```
Tool: glpi_read_resource_by_uri
Params: { "uri": "glpi://ticket-categories" }
```

---

## Cenário 10: Suporte N1 — Fluxo Rápido

**Situação:** Técnico N1 atende chamada do usuário.

```
1. Buscar histórico do usuário:
   Tool: glpi_get_prompt_template
   Params: { "name": "glpi_user_ticket_history", "arguments": { "username": "pedro.alves" } }

2. Verificar equipamento do usuário:
   Tool: glpi_get_prompt_template
   Params: { "name": "glpi_asset_lookup", "arguments": { "search_term": "Pedro Alves" } }

3. Consultar base de conhecimento:
   Tool: glpi_search_knowledge_articles
   Params: { "query": "problema relatado pelo usuário" }

4. Se não resolver, abrir chamado e escalar:
   Tool: glpi_manage_ticket_operations
   Params: {
     "action": "create",
     "title": "Problema X - Pedro Alves",
     "description": "Descrição do problema...",
     "priority": 3
   }

5. Gerar resumo para enviar ao N2:
   Tool: glpi_get_prompt_template
   Params: { "name": "glpi_ticket_summary", "arguments": { "ticket_id": 605 } }
```

---

## Cenário 11: Tickets — consulta histórica, contexto e estatísticas

**Situação:** Gestor quer auditar um chamado e comparar com o mês inteiro.

### Passo 1 — Buscar chamado pelo número público
```
Tool: glpi_manage_ticket_operations
Params: { "action": "get_by_number", "ticket_number": "542" }
→ Tenta /apirest.php/Ticket/542 direto; se falhar, faz contains no título.
```

### Passo 2 — Ver todos os acompanhamentos
```
Tool: glpi_manage_ticket_operations
Params: { "action": "get_followups", "ticket_id": 542 }
```

### Passo 3 — Ver histórico completo de alterações
```
Tool: glpi_manage_ticket_operations
Params: { "action": "get_history", "ticket_id": 542 }
```

### Passo 4 — Estatísticas agregadas do período
```
Tool: glpi_manage_ticket_operations
Params: {
  "action": "get_stats",
  "entity_name": "Skills IT",
  "date_from": "2026-04-01",
  "date_to": "2026-04-30"
}
→ Retorna total_tickets, open_tickets, closed_tickets e o detalhamento
   by_status: { new, assigned, planned, pending, solved, closed }
```

### Passo 5 — Excluir chamado de teste
```
Tool: glpi_manage_ticket_operations
Params: { "action": "delete", "ticket_id": 9999 }
→ Requer confirmationToken+reason se MCP_SAFETY_GUARD=true.
```

---

## Cenário 12: IA — Análise assíncrona de chamados

**Situação:** Automatizar triagem inicial com recomendações IA.

### Passo 1 — Disparar análise (retorna job_id)
```
Tool: glpi_manage_ticket_ai_analysis
Params: { "action": "trigger", "ticket_id": 542 }
→ Retorna: { "job_id": "ai_job_11815cf1834b", "status": "processing" }
```

### Passo 2 — Consultar resultado (após processamento)
```
Tool: glpi_manage_ticket_ai_analysis
Params: { "action": "get_result", "job_id": "ai_job_11815cf1834b" }
```

### Passo 3 — Publicar a sugestão IA como followup no ticket
```
Tool: glpi_manage_ticket_ai_analysis
Params: {
  "action": "publish",
  "job_id": "ai_job_11815cf1834b",
  "response": {
    "summary": "Diagnóstico IA: lentidão provável por falta de memória. Recomendado: verificar swap e limpar cache.",
    "suggested_category": "Estação de Trabalho",
    "suggested_priority": 3
  }
}
```

---

## Cenário 13: Ativos — detalhes enriquecidos, updates e reservas

**Situação:** Gestor precisa de auditoria completa de uma máquina e gerenciar reservas.

### Passo 1 — Detalhes enriquecidos de um Computer
```
Tool: glpi_manage_asset_operations
Params: { "action": "get_details", "asset_type": "Computer", "asset_id": 1 }
→ Retorna o ativo + seções: Sistema Operacional, Discos, Processadores,
   Memorias, Redes, Software Instalado (até 25 itens).
```

### Passo 2 — Atualizar dados do ativo
```
Tool: glpi_manage_asset_operations
Params: {
  "action": "update",
  "asset_type": "Computer",
  "asset_id": 1,
  "serial_number": "NEW-SERIAL-2026",
  "comment": "Revisão técnica - abril/2026"
}
```

### Passo 3 — Consultar reservas de um ativo
```
Tool: glpi_manage_asset_operations
Params: { "action": "get_reservations", "asset_type": "Computer", "asset_id": 1 }
```

### Passo 4 — Criar reserva
```
Tool: glpi_manage_asset_operations
Params: {
  "action": "create_reservation",
  "asset_type": "Computer",
  "asset_id": 1,
  "user_id": 804,
  "date_start": "2026-05-15 08:00:00",
  "date_end": "2026-05-15 17:00:00",
  "comment": "Reserva para apresentação externa"
}
```

### Passo 5 — Atualizar reserva
```
Tool: glpi_manage_asset_operations
Params: {
  "action": "update_reservation",
  "reservation_id": 42,
  "date_end": "2026-05-15 18:30:00",
  "comment": "Reserva prolongada por 1h30"
}
```

### Passo 6 — Deletar ativo (quando apropriado)
```
Tool: glpi_manage_asset_operations
Params: { "action": "delete", "asset_type": "Computer", "asset_id": 1 }
```

---

## Cenário 14: Admin — CRUD completo de users, groups, entities, locations

**Situação:** Automatizar onboarding/offboarding e reorganização de equipes.

### Users

```
# Buscar (search_* aceita query genérico em name/firstname/realname/email)
Tool: glpi_search_admin_resources
Params: { "resource": "users", "query": "ana.oliveira", "limit": 5 }

# Criar
Tool: glpi_manage_admin_resources
Params: {
  "resource": "users",
  "action": "create",
  "name": "ana.oliveira",
  "firstname": "Ana",
  "realname": "Oliveira",
  "email": "ana.oliveira@empresa.com"
}
→ Retorna: ID do novo usuário

# Consultar
Params: { "resource": "users", "action": "get", "resource_id": 1003 }

# Atualizar
Params: {
  "resource": "users",
  "action": "update",
  "resource_id": 1003,
  "email": "ana.oliveira@novoemail.com"
}

# Desativar/deletar (soft delete por padrão)
Params: { "resource": "users", "action": "delete", "resource_id": 1003 }
```

### Groups

```
# Listar
Tool: glpi_search_admin_resources
Params: { "resource": "groups", "limit": 50 }

# Criar
Tool: glpi_manage_admin_resources
Params: {
  "resource": "groups",
  "action": "create",
  "name": "N2-Infraestrutura",
  "entity_id": 4
}

# Renomear/atualizar
Params: {
  "resource": "groups",
  "action": "update",
  "resource_id": 68,
  "name": "N2-Infra-Cloud",
  "comment": "Renomeado em 2026-04"
}

# Remover definitivamente (purge por padrão na v2.1)
Params: { "resource": "groups", "action": "delete", "resource_id": 68 }
```

### Entities (somente leitura)

```
# Listar
Tool: glpi_search_admin_resources
Params: { "resource": "entities" }

# Detalhes da entidade raiz (MSP)
Tool: glpi_manage_admin_resources
Params: { "resource": "entities", "action": "get", "resource_id": 0 }
```
> ⚠️ Na v2.1 `resource_id=0` é aceito para `entities` (root entity do GLPI).

### Locations

```
# Listar
Tool: glpi_search_admin_resources
Params: { "resource": "locations", "entity_id": 4 }

# Criar
Tool: glpi_manage_admin_resources
Params: {
  "resource": "locations",
  "action": "create",
  "name": "Sede - 2º andar",
  "entity_id": 4,
  "town": "Palmas",
  "building": "Bloco A"
}

# Atualizar
Params: {
  "resource": "locations",
  "action": "update",
  "resource_id": 508,
  "room": "Sala 204"
}

# Remover
Params: { "resource": "locations", "action": "delete", "resource_id": 508 }
```

---

## Cenário 15: Webhooks — ciclo completo de controle

**Situação:** Gerenciar endpoints de notificação integrados ao GLPI.

```
# 1. Listar endpoints
Tool: glpi_search_webhook_integrations
Params: { "scope": "list" }

# 2. Estatísticas globais de entregas
Params: { "scope": "stats" }

# 3. Histórico de entregas de um webhook específico
Params: { "scope": "deliveries", "webhook_id": "2b27acbaca81c9e9694107d708d92dcf" }

# 4. Criar novo webhook
Tool: glpi_manage_webhook_integrations
Params: {
  "action": "create",
  "name": "Slack - Tickets Críticos",
  "url": "https://hooks.slack.com/services/XXX/YYY/ZZZ",
  "event_type": "ticket.created"
}

# 5. Consultar detalhes
Params: { "action": "get", "webhook_id": "<hash>" }

# 6. Atualizar
Params: {
  "action": "update",
  "webhook_id": "<hash>",
  "url": "https://hooks.slack.com/services/AAA/BBB/CCC"
}

# 7. Testar conectividade
Params: { "action": "test", "webhook_id": "<hash>" }

# 8. Disparar evento manualmente (para teste de integração)
Params: {
  "action": "trigger",
  "event_type": "ticket.created",
  "data": { "id": 999, "name": "Teste manual" }
}

# 9. Desabilitar temporariamente
Params: { "action": "disable", "webhook_id": "<hash>" }

# 10. Reabilitar
Params: { "action": "enable", "webhook_id": "<hash>" }

# 11. Reprocessar entregas falhadas
Params: { "action": "retry", "webhook_id": "<hash>" }

# 12. Remover definitivamente
Params: { "action": "delete", "webhook_id": "<hash>" }
```
> ℹ️ **Nota arquitetural:** o armazenamento de webhooks é in-memory no servidor
> MCP e não persiste após restart. Integração nativa com `glpi_webhooks`
> (GLPI 11) está na roadmap.

---

## Cenário 16: Bridge — descobrir recursos e prompts

**Situação:** Primeiro uso do MCP, precisa explorar o que está disponível.

```
# 1. Listar 4 resources estáticos (entities/status/categories/priorities)
Tool: glpi_list_available_resources

# 2. Ler entidades
Tool: glpi_read_resource_by_uri
Params: { "uri": "glpi://entities" }

# 3. Ler códigos de status
Params: { "uri": "glpi://ticket-status" }

# 4. Ler árvore de categorias
Params: { "uri": "glpi://ticket-categories" }

# 5. Ler níveis de prioridade
Params: { "uri": "glpi://priorities" }

# 6. Catálogo completo de 15 prompts profissionais
Tool: glpi_list_available_prompts

# 7. Buscar na base de conhecimento
Tool: glpi_search_knowledge_articles
Params: { "query": "configuração VPN", "limit": 5 }
```

---

## Matriz de Validação — 14 tools × todas as actions

Use esta matriz para testar 100 % da superfície do MCP após mudanças:

| Tool | Action / Scope | Cenário |
|------|----------------|---------|
| `glpi_search_ticket_requests` | — (status/priority/query/entity) | 1, 6 |
| `glpi_manage_ticket_operations` | `get` | 1 |
| `glpi_manage_ticket_operations` | `get_by_number` | 11 |
| `glpi_manage_ticket_operations` | `create` | 2, 5, 7 |
| `glpi_manage_ticket_operations` | `update` | — (ajuste via examples) |
| `glpi_manage_ticket_operations` | `delete` | 11 |
| `glpi_manage_ticket_operations` | `assign` | 1 |
| `glpi_manage_ticket_operations` | `close` | — (veja TOOLS-REFERENCE) |
| `glpi_manage_ticket_operations` | `resolve` | 2 |
| `glpi_manage_ticket_operations` | `add_followup` | 2 |
| `glpi_manage_ticket_operations` | `get_followups` | 11 |
| `glpi_manage_ticket_operations` | `get_history` | 11 |
| `glpi_manage_ticket_operations` | `get_stats` | 11 |
| `glpi_manage_ticket_operations` | `find_similar` | 2, 7 |
| `glpi_manage_ticket_ai_analysis` | `trigger` | 12 |
| `glpi_manage_ticket_ai_analysis` | `get_result` | 12 |
| `glpi_manage_ticket_ai_analysis` | `publish` | 12 |
| `glpi_search_asset_inventory` | `all` / `stats` / `computers` / `reservations` / `reservable` / `software` / `monitors` / `devices` | 3 |
| `glpi_manage_asset_operations` | `get` | 3 |
| `glpi_manage_asset_operations` | `get_details` (enriched) | 13 |
| `glpi_manage_asset_operations` | `create` | 3 |
| `glpi_manage_asset_operations` | `update` | 13 |
| `glpi_manage_asset_operations` | `delete` | 13 |
| `glpi_manage_asset_operations` | `get_reservations` | 13 |
| `glpi_manage_asset_operations` | `create_reservation` | 13 |
| `glpi_manage_asset_operations` | `update_reservation` | 13 |
| `glpi_search_admin_resources` | `users`/`groups`/`entities`/`locations` | 14 |
| `glpi_manage_admin_resources` | users `get`/`create`/`update`/`delete` | 14 |
| `glpi_manage_admin_resources` | groups `get`/`create`/`update`/`delete` | 14 |
| `glpi_manage_admin_resources` | entities `get` (id=0 aceito) | 14 |
| `glpi_manage_admin_resources` | locations `get`/`create`/`update`/`delete` | 14 |
| `glpi_search_webhook_integrations` | `list`/`stats`/`deliveries` | 15 |
| `glpi_manage_webhook_integrations` | `get`/`create`/`update`/`delete`/`test`/`trigger`/`enable`/`disable`/`retry` | 15 |
| `glpi_list_available_resources` | — | 16 |
| `glpi_read_resource_by_uri` | 4 URIs estáticos | 9, 16 |
| `glpi_list_available_prompts` | — | 16 |
| `glpi_get_prompt_template` | 15 prompts | 3 (ROI), 4 (SLA, Trends, Productivity, Recurring, Satisfaction), 5 (Onboarding, Hardware), 6 (Change), 7 (Incident), 10 (UserHistory, AssetLookup, Summary) |
| `glpi_search_knowledge_articles` | — | 2, 10, 16 |

> ✅ **Cobertura total:** todas as 14 tools e todas as actions/scopes estão
> exemplificadas em pelo menos um cenário acima.
