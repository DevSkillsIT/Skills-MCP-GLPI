# MCP GLPI - Testes do Sistema de Prompts

**Implementado em:** Dezembro 2025
**Skills IT - Soluções em Tecnologia**

---

## 📊 Visão Geral

O MCP GLPI agora inclui 15 prompts profissionais pré-configurados para:

- **7 Prompts de Gestão de TI** (relatórios executivos, KPIs, análise de tendências)
- **8 Prompts de Suporte Técnico** (investigação, checklists, templates)

Todos os prompts retornam **2 formatos**:
- **Compacto:** 10 linhas máximo (WhatsApp/Teams)
- **Detalhado:** Markdown completo (documentação, relatórios)

---

## 🔧 Testes Básicos

### 1. Health Check do Servidor

```bash
curl http://mcp.servidor.one:8824/health
```

**Resultado esperado:**
```json
{
  "status": "healthy",
  "service": "mcp-glpi",
  "version": "1.0.0",
  "transport": "streamable-http"
}
```

---

### 2. Listar Prompts Disponíveis

```bash
curl -X POST http://mcp.servidor.one:8824/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-GLPI-User-Token: SEU_USER_TOKEN_AQUI' \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "prompts_list",
      "arguments": {}
    }
  }'
```

**Resultado esperado:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [{
      "type": "text",
      "text": "{\"prompts\": [{\"name\": \"glpi_sla_performance\", ...}, ...]}"
    }]
  }
}
```

---

## 📋 Prompts de Gestão de TI

### 3. Relatório de SLA Performance

**Objetivo:** Relatório de desempenho de SLA mensal com tempo médio de resposta e resolução.

```bash
curl -X POST http://mcp.servidor.one:8824/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-GLPI-User-Token: SEU_USER_TOKEN_AQUI' \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "prompts_get",
      "arguments": {
        "name": "glpi_sla_performance",
        "arguments": {
          "entity_name": "Skills IT",
          "period_days": 30
        }
      }
    }
  }'
```

**Retorna:**
- `compact`: Resumo de 10 linhas para WhatsApp
- `detailed`: Relatório Markdown completo com análise

---

### 4. Tendências de Tickets

**Objetivo:** Análise de tendências de tickets por categoria.

```bash
curl -X POST http://mcp.servidor.one:8824/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-GLPI-User-Token: SEU_USER_TOKEN_AQUI' \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "prompts_get",
      "arguments": {
        "name": "glpi_ticket_trends",
        "arguments": {
          "period_days": 30
        }
      }
    }
  }'
```

---

### 5. ROI de Ativos

**Objetivo:** Calcula ROI de ativos por cliente.

```bash
curl -X POST http://mcp.servidor.one:8824/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-GLPI-User-Token: SEU_USER_TOKEN_AQUI' \
  -d '{
    "jsonrpc": "2.0",
    "id": 4,
    "method": "tools/call",
    "params": {
      "name": "prompts_get",
      "arguments": {
        "name": "glpi_asset_roi",
        "arguments": {
          "entity_name": "Skills IT"
        }
      }
    }
  }'
```

---

### 6. Produtividade de Técnicos

**Objetivo:** Mede produtividade de técnicos (tickets resolvidos, tempo médio).

```bash
curl -X POST http://mcp.servidor.one:8824/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-GLPI-User-Token: SEU_USER_TOKEN_AQUI' \
  -d '{
    "jsonrpc": "2.0",
    "id": 5,
    "method": "tools/call",
    "params": {
      "name": "prompts_get",
      "arguments": {
        "name": "glpi_technician_productivity",
        "arguments": {
          "period_days": 30
        }
      }
    }
  }'
```

---

### 7. Custo por Ticket

**Objetivo:** Calcula custo médio por ticket.

```bash
curl -X POST http://mcp.servidor.one:8824/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-GLPI-User-Token: SEU_USER_TOKEN_AQUI' \
  -d '{
    "jsonrpc": "2.0",
    "id": 6,
    "method": "tools/call",
    "params": {
      "name": "prompts_get",
      "arguments": {
        "name": "glpi_cost_per_ticket",
        "arguments": {
          "entity_name": "Skills IT",
          "period_days": 30
        }
      }
    }
  }'
