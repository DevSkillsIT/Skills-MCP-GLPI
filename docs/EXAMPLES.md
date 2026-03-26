# GLPI MCP Server — Exemplos de Uso

> Cenários completos do dia a dia de suporte com as tools e prompts do MCP GLPI

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

### Passo 2 — Buscar chamados similares
```
Tool: glpi_manage_ticket_operations
Params: { "action": "find_similar", "query": "erro Outlook servidor conexão" }
```

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
Params: { "scope": "computers", "entity_name": "Ramada Lindacor", "limit": 50 }
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
Params: { "name": "glpi_asset_roi", "arguments": { "entity_name": "Ramada Lindacor" } }
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
  "entity_name": "Ramada Lindacor"
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

### Passo 3 — Buscar incidentes similares passados
```
Tool: glpi_manage_ticket_operations
Params: { "action": "find_similar", "query": "ERP Protheus indisponível fora do ar" }
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
  "event_type": "ticket_created"
}
```

### Passo 3 — Testar conectividade
```
Tool: glpi_manage_webhook_integrations
Params: { "action": "test", "webhook_id": 12 }
```

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
