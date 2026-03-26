# GLPI MCP Server — Guia Rápido

## Visão Geral

O MCP GLPI Server é um servidor MCP (Model Context Protocol) que permite a Claude, Gemini e outros LLMs interagirem diretamente com o GLPI 10 para gestão de chamados, ativos, usuários e integrações.

**Versão:** 2.0 | **Protocolo:** MCP 2024-11-05 | **Transporte:** Streamable HTTP

## Arquitetura

```
Claude / Gemini CLI
       │
       ▼ (Streamable HTTP)
┌──────────────────────┐
│   MCP GLPI Server    │
│   FastAPI + uvicorn  │
│   14 Tools │ 15 Prompts │ 4 Resources
└──────────┬───────────┘
           │ REST API
           ▼
┌──────────────────────┐
│      GLPI 10 API     │
│   (por cliente)      │
└──────────────────────┘
```

## Instalação Rápida

```bash
# 1. Clonar o repositório
git clone https://github.com/DevSkillsIT/Skills-MCP-GLPI.git
cd Skills-MCP-GLPI

# 2. Criar virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Instalar dependências
pip install -r requirements.txt

# 4. Configurar
cp .env.example .env
# Editar .env com as credenciais do GLPI
```

## Configuração do Cliente

Crie um arquivo `glpi-config.json` para cada cliente:

```json
{
  "glpi": {
    "base_url": "https://suporte.empresa.com.br",
    "app_token": "SEU_APP_TOKEN_GLPI",
    "user_token": ""
  },
  "http": {
    "host": "0.0.0.0",
    "port": 8824,
    "path": "/mcp"
  },
  "client": {
    "name": "Nome da Empresa",
    "slug": "empresa",
    "type": "cliente"
  }
}
```

## Executando

```bash
# Modo desenvolvimento
PYTHONPATH=. GLPI_MCP_CONFIG=path/to/glpi-config.json \
  python -m uvicorn src.main:app --host 0.0.0.0 --port 8824

# Modo produção (PM2)
pm2 start ecosystem.http.config.js
```

## Configuração no Claude Code

Adicione ao `.mcp.json` do projeto:

```json
{
  "mcpServers": {
    "glpi": {
      "type": "streamable-http",
      "url": "http://localhost:8824/mcp"
    }
  }
}
```

## Endpoints HTTP

| Método | Rota | Função |
|--------|------|--------|
| `POST` | `/mcp` | JSON-RPC 2.0 (chamadas MCP) |
| `GET` | `/mcp` | SSE (notificações servidor→cliente) |
| `DELETE` | `/mcp` | Encerrar sessão |
| `GET` | `/health` | Health check |

## Próximos Passos

- [Referência Completa de Tools](./TOOLS-REFERENCE.md) — 14 ferramentas com parâmetros e exemplos
- [Referência de Prompts](./PROMPTS-REFERENCE.md) — 15 prompts prontos para relatórios gerenciais
- [Exemplos de Uso](./EXAMPLES.md) — Cenários completos passo a passo