```

---

### 8. Problemas Recorrentes

**Objetivo:** Identifica problemas recorrentes para ação preventiva.

```bash
curl -X POST http://mcp.servidor.one:8824/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-GLPI-User-Token: SEU_USER_TOKEN_AQUI' \
  -d '{
    "jsonrpc": "2.0",
    "id": 7,
    "method": "tools/call",
    "params": {
      "name": "prompts_get",
      "arguments": {
        "name": "glpi_recurring_problems",
        "arguments": {
          "entity_name": "Skills IT",
          "min_occurrences": 3
        }
      }
    }
  }'
```

---

### 9. Satisfação do Cliente

**Objetivo:** Relatório de indicadores de satisfação do cliente.

```bash
curl -X POST http://mcp.servidor.one:8824/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-GLPI-User-Token: SEU_USER_TOKEN_AQUI' \
  -d '{
    "jsonrpc": "2.0",
    "id": 8,
    "method": "tools/call",
    "params": {
      "name": "prompts_get",
      "arguments": {
        "name": "glpi_client_satisfaction",
        "arguments": {
          "entity_name": "Skills IT",
          "period_days": 30
        }
      }
    }
  }'
```

---

## 🎯 Prompts de Suporte Técnico

### 10. Resumo de Ticket

**Objetivo:** Resumo rápido de ticket para WhatsApp/Teams.

```bash
curl -X POST http://mcp.servidor.one:8824/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-GLPI-User-Token: SEU_USER_TOKEN_AQUI' \
  -d '{
    "jsonrpc": "2.0",
    "id": 9,
    "method": "tools/call",
    "params": {
      "name": "prompts_get",
      "arguments": {
        "name": "glpi_ticket_summary",
        "arguments": {
          "ticket_id": 123
        }
      }
    }
  }'
```

---

### 11. Histórico de Tickets do Usuário

**Objetivo:** Histórico completo de tickets do usuário.

```bash
curl -X POST http://mcp.servidor.one:8824/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-GLPI-User-Token: SEU_USER_TOKEN_AQUI' \
  -d '{
    "jsonrpc": "2.0",
    "id": 10,
    "method": "tools/call",
    "params": {
      "name": "prompts_get",
      "arguments": {
        "name": "glpi_user_ticket_history",
        "arguments": {
          "username": "adriano.fante"
        }
      }
    }
  }'
```

---

### 12. Busca de Ativo

**Objetivo:** Busca rápida de ativo (computador, serial, usuário).

```bash
curl -X POST http://mcp.servidor.one:8824/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-GLPI-User-Token: SEU_USER_TOKEN_AQUI' \
  -d '{
    "jsonrpc": "2.0",
    "id": 11,
    "method": "tools/call",
    "params": {
      "name": "prompts_get",
      "arguments": {
        "name": "glpi_asset_lookup",
        "arguments": {
          "search_term": "NB-001"
        }
      }
    }
  }'
```

---

### 13. Checklist de Onboarding

**Objetivo:** Checklist de onboarding para novo usuário.

```bash
curl -X POST http://mcp.servidor.one:8824/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-GLPI-User-Token: SEU_USER_TOKEN_AQUI' \
  -d '{
    "jsonrpc": "2.0",
    "id": 12,
    "method": "tools/call",
    "params": {
      "name": "prompts_get",
      "arguments": {
        "name": "glpi_onboarding_checklist",
        "arguments": {
          "username": "João Silva",
          "entity_name": "Skills IT"
        }
      }
    }
  }'
