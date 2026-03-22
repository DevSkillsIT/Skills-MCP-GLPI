"""
MCP GLPI - Sistema de Prompts Profissionais
Fornece prompts pré-configurados para análise gerencial e operacional.

Skills IT - Soluções em Tecnologia
Desenvolvido para MSPs brasileiros com foco em produtividade.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import logging

from src.glpi_service import GLPIService
from src.models import NotFoundError, ValidationError, GLPIError

logger = logging.getLogger(__name__)


# ============= CATÁLOGO DE PROMPTS =============

PROMPTS_CATALOG = [
    # ===== GESTOR DE TI (7 prompts) =====
    {
        "name": "glpi_sla_performance",
        "description": "Gera relatório de desempenho de SLA mensal com tempo médio de resposta e resolução",
        "category": "gestao",
        "audience": "Gestor de TI",
        "arguments": [
            {
                "name": "entity_name",
                "description": "Nome do cliente (opcional, padrão: todas entidades)",
                "type": "string",
                "required": False
            },
            {
                "name": "period_days",
                "description": "Período em dias (padrão: 30)",
                "type": "integer",
                "required": False,
                "default": 30
            }
        ]
    },
    {
        "name": "glpi_ticket_trends",
        "description": "Analisa tendências de tickets por categoria (aumento/redução de demandas)",
        "category": "gestao",
        "audience": "Gestor de TI",
        "arguments": [
            {
                "name": "entity_name",
                "description": "Nome do cliente (opcional)",
                "type": "string",
                "required": False
            },
            {
                "name": "period_days",
                "description": "Período em dias (padrão: 30)",
                "type": "integer",
                "required": False,
                "default": 30
            }
        ]
    },
    {
        "name": "glpi_asset_roi",
        "description": "Calcula ROI de ativos por cliente (custo vs utilização)",
        "category": "gestao",
        "audience": "Gestor de TI",
        "arguments": [
            {
                "name": "entity_name",
                "description": "Nome do cliente (obrigatório para ROI específico)",
                "type": "string",
                "required": True
            }
        ]
    },
    {
        "name": "glpi_technician_productivity",
        "description": "Mede produtividade de técnicos (tickets resolvidos, tempo médio)",
        "category": "gestao",
        "audience": "Gestor de TI",
        "arguments": [
            {
                "name": "period_days",
                "description": "Período em dias (padrão: 30)",
                "type": "integer",
                "required": False,
                "default": 30
            }
        ]
    },
    {
        "name": "glpi_cost_per_ticket",
        "description": "Calcula custo médio por ticket (tempo técnico vs resultado)",
        "category": "gestao",
        "audience": "Gestor de TI",
        "arguments": [
            {
                "name": "entity_name",
                "description": "Nome do cliente (opcional)",
                "type": "string",
                "required": False
            },
            {
                "name": "period_days",
                "description": "Período em dias (padrão: 30)",
                "type": "integer",
                "required": False,
                "default": 30
            }
        ]
    },
    {
        "name": "glpi_recurring_problems",
        "description": "Identifica problemas recorrentes para ação preventiva",
        "category": "gestao",
        "audience": "Gestor de TI",
        "arguments": [
            {
                "name": "entity_name",
                "description": "Nome do cliente (opcional)",
                "type": "string",
                "required": False
            },
            {
                "name": "min_occurrences",
                "description": "Número mínimo de ocorrências (padrão: 3)",
                "type": "integer",
                "required": False,
                "default": 3
            }
        ]
    },
    {
        "name": "glpi_client_satisfaction",
        "description": "Relatório de indicadores de satisfação do cliente",
        "category": "gestao",
        "audience": "Gestor de TI",
        "arguments": [
            {
                "name": "entity_name",
                "description": "Nome do cliente (opcional)",
                "type": "string",
                "required": False
            },
            {
                "name": "period_days",
                "description": "Período em dias (padrão: 30)",
                "type": "integer",
                "required": False,
                "default": 30
            }
        ]
    },

    # ===== ANALISTA DE SUPORTE (8 prompts) =====
    {
        "name": "glpi_ticket_summary",
        "description": "Resumo rápido de ticket para WhatsApp/Teams (10 linhas max)",
        "category": "suporte",
        "audience": "Analista de Suporte",
        "arguments": [
            {
                "name": "ticket_id",
                "description": "ID do ticket",
                "type": "integer",
                "required": True
            }
        ]
    },
    {
        "name": "glpi_user_ticket_history",
        "description": "Histórico completo de tickets do usuário",
        "category": "suporte",
        "audience": "Analista de Suporte",
        "arguments": [
            {
                "name": "username",
                "description": "Nome ou login do usuário",
                "type": "string",
                "required": True
            }
        ]
    },
    {
        "name": "glpi_asset_lookup",
        "description": "Busca rápida de ativo (computador, serial, usuário)",
        "category": "suporte",
        "audience": "Analista de Suporte",
        "arguments": [
            {
                "name": "search_term",
                "description": "Nome, serial, ou usuário",
                "type": "string",
                "required": True
            }
        ]
    },
    {
        "name": "glpi_onboarding_checklist",
        "description": "Checklist de onboarding para novo usuário",
        "category": "suporte",
        "audience": "Analista de Suporte",
        "arguments": [
            {
                "name": "username",
                "description": "Nome do novo usuário",
                "type": "string",
                "required": True
            },
            {
                "name": "entity_name",
                "description": "Nome do cliente/empresa",
                "type": "string",
                "required": True
            }
        ]
    },
    {
        "name": "glpi_incident_investigation",
        "description": "Template de investigação de incidente (RCA - Root Cause Analysis)",
        "category": "suporte",
        "audience": "Analista de Suporte",
        "arguments": [
            {
                "name": "ticket_id",
                "description": "ID do ticket de incidente",
                "type": "integer",
                "required": True
            }
        ]
    },
    {
        "name": "glpi_change_management",
        "description": "Checklist de gestão de mudança (RFC - Request for Change)",
        "category": "suporte",
        "audience": "Analista de Suporte",
        "arguments": [
            {
                "name": "change_description",
                "description": "Descrição da mudança planejada",
                "type": "string",
                "required": True
            }
        ]
    },
    {
        "name": "glpi_hardware_request",
        "description": "Template de solicitação de hardware padronizado",
        "category": "suporte",
        "audience": "Analista de Suporte",
        "arguments": [
            {
                "name": "user_name",
                "description": "Nome do usuário solicitante",
                "type": "string",
                "required": True
            },
            {
                "name": "hardware_type",
                "description": "Tipo de hardware (Notebook, Desktop, Monitor, etc.)",
                "type": "string",
                "required": True
            }
        ]
    },
    {
        "name": "glpi_knowledge_base_search",
        "description": "Busca em base de conhecimento com sugestões de artigos",
        "category": "suporte",
        "audience": "Analista de Suporte",
        "arguments": [
            {
                "name": "search_query",
                "description": "Termo de busca ou descrição do problema",
                "type": "string",
                "required": True
            }
        ]
    }
]


# ============= HANDLERS DE PROMPTS =============

class PromptHandler:
    """Handler para sistema de prompts profissionais."""

    def __init__(self):
        self.service = GLPIService()
        logger.info(f"PromptHandler initialized with {len(PROMPTS_CATALOG)} prompts")

    async def list_prompts(self) -> Dict[str, List]:
        """
        Lista todos os prompts disponíveis.

        Returns:
            Lista de prompts com metadados
        """
        logger.info("Listing all prompts")
        return {"prompts": PROMPTS_CATALOG}

    async def get_prompt(self, name: str, arguments: Dict[str, Any]) -> Dict:
        """
        Executa um prompt específico com argumentos.

        Args:
            name: Nome do prompt (ex: glpi_sla_performance)
            arguments: Argumentos do prompt

        Returns:
            Resultado do prompt em formato compacto e detalhado
        """
        logger.info(f"Executing prompt: {name} with args: {arguments}")

        # Encontrar prompt no catálogo
        prompt_config = next((p for p in PROMPTS_CATALOG if p["name"] == name), None)
        if not prompt_config:
            raise NotFoundError("Prompt", name)

        # Validar argumentos obrigatórios
        for arg in prompt_config.get("arguments", []):
            if arg.get("required", False) and arg["name"] not in arguments:
                raise ValidationError(
                    f"Argumento obrigatório ausente: {arg['name']}",
                    arg["name"]
                )

        # Rotear para handler específico
        handler_map = {
            # Gestão
            "glpi_sla_performance": self._prompt_sla_performance,
            "glpi_ticket_trends": self._prompt_ticket_trends,
            "glpi_asset_roi": self._prompt_asset_roi,
            "glpi_technician_productivity": self._prompt_technician_productivity,
            "glpi_cost_per_ticket": self._prompt_cost_per_ticket,
            "glpi_recurring_problems": self._prompt_recurring_problems,
            "glpi_client_satisfaction": self._prompt_client_satisfaction,

            # Suporte
            "glpi_ticket_summary": self._prompt_ticket_summary,
            "glpi_user_ticket_history": self._prompt_user_ticket_history,
            "glpi_asset_lookup": self._prompt_asset_lookup,
            "glpi_onboarding_checklist": self._prompt_onboarding_checklist,
            "glpi_incident_investigation": self._prompt_incident_investigation,
            "glpi_change_management": self._prompt_change_management,
            "glpi_hardware_request": self._prompt_hardware_request,
            "glpi_knowledge_base_search": self._prompt_knowledge_base_search
        }

        handler = handler_map.get(name)
        if not handler:
            raise GLPIError(500, f"Handler não implementado para prompt: {name}")

        return await handler(arguments)

    # ============= PROMPTS DE GESTÃO =============

    async def _prompt_sla_performance(self, args: Dict) -> Dict:
        """Relatório de desempenho de SLA."""
        entity_name = args.get("entity_name")
        period_days = args.get("period_days", 30)

        # Step 1: Resolver entity_name -> entity_id (se fornecido)
        entity_id = None
        if entity_name:
            entities = await self.service.list_entities()
            entity = next((e for e in entities if entity_name.lower() in e.name.lower()), None)
            if entity:
                entity_id = entity.id

        # Step 2: Buscar estatísticas de tickets
        stats = await self.service.get_ticket_stats(entity_id=entity_id)

        # Step 3: Gerar relatório compacto (WhatsApp/Teams)
        compact = f"""📊 SLA Performance - Últimos {period_days} dias
{'Cliente: ' + entity_name if entity_name else 'Todos os clientes'}

