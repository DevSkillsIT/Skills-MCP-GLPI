# TESTING.md - Guia de Testes do MCP GLPI

Documentação completa para testes e validação do MCP GLPI usando curl.

## Pré-requisitos

- Servidor MCP GLPI rodando (porta 8824 por padrão)
- curl instalado
- Acesso à GLPI com credenciais válidas
- **User Token do GLPI** (cada usuário precisa do seu próprio token)

## Autenticação Per-User (IMPORTANTE!)

O MCP GLPI implementa **autenticação per-user** para garantir que cada usuário opere com suas próprias permissões no GLPI.

### Por que isso é importante?

- **Segurança**: Cada usuário usa suas próprias credenciais
- **Permissões**: O usuário só vê/faz o que tem permissão no GLPI
- **Auditoria**: Todas as ações são rastreáveis ao usuário real

### Como obter seu User Token

1. Acesse o GLPI com suas credenciais
2. Vá em: **Administração > Usuários > [seu usuário]**
3. Clique na aba **Configurações remotas** (ou "Remote access keys")
4. Gere ou copie seu **User Token**

### Configuração para Testes

```bash
# Configure seu User Token (substitua pelo seu token real)
export GLPI_USER_TOKEN="seu_user_token_aqui"

# URL do servidor MCP
export GLPI_MCP_URL="http://mcp.servidor.one:8824"
```

### Header obrigatório em todas as requisições

Todas as chamadas ao MCP (exceto health check e tools/list) requerem o header:

```
X-GLPI-User-Token: seu_user_token_aqui
```

## Health Check (Obrigatório)

Verifica se o servidor está ativo e saudável.

```bash
# Simples
curl http://localhost:8824/health

# Com formatação
curl -s http://localhost:8824/health | jq .

# Com verbose
curl -v http://localhost:8824/health
```

Resposta esperada:
```json
{
  "status": "healthy",
  "service": "mcp-glpi",
  "version": "1.0.0",
  "timestamp": "2025-12-07T12:00:00.000000"
}
```

## Testes Básicos MCP

### 1. Listar Ferramentas

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/list",
    "id": 1
  }' | jq .
```

Resposta esperada: Array com 48 tools.

### 2. Informações do Servidor

```bash
curl http://localhost:8824/ | jq .
```

## Testes de Tickets

### Listar Tickets

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "list_tickets",
      "arguments": {
        "limit": 10,
        "offset": 0
      }
    },
    "id": 1
  }' | jq .
```

### Obter Ticket Específico

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "get_ticket",
      "arguments": {
        "ticket_id": 1
      }
    },
    "id": 1
  }' | jq .
```

### Criar Ticket

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "create_ticket",
      "arguments": {
        "title": "Novo Ticket de Teste",
        "description": "Descrição do problema",
        "priority": 3,
        "requesters": [1, 2]
      }
    },
    "id": 1
  }' | jq .
```

### Atualizar Ticket

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "update_ticket",
      "arguments": {
        "ticket_id": 1,
        "status": "assigned",
        "priority": 2
      }
    },
    "id": 1
  }' | jq .
```

### Atribuir Ticket

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "assign_ticket",
      "arguments": {
        "ticket_id": 1,
        "user_id": 5
      }
    },
    "id": 1
  }' | jq .
```

### Fechar Ticket

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "close_ticket",
      "arguments": {
        "ticket_id": 1,
        "resolution": "Problema resolvido"
      }
    },
    "id": 1
  }' | jq .
```

### Deletar Ticket

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "delete_ticket",
      "arguments": {
        "ticket_id": 1
      }
    },
    "id": 1
  }' | jq .
```

### Opções de Status de Ticket

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "get_ticket_status_options",
      "arguments": {}
    },
    "id": 1
  }' | jq .
```

## Testes de Assets

### Listar Computadores

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "list_computers",
      "arguments": {
        "limit": 10,
        "offset": 0
      }
    },
    "id": 1
  }' | jq .
```

### Criar Computador

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "create_computer",
      "arguments": {
        "name": "PC-TESTE-001",
        "serial_number": "SN-123456",
        "model": "Lenovo Think Pad",
        "manufacturer": "Lenovo"
      }
    },
    "id": 1
  }' | jq .
```

### Listar Monitores

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "list_monitors",
      "arguments": {}
    },
    "id": 1
  }' | jq .
```

### Listar Impressoras

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "list_printers",
      "arguments": {}
    },
    "id": 1
  }' | jq .
```

### Atribuir Asset a Usuário

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "assign_asset_to_user",
      "arguments": {
        "asset_id": 1,
        "asset_type": "Computer",
        "user_id": 5
      }
    },
    "id": 1
  }' | jq .
```

