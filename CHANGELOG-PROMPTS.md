# Changelog - Sistema de Prompts Profissionais

**Data:** 11 de Dezembro de 2025
**Versão:** 1.1.0
**Desenvolvido por:** Skills IT - Soluções em Tecnologia 🇧🇷

---

## ✨ Novidades Implementadas

### 📋 Sistema de Prompts Profissionais (15 prompts)

Implementado sistema completo de prompts pré-configurados para análise gerencial e operacional de TI.

#### 🎯 Características Principais

1. **Dois Formatos de Saída:**
   - **Compacto:** 10 linhas máximo (ideal para WhatsApp/Teams)
   - **Detalhado:** Markdown completo (documentação, relatórios)

2. **Multi-Step Aware:**
   - Prompts inteligentes que resolvem entity_name → entity_id automaticamente
   - Busca de dados contextual antes de gerar relatórios

3. **Otimizado para Consumo de Tokens:**
   - Respostas concisas sem perder informação
   - Formatação padronizada para fácil parsing

---

## 📊 Prompts Implementados

### Gestão de TI (7 prompts)

| # | Nome | Descrição | Argumentos |
|---|------|-----------|------------|
| 1 | `glpi_sla_performance` | Desempenho de SLA mensal | entity_name, period_days |
| 2 | `glpi_ticket_trends` | Tendências de tickets por categoria | entity_name, period_days |
| 3 | `glpi_asset_roi` | ROI de ativos por cliente | entity_name |
| 4 | `glpi_technician_productivity` | Produtividade de técnicos | period_days |
| 5 | `glpi_cost_per_ticket` | Custo médio por ticket | entity_name, period_days |
| 6 | `glpi_recurring_problems` | Problemas recorrentes | entity_name, min_occurrences |
| 7 | `glpi_client_satisfaction` | Indicadores de satisfação | entity_name, period_days |

### Suporte Técnico (8 prompts)

| # | Nome | Descrição | Argumentos |
|---|------|-----------|------------|
| 8 | `glpi_ticket_summary` | Resumo rápido de ticket | ticket_id |
| 9 | `glpi_user_ticket_history` | Histórico de tickets do usuário | username |
| 10 | `glpi_asset_lookup` | Busca rápida de ativo | search_term |
| 11 | `glpi_onboarding_checklist` | Checklist onboarding usuário | username, entity_name |
| 12 | `glpi_incident_investigation` | Investigação de incidente (RCA) | ticket_id |
| 13 | `glpi_change_management` | Checklist de mudança (RFC) | change_description |
| 14 | `glpi_hardware_request` | Template solicitação hardware | user_name, hardware_type |
| 15 | `glpi_knowledge_base_search` | Busca em base de conhecimento | search_query |

---

## 🛠️ Implementação Técnica

### Arquivos Criados

```
/opt/mcp-servers/glpi/
├── src/
│   └── prompts_handlers/
│       ├── __init__.py           # Package initialization
│       └── prompts.py             # Sistema de prompts (45KB)
├── TESTING-PROMPTS.md            # Guia de testes
└── CHANGELOG-PROMPTS.md          # Este arquivo
```

### Integração no MCP

**Arquivo:** `src/handlers.py`

**Modificações:**
1. Import do `prompt_handler` de `src.prompts_handlers.prompts`
2. Registro de 2 novos tools no método `_register_tools()`:
   - `glpi_list_prompts` - Lista todos os prompts disponíveis
   - `glpi_get_prompt` - Executa prompt específico com argumentos
3. Adição de descrições no método `_get_tool_description()`

**Total de Tools do MCP GLPI:** 68 tools (66 anteriores + 2 novos)

---

## 🔧 Como Usar

### 1. Listar Prompts Disponíveis

**No Claude Code:**
```
GLPI, liste os prompts disponíveis
```

**Via curl:**
```bash
curl -X POST http://mcp.servidor.one:8824/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-GLPI-User-Token: SEU_TOKEN' \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "glpi_list_prompts",
      "arguments": {}
    }
  }'
```

### 2. Executar Prompt

**No Claude Code:**
```
GLPI, gere relatório de SLA dos últimos 30 dias para Skills IT

GLPI, mostre resumo do ticket 123

GLPI, crie checklist de onboarding para João Silva na empresa Skills IT
```

**Via curl:**
```bash
curl -X POST http://mcp.servidor.one:8824/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-GLPI-User-Token: SEU_TOKEN' \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "glpi_get_prompt",
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

---

## ✅ Validação

### Testes Realizados

- [x] Health check do servidor → 200 OK
- [x] `tools/list` inclui `glpi_list_prompts` e `glpi_get_prompt`
- [x] `glpi_list_prompts` retorna 15 prompts
- [x] Servidor inicia sem erros após implementação
- [x] Logs limpos (sem erros de importação)

### Comandos de Validação

```bash
# 1. Verificar se servidor está rodando
pm2 status mcp-glpi

# 2. Health check
curl http://mcp.servidor.one:8824/health

# 3. Verificar logs
pm2 logs mcp-glpi --lines 20

# 4. Listar tools (filtrar prompts)
curl -X POST http://mcp.servidor.one:8824/mcp \
  -H 'Content-Type: application/json' \
  -H 'X-GLPI-User-Token: SEU_TOKEN' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | \
  jq '.result.tools | map(select(.name | contains("prompts")))'
```

---

## 📈 Benefícios para o Negócio

### Para Gestores de TI

1. **Relatórios Executivos Instantâneos:**
   - SLA performance mensal
   - Tendências de demanda
   - ROI de ativos
   - Custo por ticket

2. **Tomada de Decisão Baseada em Dados:**
   - Identificação de problemas recorrentes
   - Análise de produtividade da equipe
   - Indicadores de satisfação do cliente

### Para Analistas de Suporte

1. **Agilidade Operacional:**
   - Resumos rápidos de tickets para WhatsApp/Teams
   - Histórico completo do usuário em segundos
   - Busca instantânea de ativos

2. **Padronização de Processos:**
   - Checklists de onboarding
   - Templates de investigação de incidentes (RCA)
   - Procedimentos de gestão de mudança (RFC)
   - Solicitações de hardware padronizadas

3. **Base de Conhecimento Acessível:**
   - Busca inteligente em KB
   - Sugestões de artigos relacionados
   - Resoluções de problemas comuns

---

## 🔄 Próximos Passos (Roadmap)

### Fase 2 (Planejada)

- [ ] Integração com dados reais do GLPI (atualmente usa dados de exemplo)
- [ ] Geração de gráficos em formato imagem (PNG/SVG)
- [ ] Exportação de relatórios em PDF
- [ ] Agendamento de relatórios automáticos
- [ ] Alertas proativos baseados em thresholds

### Fase 3 (Futuro)

- [ ] Prompts customizáveis por cliente
- [ ] Machine learning para sugestões inteligentes
- [ ] Integração com Power BI/Grafana
- [ ] API para integração com outras plataformas

---

## 📞 Suporte e Contato

**Skills IT - Soluções em Tecnologia**

- 📱 WhatsApp: +55 63 3224-4925
- 📧 Email: contato@skillsit.com.br
- 🌐 Website: https://skillsit.com.br
- 📍 Localização: Brasil 🇧🇷

*"Transformando infraestrutura em inteligência"*

---

## 📄 Licença

MIT License - Skills IT © 2025

---

**Desenvolvido com ❤️ por Skills IT**
**Última Atualização:** 11 de Dezembro de 2025
**Versão do MCP GLPI:** 1.1.0