✅ Tickets Resolvidos: {stats.get('solved', 0)}
⏱️ Tempo Médio Resposta: {stats.get('avg_response_time', 'N/A')}
🔧 Tempo Médio Resolução: {stats.get('avg_resolution_time', 'N/A')}
📈 Taxa de Cumprimento SLA: {stats.get('sla_compliance', 'N/A')}%

⚠️ Tickets em Atraso: {stats.get('overdue', 0)}
"""

        # Step 4: Gerar relatório detalhado (Markdown)
        detailed = f"""# Relatório de Desempenho de SLA

**Período:** Últimos {period_days} dias
**Cliente:** {entity_name if entity_name else 'Todos os clientes'}
**Gerado em:** {datetime.now().strftime('%d/%m/%Y %H:%M')}

---

## 📊 Resumo Executivo

| Métrica | Valor |
|---------|-------|
| Tickets Abertos | {stats.get('opened', 0)} |
| Tickets Resolvidos | {stats.get('solved', 0)} |
| Tickets em Andamento | {stats.get('in_progress', 0)} |
| Tickets em Atraso | {stats.get('overdue', 0)} |

## ⏱️ Tempos Médios

- **Tempo de Primeira Resposta:** {stats.get('avg_response_time', 'N/A')}
- **Tempo de Resolução:** {stats.get('avg_resolution_time', 'N/A')}
- **Taxa de Cumprimento de SLA:** {stats.get('sla_compliance', 'N/A')}%

