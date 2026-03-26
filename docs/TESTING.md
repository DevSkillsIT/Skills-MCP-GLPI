# GLPI MCP Server — Guia de Testes

> Testes via curl e pytest para as 14 tools consolidadas (v2.0)

## Pre-requisitos

- Servidor MCP GLPI rodando (porta 8824 padrao)
- curl e jq instalados
- User Token do GLPI (por usuario)

## Configuracao

```bash
# URL do servidor
export GLPI_MCP_URL="http://localhost:8824"

# Seu User Token pessoal do GLPI
# Obter em: GLPI > Administracao > Usuarios > [seu usuario] > Configuracoes remotas
export GLPI_USER_TOKEN="seu_user_token_aqui"
```

### Header obrigatorio

Todas as chamadas MCP (exceto health check) requerem:

```
X-GLPI-User-Token: seu_user_token_aqui
```

---

## 1. Health Check

```bash
curl -s $GLPI_MCP_URL/health | jq .
```

Resposta esperada:
```json
{
  "status": "healthy",
  "service": "mcp-glpi",
  "version": "1.0.0",
  "transport": "streamable-http"
}
```

## 2. Listar Tools

```bash
curl -s -X POST $GLPI_MCP_URL/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | \
  jq '.result.tools | length'
```

Resultado esperado: `14`

Listar nomes de todas as tools:
```bash
curl -s -X POST $GLPI_MCP_URL/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | \
  jq -r '.result.tools[].name'
```

---

## 3. Testes de Tickets

### Buscar chamados novos

```bash
curl -s -X POST $GLPI_MCP_URL/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "glpi_search_ticket_requests",
      "arguments": {"status": "new", "limit": 5}
    }
  }' | jq .
```

### Consultar chamado especifico

```bash
curl -s -X POST $GLPI_MCP_URL/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "glpi_manage_ticket_operations",
      "arguments": {"action": "get", "ticket_id": 1}
    }
  }' | jq .
```

### Criar chamado

```bash
curl -s -X POST $GLPI_MCP_URL/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "glpi_manage_ticket_operations",
      "arguments": {
        "action": "create",
        "title": "Teste MCP - Chamado automatico",
        "description": "Chamado criado via MCP para validacao",
        "priority": 2
      }
    }
  }' | jq .
```

### Adicionar acompanhamento

```bash
curl -s -X POST $GLPI_MCP_URL/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 4,
    "method": "tools/call",
    "params": {
      "name": "glpi_manage_ticket_operations",
      "arguments": {
        "action": "add_followup",
        "ticket_id": 1,
        "content": "Acompanhamento de teste via MCP"
      }
    }
  }' | jq .
```

### Resolver e fechar chamado

```bash
curl -s -X POST $GLPI_MCP_URL/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 5,
    "method": "tools/call",
    "params": {
      "name": "glpi_manage_ticket_operations",
      "arguments": {
        "action": "resolve",
        "ticket_id": 1,
        "solution": "Problema resolvido via teste MCP"
      }
    }
  }' | jq .
```

### Estatisticas de chamados

```bash
curl -s -X POST $GLPI_MCP_URL/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 6,
    "method": "tools/call",
    "params": {
      "name": "glpi_manage_ticket_operations",
      "arguments": {"action": "get_stats"}
    }
  }' | jq .
```

---

## 4. Testes de Ativos

### Listar computadores

```bash
curl -s -X POST $GLPI_MCP_URL/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 10,
    "method": "tools/call",
    "params": {
      "name": "glpi_search_asset_inventory",
      "arguments": {"scope": "computers", "limit": 10}
    }
  }' | jq .
```

### Estatisticas do inventario

```bash
curl -s -X POST $GLPI_MCP_URL/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 11,
    "method": "tools/call",
    "params": {
      "name": "glpi_search_asset_inventory",
      "arguments": {"scope": "stats"}
    }
  }' | jq .
```

### Cadastrar computador

```bash
curl -s -X POST $GLPI_MCP_URL/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 12,
    "method": "tools/call",
    "params": {
      "name": "glpi_manage_asset_operations",
      "arguments": {
        "action": "create",
        "asset_type": "Computer",
        "name": "PC-TESTE-MCP-001",
        "serial_number": "SN-MCP-TEST"
      }
    }
  }' | jq .
```

---

## 5. Testes de Admin

### Listar usuarios

```bash
curl -s -X POST $GLPI_MCP_URL/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 20,
    "method": "tools/call",
    "params": {
      "name": "glpi_search_admin_resources",
      "arguments": {"resource": "users", "limit": 10}
    }
  }' | jq .
```

### Listar entidades

```bash
curl -s -X POST $GLPI_MCP_URL/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 21,
    "method": "tools/call",
    "params": {
      "name": "glpi_search_admin_resources",
      "arguments": {"resource": "entities"}
    }
  }' | jq .
```

