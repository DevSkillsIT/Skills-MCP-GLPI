# GLPI MCP Server — Referência de Prompts

> 15 prompts profissionais prontos para relatórios gerenciais e operacionais

## Como Usar Prompts

Prompts são modelos pré-configurados que geram relatórios, análises e checklists. Para executar:

1. Liste os prompts disponíveis:
   - Tool: `glpi_list_available_prompts` (sem parâmetros)

2. Execute o prompt desejado:
   - Tool: `glpi_get_prompt_template`
   - Params: `{ "name": "nome_do_prompt", "arguments": { ... } }`

---

## Prompts de Gestão (7)

Para gestores de TI, coordenadores e diretores.

### 1. `glpi_sla_performance`

**Relatório de Performance SLA** — Métricas de tempo médio de resposta e resolução.

| Argumento | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `entity_name` | string | Não | Nome da entidade/cliente |
| `period_days` | integer | Não | Período em dias (padrão: 30) |

**Exemplo de uso:**
```
"Relatório de SLA da Acme Corp nos últimos 90 dias"
→ { "name": "glpi_sla_performance", "arguments": { "entity_name": "Acme Corp", "period_days": 90 } }
```

**Retorna:** Tabela com tempo médio de primeira resposta, tempo médio de resolução, taxa de cumprimento de SLA por categoria, tendência mensal.

---

### 2. `glpi_ticket_trends`

**Análise de Tendências de Chamados** — Aumento/diminuição por categoria ao longo do tempo.

| Argumento | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `entity_name` | string | Não | Nome da entidade |
| `period_days` | integer | Não | Período em dias (padrão: 30) |

**Exemplo:**
```
"Tendência de chamados do último trimestre"
→ { "name": "glpi_ticket_trends", "arguments": { "period_days": 90 } }
```

**Retorna:** Volume de chamados por semana, categorias com mais crescimento, horários de pico, comparativo com período anterior.

---

### 3. `glpi_asset_roi`

**ROI de Ativos** — Cálculo de retorno sobre investimento em equipamentos.

| Argumento | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `entity_name` | string | **Sim** | Nome da entidade |

**Exemplo:**
```
"Análise de ROI dos ativos da Skills IT"
→ { "name": "glpi_asset_roi", "arguments": { "entity_name": "Skills IT" } }
```

**Retorna:** Custo total de aquisição, custo de manutenção (chamados relacionados), utilização média, idade média do parque, recomendações de substituição.

---

### 4. `glpi_technician_productivity`

**Produtividade de Técnicos** — Métricas de desempenho individual e da equipe.

| Argumento | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `period_days` | integer | Não | Período em dias (padrão: 30) |

**Exemplo:**
```
"Produtividade da equipe no último mês"
→ { "name": "glpi_technician_productivity", "arguments": { "period_days": 30 } }
```

**Retorna:** Chamados resolvidos por técnico, tempo médio de resolução, taxa de reabertura, backlog individual, ranking.

---

### 5. `glpi_cost_per_ticket`

**Custo Médio por Chamado** — Análise financeira do suporte.

| Argumento | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `entity_name` | string | Não | Nome da entidade |
| `period_days` | integer | Não | Período em dias (padrão: 30) |

**Exemplo:**
```
"Custo por chamado da Acme no semestre"
→ { "name": "glpi_cost_per_ticket", "arguments": { "entity_name": "Acme Corp", "period_days": 180 } }
```

---

### 6. `glpi_recurring_problems`

**Problemas Recorrentes** — Identificação de padrões para ação preventiva.

| Argumento | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `entity_name` | string | Não | Nome da entidade |
| `min_occurrences` | integer | Não | Mínimo de ocorrências para reportar (padrão: 3) |

**Exemplo:**
```
"Quais problemas se repetem mais de 5 vezes?"
→ { "name": "glpi_recurring_problems", "arguments": { "min_occurrences": 5 } }
```

**Retorna:** Top problemas recorrentes, frequência, categoria, impacto estimado, sugestões de prevenção.

---

### 7. `glpi_client_satisfaction`

**Indicadores de Satisfação do Cliente** — Métricas de qualidade percebida.

| Argumento | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `entity_name` | string | Não | Nome da entidade |
| `period_days` | integer | Não | Período em dias (padrão: 30) |

**Exemplo:**
```
"Satisfação da Skills IT no trimestre"
→ { "name": "glpi_client_satisfaction", "arguments": { "entity_name": "Skills IT", "period_days": 90 } }
```