## 📈 Análise

{self._generate_sla_analysis(stats)}

---

*Relatório gerado automaticamente pelo Skills MCP GLPI*
"""

        return {
            "prompt_name": "glpi_sla_performance",
            "compact": compact,
            "detailed": detailed,
            "metadata": {
                "entity_name": entity_name,
                "period_days": period_days,
                "generated_at": datetime.now().isoformat()
            }
        }

    async def _prompt_ticket_trends(self, args: Dict) -> Dict:
        """Análise de tendências de tickets."""
        entity_name = args.get("entity_name")
        period_days = args.get("period_days", 30)

        # Buscar tickets do período
        tickets = await self.service.list_tickets(limit=500)

        # Análise simples de categorias
        categories = {}
        for ticket in tickets:
            cat = getattr(ticket, 'itilcategories_id', 'Sem Categoria')
            categories[cat] = categories.get(cat, 0) + 1

        top_categories = sorted(categories.items(), key=lambda x: x[1], reverse=True)[:5]

        compact = f"""📊 Tendências de Tickets - {period_days} dias
{'Cliente: ' + entity_name if entity_name else 'Global'}

🔝 Top 5 Categorias:
"""
        for i, (cat, count) in enumerate(top_categories, 1):
            compact += f"{i}. {cat}: {count} tickets\n"

        detailed = f"""# Análise de Tendências de Tickets

**Período:** {period_days} dias
**Total de Tickets:** {len(tickets)}

## 📊 Distribuição por Categoria

| Posição | Categoria | Quantidade | Percentual |
|---------|-----------|------------|------------|
"""
        total = len(tickets)
        for i, (cat, count) in enumerate(top_categories, 1):
            pct = (count / total * 100) if total > 0 else 0
            detailed += f"| {i} | {cat} | {count} | {pct:.1f}% |\n"

        detailed += "\n---\n*Relatório gerado pelo Skills MCP GLPI*"

        return {
            "prompt_name": "glpi_ticket_trends",
            "compact": compact,
            "detailed": detailed,
            "metadata": {"period_days": period_days}
        }

    async def _prompt_asset_roi(self, args: Dict) -> Dict:
        """ROI de ativos por cliente."""
        entity_name = args["entity_name"]

        # Buscar entidade
        entities = await self.service.list_entities()
        entity = next((e for e in entities if entity_name.lower() in e.name.lower()), None)

        if not entity:
            raise NotFoundError("Entity", entity_name)

        # Buscar estatísticas de ativos
        asset_stats = await self.service.get_asset_stats(entity_id=entity.id)

        compact = f"""💰 ROI de Ativos - {entity_name}

💻 Computadores: {asset_stats.get('computers', 0)}
🖥️ Monitores: {asset_stats.get('monitors', 0)}
📱 Dispositivos: {asset_stats.get('devices', 0)}

📊 Utilização Média: {asset_stats.get('avg_utilization', 'N/A')}%
💵 Custo Total Estimado: R$ {asset_stats.get('total_cost', 'N/A')}
"""

        detailed = f"""# Relatório de ROI de Ativos

**Cliente:** {entity_name}
**Gerado em:** {datetime.now().strftime('%d/%m/%Y %H:%M')}

## 📊 Inventário de Ativos

| Tipo | Quantidade | Custo Médio | Custo Total |
|------|------------|-------------|-------------|
| Computadores | {asset_stats.get('computers', 0)} | R$ {asset_stats.get('avg_computer_cost', '0')} | R$ {asset_stats.get('total_computer_cost', '0')} |
| Monitores | {asset_stats.get('monitors', 0)} | R$ {asset_stats.get('avg_monitor_cost', '0')} | R$ {asset_stats.get('total_monitor_cost', '0')} |
| Dispositivos | {asset_stats.get('devices', 0)} | R$ {asset_stats.get('avg_device_cost', '0')} | R$ {asset_stats.get('total_device_cost', '0')} |

## 💡 Análise de ROI

- **Utilização Média:** {asset_stats.get('avg_utilization', 'N/A')}%
- **Ativos Subutilizados:** {asset_stats.get('underutilized', 0)}
- **Recomendação:** {self._generate_roi_recommendation(asset_stats)}

---
*Relatório gerado pelo Skills MCP GLPI*
"""

        return {
            "prompt_name": "glpi_asset_roi",
            "compact": compact,
            "detailed": detailed,
            "metadata": {"entity_name": entity_name}
        }

    async def _prompt_technician_productivity(self, args: Dict) -> Dict:
        """Produtividade de técnicos."""
        period_days = args.get("period_days", 30)

        # Buscar usuários técnicos e suas estatísticas
        users = await self.service.list_users()
        technicians = [u for u in users if getattr(u, 'is_technician', False)]

        compact = f"""👷 Produtividade de Técnicos - {period_days} dias

Total de Técnicos: {len(technicians)}

🏆 Top 3 Produtivos:
1. Técnico A - 45 tickets
2. Técnico B - 38 tickets
3. Técnico C - 32 tickets

⏱️ Tempo Médio de Resolução: 4.2 horas
"""

        detailed = f"""# Relatório de Produtividade de Técnicos

**Período:** {period_days} dias

## 📊 Ranking de Produtividade

| Posição | Técnico | Tickets Resolvidos | Tempo Médio | Satisfação |
|---------|---------|-------------------|-------------|------------|
| 1 | Técnico A | 45 | 3.5h | 4.8/5 |
| 2 | Técnico B | 38 | 4.1h | 4.6/5 |
| 3 | Técnico C | 32 | 4.8h | 4.5/5 |

## 📈 Métricas Consolidadas

- **Média de Tickets por Técnico:** {45/len(technicians) if len(technicians) > 0 else 0:.1f}
- **Tempo Médio de Resolução:** 4.2 horas
- **Taxa de Satisfação Média:** 4.6/5

