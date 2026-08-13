# GLPI MCP Server — Guia Rápido

## Visão Geral

O MCP GLPI Server é um servidor MCP (Model Context Protocol) que permite a Claude, Gemini e outros LLMs interagirem diretamente com o GLPI (10.x e 11.x) para gestão de chamados, ativos, usuários e integrações.

**Versão:** 2.2.0 | **Protocolo:** MCP 2024-11-05 | **Transporte:** Streamable HTTP | **GLPI:** 10.x e 11.x

## Arquitetura

```
Claude / Gemini CLI
       │
       ▼ (Streamable HTTP)
┌──────────────────────┐
│   MCP GLPI Server    │
│   FastAPI + uvicorn  │
│   18 Tools │ 15 Prompts │ 4 Resources
└──────────┬───────────┘
           │ REST API v1 (apirest.php)
           ▼
┌──────────────────────┐
│   GLPI 10.x / 11.x   │
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

## Resiliência da conexão com o GLPI

Toda chamada ao GLPI passa por um único ponto que aplica timeout, retentativa com
espera exponencial e jitter, respeito ao `Retry-After` em `429` e reautenticação
automática em `401`.

| Variável | Padrão | Função |
|----------|--------|--------|
| `CONNECTION_TIMEOUT` | `30` | Timeout de conexão (segundos) |
| `REQUEST_TIMEOUT` | `60` | Timeout de requisição (segundos) |
| `GLPI_MAX_RETRIES` | `2` | Conta apenas as retentativas — 2 significa até 3 chamadas no total |
| `GLPI_RETRY_BACKOFF_BASE` | `1.5` | Base da espera exponencial |
| `GLPI_RETRY_BACKOFF_CAP` | `20.0` | Teto da espera (segundos) |
| `MAX_CONNECTIONS` | `20` | Conexões simultâneas no pool |
| `MAX_KEEPALIVE_CONNECTIONS` | `10` | Conexões keep-alive no pool |

> ⚠️ **Escrita nunca é repetida depois que o servidor respondeu.** O GLPI pode ter
> aplicado a escrita antes de falhar; repetir criaria um segundo chamado. Só se repete
> o que comprovadamente não chegou ao servidor (conexão recusada, timeout de conexão) e
> o `429`, em que o servidor recusou sem processar. Timeout de leitura/escrita e erro
> `5xx` são repetidos apenas em `GET`.

## Política de escrita

Um interruptor global e uma variável por operação decidem o que o servidor aceita
gravar. As leituras **nunca** são afetadas.

| Variável | Padrão | Função |
|----------|--------|--------|
| `GLPI_READ_ONLY` | `false` | Modo somente-leitura global: bloqueia **toda** escrita |
| `GLPI_ALLOW_<OPERACAO>` | ver abaixo | Um interruptor por operação de escrita |

O nome da variável por operação é `GLPI_ALLOW_` + o nome da operação em maiúsculas com
`.` trocado por `_`. Exemplos: `ticket.create` → `GLPI_ALLOW_TICKET_CREATE`;
`asset.reservation_create` → `GLPI_ALLOW_ASSET_RESERVATION_CREATE`.

**Padrões:** operações não destrutivas vêm **habilitadas**; as seis exclusões vêm
**desabilitadas** e precisam ser ligadas explicitamente —
`GLPI_ALLOW_TICKET_DELETE`, `GLPI_ALLOW_ASSET_DELETE`, `GLPI_ALLOW_USER_DELETE`,
`GLPI_ALLOW_GROUP_DELETE`, `GLPI_ALLOW_LOCATION_DELETE`, `GLPI_ALLOW_WEBHOOK_DELETE`.

Uma escrita bloqueada responde com erro explicando qual variável ligar — não com um
sucesso silencioso. As variáveis são lidas na inicialização: alterá-las exige reiniciar
o servidor.

> O portão de política cobre as tools consolidadas de chamados, ativos, admin e
> webhooks. As escritas ITIL passam pelo safety guard de confirmação
> (`confirmation_token` + `reason`).

## Idempotência

| Variável | Padrão | Função |
|----------|--------|--------|
| `GLPI_IDEMPOTENCY_ENABLED` | `true` | Liga o guarda de idempotência |
| `GLPI_IDEMPOTENCY_BACKEND` | `sqlite` | `sqlite`, `memory` ou `none` |
| `GLPI_IDEMPOTENCY_DB_PATH` | `var/idempotency/store.sqlite3` | Caminho do banco SQLite |
| `GLPI_IDEMPOTENCY_NAMESPACE` | `default` | Isola instâncias que compartilham o mesmo banco |
| `GLPI_IDEMPOTENCY_TTL_SECONDS` | `86400` | Retenção dos registros no armazenamento (24 h) |
| `GLPI_IDEMPOTENCY_LEASE_SECONDS` | `60` | Duração da reserva de uma execução em andamento |
| `GLPI_IDEMPOTENCY_WAIT_TIMEOUT` | `30` | Espera máxima por uma execução concorrente |
| `GLPI_IDEMPOTENCY_POLL_INTERVAL` | `0.25` | Intervalo de sondagem da reserva |
| `GLPI_IDEMPOTENCY_PURGE_INTERVAL` | `300` | Intervalo de limpeza dos expirados |

Repetir exatamente a mesma criação **não cria duas vezes**: a segunda chamada recebe o
resultado da primeira, marcado com `replayed: true`, sem tocar no GLPI. A janela de
proteção no despacho das tools é de **120 segundos** — curta de propósito, para cobrir
o retry do cliente ou do modelo sem impedir que alguém registre, mais tarde, um
comentário legitimamente idêntico.

Se o armazenamento falhar, a operação **não é bloqueada**: executa normalmente e o modo
degradado vai para o log.

## Teste de fumaça contra instância real

A suíte automatizada simula as respostas do GLPI, então não enxerga as semânticas da
própria API. `scripts/smoke_live.sh` roda um conjunto de asserções contra uma instância
de verdade — foi ele que revelou defeitos que os mocks não pegavam, como o operador de
ordem sobre status se comportando como igualdade e a listagem simples ignorando filtros.

```bash
# Somente leitura (padrão). A porta é o primeiro argumento (padrão: 8826).
GLPI_TOKEN=<token do usuário> ./scripts/smoke_live.sh 8826

