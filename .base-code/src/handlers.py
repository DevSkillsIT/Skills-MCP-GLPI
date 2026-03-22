"""
MCP Handlers - Conforme SPEC.md seção 4.2
Integração das 48 tools MCP em handlers centralizados
Roteamento JSON-RPC 2.0 para execução das tools
"""

from typing import Dict, Any, List, Optional
import json
from datetime import datetime

from src.tools.tickets import ticket_tools
from src.tools.assets import asset_tools
from src.tools.admin import admin_tools
from src.tools.webhooks import webhook_tools
from src.tools.ai_tools import ai_tools
# SPEC-GLPI-ENHANCE-001/F04: Consolidated tools
from src.tools.consolidated_tickets import search_tickets, manage_tickets, manage_ai_analysis
from src.tools.consolidated_assets import search_assets, manage_assets
from src.tools.consolidated_admin import search_admin, manage_admin
from src.tools.consolidated_webhooks import search_webhooks, manage_webhooks
from src.tools.bridge_tools import bridge_tools
from src.models.exceptions import (
    GLPIError,
    NotFoundError,
    ValidationError,
    SimilarityError,
    MethodNotFoundError,
    InvalidRequestError,
    HTTP_TO_JSONRPC,
)
from src.utils.helpers import logger
from src.formatters.response_formatter import format_tool_response