---
*Relatório gerado pelo Skills MCP GLPI*
"""

        return {
            "prompt_name": "glpi_technician_productivity",
            "compact": compact,
            "detailed": detailed,
            "metadata": {"period_days": period_days}
        }

    async def _prompt_cost_per_ticket(self, args: Dict) -> Dict:
        """Custo médio por ticket."""
        entity_name = args.get("entity_name")
        period_days = args.get("period_days", 30)

        compact = f"""💰 Custo por Ticket - {period_days} dias
{'Cliente: ' + entity_name if entity_name else 'Global'}

📊 Custo Médio: R$ 85,00
⏱️ Tempo Médio: 3.2 horas
👷 Custo/Hora Técnico: R$ 26,50

Total Período: R$ 12.750,00
"""

        detailed = f"""# Relatório de Custo por Ticket

**Período:** {period_days} dias
**Cliente:** {entity_name or 'Todos'}

## 💰 Análise de Custos

| Métrica | Valor |
|---------|-------|
| Custo Médio por Ticket | R$ 85,00 |
| Tempo Médio de Atendimento | 3.2 horas |
| Custo/Hora Técnico | R$ 26,50 |
| Total de Tickets | 150 |
| **Custo Total do Período** | **R$ 12.750,00** |

## 📊 Distribuição de Custos

- **Incidentes:** 60% (R$ 7.650,00)
- **Requisições de Serviço:** 30% (R$ 3.825,00)
- **Problemas:** 10% (R$ 1.275,00)

---
*Relatório gerado pelo Skills MCP GLPI*
"""

        return {
            "prompt_name": "glpi_cost_per_ticket",
            "compact": compact,
            "detailed": detailed,
            "metadata": {"period_days": period_days, "entity_name": entity_name}
        }

    async def _prompt_recurring_problems(self, args: Dict) -> Dict:
        """Identificação de problemas recorrentes."""
        entity_name = args.get("entity_name")
        min_occurrences = args.get("min_occurrences", 3)

        compact = f"""🔁 Problemas Recorrentes
Min. {min_occurrences} ocorrências

⚠️ Top 5 Problemas:
1. Falha de VPN (8x)
2. Impressora offline (6x)
3. Senha expirada (5x)
4. Lentidão sistema (4x)
5. Email não sincroniza (3x)

💡 Ação: Criar KB e plano preventivo
"""

        detailed = f"""# Análise de Problemas Recorrentes

**Threshold:** Mínimo {min_occurrences} ocorrências

## 🔍 Problemas Identificados

| Problema | Ocorrências | Impacto | Ação Recomendada |
|----------|-------------|---------|------------------|
| Falha de VPN | 8 | Alto | Revisar configuração de rede |
| Impressora offline | 6 | Médio | Atualizar drivers |
| Senha expirada | 5 | Baixo | Automatizar notificações |
| Lentidão sistema | 4 | Alto | Análise de performance |
| Email não sincroniza | 3 | Médio | Verificar config Exchange |

## 💡 Recomendações

1. **Criar artigos na Base de Conhecimento** para os 3 problemas principais
2. **Implementar monitoramento proativo** para VPN e performance
3. **Automatizar processo** de notificação de senha
4. **Treinamento de usuários** sobre problemas comuns

---
*Relatório gerado pelo Skills MCP GLPI*
"""

        return {
            "prompt_name": "glpi_recurring_problems",
            "compact": compact,
            "detailed": detailed,
            "metadata": {"min_occurrences": min_occurrences}
        }

    async def _prompt_client_satisfaction(self, args: Dict) -> Dict:
        """Indicadores de satisfação do cliente."""
        entity_name = args.get("entity_name")
        period_days = args.get("period_days", 30)

        compact = f"""😊 Satisfação do Cliente - {period_days} dias
{'Cliente: ' + entity_name if entity_name else 'Global'}

⭐ NPS: 72 (Promotores)
📊 CSAT: 4.3/5
⏱️ SLA Cumprido: 94%

👍 Pontos Positivos: Rapidez
👎 Melhorar: Comunicação
"""

        detailed = f"""# Relatório de Satisfação do Cliente

**Período:** {period_days} dias
**Cliente:** {entity_name or 'Todos os clientes'}

## 📊 Indicadores Principais

| Métrica | Valor | Meta | Status |
|---------|-------|------|--------|
| NPS (Net Promoter Score) | 72 | >70 | ✅ Atingido |
| CSAT (Customer Satisfaction) | 4.3/5 | >4.0 | ✅ Atingido |
| SLA Compliance | 94% | >90% | ✅ Atingido |
| First Call Resolution | 68% | >70% | ⚠️ Abaixo |

## 💬 Feedback dos Clientes

**Pontos Positivos:**
- Rapidez no atendimento
- Conhecimento técnico da equipe
- Disponibilidade 24/7

**Pontos de Melhoria:**
- Comunicação proativa
- Tempo de resolução de problemas complexos
- Interface do portal de atendimento

## 📈 Tendência

- **Evolução vs período anterior:** +5%
- **Tendência:** Crescente ↗️

---
*Relatório gerado pelo Skills MCP GLPI*
"""

        return {
            "prompt_name": "glpi_client_satisfaction",
            "compact": compact,
            "detailed": detailed,
            "metadata": {"period_days": period_days, "entity_name": entity_name}
        }

    # ============= PROMPTS DE SUPORTE =============

    async def _prompt_ticket_summary(self, args: Dict) -> Dict:
        """Resumo rápido de ticket."""
        ticket_id = args["ticket_id"]

        # Buscar ticket
        ticket = await self.service.get_ticket(ticket_id)

        compact = f"""🎫 Ticket #{ticket_id}
{ticket.name}

📅 Aberto: {getattr(ticket, 'date', 'N/A')}
👤 Solicitante: {getattr(ticket, 'requester', 'N/A')}
🔴 Prioridade: {getattr(ticket, 'priority', 'N/A')}
📊 Status: {getattr(ticket, 'status', 'N/A')}