---

## Prompts de Suporte (8)

Para analistas de suporte N1/N2/N3 e técnicos de campo.

### 8. `glpi_ticket_summary`

**Resumo Rápido de Chamado** — Formato compacto (10 linhas) para WhatsApp/Teams.

| Argumento | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `ticket_id` | integer | **Sim** | ID do chamado |

**Exemplo:**
```
"Resumo do chamado 542 para enviar no Teams"
→ { "name": "glpi_ticket_summary", "arguments": { "ticket_id": 542 } }
```

---

### 9. `glpi_user_ticket_history`

**Histórico Completo do Usuário** — Todos os chamados de um usuário específico.

| Argumento | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `username` | string | **Sim** | Login do usuário no GLPI |

**Exemplo:**
```
"Histórico de chamados do João Silva"
→ { "name": "glpi_user_ticket_history", "arguments": { "username": "jsilva" } }
```

---

### 10. `glpi_asset_lookup`

**Busca Rápida de Ativo** — Localizar equipamento por nome, serial ou usuário.

| Argumento | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `search_term` | string | **Sim** | Termo de busca |

**Exemplo:**
```
"Qual computador está com o João?"
→ { "name": "glpi_asset_lookup", "arguments": { "search_term": "João Silva" } }
```

---

### 11. `glpi_onboarding_checklist`

**Checklist de Onboarding** — Lista de tarefas para novos colaboradores.

| Argumento | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `username` | string | **Sim** | Nome do novo colaborador |
| `entity_name` | string | **Sim** | Nome da entidade/empresa |

**Exemplo:**
```
"Checklist de onboarding para Maria Souza na Skills IT"
→ { "name": "glpi_onboarding_checklist", "arguments": { "username": "Maria Souza", "entity_name": "Skills IT" } }
```

**Retorna:** Checklist com: criação de conta, e-mail, VPN, estação de trabalho, acessos aos sistemas, treinamentos.

---

### 12. `glpi_incident_investigation`

**Template de Investigação de Incidente** — Análise de causa raiz (RCA).

| Argumento | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `ticket_id` | integer | **Sim** | ID do chamado/incidente |

**Exemplo:**
```
"Investigar causa raiz do incidente 300"
→ { "name": "glpi_incident_investigation", "arguments": { "ticket_id": 300 } }
```

**Retorna:** Template RCA com: timeline do incidente, impacto, causa raiz provável, ações corretivas, lições aprendidas.

---

### 13. `glpi_change_management`

**Checklist de Gestão de Mudança** — Template RFC (Request for Change).

| Argumento | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `change_description` | string | **Sim** | Descrição da mudança planejada |

**Exemplo:**
```
"RFC para migração do servidor de email para Office 365"
→ { "name": "glpi_change_management", "arguments": { "change_description": "Migração do servidor Exchange on-premises para Microsoft 365" } }
```

**Retorna:** Checklist com: justificativa, impacto, riscos, plano de rollback, janela de manutenção, comunicação, aprovações.

---

### 14. `glpi_hardware_request`

**Requisição de Hardware Padronizada** — Formulário para solicitação de equipamentos.

| Argumento | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `user_name` | string | **Sim** | Nome do solicitante |
| `hardware_type` | string | **Sim** | Tipo de hardware solicitado |

**Exemplo:**
```
"Requisição de notebook para Ana Oliveira"
→ { "name": "glpi_hardware_request", "arguments": { "user_name": "Ana Oliveira", "hardware_type": "Notebook Dell Latitude 5540" } }
```

---

### 15. `glpi_knowledge_base_search`

**Busca Inteligente na Base de Conhecimento** — Artigos com sugestões.

| Argumento | Tipo | Obrigatório | Descrição |
|-----------|------|:-----------:|-----------|
| `search_query` | string | **Sim** | Termo de busca |

**Exemplo:**
```
"Buscar solução para Blue Screen of Death"
→ { "name": "glpi_knowledge_base_search", "arguments": { "search_query": "BSOD Blue Screen" } }
```

---

## Resumo

| Categoria | Qtd | Público-Alvo |
|-----------|:---:|-------------|
| Gestão | 7 | Gestores de TI, Coordenadores, Diretores |
| Suporte | 8 | Analistas N1/N2/N3, Técnicos de Campo |
| **Total** | **15** | |