### Listar grupos

```bash
curl -s -X POST $GLPI_MCP_URL/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 22,
    "method": "tools/call",
    "params": {
      "name": "glpi_search_admin_resources",
      "arguments": {"resource": "groups"}
    }
  }' | jq .
```

---

## 6. Testes de Prompts

### Listar prompts disponiveis

```bash
curl -s -X POST $GLPI_MCP_URL/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 30,
    "method": "tools/call",
    "params": {
      "name": "glpi_list_available_prompts",
      "arguments": {}
    }
  }' | jq .
```

### Executar prompt de SLA

```bash
curl -s -X POST $GLPI_MCP_URL/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 31,
    "method": "tools/call",
    "params": {
      "name": "glpi_get_prompt_template",
      "arguments": {
        "name": "glpi_sla_performance",
        "arguments": {"entity_name": "Skills IT", "period_days": 30}
      }
    }
  }' | jq .
```

### Executar prompt de resumo de ticket

```bash
curl -s -X POST $GLPI_MCP_URL/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 32,
    "method": "tools/call",
    "params": {
      "name": "glpi_get_prompt_template",
      "arguments": {
        "name": "glpi_ticket_summary",
        "arguments": {"ticket_id": 1}
      }
    }
  }' | jq .
```

---

## 7. Testes de Resources

### Listar resources disponiveis

```bash
curl -s -X POST $GLPI_MCP_URL/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 40,
    "method": "tools/call",
    "params": {
      "name": "glpi_list_available_resources",
      "arguments": {}
    }
  }' | jq .
```

### Ler status de tickets

```bash
curl -s -X POST $GLPI_MCP_URL/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 41,
    "method": "tools/call",
    "params": {
      "name": "glpi_read_resource_by_uri",
      "arguments": {"uri": "glpi://ticket-status"}
    }
  }' | jq .
```

---

## 8. Testes de Webhooks

### Listar webhooks

```bash
curl -s -X POST $GLPI_MCP_URL/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 50,
    "method": "tools/call",
    "params": {
      "name": "glpi_search_webhook_integrations",
      "arguments": {"scope": "list"}
    }
  }' | jq .
```

---

## 9. Testes de Base de Conhecimento

```bash
curl -s -X POST $GLPI_MCP_URL/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 60,
    "method": "tools/call",
    "params": {
      "name": "glpi_search_knowledge_articles",
      "arguments": {"query": "VPN", "limit": 5}
    }
  }' | jq .
```

---

## 10. Testes com pytest

```bash
cd /opt/mcp-servers/glpi/.base-code

# Todos os testes
PYTHONPATH=. pytest tests/ -v

# Com cobertura
PYTHONPATH=. pytest tests/ --cov=src --cov-report=html

# Testes unitarios de formatters
PYTHONPATH=. pytest tests/unit/ -v

# Testes de integracao
PYTHONPATH=. pytest tests/integration/ -v

# Testes de contrato (formato Markdown, tokens)
PYTHONPATH=. pytest tests/contract/ -v

# Teste especifico
PYTHONPATH=. pytest tests/test_models.py -v -s
```

---

## Troubleshooting

### "GLPI user_token required"
```json
{"error": {"code": -32099, "message": "GLPI user_token required..."}}
```
Adicione o header `X-GLPI-User-Token` com seu token pessoal do GLPI.

### 401 - Authentication failed
Verifique seu User Token e o `app_token` no `glpi-config.json`.

### 404 - Resource not found
O ID do recurso (ticket, ativo, usuario) nao existe no GLPI.

### "Tool not found"
```bash
# Reiniciar servidor e verificar logs
pm2 restart mcp-glpi-skills
pm2 logs mcp-glpi-skills --lines 50
```

### Verificar tools registradas
```bash
curl -s -X POST $GLPI_MCP_URL/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | \
  jq -r '.result.tools[] | "\(.name) [\(if .annotations.readOnlyHint then "READ" else "WRITE" end)]"'
```

---

## Checklist de Validacao

- [ ] Health check responde 200 com `status: healthy`
- [ ] `tools/list` retorna 14 ferramentas (todas com prefixo `glpi_`)
- [ ] Requisicao sem User Token retorna erro claro
- [ ] Requisicao com User Token valido funciona
- [ ] 3 tools de tickets funcionam (search, manage, ai_analysis)
- [ ] 2 tools de ativos funcionam (search, manage)
- [ ] 2 tools de admin funcionam (search, manage)
- [ ] 2 tools de webhooks funcionam (search, manage)
- [ ] 4 tools de bridge funcionam (list_resources, read_resource, list_prompts, get_prompt)
- [ ] 1 tool de conhecimento funciona (search_knowledge)
- [ ] Mensagens de erro seguem JSON-RPC 2.0
- [ ] PM2 gerencia o servico corretamente