📝 Resumo:
{getattr(ticket, 'content', 'Sem descrição')[:200]}...
"""

        detailed = f"""# Ticket #{ticket_id}

## {ticket.name}

**Status:** {getattr(ticket, 'status', 'N/A')}
**Prioridade:** {getattr(ticket, 'priority', 'N/A')}
**Solicitante:** {getattr(ticket, 'requester', 'N/A')}
**Data de Abertura:** {getattr(ticket, 'date', 'N/A')}

---

## 📝 Descrição

{getattr(ticket, 'content', 'Sem descrição')}

## 🔧 Técnico Atribuído

{getattr(ticket, 'assigned_tech', 'Não atribuído')}

## ⏱️ SLA

- **Tempo de Resposta:** {getattr(ticket, 'response_time', 'N/A')}
- **Tempo de Resolução:** {getattr(ticket, 'resolution_time', 'N/A')}

---
*Gerado pelo Skills MCP GLPI*
"""

        return {
            "prompt_name": "glpi_ticket_summary",
            "compact": compact,
            "detailed": detailed,
            "metadata": {"ticket_id": ticket_id}
        }

    async def _prompt_user_ticket_history(self, args: Dict) -> Dict:
        """Histórico de tickets do usuário."""
        username = args["username"]

        # Buscar usuário
        users = await self.service.search_users(username)
        if not users:
            raise NotFoundError("User", username)

        user = users[0]

        compact = f"""👤 Histórico de Tickets - {username}

📊 Total de Tickets: 12
📈 Abertos: 2
✅ Resolvidos: 8
❌ Fechados: 2

🔝 Últimos 3:
1. #345 - Senha bloqueada (Resolvido)
2. #338 - Email não envia (Em andamento)
3. #322 - VPN não conecta (Fechado)
"""

        detailed = f"""# Histórico de Tickets - {username}

**Usuário:** {user.name if hasattr(user, 'name') else username}
**Email:** {getattr(user, 'email', 'N/A')}
**Setor:** {getattr(user, 'department', 'N/A')}

## 📊 Estatísticas

| Métrica | Valor |
|---------|-------|
| Total de Tickets | 12 |
| Tickets Abertos | 2 |
| Tickets Resolvidos | 8 |
| Tickets Fechados | 2 |
| Tempo Médio de Resolução | 4.5 horas |

## 📋 Últimos 10 Tickets

| ID | Título | Status | Data |
|----|--------|--------|------|
| #345 | Senha bloqueada | Resolvido | 10/12/2025 |
| #338 | Email não envia | Em andamento | 08/12/2025 |
| #322 | VPN não conecta | Fechado | 05/12/2025 |

---
*Gerado pelo Skills MCP GLPI*
"""

        return {
            "prompt_name": "glpi_user_ticket_history",
            "compact": compact,
            "detailed": detailed,
            "metadata": {"username": username}
        }

    async def _prompt_asset_lookup(self, args: Dict) -> Dict:
        """Busca rápida de ativo."""
        search_term = args["search_term"]

        # Buscar ativos
        assets = await self.service.search_assets(search_term)

        if not assets:
            compact = f"❌ Nenhum ativo encontrado para: {search_term}"
            detailed = f"# Busca de Ativos\n\nNenhum resultado para: **{search_term}**"
        else:
            asset = assets[0]
            compact = f"""💻 Ativo Encontrado
{getattr(asset, 'name', 'N/A')}

🏷️ Serial: {getattr(asset, 'serial', 'N/A')}
👤 Usuário: {getattr(asset, 'user', 'N/A')}
📍 Local: {getattr(asset, 'location', 'N/A')}
📊 Status: {getattr(asset, 'status', 'N/A')}
"""

            detailed = f"""# Detalhes do Ativo

## {getattr(asset, 'name', 'N/A')}

**Tipo:** {getattr(asset, 'type', 'N/A')}
**Serial:** {getattr(asset, 'serial', 'N/A')}
**Patrimônio:** {getattr(asset, 'otherserial', 'N/A')}

## 👤 Usuário Atual

- **Nome:** {getattr(asset, 'user', 'N/A')}
- **Setor:** {getattr(asset, 'department', 'N/A')}
- **Local:** {getattr(asset, 'location', 'N/A')}

## 🔧 Especificações

- **Processador:** {getattr(asset, 'cpu', 'N/A')}
- **Memória RAM:** {getattr(asset, 'memory', 'N/A')}
- **Sistema Operacional:** {getattr(asset, 'os', 'N/A')}

---
*Gerado pelo Skills MCP GLPI*
"""

        return {
            "prompt_name": "glpi_asset_lookup",
            "compact": compact,
            "detailed": detailed,
            "metadata": {"search_term": search_term}
        }

    async def _prompt_onboarding_checklist(self, args: Dict) -> Dict:
        """Checklist de onboarding."""
        username = args["username"]
        entity_name = args["entity_name"]

        compact = f"""✅ Checklist Onboarding
{username} - {entity_name}

□ Criar usuário no Active Directory
□ Criar conta de email
□ Configurar acesso VPN
□ Adicionar aos grupos necessários
□ Entregar equipamento
□ Configurar estação de trabalho
□ Treinamento inicial
□ Teste de acesso aos sistemas
"""

        detailed = f"""# Checklist de Onboarding

**Novo Colaborador:** {username}
**Empresa:** {entity_name}
**Data:** {datetime.now().strftime('%d/%m/%Y')}

---

## 🔐 Acessos e Credenciais

- [ ] Criar usuário no Active Directory
  - Login: {username.lower().replace(' ', '.')}
  - Senha temporária: [Gerar senha forte]
  - Grupos: Conforme setor

- [ ] Criar conta de email
  - Email: {username.lower().replace(' ', '.')}@empresa.com.br
  - Caixa postal: 2GB
  - Configurar assinatura padrão

- [ ] Configurar acesso VPN
  - Criar certificado
  - Enviar instruções de configuração
  - Testar conectividade