## Testes de Usuários

### Listar Usuários

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "list_users",
      "arguments": {
        "limit": 10,
        "offset": 0
      }
    },
    "id": 1
  }' | jq .
```

### Criar Usuário

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "create_user",
      "arguments": {
        "firstname": "João",
        "lastname": "Silva",
        "email": "joao.silva@example.com",
        "phone": "(11) 99999-9999"
      }
    },
    "id": 1
  }' | jq .
```

### Atualizar Usuário

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "update_user",
      "arguments": {
        "user_id": 10,
        "email": "novo@example.com",
        "phone": "(11) 98888-8888"
      }
    },
    "id": 1
  }' | jq .
```

## Testes de Grupos

### Listar Grupos

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "list_groups",
      "arguments": {}
    },
    "id": 1
  }' | jq .
```

### Criar Grupo

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "create_group",
      "arguments": {
        "name": "Suporte Técnico",
        "comment": "Equipe de suporte técnico"
      }
    },
    "id": 1
  }' | jq .
```

### Adicionar Usuário a Grupo

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "add_user_to_group",
      "arguments": {
        "user_id": 5,
        "group_id": 3
      }
    },
    "id": 1
  }' | jq .
```

## Testes de Entidades

### Listar Entidades

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "list_entities",
      "arguments": {}
    },
    "id": 1
  }' | jq .
```

### Criar Entidade

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "create_entity",
      "arguments": {
        "name": "ACME Corporation",
        "entity_type": "Cliente",
        "phone": "(11) 3456-7890"
      }
    },
    "id": 1
  }' | jq .
```

## Testes de Localizações

### Listar Localizações

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "list_locations",
      "arguments": {}
    },
    "id": 1
  }' | jq .
```

### Criar Localização

```bash
curl -X POST http://localhost:8824/mcp \
  -H 'Content-Type: application/json' \
  -H "X-GLPI-User-Token: $GLPI_USER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "create_location",
      "arguments": {
        "name": "São Paulo",
        "address": "Av. Paulista, 1000",
        "phone": "(11) 3000-0000"
      }
    },
    "id": 1
  }' | jq .
```

## Testes Unitários

Execute os testes com pytest:

```bash
# Todos os testes
pytest tests/ -v

# Com cobertura
pytest tests/ --cov=src --cov-report=html

# Teste específico
pytest tests/test_models.py::TestTicketModel::test_create_valid_ticket -v

# Mostrar prints
pytest tests/ -s

# Apenas um arquivo
pytest tests/test_handlers.py -v
```

## Troubleshooting

### Erro: User Token Requerido
```
{
  "error": {
    "code": -32099,
    "message": "GLPI user_token required. Configure X-GLPI-User-Token header..."
  }
}
```
**Solução**: Configure o header `X-GLPI-User-Token` com seu token pessoal do GLPI. Veja seção "Autenticação Per-User" acima.

### Erro 401 - Autenticação
```
{
  "error": {
    "code": 401,
    "message": "Authentication failed"
  }
}
```
**Solução**: Verifique seu User Token e o GLPI_APP_TOKEN em .env

### Erro 404 - Recurso não encontrado
```
{
  "error": {
    "code": 404,
    "message": "Resource not found"
  }
}
```
**Solução**: Verifique se o ID do recurso existe

### Erro 400 - Validação
```
{
  "error": {
    "code": 400,
    "message": "Validation error",
    "data": {
      "field": "priority",
      "detail": "Priority must be between 1 and 5"
    }
  }
}
```
**Solução**: Revise os parâmetros enviados

## Checklist de Validação

- [ ] Health check responde 200
- [ ] `/health` retorna `status: healthy`
- [ ] `/mcp` com `tools/list` retorna 65 ferramentas
- [ ] Requisição sem User Token retorna erro claro de autenticação
- [ ] Requisição com User Token válido funciona corretamente
- [ ] Todas as 12 ticket tools funcionam
- [ ] Todas as 12 asset tools funcionam
- [ ] Todas as 13 user/group tools funcionam
- [ ] Todas as 5 entity tools funcionam
- [ ] Todas as 6 location tools funcionam
- [ ] Mensagens de erro seguem JSON-RPC
- [ ] Logs são gerados corretamente
- [ ] PM2 consegue gerenciar o serviço

## Performance

Teste de performance com Apache Bench:

```bash
# 100 requisições com 10 concorrentes
ab -n 100 -c 10 http://localhost:8824/health

# POST com dados
ab -n 100 -c 10 -p data.json -T application/json http://localhost:8824/mcp
```

---

**Última atualização**: Dezembro 2025
**Versão**: 1.0.0