# Incluindo o ciclo de escrita, contra um chamado de teste
GLPI_TOKEN=<token> SMOKE_WRITE=1 SMOKE_TICKET_ID=<id de teste> \
  ./scripts/smoke_live.sh 8826
```

> ⚠️ **O token vem SEMPRE do ambiente.** Nunca grave o token no script nem o adicione
> ao `.env` do servidor: ali ele viraria *fallback*, e o servidor passaria a aceitar
> chamadas **sem identificação** usando essa identidade — quebrando o isolamento entre
> clientes e a autoria correta dos registros no GLPI.

## Diagnóstico: conexão e autenticação

Os dois problemas mais comuns na primeira conexão se parecem, mas têm causas
opostas. O que os separa é **em que momento** a falha aparece.

### 1. "Server unreachable" / `McpError` — quase sempre a URL sem `/mcp`

O servidor só expõe o MCP em `/mcp`. Apontar o cliente para a raiz devolve **404**,
e os clientes MCP traduzem isso como servidor inacessível — o que leva a procurar
firewall, porta e serviço fora do ar, quando o processo está saudável.

```
✅ http://<host>:<porta>/mcp
❌ http://<host>:<porta>
```

Confirme antes de investigar rede:

```bash
curl -s http://<host>:<porta>/health          # o serviço está de pé?
curl -s -X POST http://<host>:<porta>/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | head -c 300
```

### 2. As tools aparecem, mas toda chamada falha — é o token

**Descobrir as tools não prova que a credencial está certa.** `initialize`,
`tools/list`, `prompts/list` e `resources/list` são servidos de um registro em
memória e **não exigem token algum**. Só `tools/call` autentica no GLPI. Um cliente
que lista as tools e falha em todas está com problema de credencial, não de
conexão.

**E credencial válida ≠ permissão suficiente.** O `X-GLPI-User-Token` autentica um
USUÁRIO do GLPI, e o `initSession` assume o **perfil padrão** dele. Um usuário com
perfil *Self-Service* abre sessão sem erro, mas `GET /Ticket/{id}` de um chamado que
não é dele volta `ERROR_RIGHT_MISSING` — enquanto a busca continua funcionando. Se as
leituras de chamado falham e a listagem não, olhe o perfil, não o token. Use
`glpi_manage_admin_resources(resource='users', action='get', resource_id=...)`, que
mostra os perfis do usuário.

Ambas as falhas de autenticação retornam o mesmo código JSON-RPC **`-32001`**; o
que distingue a causa é a **mensagem**:

| Mensagem | Causa | O que fazer |
|----------|-------|-------------|
| `GLPI user_token required. Configure X-GLPI-User-Token header…` | O header **não chegou** ao servidor | Verifique se o cliente MCP está enviando `X-GLPI-User-Token` (em proxies, se o header é repassado) |
| `Token de usuario do GLPI invalido ou expirado…` | O header chegou, mas o **GLPI recusou** o valor | Gere um novo token em *Administração > Usuários > [usuário] > Chaves de acesso remoto* |

> `-32099` é outra coisa: é o envelope genérico de falha inesperada **dentro de uma
> tool** (`Tool 'X' falhou: …`). Não indique problema de token só por vê-lo.

### 3. O token é por instância do GLPI

O `user_token` é emitido por uma instância específica e **não vale em outra**,
mesmo que os dois MCPs rodem o mesmo código. Ao operar mais de um cliente, cada
conexão precisa do token daquele GLPI — reaproveitar o token do GLPI A no GLPI B
produz exatamente a mensagem de "inválido ou expirado" acima.

O **`App-Token`, por outro lado, é fixo na configuração do servidor** e o cliente
não envia: se ele estiver errado, o erro é o mesmo para todos os usuários daquela
instância, não para um só.

## Próximos Passos

- [Referência Completa de Tools](./TOOLS-REFERENCE.md) — 17 ferramentas com parâmetros e exemplos
- [Referência de Prompts](./PROMPTS-REFERENCE.md) — 15 prompts prontos para relatórios gerenciais
- [Exemplos de Uso](./EXAMPLES.md) — Cenários completos passo a passo
- [CHANGELOG](../CHANGELOG.md) — Histórico de versões e correções

## Dicas Importantes (v2.2+)

- **Token do usuário:** cada cliente MCP envia seu próprio `X-GLPI-User-Token` no header. Isso respeita as permissões nativas do GLPI.
- **Filtros por nome:** técnico, grupo, solicitante, categoria e responsável por ativo aceitam o **nome** — não é preciso descobrir o ID antes.
- **Busca textual não anula filtros:** `query` combina com status, prioridade, datas e atores.
- **Contar sem paginar:** `count_only` (ITIL) e `scope=count` (consulta livre) devolvem só o total.
- **Descobrir campos:** `glpi_search_records_by_criteria` com `scope=fields` lista os campos filtráveis da **sua** instância.
- **Rate limit localhost:** chamadas vindas de `127.0.0.1` / `::1` ignoram o rate limit — ideal para LLMs locais que fazem chamadas paralelas.
- **Entity ID=0 é válido:** o entity root do GLPI (MSP) pode ser consultado com `resource_id=0` em `glpi_manage_admin_resources`.
- **Webhooks são nativos do GLPI 11** — persistem a reinícios do MCP e aparecem na interface do GLPI. IDs são hashes alfanuméricos (não inteiros).
- **event_type usa ponto:** `ticket.created`, não `ticket_created`.
- **`get_details` de Computer** traz OS + discos + CPU + memória + rede + software em uma única resposta Markdown.