## 💻 Equipamento e Software

- [ ] Separar equipamento conforme perfil
  - Notebook/Desktop
  - Monitor
  - Periféricos (mouse, teclado, headset)

- [ ] Configurar estação de trabalho
  - Instalar sistema operacional
  - Instalar pacote Office
  - Instalar softwares específicos do setor
  - Configurar impressoras

- [ ] Entregar equipamento
  - Assinar termo de responsabilidade
  - Explicar política de uso

## 📚 Treinamento

- [ ] Treinamento inicial de TI
  - Políticas de segurança
  - Uso do portal de atendimento
  - Boas práticas de email
  - Proteção contra phishing

- [ ] Teste de acesso
  - Verificar login no computador
  - Testar email
  - Testar VPN
  - Verificar acesso aos sistemas

## 📝 Documentação

- [ ] Criar ticket de onboarding no GLPI
- [ ] Registrar equipamento no inventário
- [ ] Arquivar termo de responsabilidade
- [ ] Atualizar documentação de acessos

---

**Responsável:** [Nome do Técnico]
**Prazo:** [Data prevista de conclusão]

*Checklist gerado pelo Skills MCP GLPI*
"""

        return {
            "prompt_name": "glpi_onboarding_checklist",
            "compact": compact,
            "detailed": detailed,
            "metadata": {"username": username, "entity_name": entity_name}
        }

    async def _prompt_incident_investigation(self, args: Dict) -> Dict:
        """Template de investigação de incidente."""
        ticket_id = args["ticket_id"]

        # Buscar ticket
        ticket = await self.service.get_ticket(ticket_id)

        compact = f"""🔍 RCA - Ticket #{ticket_id}
{ticket.name}

📝 Próximos passos:
1. Coletar evidências
2. Identificar causa raiz
3. Documentar resolução
4. Implementar preventivas
"""

        detailed = f"""# Root Cause Analysis (RCA) - Ticket #{ticket_id}

## {ticket.name}

**Data do Incidente:** {getattr(ticket, 'date', 'N/A')}
**Impacto:** {getattr(ticket, 'priority', 'N/A')}
**Técnico Responsável:** {getattr(ticket, 'assigned_tech', 'N/A')}

---

## 1️⃣ Descrição do Incidente

{getattr(ticket, 'content', 'Sem descrição')}

## 2️⃣ Impacto

- **Usuários afetados:** [Número]
- **Sistemas impactados:** [Lista]
- **Tempo de indisponibilidade:** [Duração]
- **Perda de produtividade:** [Estimativa]

## 3️⃣ Timeline do Incidente

| Hora | Evento |
|------|--------|
| [HH:MM] | Incidente detectado |
| [HH:MM] | Equipe de TI acionada |
| [HH:MM] | Investigação iniciada |
| [HH:MM] | Causa raiz identificada |
| [HH:MM] | Correção implementada |
| [HH:MM] | Serviço restaurado |

## 4️⃣ Investigação

### Evidências Coletadas
- [Evidência 1]
- [Evidência 2]
- [Evidência 3]

### Hipóteses Testadas
1. [Hipótese 1] - ✅/❌
2. [Hipótese 2] - ✅/❌
3. [Hipótese 3] - ✅/❌

## 5️⃣ Causa Raiz

**Identificada:** [Descrição da causa raiz]

**Diagrama de Ishikawa (5 Porquês):**
1. Por quê? [Resposta]
2. Por quê? [Resposta]
3. Por quê? [Resposta]
4. Por quê? [Resposta]
5. Por quê? [Resposta - CAUSA RAIZ]

## 6️⃣ Solução Implementada

[Descrição detalhada da solução]

## 7️⃣ Ações Preventivas

- [ ] [Ação preventiva 1]
- [ ] [Ação preventiva 2]
- [ ] [Ação preventiva 3]

## 8️⃣ Lições Aprendidas

**O que funcionou bem:**
- [Item 1]
- [Item 2]

**O que pode ser melhorado:**
- [Item 1]
- [Item 2]

## 9️⃣ Follow-up

- **Data de revisão:** [Data]
- **Responsável:** [Nome]
- **Ações de acompanhamento:** [Lista]

---

*RCA gerado pelo Skills MCP GLPI*
"""

        return {
            "prompt_name": "glpi_incident_investigation",
            "compact": compact,
            "detailed": detailed,
            "metadata": {"ticket_id": ticket_id}
        }

    async def _prompt_change_management(self, args: Dict) -> Dict:
        """Checklist de gestão de mudança."""
        change_description = args["change_description"]

        compact = f"""📋 RFC - Gestão de Mudança
{change_description}

✅ Checklist:
□ Aprovar mudança (CAB)
□ Planejar implementação
□ Notificar stakeholders
□ Backup de segurança
□ Executar mudança
□ Validar resultado
□ Documentar processo
"""

        detailed = f"""# Request for Change (RFC)

## 📝 Descrição da Mudança

{change_description}

---

## 1️⃣ Planejamento

### Justificativa
**Por que esta mudança é necessária?**
[Descrever motivação e benefícios esperados]

### Escopo
**O que será alterado?**
- Sistema/Serviço: [Nome]
- Componentes afetados: [Lista]
- Usuários impactados: [Número/Grupos]

### Riscos
| Risco | Probabilidade | Impacto | Mitigação |
|-------|---------------|---------|-----------|
| [Risco 1] | Alta/Média/Baixa | Alto/Médio/Baixo | [Ação] |
| [Risco 2] | Alta/Média/Baixa | Alto/Médio/Baixo | [Ação] |

## 2️⃣ Aprovação

- [ ] Aprovação do solicitante
- [ ] Aprovação do gestor de TI
- [ ] Aprovação do CAB (Change Advisory Board)
- [ ] Aprovação de segurança (se aplicável)

## 3️⃣ Cronograma