```

---

### 14. Investigação de Incidente (RCA)

**Objetivo:** Template de investigação de incidente (Root Cause Analysis).

```bash
curl -X POST http://mcp.servidor.one:8824/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-GLPI-User-Token: SEU_USER_TOKEN_AQUI' \
  -d '{
    "jsonrpc": "2.0",
    "id": 13,
    "method": "tools/call",
    "params": {
      "name": "prompts_get",
      "arguments": {
        "name": "glpi_incident_investigation",
        "arguments": {
          "ticket_id": 456
        }
      }
    }
  }'
```

---

### 15. Gestão de Mudança (RFC)

**Objetivo:** Checklist de gestão de mudança (Request for Change).

```bash
curl -X POST http://mcp.servidor.one:8824/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-GLPI-User-Token: SEU_USER_TOKEN_AQUI' \
  -d '{
    "jsonrpc": "2.0",
    "id": 14,
    "method": "tools/call",
    "params": {
      "name": "prompts_get",
      "arguments": {
        "name": "glpi_change_management",
        "arguments": {
          "change_description": "Atualização do firewall para versão 8.2"
        }
      }
    }
  }'
```

---

### 16. Solicitação de Hardware

**Objetivo:** Template de solicitação de hardware padronizado.

```bash
curl -X POST http://mcp.servidor.one:8824/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-GLPI-User-Token: SEU_USER_TOKEN_AQUI' \
  -d '{
    "jsonrpc": "2.0",
    "id": 15,
    "method": "tools/call",
    "params": {
      "name": "prompts_get",
      "arguments": {
        "name": "glpi_hardware_request",
        "arguments": {
          "user_name": "Maria Santos",
          "hardware_type": "Notebook"
        }
      }
    }
  }'
```

---

### 17. Busca em Base de Conhecimento

**Objetivo:** Busca em base de conhecimento com sugestões de artigos.

```bash
curl -X POST http://mcp.servidor.one:8824/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-GLPI-User-Token: SEU_USER_TOKEN_AQUI' \
  -d '{
    "jsonrpc": "2.0",
    "id": 16,
    "method": "tools/call",
    "params": {
      "name": "prompts_get",
      "arguments": {
        "name": "glpi_knowledge_base_search",
        "arguments": {
          "search_query": "resetar senha Windows"
        }
      }
    }
  }'
```

---

## ✅ Validação de Sucesso

Para cada teste acima, valide:

1. **Status HTTP:** 200 OK
2. **JSON-RPC válido:** `jsonrpc: "2.0"`, `id` correspondente
3. **Resultado contém:**
   - `content` array
   - `type: "text"`
   - `text` contendo JSON com `compact` e `detailed`
4. **Formato compact:** Máximo 10 linhas, ideal para WhatsApp/Teams
5. **Formato detailed:** Markdown estruturado com seções claras

---

## 🔍 Troubleshooting

### Erro: "Tool not found"
```bash
# Verifique se o servidor foi reiniciado após implementação
pm2 restart mcp-glpi
pm2 logs mcp-glpi --lines 50
```

### Erro: "Invalid arguments"
```bash
# Verifique se todos os argumentos obrigatórios foram enviados
# Use prompts_list para ver argumentos requeridos
```

### Erro: "NotFoundError"
```bash
# Alguns prompts dependem de dados GLPI (tickets, entidades, usuários)
# Verifique se entity_name, ticket_id, username existem no GLPI
```

---

## 📊 Uso no Claude Code

No Claude Code, você pode usar os prompts naturalmente:

```
GLPI, liste os prompts disponíveis

GLPI, gere relatório de SLA dos últimos 30 dias para Skills IT

GLPI, mostre resumo do ticket 123

GLPI, crie checklist de onboarding para João Silva na empresa Skills IT
```

---

## 📞 Suporte

**Skills IT - Soluções em Tecnologia**
WhatsApp: +55 63 3224-4925
Email: contato@skillsit.com.br
Site: https://skillsit.com.br

---

**Versão:** 1.0.0
**Última Atualização:** Dezembro 2025
**Desenvolvido por:** Skills IT - Soluções em Tecnologia 🇧🇷