class MCPHandler:
    """
    Handler principal para protocolo MCP (Model Context Protocol).
    Implementa JSON-RPC 2.0 conforme SPEC.md
    """

    def __init__(self):
        """Inicializa handler MCP."""
        self.tools = self._register_tools()

        logger.info(f"MCPHandler initialized with {len(self.tools)} tools")

    def _register_tools(self) -> Dict[str, Any]:
        """
        SPEC-GLPI-ENHANCE-001/F04: Registra 14 consolidated tools com annotations.
        Consolidação: 68 tools originais → 14 tools (9 core + 4 bridge + 1 knowledge).
        """
        tools = {}

        # SPEC-GLPI-ENHANCE-001/F03+F04: Consolidated tools with annotations
        # Pattern: search_* (read-only) + manage_* (CRUD with destructiveHint)
        CONSOLIDATED_TOOLS = [
            # === TICKETS (3 tools) ===
            {
                "name": "glpi_search_tickets",
                "description": self._get_tool_description("glpi_search_tickets"),
                "input_schema": self._get_tool_schema("glpi_search_tickets", "ticket"),
                "handler": search_tickets,
                "category": "tickets",
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
            },
            {
                "name": "glpi_manage_tickets",
                "description": "Chamado e operacoes CRUD no GLPI — detalhes, criar, atualizar, fechar, resolver, followups, historico, similares. Use action para especificar operacao (get/create/update/delete/assign/close/resolve/add_followup/get_followups/get_history/get_stats/find_similar). Retorna Markdown.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "Operacao a executar", "enum": ["get", "get_by_number", "create", "update", "delete", "assign", "close", "resolve", "add_followup", "get_followups", "get_history", "get_stats", "find_similar"]},
                        "ticket_id": {"type": "integer", "description": "ID do ticket (obrigatorio para maioria das actions)"},
                        "title": {"type": "string", "description": "Titulo (para create)"},
                        "description": {"type": "string", "description": "Descricao (para create)"},
                        "content": {"type": "string", "description": "Conteudo do followup (para add_followup)"},
                        "status": {"type": "string", "enum": ["new", "processing", "pending", "solved", "closed"]},
                        "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                        "entity_id": {"type": "integer"},
                        "entity_name": {"type": "string"},
                        "user_id": {"type": "integer", "description": "ID do tecnico (para assign)"},
                        "solution": {"type": "string", "description": "Texto da solucao (para resolve/close)"},
                        "ticket_number": {"type": "string", "description": "Numero do ticket (para get_by_number)"},
                        "query": {"type": "string", "description": "Texto para busca de similares (para find_similar)"},
                        "is_private": {"type": "boolean", "default": False},
                    },
                    "required": ["action"],
                },
                "handler": manage_tickets,
                "category": "tickets",
                "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
            },
            {
                "name": "glpi_manage_ai_analysis",
                "description": "Analise de IA em chamados no GLPI — dispara, consulta resultado ou publica resposta. Use action: trigger/get_result/publish. Retorna Markdown.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["trigger", "get_result", "publish"]},
                        "ticket_id": {"type": "integer"},
                    },
                    "required": ["action"],
                },
                "handler": manage_ai_analysis,
                "category": "tickets",
                "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
            },
            # === ASSETS (2 tools) ===
            {
                "name": "glpi_search_assets",
                "description": "Ativos de TI no GLPI — buscar computadores, monitores, software, dispositivos, reservas e estatisticas. Use scope para tipo de busca (all/computers/monitors/software/devices/reservations/reservable/stats). Retorna Markdown.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "scope": {"type": "string", "enum": ["all", "computers", "monitors", "software", "devices", "reservations", "reservable", "stats"], "default": "all"},
                        "asset_type": {"type": "string", "enum": ["Computer", "Monitor", "Printer", "NetworkEquipment", "Phone", "Peripheral"]},
                        "query": {"type": "string"},
                        "entity_id": {"type": "integer"},
                        "entity_name": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                        "offset": {"type": "integer", "minimum": 0, "default": 0},
                    },
                },
                "handler": search_assets,
                "category": "assets",
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
            },
            {
                "name": "glpi_manage_assets",
                "description": "Ativo e operacoes CRUD no GLPI — detalhes, criar, atualizar, excluir, reservas. Use action (get/get_details/create/update/delete/get_reservations/create_reservation/update_reservation). Retorna Markdown.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["get", "get_details", "create", "update", "delete", "get_reservations", "create_reservation", "update_reservation"]},
                        "asset_type": {"type": "string", "enum": ["Computer", "Monitor", "Printer", "NetworkEquipment", "Phone", "Peripheral"]},
                        "asset_id": {"type": "integer"},
                        "name": {"type": "string"},
                        "serial_number": {"type": "string"},
                    },
                    "required": ["action"],
                },
                "handler": manage_assets,
                "category": "assets",
                "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
            },
            # === ADMIN (2 tools) ===
            {
                "name": "glpi_search_admin",
                "description": "Usuarios, grupos, entidades e localizacoes no GLPI — buscar por resource (users/groups/entities/locations) com filtros. Retorna Markdown.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "resource": {"type": "string", "enum": ["users", "groups", "entities", "locations"], "default": "users"},
                        "query": {"type": "string"},
                        "entity_id": {"type": "integer"},
                        "entity_name": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                        "offset": {"type": "integer", "minimum": 0, "default": 0},
                    },
                },
                "handler": search_admin,
                "category": "admin",
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
            },
            {
                "name": "glpi_manage_admin",
                "description": "Operacoes CRUD em usuarios, grupos, entidades e localizacoes no GLPI. Use resource + action (get/create/update/delete). Retorna Markdown.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "resource": {"type": "string", "enum": ["users", "groups", "entities", "locations"]},
                        "action": {"type": "string", "enum": ["get", "create", "update", "delete"]},
                        "resource_id": {"type": "integer"},
                        "name": {"type": "string"},
                        "email": {"type": "string"},
                    },
                    "required": ["resource", "action"],
                },
                "handler": manage_admin,
                "category": "admin",
                "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
            },
            # === WEBHOOKS (2 tools) ===
            {
                "name": "glpi_search_webhooks",
                "description": "Webhooks no GLPI — listar, estatisticas ou entregas. Use scope (list/stats/deliveries). Retorna Markdown.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "scope": {"type": "string", "enum": ["list", "stats", "deliveries"], "default": "list"},
                        "webhook_id": {"type": "integer", "description": "ID do webhook (obrigatorio para deliveries)"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                        "offset": {"type": "integer", "minimum": 0, "default": 0},
                    },
                },
                "handler": search_webhooks,
                "category": "webhooks",
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
            },
            {
                "name": "glpi_manage_webhooks",
                "description": "Operacoes em webhooks no GLPI — CRUD e controle. Use action (get/create/update/delete/test/trigger/enable/disable/retry). Retorna Markdown.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["get", "create", "update", "delete", "test", "trigger", "enable", "disable", "retry"]},
                        "webhook_id": {"type": "integer"},
                        "name": {"type": "string"},
                        "url": {"type": "string"},
                        "event_type": {"type": "string"},
                    },
                    "required": ["action"],
                },
                "handler": manage_webhooks,
                "category": "webhooks",
                "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True},
            },
            # === BRIDGE (4 tools) ===
            {
                "name": "glpi_list_resources",
                "description": "Resources MCP do GLPI — lista URIs disponiveis (glpi://entities, glpi://ticket-status, etc.). Retorna Markdown.",
                "input_schema": {"type": "object"},
                "handler": bridge_tools.list_resources_tool,
                "category": "bridge",
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
            },
            {
                "name": "glpi_read_resource",
                "description": "Resource MCP do GLPI — le conteudo de uma URI especifica. Use uri (glpi://entities, glpi://ticket-status, glpi://ticket-categories, glpi://priorities). Retorna Markdown.",
                "input_schema": {"type": "object", "properties": {"uri": {"type": "string", "description": "URI do resource (ex: glpi://entities)"}}, "required": ["uri"]},
                "handler": bridge_tools.read_resource_tool,
                "category": "bridge",
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
            },
            {
                "name": "glpi_list_prompts",
                "description": "Prompts profissionais no GLPI — catalogo de 15 modelos prontos para gestores e analistas. Retorna Markdown.",
                "input_schema": {"type": "object"},
                "handler": bridge_tools.list_prompts_tool,
                "category": "bridge",
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
            },
            {
                "name": "glpi_get_prompt",
                "description": "Prompt e execucao de modelo no GLPI — processa relatorio ou analise especifica com argumentos. Retorna Markdown.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Nome do prompt"},
                        "arguments": {"type": "object", "description": "Argumentos do prompt"},
                    },
                    "required": ["name"],
                },
                "handler": bridge_tools.get_prompt_tool,
                "category": "bridge",
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
            },
            # === KNOWLEDGE (1 tool) ===
            {
                "name": "glpi_search_knowledge",
                "description": "Base de conhecimento GLPI — busca em solucoes, artigos e resolucoes de chamados. Retorna Markdown.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Texto para busca (minimo 2 caracteres)"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                    },
                    "required": ["query"],
                },
                "handler": bridge_tools.search_knowledge,
                "category": "knowledge",
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
            },
        ]

        for tool_def in CONSOLIDATED_TOOLS:
            tools[tool_def["name"]] = tool_def

        logger.info(
            f"Registered {len(tools)} consolidated MCP tools (SPEC-GLPI-ENHANCE-001/F04)"
        )
        return tools

    def _get_tool_description(self, tool_name: str) -> str:
        """
        Obtém descrição da tool conforme SPEC.md seção 4.2.

        Args:
            tool_name: Nome da tool

        Returns:
            Descrição da tool
        """
        descriptions = {
            # ============= TICKETS (18 tools) =============
            "glpi_list_tickets": "Chamados, tickets e incidentes no GLPI — listagem com filtros por status, entidade e paginação. Use quando precisar consultar solicitações abertas, pendentes ou fechadas de um cliente no GLPI. Retorna lista com id, título, status, prioridade e data de abertura. Consulta somente leitura.",
            "glpi_get_ticket": "Chamado e seus detalhes completos no GLPI — consulta por ID com todos os campos do ticket. Use quando já possuir o ID do chamado e precisar de informações detalhadas no GLPI. Retorna id, título, descrição, status, prioridade, urgência, datas, solicitante, entidade e SLA.",
            "glpi_get_ticket_by_id": "Chamado por ID numérico no GLPI — obtém detalhes completos de um ticket, incidente ou requisição específica. Use quando tiver o ID do chamado e precisar de todos os campos no GLPI. Retorna os mesmos dados de glpi_get_ticket. Consulta somente leitura.",
            "glpi_get_ticket_by_number": "Chamado por número (string) no GLPI — busca ticket pelo campo número, que pode diferir do ID interno. Use quando o usuário mencionar 'chamado #X' ou 'ticket número X' no GLPI. Retorna detalhes completos do incidente ou requisição. Em alguns ambientes GLPI, número e ID são distintos.",
            "glpi_create_ticket": "Chamado, incidente ou requisição no GLPI — criação de novo ticket com título, descrição e prioridade. Use quando precisar abrir uma nova solicitação ou demanda de suporte no GLPI. Retorna ID do chamado criado. Aceita entity_name para vincular ao cliente correto.",
            "glpi_update_ticket": "Chamado e suas propriedades no GLPI — atualização de status, prioridade ou técnico atribuído em ticket existente. Use quando precisar modificar dados de um incidente ou requisição no GLPI. Retorna o chamado atualizado. Não altera histórico de acompanhamentos.",
            "glpi_delete_ticket": "Chamado e remoção permanente no GLPI — exclusão definitiva de um ticket, incidente ou requisição do sistema. Use apenas quando for necessário remover completamente um chamado do GLPI. OPERAÇÃO DESTRUTIVA e irreversível. Requer parâmetro ticket_id obrigatório.",
            "glpi_assign_ticket": "Chamado e atribuição de técnico no GLPI — vincula um ticket a um usuário responsável pelo atendimento. Use quando precisar distribuir ou reatribuir incidentes e requisições a técnicos no GLPI. Requer ticket_id e user_id do técnico. Não altera status do chamado.",
            "glpi_close_ticket": "Chamado e encerramento com resolução no GLPI — fecha um ticket registrando a solução aplicada. Use quando o incidente ou requisição estiver resolvido e precisar registrar a resolução final no GLPI. Muda status para fechado (5). Diferente de glpi_resolve_ticket que marca solucionado (4).",
            "glpi_find_similar_tickets": "Chamados similares no GLPI — busca tickets com problemas parecidos usando algoritmo de similaridade textual. Use quando precisar encontrar incidentes ou requisições semelhantes para reutilizar soluções no GLPI. Aceita threshold (0-1) para ajustar sensibilidade. Retorna lista ranqueada por score.",
            "glpi_search_similar_tickets": "Chamados similares no GLPI — versão simplificada da busca por similaridade textual de tickets e incidentes. Use quando precisar localizar solicitações parecidas sem configurar threshold no GLPI. Diferente de glpi_find_similar_tickets que aceita threshold customizado. Retorna lista de tickets semelhantes.",
            "glpi_search_tickets": "Chamados e busca textual no GLPI — pesquisa tickets por palavras-chave em título e conteúdo. Use quando precisar localizar incidentes, requisições ou solicitações por termos específicos no GLPI. Aceita filtro por entidade. Retorna lista paginada. Mínimo 2 caracteres na query.",
            "glpi_get_ticket_stats": "Estatísticas de chamados no GLPI — métricas agregadas por status, prioridade e entidade. Use quando precisar de relatórios, dashboards ou análise quantitativa de tickets e incidentes no GLPI. Retorna totais por status (abertos, pendentes, resolvidos, fechados) e por prioridade. Consulta somente leitura.",
            "glpi_get_ticket_history": "Histórico de alterações de chamado no GLPI — rastreamento completo de mudanças em um ticket. Use quando precisar auditar quem alterou o quê e quando em um incidente ou requisição no GLPI. Retorna mudanças de status, atribuições, atualizações de campos com autor e timestamp.",
            "glpi_add_ticket_followup": "Acompanhamento de chamado no GLPI — adiciona comentário ou interação a um ticket existente. Use quando precisar registrar comunicações, atualizações ou notas em incidentes e requisições no GLPI. Aceita is_private para notas visíveis apenas a técnicos. Requer ticket_id e content.",
            "glpi_post_private_note": "Nota privada em chamado no GLPI — adiciona anotação interna visível apenas para técnicos e equipe de suporte. Use quando precisar registrar observações internas que o solicitante não deve ver em tickets do GLPI. Diferente de glpi_add_ticket_followup com is_private. Requer ticket_id e content.",
            "glpi_get_ticket_followups": "Acompanhamentos de chamado no GLPI — lista todos os comentários e interações de um ticket específico. Use quando precisar consultar o histórico de comunicações de um incidente ou requisição no GLPI. Retorna lista com id, conteúdo, data, autor e flag de privacidade. Consulta somente leitura.",
            "glpi_resolve_ticket": "Resolução de chamado no GLPI — registra a solução técnica de um ticket, marcando como solucionado (status 4). Use quando o incidente tiver solução definida mas ainda aguardar validação do solicitante no GLPI. Diferente de glpi_close_ticket que fecha diretamente (status 5). Requer ticket_id e solution.",
            # ============= ASSETS (20 tools) =============
            "glpi_list_assets": "Ativos de TI, equipamentos e patrimônio no GLPI — listagem com filtros por tipo, entidade e paginação. Use quando precisar consultar o inventário de computadores, monitores, impressoras ou periféricos no GLPI. Retorna lista com id, nome, serial, status e localização. Consulta somente leitura.",
            "glpi_get_asset": "Ativo e detalhes completos no GLPI — consulta equipamento específico por tipo e ID. Use quando já possuir o ID e tipo do patrimônio e precisar de informações detalhadas no GLPI. Retorna id, nome, serial, status, localização, fabricante, modelo e usuário responsável pelo equipamento.",
            "glpi_create_asset": "Ativo, equipamento ou patrimônio no GLPI — cadastro de novo item no inventário de TI. Use quando precisar registrar um computador, monitor, impressora ou periférico no GLPI. Requer asset_type e nome obrigatórios. Aceita serial, entidade e localização. Retorna ID do ativo criado.",
            "glpi_update_asset": "Ativo e atualização de propriedades no GLPI — modifica dados de equipamento ou patrimônio existente no inventário. Use quando precisar alterar nome, serial, status ou localização de um item de TI no GLPI. Requer asset_type e asset_id. Retorna o ativo atualizado com os campos modificados.",
            "glpi_delete_asset": "Ativo e remoção permanente no GLPI — exclusão definitiva de equipamento ou patrimônio do inventário de TI. Use apenas quando for necessário remover completamente um item do GLPI. OPERAÇÃO DESTRUTIVA e irreversível. Requer asset_type e asset_id obrigatórios.",
            "glpi_search_assets": "Ativos e busca inteligente no GLPI — Smart Search v2.0 com pesquisa em nome, serial, contact e usuário vinculado. Use quando precisar localizar equipamentos ou patrimônio por texto livre no GLPI. FALLBACK: se o usuário foi deletado (sync LDAP), busca automaticamente em deletados.",
            "glpi_get_asset_reservations": "Reservas de ativo no GLPI — consulta agendamentos de um equipamento específico por tipo e ID. Use quando precisar verificar disponibilidade ou ocupação de um patrimônio reservável no GLPI. Retorna lista de reservas com datas, usuário e comentário. Consulta somente leitura.",
            "glpi_create_reservation": "Reserva de ativo no GLPI — agendamento de uso de equipamento com data início e fim em formato ISO 8601. Use quando precisar reservar computador, monitor ou periférico para um período específico no GLPI. Valida conflitos automaticamente. Requer asset_type, asset_id, start_date e end_date.",
            "glpi_list_reservations": "Reservas de ativos no GLPI — listagem de todos os agendamentos de equipamentos e patrimônio com filtros. Use quando precisar consultar reservas ativas de dispositivos no GLPI. Retorna id, ativo, usuário, período e status de cada reserva. Aceita filtro por entidade. Consulta somente leitura.",
            "glpi_list_reservable_items": "Itens reserváveis no GLPI — lista ativos habilitados para reserva no sistema de patrimônio. Use quando precisar saber quais equipamentos e dispositivos estão configurados como reserváveis no GLPI. Nem todo ativo é reservável — precisa ser habilitado pelo administrador. Aceita filtro por entidade.",
            "glpi_update_reservation": "Reserva e atualização de agendamento no GLPI — modifica datas ou comentário de uma reserva de equipamento existente. Use quando precisar alterar período ou detalhes de uso de um ativo no GLPI. Requer reservation_id obrigatório. Aceita start_date e end_date em formato ISO 8601.",
            "glpi_get_asset_stats": "Estatísticas de ativos no GLPI — métricas agregadas por tipo de equipamento, status, localização e fabricante. Use quando precisar de relatórios quantitativos do inventário de patrimônio e dispositivos no GLPI. Aceita filtro por entidade. Retorna totais categorizados. Consulta somente leitura.",
            "glpi_list_computers": "Computadores e dados enriquecidos no GLPI — listagem com memória, CPU, AnyDesk, contact e informações do usuário em uma única chamada. Use quando precisar consultar máquinas com detalhes de hardware no GLPI. NÃO use glpi_get_computer_details para listar — esta tool já traz dados completos.",
            "glpi_get_computer_details": "Computador e detalhes granulares no GLPI — componentes individuais de memória, CPU, discos, rede, sistema operacional e software instalado. Use quando precisar de informações detalhadas de UMA máquina específica no GLPI. Para listar múltiplos computadores, use glpi_list_computers.",
            "glpi_list_monitors": "Monitores, telas e displays no GLPI — listagem do inventário de vídeo com filtros por entidade. Use quando precisar consultar monitores cadastrados no patrimônio de TI do GLPI. Retorna id, nome, serial, fabricante, modelo e tamanho em polegadas. Consulta somente leitura.",
            "glpi_get_monitor": "Monitor e detalhes completos no GLPI — consulta display específico por ID com todos os campos do patrimônio. Use quando precisar de informações detalhadas de um monitor ou tela do inventário no GLPI. Retorna id, nome, serial, fabricante, modelo, tamanho, comentário, entidade e localização.",
            "glpi_list_software": "Softwares e licenças no GLPI — listagem de programas cadastrados no inventário com contagem de instalações. Use quando precisar consultar aplicativos, programas ou sistemas do parque de TI no GLPI. Retorna id, nome, publisher, validade da licença e total de instalações. Consulta somente leitura.",
            "glpi_get_software": "Software e detalhes completos no GLPI — consulta programa específico por ID com versões e instalações ativas. Use quando precisar de informações detalhadas de um aplicativo ou sistema cadastrado no inventário do GLPI. Retorna id, nome, publisher, versões, instalações e licenças vinculadas.",
            "glpi_list_devices": "Dispositivos de rede, telefones e periféricos no GLPI — listagem por tipo de equipamento do inventário. Use quando precisar consultar switches, roteadores, telefones ou periféricos cadastrados no GLPI. Aceita device_type para filtrar. Retorna lista com id, nome, serial e entidade.",
            "glpi_get_device": "Dispositivo e detalhes específicos no GLPI — consulta equipamento de rede, telefone ou periférico por tipo e ID. Use quando precisar de informações completas de um switch, roteador ou periférico no inventário do GLPI. Requer device_type e device_id obrigatórios. Retorna dados específicos.",
            # ============= ADMIN/USERS (13 tools) =============
            "glpi_list_users": "Usuários, colaboradores e técnicos no GLPI — listagem com filtros por entidade, grupo, perfil e status. Use quando precisar consultar pessoas cadastradas, membros de equipe ou funcionários no GLPI. Retorna id, login, nome, sobrenome, email e status ativo. Consulta somente leitura.",
            "glpi_search_users": "Usuários e busca completa no GLPI — pesquisa por nome, sobrenome, email ou username com todos os 20+ campos. Use quando precisar localizar colaboradores, técnicos ou funcionários por qualquer critério no GLPI. FALLBACK: se nenhum ativo encontrado, busca automaticamente em deletados (sync AD/LDAP).",
            "glpi_get_user": "Usuário e detalhes completos no GLPI — consulta colaborador específico por ID com todos os campos disponíveis. Use quando já possuir o ID do técnico ou funcionário e precisar de informações detalhadas no GLPI. Retorna dados pessoais, contatos, localização, cargo, perfil e status.",
            "glpi_create_user": "Usuário, colaborador ou técnico no GLPI — cadastro de nova pessoa no sistema com dados completos. Use quando precisar criar um novo membro, funcionário ou conta de acesso no GLPI. Requer name (login) obrigatório. Aceita dados pessoais, contato, perfil, grupo e tipo de autenticação (Local, LDAP, Mail).",
            "glpi_update_user": "Usuário e atualização de dados no GLPI — modifica informações de colaborador ou técnico existente no cadastro. Use quando precisar alterar nome, email, telefone, cargo ou status de uma pessoa no GLPI. Requer user_id obrigatório. Retorna usuário atualizado com campos modificados.",
            "glpi_delete_user": "Usuário e remoção no GLPI — exclusão ou desativação de colaborador, técnico ou conta do sistema. Use quando precisar remover acesso de um funcionário ou membro no GLPI. Pode ser desativação lógica ou exclusão física conforme configuração do ambiente. OPERAÇÃO DESTRUTIVA. Requer user_id.",
            "glpi_list_groups": "Grupos, equipes e times no GLPI — listagem de agrupamentos de usuários com filtros por entidade. Use quando precisar consultar departamentos, setores ou equipes técnicas cadastradas no GLPI. Retorna id, nome, descrição, entidade e quantidade de membros. Consulta somente leitura.",
            "glpi_get_group": "Grupo e detalhes completos no GLPI — consulta equipe específica por ID com lista de membros e configurações. Use quando precisar de informações detalhadas de um departamento, setor ou time técnico no GLPI. Retorna id, nome, descrição, entidade e lista de usuários membros.",
            "glpi_create_group": "Grupo, equipe ou departamento no GLPI — criação de novo agrupamento de usuários para organização do suporte. Use quando precisar criar um time, setor ou departamento para organizar colaboradores e técnicos no GLPI. Requer nome obrigatório. Aceita descrição e entidade.",
            "glpi_list_entities": "Entidades, clientes e organizações no GLPI — listagem de empresas cadastradas com hierarquia e filtros. Use quando precisar consultar clientes, filiais ou unidades de negócio no GLPI. Retorna id, nome, caminho completo, entidade pai, endereço e telefone. Aceita filtro por parent_id.",
            "glpi_get_entity": "Entidade e detalhes completos no GLPI — consulta cliente ou organização específica por ID com configurações. Use quando precisar de informações detalhadas de uma empresa, filial ou unidade cadastrada no GLPI. Retorna id, nome, caminho, entidade pai, endereço, contatos e configurações de SLA.",
            "glpi_list_locations": "Localizações, escritórios e filiais no GLPI — listagem de endereços e sites cadastrados no patrimônio. Use quando precisar consultar salas, prédios ou filiais vinculadas ao inventário de TI no GLPI. Retorna id, nome, caminho completo, entidade, endereço, prédio e sala. Consulta somente leitura.",
            "glpi_get_location": "Localização e detalhes completos no GLPI — consulta endereço ou site específico por ID com coordenadas. Use quando precisar de informações detalhadas de um escritório, prédio ou filial cadastrada no GLPI. Retorna id, nome, caminho, entidade, endereço, latitude, longitude, prédio e sala.",
            # ============= WEBHOOKS (12 tools) =============
            "glpi_list_webhooks": "Webhooks e integrações no GLPI — listagem de endpoints configurados para notificações automáticas de eventos. Use quando precisar consultar integrações ativas ou inativas de callbacks HTTP no GLPI. Retorna id, nome, URL de destino, tipo de evento e status. Aceita filtro por is_active.",
            "glpi_get_webhook": "Webhook e detalhes completos no GLPI — consulta integração específica por ID com estatísticas de entrega. Use quando precisar de informações detalhadas de um endpoint de callback configurado no GLPI. Retorna id, nome, URL, tipo de evento, secret, headers e delivery_stats.",
            "glpi_create_webhook": "Webhook e nova integração no GLPI — cadastro de endpoint para receber notificações automáticas de eventos. Use quando precisar configurar um callback HTTP para tickets, ativos ou outros eventos no GLPI. Requer nome, URL de destino e tipo de evento. Aceita secret para assinatura HMAC.",
            "glpi_update_webhook": "Webhook e atualização de integração no GLPI — modifica configuração de endpoint de notificação existente. Use quando precisar alterar URL, nome ou status de ativação de um callback HTTP no GLPI. Requer webhook_id obrigatório. Aceita name, url e is_active para ativação ou desativação.",
            "glpi_delete_webhook": "Webhook e remoção permanente no GLPI — exclusão definitiva de integração de notificação automática do sistema. Use apenas quando for necessário remover completamente um endpoint de callback do GLPI. OPERAÇÃO DESTRUTIVA e irreversível. Requer webhook_id obrigatório.",
            "glpi_test_webhook": "Webhook e teste de conectividade no GLPI — envia payload de verificação para confirmar funcionamento do endpoint. Use quando precisar validar se uma integração de callback está respondendo corretamente no GLPI. Requer webhook_id. Retorna status HTTP da entrega de teste.",
            "glpi_get_webhook_deliveries": "Entregas de webhook no GLPI — histórico de tentativas de notificação de um endpoint específico configurado. Use quando precisar diagnosticar falhas ou verificar entregas de integrações no GLPI. Retorna tentativas, status HTTP, response_code e detalhes de erro. Consulta somente leitura.",
            "glpi_trigger_webhook": "Webhook e disparo manual no GLPI — envia evento customizado para endpoints de integração configurados. Use quando precisar testar integrações ou disparar notificações manualmente no GLPI. Requer event_type obrigatório. Aceita payload com dados customizados para o evento disparado.",
            "glpi_get_webhook_stats": "Estatísticas de webhooks no GLPI — métricas agregadas de integrações e entregas de notificações automáticas. Use quando precisar de relatórios sobre callbacks HTTP configurados no GLPI. Retorna total configurados, ativos, entregas com sucesso e falha, e latência média. Consulta somente leitura.",
            "glpi_enable_webhook": "Webhook e ativação no GLPI — reativa um endpoint de notificação automática previamente desativado. Use quando precisar religar uma integração de callback que estava pausada no GLPI. Requer webhook_id obrigatório. O webhook volta a receber eventos conforme configuração original.",
            "glpi_disable_webhook": "Webhook e desativação temporária no GLPI — pausa um endpoint de notificação automática sem excluí-lo do sistema. Use quando precisar suspender temporariamente uma integração de callback no GLPI. Requer webhook_id. Para remoção definitiva, use glpi_delete_webhook.",
            "glpi_retry_failed_deliveries": "Entregas falhadas de webhook no GLPI — re-tentativa de notificações que não foram entregues ao endpoint de destino. Use quando o servidor estava indisponível e as entregas falharam no GLPI. Requer webhook_id obrigatório. Reprocessa todas as entregas com status de falha.",
            # ============= AI TOOLS (3 tools) =============
            "glpi_trigger_ai_analysis": "Análise de IA em chamados no GLPI — dispara processamento inteligente de tickets pendentes com sugestões automáticas. Use quando precisar de categorização, priorização e sugestões de solução baseadas no histórico do GLPI. Analisa conteúdo dos incidentes e requisições pendentes.",
            "glpi_get_ai_analysis_result": "Resultado de análise de IA no GLPI — obtém sugestões geradas pelo último processamento inteligente de chamados. Use quando precisar consultar recomendações de categorização, priorização e soluções de tickets no GLPI. Retorna tickets analisados, categorias sugeridas e soluções similares.",
            "glpi_publish_ai_response": "Resposta de IA em chamado no GLPI — publica sugestão gerada por inteligência artificial como acompanhamento em um ticket. Use quando precisar adicionar resposta automatizada com marcação de origem IA em incidentes do GLPI. A resposta é adicionada como followup identificado.",
            # ============= PROMPTS (2 tools) =============
            "glpi_list_prompts": "Prompts profissionais no GLPI — catálogo de 15 modelos prontos para gestores e analistas de suporte técnico. Use quando precisar descobrir quais relatórios e análises estão disponíveis no sistema GLPI. Retorna nome, descrição, categoria (gestão/suporte), público-alvo e argumentos de cada prompt.",
            "glpi_get_prompt": "Prompt e execução de modelo no GLPI — processa um relatório ou análise específica com argumentos customizados. Use quando precisar gerar relatório de SLA, tendências, produtividade ou investigação no GLPI. Retorna resultado em formato compact (10 linhas) e detailed (Markdown completo).",
        }

        return descriptions.get(tool_name, f"Tool MCP: {tool_name}")

    def _get_tool_schema(self, tool_name: str, category: str) -> Dict[str, Any]:
        """
        Obtém schema JSON específico para cada tool.
        Schemas precisos evitam que a IA envie parâmetros errados.

        Args:
            tool_name: Nome da tool
            category: Categoria da tool

        Returns:
            Schema JSON específico da tool
        """
        # ============= SCHEMAS ESPECÍFICOS POR TOOL =============
        specific_schemas = {
            # ----- TICKETS -----
            "glpi_list_tickets": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Status do chamado no GLPI. Valores: new (novo), processing (em atendimento), pending (pendente), solved (solucionado), closed (fechado)",
                        "enum": ["new", "processing", "pending", "solved", "closed"],
                    },
                    "entity_id": {
                        "type": "integer",
                        "description": "ID da entidade/cliente",
                    },
                    "entity_name": {
                        "type": "string",
                        "description": "Nome da entidade/cliente (ex: 'GSM', 'Skills IT')",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 10,
                    },
                    "offset": {"type": "integer", "minimum": 0, "default": 0},
                },
            },
            "glpi_get_ticket": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"}
                },
                "required": ["ticket_id"],
            },
            "glpi_get_ticket_by_id": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"}
                },
                "required": ["ticket_id"],
            },
            "glpi_get_ticket_by_number": {
                "type": "object",
                "properties": {
                    "ticket_number": {
                        "type": "string",
                        "description": "Número do ticket",
                    }
                },
                "required": ["ticket_number"],
            },
            "glpi_create_ticket": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título do ticket"},
                    "description": {
                        "type": "string",
                        "description": "Descrição detalhada do problema",
                    },
                    "priority": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                        "default": 3,
                    },
                    "entity_id": {
                        "type": "integer",
                        "description": "ID da entidade/cliente",
                    },
                    "entity_name": {
                        "type": "string",
                        "description": "Nome da entidade/cliente",
                    },
                    "category_id": {
                        "type": "integer",
                        "description": "ID da categoria",
                    },
                    "requester_id": {
                        "type": "integer",
                        "description": "ID do solicitante",
                    },
                },
                "required": ["title", "description"],
            },
            "glpi_update_ticket": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"},
                    "status": {
                        "type": "string",
                        "description": "Novo status do chamado no GLPI. Valores: new, processing, pending, solved, closed",
                        "enum": ["new", "processing", "pending", "solved", "closed"],
                    },
                    "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                    "assignee_id": {
                        "type": "integer",
                        "description": "ID do técnico atribuído",
                    },
                },
                "required": ["ticket_id"],
            },
            "glpi_delete_ticket": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"}
                },
                "required": ["ticket_id"],
            },
            "glpi_assign_ticket": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"},
                    "user_id": {
                        "type": "integer",
                        "description": "ID do usuário/técnico para atribuir",
                    },
                },
                "required": ["ticket_id", "user_id"],
            },
            "glpi_close_ticket": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"},
                    "resolution": {
                        "type": "string",
                        "description": "Texto da solução/resolução",
                    },
                },
                "required": ["ticket_id", "resolution"],
            },
            "glpi_search_tickets": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Texto para buscar nos tickets (mínimo 2 caracteres)",
                    },
                    "entity_id": {
                        "type": "integer",
                        "description": "ID da entidade/cliente",
                    },
                    "entity_name": {
                        "type": "string",
                        "description": "Nome da entidade/cliente",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 10,
                    },
                    "offset": {"type": "integer", "minimum": 0, "default": 0},
                },
                "required": ["query"],
            },
            "glpi_find_similar_tickets": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Título para buscar similares",
                    },
                    "description": {
                        "type": "string",
                        "description": "Descrição para buscar similares",
                    },
                    "threshold": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "default": 0.6,
                    },
                },
                "required": ["title"],
            },
            "glpi_search_similar_tickets": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Título para buscar similares",
                    },
                    "description": {
                        "type": "string",
                        "description": "Descrição para buscar similares",
                    },
                },
                "required": ["title"],
            },
            "glpi_get_ticket_stats": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "integer",
                        "description": "ID da entidade/cliente",
                    },
                    "entity_name": {
                        "type": "string",
                        "description": "Nome da entidade/cliente",
                    },
                },
            },
            "glpi_get_ticket_history": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"}
                },
                "required": ["ticket_id"],
            },
            "glpi_add_ticket_followup": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"},
                    "content": {
                        "type": "string",
                        "description": "Conteúdo do acompanhamento",
                    },
                    "is_private": {"type": "boolean", "default": False},
                },
                "required": ["ticket_id", "content"],
            },
            "glpi_post_private_note": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"},
                    "content": {
                        "type": "string",
                        "description": "Conteúdo da nota privada",
                    },
                },
                "required": ["ticket_id", "content"],
            },
            "glpi_get_ticket_followups": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"}
                },
                "required": ["ticket_id"],
            },
            "glpi_resolve_ticket": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"},
                    "solution": {"type": "string", "description": "Texto da solução"},
                },
                "required": ["ticket_id", "solution"],
            },
            # ----- ASSETS -----
            "glpi_list_assets": {
                "type": "object",
                "properties": {
                    "asset_type": {
                        "type": "string",
                        "description": "Tipo de ativo no GLPI. Valores: Computer, Monitor, Printer, NetworkEquipment, Phone, Peripheral",
                        "enum": [
                            "Computer",
                            "Monitor",
                            "Printer",
                            "NetworkEquipment",
                            "Phone",
                            "Peripheral",
                        ],
                    },
                    "entity_id": {
                        "type": "integer",
                        "description": "ID da entidade/cliente",
                    },
                    "entity_name": {
                        "type": "string",
                        "description": "Nome da entidade/cliente",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 10,
                    },
                    "offset": {"type": "integer", "minimum": 0, "default": 0},
                },
            },
            "glpi_get_asset": {
                "type": "object",
                "properties": {
                    "asset_type": {
                        "type": "string",
                        "description": "Tipo de ativo no GLPI. Valores: Computer, Monitor, Printer, NetworkEquipment, Phone, Peripheral",
                        "enum": [
                            "Computer",
                            "Monitor",
                            "Printer",
                            "NetworkEquipment",
                            "Phone",
                            "Peripheral",
                        ],
                    },
                    "asset_id": {"type": "integer", "description": "ID do asset"},
                },
                "required": ["asset_type", "asset_id"],
            },
            "glpi_create_asset": {
                "type": "object",
                "properties": {
                    "asset_type": {
                        "type": "string",
                        "description": "Tipo de ativo no GLPI. Valores: Computer, Monitor, Printer, NetworkEquipment, Phone, Peripheral",
                        "enum": [
                            "Computer",
                            "Monitor",
                            "Printer",
                            "NetworkEquipment",
                            "Phone",
                            "Peripheral",
                        ],
                    },
                    "name": {"type": "string", "description": "Nome do asset"},
                    "serial_number": {
                        "type": "string",
                        "description": "Número de série",
                    },
                    "entity_id": {"type": "integer", "description": "ID da entidade"},
                    "entity_name": {
                        "type": "string",
                        "description": "Nome da entidade",
                    },
                },
                "required": ["asset_type", "name"],
            },
            "glpi_update_asset": {
                "type": "object",
                "properties": {
                    "asset_type": {
                        "type": "string",
                        "description": "Tipo de ativo no GLPI. Valores: Computer, Monitor, Printer, NetworkEquipment, Phone, Peripheral",
                        "enum": [
                            "Computer",
                            "Monitor",
                            "Printer",
                            "NetworkEquipment",
                            "Phone",
                            "Peripheral",
                        ],
                    },
                    "asset_id": {"type": "integer", "description": "ID do asset"},
                    "name": {"type": "string"},
                    "serial_number": {"type": "string"},
                    "status": {"type": "string"},
                },
                "required": ["asset_type", "asset_id"],
            },
            "glpi_delete_asset": {
                "type": "object",
                "properties": {
                    "asset_type": {
                        "type": "string",
                        "description": "Tipo de ativo no GLPI. Valores: Computer, Monitor, Printer, NetworkEquipment, Phone, Peripheral",
                        "enum": [
                            "Computer",
                            "Monitor",
                            "Printer",
                            "NetworkEquipment",
                            "Phone",
                            "Peripheral",
                        ],
                    },
                    "asset_id": {"type": "integer", "description": "ID do asset"},
                },
                "required": ["asset_type", "asset_id"],
            },
            "glpi_search_assets": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Texto para buscar (Nome, Serial, Contact/Nome Alternativo, ou Nome de Usuário associado). Aceita caracteres especiais como '.' e '@' (ex: joana.rodrigues@DOMINIO)",
                    },
                    "asset_type": {
                        "type": "string",
                        "description": "Tipo de ativo no GLPI. Valores: Computer, Monitor, Printer, NetworkEquipment, Phone, Peripheral",
                        "enum": [
                            "Computer",
                            "Monitor",
                            "Printer",
                            "NetworkEquipment",
                            "Phone",
                            "Peripheral",
                        ],
                    },
                    "entity_id": {"type": "integer"},
                    "entity_name": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
                "description": "Busca assets por texto livre com Smart Search v2.0: busca em múltiplos campos (Nome, Serial, Contact/Nome Alternativo, users_id). Se o usuário foi DELETADO (ex: removido do AD/LDAP), busca automaticamente nos deletados como fallback. Retorna 'smart_search_warning' quando encontrado via usuário deletado. Sempre retorna ID do asset.",
                "required": ["query"],
            },
            "glpi_list_computers": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "integer",
                        "description": "ID da entidade/cliente",
                    },
                    "entity_name": {
                        "type": "string",
                        "description": "Nome da entidade/cliente (ex: 'Ramada', 'Grupo Wink', 'GSM')",
                    },
                    "location_id": {
                        "type": "integer",
                        "description": "Filtrar por localização",
                    },
                    "manufacturer_id": {
                        "type": "integer",
                        "description": "Filtrar por fabricante",
                    },
                    "user_id": {
                        "type": "integer",
                        "description": "Filtrar por ID do usuário responsável",
                    },
                    "username": {
                        "type": "string",
                        "description": "Filtrar por nome do usuário",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 10,
                    },
                    "offset": {"type": "integer", "minimum": 0, "default": 0},
                },
                "description": "RETORNA DADOS ENRIQUECIDOS para cada computador: id, name, serial, memory_info (ex: '16.0 GB', '8.0 GB'), cpu_info (ex: '1x Intel Core i7-8550U'), anydesk_id, contact (Nome Alternativo), last_inventory_update, users_id, locations_id, manufacturers_id, models_id, types_id, states_id. NÃO USE get_computer_details para listar - esta tool já traz os dados necessários! Para filtrar por memória (ex: <8GB), processe o campo memory_info do resultado.",
            },
            "glpi_get_computer_details": {
                "type": "object",
                "properties": {
                    "computer_id": {
                        "type": "integer",
                        "description": "ID do computador",
                    }
                },
                "required": ["computer_id"],
            },
            "glpi_list_monitors": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer"},
                    "entity_name": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                    "offset": {"type": "integer", "default": 0},
                },
            },
            "glpi_get_monitor": {
                "type": "object",
                "properties": {
                    "monitor_id": {"type": "integer", "description": "ID do monitor"}
                },
                "required": ["monitor_id"],
            },
            "glpi_list_software": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer"},
                    "entity_name": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
            },
            "glpi_get_software": {
                "type": "object",
                "properties": {
                    "software_id": {"type": "integer", "description": "ID do software"}
                },
                "required": ["software_id"],
            },
            "glpi_list_devices": {
                "type": "object",
                "properties": {
                    "device_type": {
                        "type": "string",
                        "description": "Tipo de dispositivo no GLPI. Valores: NetworkEquipment (rede), Phone (telefone), Peripheral (periférico)",
                        "enum": ["NetworkEquipment", "Phone", "Peripheral"],
                    },
                    "entity_id": {"type": "integer"},
                    "entity_name": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
            },
            "glpi_get_device": {
                "type": "object",
                "properties": {
                    "device_type": {"type": "string"},
                    "device_id": {"type": "integer"},
                },
                "required": ["device_type", "device_id"],
            },
            "glpi_get_asset_reservations": {
                "type": "object",
                "properties": {
                    "asset_type": {"type": "string"},
                    "asset_id": {"type": "integer"},
                },
                "required": ["asset_type", "asset_id"],
            },
            "glpi_create_reservation": {
                "type": "object",
                "properties": {
                    "asset_type": {"type": "string"},
                    "asset_id": {"type": "integer"},
                    "start_date": {
                        "type": "string",
                        "description": "Data de início da reserva no formato ISO 8601 (AAAA-MM-DDTHH:mm:ss). Ex: 2025-03-15T09:00:00",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Data de término da reserva no formato ISO 8601 (AAAA-MM-DDTHH:mm:ss). Ex: 2025-03-15T18:00:00",
                    },
                    "comment": {"type": "string"},
                },
                "required": ["asset_type", "asset_id", "start_date", "end_date"],
            },
            "glpi_list_reservations": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer"},
                    "entity_name": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
            },
            "glpi_list_reservable_items": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer"},
                    "entity_name": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
            },
            "glpi_update_reservation": {
                "type": "object",
                "properties": {
                    "reservation_id": {"type": "integer"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "comment": {"type": "string"},
                },
                "required": ["reservation_id"],
            },
            "glpi_get_asset_stats": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer"},
                    "entity_name": {"type": "string"},
                },
            },
            # ----- ADMIN -----
            "glpi_list_users": {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "integer",
                        "description": "ID da entidade/cliente",
                    },
                    "entity_name": {
                        "type": "string",
                        "description": "Nome da entidade/cliente",
                    },
                    "group_id": {"type": "integer", "description": "ID do grupo"},
                    "profile_id": {"type": "integer", "description": "ID do perfil"},
                    "is_active": {
                        "type": "boolean",
                        "description": "Filtrar ativos/inativos",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 10,
                    },
                    "offset": {"type": "integer", "minimum": 0, "default": 0},
                },
            },
            "glpi_search_users": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Login/username do usuário",
                    },
                    "firstname": {"type": "string", "description": "Nome"},
                    "realname": {"type": "string", "description": "Sobrenome"},
                    "email": {"type": "string", "description": "Email"},
                    "entity_name": {
                        "type": "string",
                        "description": "Nome da entidade/cliente para filtrar",
                    },
                    "entity_id": {
                        "type": "integer",
                        "description": "ID da entidade para filtrar",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 10,
                    },
                    "offset": {"type": "integer", "minimum": 0, "default": 0},
                },
                "description": "Busca usuários por login, nome, sobrenome ou email. Retorna TODOS os campos: ID, nome completo, contatos, status ativo, localização, título, categoria, entidade, grupo, perfil, comentários, etc. FALLBACK AUTOMÁTICO: Se nenhum usuário ativo for encontrado, busca automaticamente nos DELETADOS (ex: removidos do AD/LDAP), retornando 'deleted_users_warning' e 'is_deleted: true' em cada usuário deletado.",
            },
            "glpi_get_user": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer", "description": "ID do usuário"}
                },
                "required": ["user_id"],
            },
            "glpi_create_user": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Login do usuário"},
                    "password": {
                        "type": "string",
                        "description": "Senha (obrigatório para authtype=1)",
                    },
                    "password2": {
                        "type": "string",
                        "description": "Confirmação da senha",
                    },
                    "firstname": {"type": "string", "description": "Primeiro nome"},
                    "realname": {"type": "string", "description": "Sobrenome"},
                    "email": {"type": "string", "description": "Email"},
                    "phone": {"type": "string", "description": "Telefone principal"},
                    "phone2": {"type": "string", "description": "Telefone secundário"},
                    "mobile": {"type": "string", "description": "Celular"},
                    "location_id": {
                        "type": "integer",
                        "description": "ID da localização",
                    },
                    "usertitle_id": {
                        "type": "integer",
                        "description": "ID do título/cargo",
                    },
                    "usercategory_id": {
                        "type": "integer",
                        "description": "ID da categoria",
                    },
                    "registration_number": {
                        "type": "string",
                        "description": "Número administrativo/matrícula",
                    },
                    "comment": {"type": "string", "description": "Comentários"},
                    "entity_id": {"type": "integer", "description": "ID da entidade"},
                    "entity_name": {
                        "type": "string",
                        "description": "Nome da entidade/cliente",
                    },
                    "profile_id": {"type": "integer", "description": "ID do perfil"},
                    "group_id": {"type": "integer", "description": "ID do grupo"},
                    "authtype": {
                        "type": "integer",
                        "description": "Tipo de autenticação no GLPI. Valores: 1 (local), 2 (email), 3 (LDAP/AD)",
                        "enum": [1, 2, 3],
                        "default": 1,
                    },
                    "is_active": {
                        "type": "boolean",
                        "description": "Status ativo",
                        "default": True,
                    },
                },
                "required": ["name"],
            },
            "glpi_update_user": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer", "description": "ID do usuário"},
                    "firstname": {"type": "string", "description": "Primeiro nome"},
                    "realname": {"type": "string", "description": "Sobrenome"},
                    "email": {"type": "string", "description": "Email"},
                    "phone": {"type": "string", "description": "Telefone principal"},
                    "phone2": {"type": "string", "description": "Telefone secundário"},
                    "mobile": {"type": "string", "description": "Celular"},
                    "location_id": {
                        "type": "integer",
                        "description": "ID da localização",
                    },
                    "usertitle_id": {
                        "type": "integer",
                        "description": "ID do título/cargo",
                    },
                    "usercategory_id": {
                        "type": "integer",
                        "description": "ID da categoria",
                    },
                    "registration_number": {
                        "type": "string",
                        "description": "Número administrativo/matrícula",
                    },
                    "comment": {"type": "string", "description": "Comentários"},
                    "is_active": {"type": "boolean", "description": "Status ativo"},
                },
                "required": ["user_id"],
            },
            "glpi_delete_user": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer", "description": "ID do usuário"}
                },
                "required": ["user_id"],
            },
            "glpi_list_groups": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer"},
                    "entity_name": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                    "offset": {"type": "integer", "default": 0},
                },
            },
            "glpi_get_group": {
                "type": "object",
                "properties": {
                    "group_id": {"type": "integer", "description": "ID do grupo"}
                },
                "required": ["group_id"],
            },
            "glpi_create_group": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nome do grupo"},
                    "comment": {"type": "string", "description": "Descrição"},
                    "entity_id": {"type": "integer"},
                    "entity_name": {"type": "string"},
                },
                "required": ["name"],
            },
            "glpi_list_entities": {
                "type": "object",
                "properties": {
                    "parent_id": {
                        "type": "integer",
                        "description": "ID da entidade pai",
                    },
                    "limit": {"type": "integer", "default": 50},
                    "offset": {"type": "integer", "default": 0},
                },
            },
            "glpi_get_entity": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer", "description": "ID da entidade"}
                },
                "required": ["entity_id"],
            },
            "glpi_list_locations": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer"},
                    "entity_name": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                    "offset": {"type": "integer", "default": 0},
                },
            },
            "glpi_get_location": {
                "type": "object",
                "properties": {
                    "location_id": {
                        "type": "integer",
                        "description": "ID da localização",
                    }
                },
                "required": ["location_id"],
            },
            # ----- WEBHOOKS -----
            "glpi_list_webhooks": {
                "type": "object",
                "properties": {
                    "is_active": {"type": "boolean"},
                    "limit": {"type": "integer", "default": 50},
                },
            },
            "glpi_get_webhook": {
                "type": "object",
                "properties": {
                    "webhook_id": {"type": "string", "description": "ID do webhook"}
                },
                "required": ["webhook_id"],
            },
            "glpi_create_webhook": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nome do webhook"},
                    "url": {"type": "string", "description": "URL de destino"},
                    "event_type": {
                        "type": "string",
                        "description": "Tipo de evento do GLPI. Valores: ticket_created, ticket_updated, ticket_closed, ticket_deleted, asset_created, asset_updated, asset_deleted",
                        "enum": [
                            "ticket_created",
                            "ticket_updated",
                            "ticket_closed",
                            "ticket_deleted",
                            "asset_created",
                            "asset_updated",
                            "asset_deleted",
                        ],
                    },
                    "secret": {
                        "type": "string",
                        "description": "Secret para assinatura",
                    },
                },
                "required": ["name", "url", "event_type"],
            },
            "glpi_update_webhook": {
                "type": "object",
                "properties": {
                    "webhook_id": {"type": "string"},
                    "name": {"type": "string"},
                    "url": {"type": "string"},
                    "is_active": {"type": "boolean"},
                },
                "required": ["webhook_id"],
            },
            "glpi_delete_webhook": {
                "type": "object",
                "properties": {
                    "webhook_id": {"type": "string", "description": "ID do webhook"}
                },
                "required": ["webhook_id"],
            },
            "glpi_test_webhook": {
                "type": "object",
                "properties": {
                    "webhook_id": {"type": "string", "description": "ID do webhook"}
                },
                "required": ["webhook_id"],
            },
            "glpi_get_webhook_deliveries": {
                "type": "object",
                "properties": {
                    "webhook_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": ["webhook_id"],
            },
            "glpi_trigger_webhook": {
                "type": "object",
                "properties": {
                    "event_type": {
                        "type": "string",
                        "description": "Tipo de evento para disparar no GLPI. Valores: ticket_created, ticket_updated, ticket_closed, ticket_deleted, asset_created, asset_updated, asset_deleted",
                        "enum": [
                            "ticket_created",
                            "ticket_updated",
                            "ticket_closed",
                            "ticket_deleted",
                            "asset_created",
                            "asset_updated",
                            "asset_deleted",
                        ],
                    },
                    "payload": {"type": "object", "description": "Dados do evento"},
                },
                "required": ["event_type"],
            },
            "glpi_get_webhook_stats": {"type": "object", "properties": {}},
            "glpi_enable_webhook": {
                "type": "object",
                "properties": {
                    "webhook_id": {"type": "string", "description": "ID do webhook"}
                },
                "required": ["webhook_id"],
            },
            "glpi_disable_webhook": {
                "type": "object",
                "properties": {
                    "webhook_id": {"type": "string", "description": "ID do webhook"}
                },
                "required": ["webhook_id"],
            },
            "glpi_retry_failed_deliveries": {
                "type": "object",
                "properties": {
                    "webhook_id": {"type": "string", "description": "ID do webhook"}
                },
                "required": ["webhook_id"],
            },
        }

        # Retornar schema específico ou genérico como fallback
        if tool_name in specific_schemas:
            return specific_schemas[tool_name]

        # Fallback para schemas genéricos por categoria (não recomendado)
        base_schemas = {
            "ticket": {"type": "object", "properties": {}},
            "asset": {"type": "object", "properties": {}},
            "admin": {"type": "object", "properties": {}},
            "webhook": {"type": "object", "properties": {}},
        }

        return base_schemas.get(category, {"type": "object"})

    async def handle_list_tools(self) -> Dict[str, Any]:
        """
        Handler MCP: tools/list
        Lista todas as tools disponíveis conforme JSON-RPC 2.0.

        Returns:
            Lista de tools MCP disponíveis
        """
        try:
            logger.info("MCP Handler: tools/list")

            tools_list = []
            for tool_name, tool_info in self.tools.items():
                tool_entry = {
                    "name": tool_info["name"],
                    "description": tool_info["description"],
                    "inputSchema": tool_info["input_schema"],
                }
                # SPEC-GLPI-ENHANCE-001/F03: Emit annotations in tools/list
                if "annotations" in tool_info:
                    tool_entry["annotations"] = tool_info["annotations"]
                tools_list.append(tool_entry)

            result = {
                "tools": tools_list,
                "total_count": len(tools_list),
                "categories": {
                    "tickets": len(
                        [t for t in self.tools.values() if t["category"] == "tickets"]
                    ),
                    "assets": len(
                        [t for t in self.tools.values() if t["category"] == "assets"]
                    ),
                    "admin": len(
                        [t for t in self.tools.values() if t["category"] == "admin"]
                    ),
                    "webhooks": len(
                        [t for t in self.tools.values() if t["category"] == "webhooks"]
                    ),
                },
            }

            logger.info(f"tools/list completed: {len(tools_list)} tools returned")
            return result

        except Exception as e:
            logger.error(f"tools/list error: {e}")
            raise GLPIError(500, f"Failed to list tools: {str(e)}")

    async def handle_call_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handler MCP: tools/call
        Executa uma tool específica conforme JSON-RPC 2.0.

        Args:
            tool_name: Nome da tool para executar
            arguments: Argumentos da tool

        Returns:
            Resultado da execução da tool
        """
        try:
            logger.info(f"MCP Handler: tools/call {tool_name}")

            # Verificar se tool existe
            if tool_name not in self.tools:
                raise MethodNotFoundError(tool_name)

            tool_info = self.tools[tool_name]
            handler = tool_info["handler"]

            # Validar argumentos contra schema (básico)
            self._validate_arguments(tool_name, arguments, tool_info["input_schema"])

            # Executar tool
            start_time = datetime.now()
            result = await handler(**arguments)
            execution_time = (datetime.now() - start_time).total_seconds()

            # SPEC-GLPI-ENHANCE-001/F01: Interceptor Markdown centralizado
            # Pattern identico ao Hudu server.ts:388 com fallback chain de 3 niveis:
            # 1. Markdown formatado | 2. result.message | 3. JSON fallback
            markdown = format_tool_response(tool_name, result, arguments)
            fallback_message = result.get("message", "") if isinstance(result, dict) else ""
            final_text = markdown or fallback_message or json.dumps(result, ensure_ascii=False, default=str)

            # MCP Protocol: tools/call DEVE retornar content array
            wrapped_result = {
                "content": [
                    {
                        "type": "text",
                        "text": final_text,
                    }
                ]
            }

            logger.info(f"tools/call completed: {tool_name} in {execution_time:.3f}s")
            return wrapped_result

        except (GLPIError, NotFoundError, ValidationError, SimilarityError) as e:
            logger.error(f"tools/call validation error for {tool_name}: {e.message}")
            raise
        except Exception as e:
            logger.error(f"tools/call unexpected error for {tool_name}: {e}")
            raise GLPIError(500, f"Failed to execute tool {tool_name}: {str(e)}")

    def _validate_arguments(
        self, tool_name: str, arguments: Dict[str, Any], schema: Dict[str, Any]
    ):
        """
        Valida argumentos contra schema JSON.

        Args:
            tool_name: Nome da tool
            arguments: Argumentos fornecidos
            schema: Schema JSON para validação
        """
        # Validação básica - verificar se é objeto
        if schema.get("type") == "object" and not isinstance(arguments, dict):
            raise ValidationError("Arguments must be a JSON object", "arguments")

        # TODO: Implementar validação JSON Schema completa
        # Por enquanto, validação básica é suficiente

        logger.debug(f"Arguments validated for tool: {tool_name}")

    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handler principal para requisições MCP JSON-RPC 2.0.

        Args:
            request: Requisição JSON-RPC 2.0

        Returns:
            Resposta JSON-RPC 2.0
        """
        try:
            # Validar requisição JSON-RPC 2.0 básica
            if not isinstance(request, dict):
                raise InvalidRequestError("Request must be a JSON object", "request")

            # Verificar versão JSON-RPC 2.0
            if request.get("jsonrpc") != "2.0":
                raise InvalidRequestError("JSON-RPC version must be '2.0'", "jsonrpc")

            method = request.get("method")
            params = request.get("params", {})
            request_id = request.get("id")

            if not method:
                raise ValidationError("Method is required", "method")

            logger.info(f"MCP Handler: processing method {method}")

            # Roteamento para handlers específicos
            if method == "initialize":
                # SPEC-GLPI-ENHANCE-001/F05: Server Instructions + capabilities
                result = {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "mcp-glpi", "version": "2.0.0"},
                    "capabilities": {"tools": {}, "prompts": {}, "resources": {}},
                    "instructions": (
                        "Servidor MCP GLPI - Gerenciamento de chamados, ativos, usuarios e webhooks\n\n"
                        "=== CATEGORIAS DE TOOLS ===\n\n"
                        "TICKETS (3 tools):\n"
                        "- glpi_search_tickets: Buscar/listar chamados por status, entidade, prioridade. Retorna Markdown.\n"
                        "- glpi_manage_tickets: Detalhes, criar, atualizar, fechar, resolver, followups, historico, similares (action: get/create/update/delete/assign/close/resolve/add_followup/get_followups/get_history/get_stats/find_similar). Retorna Markdown.\n"
                        "- glpi_manage_ai_analysis: Analise IA de tickets (action: trigger/get_result/publish). Retorna Markdown.\n\n"
                        "ATIVOS (2 tools):\n"
                        "- glpi_search_assets: Buscar computadores, monitores, software, dispositivos (scope: all/computers/monitors/software/devices/reservations/stats). Retorna Markdown.\n"
                        "- glpi_manage_assets: Detalhes, CRUD, reservas (action: get/create/update/delete/get_reservations/create_reservation). Retorna Markdown.\n\n"
                        "ADMIN (2 tools):\n"
                        "- glpi_search_admin: Buscar usuarios, grupos, entidades, localizacoes (resource: users/groups/entities/locations). Retorna Markdown.\n"
                        "- glpi_manage_admin: CRUD de recursos admin (action: get/create/update/delete). Retorna Markdown.\n\n"
                        "WEBHOOKS (2 tools):\n"
                        "- glpi_search_webhooks: Listar webhooks, stats, entregas (scope: list/stats/deliveries). Retorna Markdown.\n"
                        "- glpi_manage_webhooks: CRUD e controle (action: get/create/update/delete/test/trigger/enable/disable/retry). Retorna Markdown.\n\n"
                        "BRIDGE (5 tools):\n"
                        "- glpi_list_resources / glpi_read_resource: Resources MCP (entidades, status, categorias).\n"
                        "- glpi_list_prompts / glpi_get_prompt: 15 prompts de analise gerencial e operacional.\n"
                        "- glpi_search_knowledge: Base de conhecimento GLPI.\n\n"
                        "=== FORMATO ===\n"
                        "- search_*: limit (padrao 10, max 50), offset, filtros especificos.\n"
                        "- manage_*: action (obrigatorio), IDs inteiros (ticket_id, asset_id, etc.).\n"
                        "- Todas as respostas em Markdown (tabelas e detalhes).\n\n"
                        "=== DICAS ===\n"
                        "- Comece com search_ para descobrir recursos, depois manage_ para detalhes.\n"
                        "- Use resources (glpi://entities, glpi://ticket-status) para dados estaticos.\n"
                        "- Para relatorios, use glpi_get_prompt com um dos 15 prompts disponiveis."
                    ),
                }
            elif method == "tools/list":
                result = await self.handle_list_tools()
            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})

                if not tool_name:
                    raise ValidationError("Tool name is required", "name")

                result = await self.handle_call_tool(tool_name, arguments)
            elif method == "resources/list":
                # SPEC-GLPI-ENHANCE-001/F06: MCP Resources
                from src.resources import list_resources
                result = {"resources": list_resources()}
            elif method == "resources/read":
                # SPEC-GLPI-ENHANCE-001/F06: Read specific resource
                from src.resources import read_resource
                uri = params.get("uri", "")
                try:
                    session = await self.session_manager.get_current_session() if hasattr(self, 'session_manager') else None
                    resource_content = await read_resource(uri, session)
                    result = {"contents": [resource_content]}
                except ValueError as e:
                    raise InvalidRequestError(str(e))
            elif method == "prompts/list":
                # Redirecionar para o tool prompts_list e parsear resultado
                import json

                tool_result = await self.handle_call_tool("glpi_list_prompts", {})
                # tool_result é uma lista [{"type": "text", "text": "..."}]
                text_content = tool_result["content"][0]["text"]
                prompts_data = json.loads(text_content)
                result = {"prompts": prompts_data["prompts"]}
            elif method == "prompts/get":
                # Redirecionar para o tool prompts_get
                prompt_name = params.get("name")
                prompt_args = params.get("arguments", {})
                result = await self.handle_call_tool(
                    "glpi_get_prompt", {"name": prompt_name, "arguments": prompt_args}
                )
            elif method == "notifications/initialized" or method == "initialized":
                # MCP Protocol: confirmação de inicialização (notificação, retorna vazio)
                result = {}
            else:
                raise MethodNotFoundError(method)

            # Construir resposta JSON-RPC 2.0
            response = {"jsonrpc": "2.0", "id": request_id, "result": result}

            logger.info(f"MCP Handler: method {method} completed successfully")
            return response

        except (
            GLPIError,
            NotFoundError,
            ValidationError,
            SimilarityError,
            MethodNotFoundError,
        ) as e:
            # Erros esperados - mapear para JSON-RPC error
            error_response = {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {
                    "code": e.code
                    if hasattr(e, "code") and e.code < 0
                    else HTTP_TO_JSONRPC.get(e.code, -32603)
                    if hasattr(e, "code")
                    else -32603,
                    "message": e.message,
                    "data": {"type": type(e).__name__, "details": str(e)},
                },
            }

            logger.error(f"MCP Handler error: {e.message}")
            return error_response

        except Exception as e:
            # Erros inesperados
            error_response = {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {
                    "code": -32603,
                    "message": "Internal error",
                    "data": {"type": "InternalServerError", "details": str(e)},
                },
            }

            logger.error(f"MCP Handler unexpected error: {e}")
            return error_response

    def get_tool_info(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Obtém informações de uma tool específica.

        Args:
            tool_name: Nome da tool

        Returns:
            Informações da tool ou None se não existir
        """
        return self.tools.get(tool_name)

    def get_tools_by_category(self, category: str) -> List[Dict[str, Any]]:
        """
        Obtém tools por categoria.

        Args:
            category: Categoria (tickets, assets, admin, webhooks)

        Returns:
            Lista de tools da categoria
        """
        return [tool for tool in self.tools.values() if tool["category"] == category]

    def get_handler_stats(self) -> Dict[str, Any]:
        """
        Obtém estatísticas do handler.

        Returns:
            Estatísticas detalhadas
        """
        categories = {}
        for tool in self.tools.values():
            category = tool["category"]
            categories[category] = categories.get(category, 0) + 1

        return {
            "total_tools": len(self.tools),
            "categories": categories,
            "available_methods": ["tools/list", "tools/call"],
            "protocol": "JSON-RPC 2.0",
            "last_updated": datetime.now().isoformat(),
        }


# Instância global do handler MCP
mcp_handler = MCPHandler()

# Alias de compatibilidade legado
ToolHandler = MCPHandler