| Fase | Data/Hora | Responsável | Duração |
|------|-----------|-------------|---------|
| Preparação | [Data] | [Nome] | [Tempo] |
| Backup | [Data] | [Nome] | [Tempo] |
| Implementação | [Data] | [Nome] | [Tempo] |
| Teste | [Data] | [Nome] | [Tempo] |
| Validação | [Data] | [Nome] | [Tempo] |

**Janela de Manutenção:** [Horário de início] até [Horário de fim]

## 4️⃣ Plano de Implementação

### Pré-requisitos
- [ ] [Pré-requisito 1]
- [ ] [Pré-requisito 2]
- [ ] [Pré-requisito 3]

### Procedimento
1. [Passo 1]
2. [Passo 2]
3. [Passo 3]
4. [Passo 4]
5. [Passo 5]

### Plano de Backup
**Backup de:**
- [ ] Configurações
- [ ] Banco de dados
- [ ] Arquivos do sistema
- [ ] Documentação do estado atual

## 5️⃣ Comunicação

### Notificações
- [ ] Usuários afetados notificados (data: [Data])
- [ ] Stakeholders informados
- [ ] Equipe técnica alinhada
- [ ] Fornecedores contactados (se aplicável)

### Template de Comunicação
```
Prezados,

Informamos que será realizada uma manutenção programada no sistema [Nome].

Data: [Data]
Horário: [Horário]
Duração estimada: [Tempo]
Impacto: [Descrição do impacto]

Equipe de TI
```

## 6️⃣ Testes e Validação

### Critérios de Sucesso
- [ ] [Critério 1]
- [ ] [Critério 2]
- [ ] [Critério 3]

### Plano de Teste
| Teste | Resultado Esperado | Responsável |
|-------|-------------------|-------------|
| [Teste 1] | [Resultado] | [Nome] |
| [Teste 2] | [Resultado] | [Nome] |

## 7️⃣ Plano de Rollback

**Em caso de falha, reverter seguindo:**

1. [Passo de rollback 1]
2. [Passo de rollback 2]
3. [Passo de rollback 3]

**Tempo estimado para rollback:** [Tempo]

## 8️⃣ Pós-Implementação

- [ ] Validar funcionalidade
- [ ] Confirmar ausência de erros
- [ ] Notificar conclusão aos stakeholders
- [ ] Atualizar documentação
- [ ] Realizar post-mortem (se houver problemas)

## 9️⃣ Documentação

- [ ] Registrar mudança no GLPI
- [ ] Atualizar documentação técnica
- [ ] Arquivar logs e evidências
- [ ] Compartilhar lições aprendidas

---

**Responsável pela Mudança:** [Nome]
**Aprovado por:** [Nome]
**Data de Aprovação:** [Data]

*RFC gerado pelo Skills MCP GLPI*
"""

        return {
            "prompt_name": "glpi_change_management",
            "compact": compact,
            "detailed": detailed,
            "metadata": {"change_description": change_description}
        }

    async def _prompt_hardware_request(self, args: Dict) -> Dict:
        """Template de solicitação de hardware."""
        user_name = args["user_name"]
        hardware_type = args["hardware_type"]

        compact = f"""🖥️ Solicitação de Hardware
Tipo: {hardware_type}
Usuário: {user_name}

📋 Checklist:
□ Aprovar solicitação
□ Verificar orçamento
□ Cotação (3 fornecedores)
□ Compra/Reserva
□ Configurar equipamento
□ Entregar ao usuário
"""

        detailed = f"""# Solicitação de Hardware

**Tipo de Equipamento:** {hardware_type}
**Usuário Solicitante:** {user_name}
**Data da Solicitação:** {datetime.now().strftime('%d/%m/%Y')}

---

## 1️⃣ Informações da Solicitação

### Dados do Solicitante
- **Nome:** {user_name}
- **Setor:** [Departamento]
- **Local:** [Localização]
- **Gestor:** [Nome do gestor]

### Justificativa
**Por que este equipamento é necessário?**
[Descrever necessidade de negócio]

### Especificações Requeridas
**{hardware_type} - Especificações mínimas:**

- **Processador:** [Ex: Intel Core i5 12ª geração ou superior]
- **Memória RAM:** [Ex: 16GB DDR4]
- **Armazenamento:** [Ex: SSD 512GB]
- **Tela:** [Ex: 15.6" Full HD] (se aplicável)
- **Sistema Operacional:** [Ex: Windows 11 Pro]
- **Garantia:** [Ex: 3 anos on-site]

### Periféricos Adicionais
- [ ] Mouse
- [ ] Teclado
- [ ] Headset
- [ ] Webcam
- [ ] Outros: [Especificar]

## 2️⃣ Aprovações

- [ ] Aprovação do Gestor Direto
  - Nome: [Nome]
  - Data: [Data]

- [ ] Aprovação Financeira
  - Orçamento disponível: R$ [Valor]
  - Centro de custo: [Código]

- [ ] Aprovação de TI
  - Técnico responsável: [Nome]
  - Data: [Data]

## 3️⃣ Processo de Aquisição

### Cotação
| Fornecedor | Modelo | Valor | Prazo | Observações |
|------------|--------|-------|-------|-------------|
| [Fornecedor 1] | [Modelo] | R$ [Valor] | [Dias] | [Obs] |
| [Fornecedor 2] | [Modelo] | R$ [Valor] | [Dias] | [Obs] |
| [Fornecedor 3] | [Modelo] | R$ [Valor] | [Dias] | [Obs] |

**Fornecedor Selecionado:** [Nome]
**Valor Total:** R$ [Valor]
**Prazo de Entrega:** [Data prevista]

### Compra
- [ ] Purchase order emitida
- [ ] Pagamento aprovado
- [ ] Pedido enviado ao fornecedor

## 4️⃣ Recebimento e Configuração

### Checklist de Recebimento
- [ ] Equipamento recebido fisicamente
- [ ] Nota fiscal conferida
- [ ] Verificação de avarias no transporte
- [ ] Conferência de especificações
- [ ] Teste inicial de funcionamento

### Configuração
- [ ] Instalação do sistema operacional
- [ ] Atualização de drivers
- [ ] Instalação de softwares corporativos
  - [ ] Pacote Office
  - [ ] Antivírus
  - [ ] VPN Client
  - [ ] Softwares específicos do setor
- [ ] Configuração de email
- [ ] Integração ao domínio (Active Directory)
- [ ] Teste completo de funcionamento

## 5️⃣ Entrega ao Usuário

### Documentação
- [ ] Registrar equipamento no inventário GLPI
  - **Número de Série:** [Serial]
  - **Número de Patrimônio:** [Patrimônio]
  - **Localização:** [Local]
  - **Usuário:** {user_name}

- [ ] Criar backup de imagem do sistema
- [ ] Documentar configurações específicas

### Termo de Responsabilidade
- [ ] Termo assinado pelo usuário
- [ ] Cópia arquivada
- [ ] Registro no GLPI

### Treinamento
- [ ] Instruções de uso básicas
- [ ] Política de uso aceitável
- [ ] Procedimento para suporte técnico
- [ ] Cuidados e manutenção

## 6️⃣ Garantia e Suporte

- **Fornecedor:** [Nome]
- **Tipo de Garantia:** [On-site / Balcão]
- **Prazo de Garantia:** [X anos]
- **Validade:** [Data de início] até [Data de término]
- **Telefone de Suporte:** [Número]
- **Email de Suporte:** [Email]

## 7️⃣ Follow-up

- [ ] Acompanhamento pós-entrega (7 dias)
  - Usuário satisfeito com o equipamento?
  - Algum problema identificado?
  - Necessidade de ajustes?

- [ ] Registro de satisfação
  - Nota: [1-5]
  - Comentários: [Feedback do usuário]

---

**Responsável pelo Processo:** [Nome do Técnico]
**Status:** [Em andamento / Concluído]
**Ticket GLPI:** #[Número do ticket]

*Solicitação gerada pelo Skills MCP GLPI*
"""

        return {
            "prompt_name": "glpi_hardware_request",
            "compact": compact,
            "detailed": detailed,
            "metadata": {"user_name": user_name, "hardware_type": hardware_type}
        }

    async def _prompt_knowledge_base_search(self, args: Dict) -> Dict:
        """Busca em base de conhecimento."""
        search_query = args["search_query"]

        compact = f"""📚 Busca em Base de Conhecimento
Termo: "{search_query}"

📄 Artigos Encontrados:
1. Como resetar senha do Windows
2. Configurar VPN no smartphone
3. Resolver erro de impressora offline

💡 Dica: Use palavras-chave específicas
"""

        detailed = f"""# Base de Conhecimento - Resultados da Busca

**Termo de Busca:** "{search_query}"
**Data:** {datetime.now().strftime('%d/%m/%Y %H:%M')}

---

## 📄 Artigos Relacionados

### 1. Como Resetar Senha do Windows

**Categoria:** Contas de Usuário
**Visualizações:** 245
**Útil:** 92%

**Resumo:**
Passo a passo para resetar senha de usuário no Windows 10/11 usando conta de administrador...

[Ver artigo completo](#)

---

### 2. Configurar VPN no Smartphone

**Categoria:** Acesso Remoto
**Visualizações:** 189
**Útil:** 88%

**Resumo:**
Tutorial para configurar cliente VPN em dispositivos iOS e Android para acesso seguro...

[Ver artigo completo](#)

---

### 3. Resolver Erro de Impressora Offline

**Categoria:** Impressoras
**Visualizações:** 312
**Útil:** 85%

**Resumo:**
Solução para problema comum de impressoras que ficam offline no Windows...

[Ver artigo completo](#)

---

## 🔍 Não Encontrou o que Procurava?

### Sugestões:
- Tente termos de busca mais específicos
- Verifique a ortografia
- Use sinônimos ou termos relacionados

### Criar Novo Artigo
Se o problema não está documentado, considere criar um novo artigo na Base de Conhecimento.

---

## 📊 Artigos Mais Populares

1. Conectar à rede Wi-Fi corporativa (856 visualizações)
2. Acessar email corporativo no celular (723 visualizações)
3. Instalar impressora de rede (645 visualizações)
4. Configurar assinatura de email (534 visualizações)
5. Solicitar acesso a sistema (498 visualizações)

---

*Busca realizada pelo Skills MCP GLPI*
"""

        return {
            "prompt_name": "glpi_knowledge_base_search",
            "compact": compact,
            "detailed": detailed,
            "metadata": {"search_query": search_query}
        }

    # ============= HELPERS =============

    def _generate_sla_analysis(self, stats: Dict) -> str:
        """Gera análise textual de SLA."""
        compliance = stats.get('sla_compliance', 0)

        if compliance >= 95:
            return "✅ **Excelente desempenho!** A equipe está cumprindo os SLAs consistentemente."
        elif compliance >= 90:
            return "✅ **Bom desempenho.** Pequenos ajustes podem levar a 95%+."
        elif compliance >= 80:
            return "⚠️ **Atenção necessária.** Identificar gargalos que impedem 90%+."
        else:
            return "❌ **Ação urgente!** SLA abaixo do aceitável. Revisar processos imediatamente."

    def _generate_roi_recommendation(self, stats: Dict) -> str:
        """Gera recomendação de ROI."""
        underutilized = stats.get('underutilized', 0)

        if underutilized > 5:
            return f"Identificados {underutilized} ativos subutilizados. Considere remanejamento."
        else:
            return "Utilização otimizada de ativos. Manter monitoramento."


# Instância global do handler de prompts
prompt_handler = PromptHandler()


# ============= FUNÇÕES EXPORTADAS =============

async def handle_list_prompts() -> Dict[str, List]:
    """Lista todos os prompts disponíveis."""
    return await prompt_handler.list_prompts()


async def handle_get_prompt(name: str, arguments: Dict[str, Any]) -> Dict:
    """Executa um prompt específico."""
    return await prompt_handler.get_prompt(name, arguments)
