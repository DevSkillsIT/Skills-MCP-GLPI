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
from src.prompts_handlers.prompts import prompt_handler
from src.models.exceptions import (
    GLPIError,
    NotFoundError,
    ValidationError,
    SimilarityError,
    MethodNotFoundError,
    InvalidRequestError,
    HTTP_TO_JSONRPC
)
from src.utils.helpers import logger


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
        Registra todas as 48 tools MCP conforme matriz SPEC.md seção 4.2.
        
        Returns:
            Dicionário de tools mapeadas por nome
        """
        tools = {}
        
        # ============= TICKETS (12 tools) =============
        ticket_methods = [
            ("list_tickets", ticket_tools.list_tickets),
            ("get_ticket", ticket_tools.get_ticket),
            ("get_ticket_by_id", ticket_tools.get_ticket_by_id),
            ("get_ticket_by_number", ticket_tools.get_ticket_by_number),
            ("create_ticket", ticket_tools.create_ticket),
            ("update_ticket", ticket_tools.update_ticket),
            ("delete_ticket", ticket_tools.delete_ticket),
            ("assign_ticket", ticket_tools.assign_ticket),
            ("close_ticket", ticket_tools.close_ticket),
            ("find_similar_tickets", ticket_tools.find_similar_tickets),
            ("search_similar_tickets", ticket_tools.search_similar_tickets),
            ("search_tickets", ticket_tools.search_tickets),
            ("get_ticket_stats", ticket_tools.get_ticket_stats),
            ("get_ticket_history", ticket_tools.get_ticket_history),
            ("add_ticket_followup", ticket_tools.add_ticket_followup),
            ("post_private_note", ticket_tools.post_private_note),
            ("get_ticket_followups", ticket_tools.get_ticket_followups),
            ("resolve_ticket", ticket_tools.resolve_ticket)
        ]
        
        for name, method in ticket_methods:
            tools[name] = {
                "name": name,
                "description": self._get_tool_description(name),
                "input_schema": self._get_tool_schema(name, "ticket"),
                "handler": method,
                "category": "tickets"
            }
        
        # ============= ASSETS (12 tools) =============
        asset_methods = [
            ("list_assets", asset_tools.list_assets),
            ("get_asset", asset_tools.get_asset),
            ("create_asset", asset_tools.create_asset),
            ("update_asset", asset_tools.update_asset),
            ("delete_asset", asset_tools.delete_asset),
            ("search_assets", asset_tools.search_assets),
            ("get_asset_reservations", asset_tools.get_asset_reservations),
            ("create_reservation", asset_tools.create_reservation),
            ("list_reservations", asset_tools.list_reservations),
            ("list_reservable_items", asset_tools.list_reservable_items),
            ("update_reservation", asset_tools.update_reservation),
            ("get_asset_stats", asset_tools.get_asset_stats),
            ("list_computers", asset_tools.list_computers),
            ("get_computer_details", asset_tools.get_computer_details),
            ("list_monitors", asset_tools.list_monitors),
            ("get_monitor", asset_tools.get_monitor),
            ("list_software", asset_tools.list_software),
            ("get_software", asset_tools.get_software),
            ("list_devices", asset_tools.list_devices),
            ("get_device", asset_tools.get_device)
        ]
        
        for name, method in asset_methods:
            tools[name] = {
                "name": name,
                "description": self._get_tool_description(name),
                "input_schema": self._get_tool_schema(name, "asset"),
                "handler": method,
                "category": "assets"
            }
        
        # ============= ADMIN (13 tools) =============
        admin_methods = [
            ("list_users", admin_tools.list_users),
            ("search_users", admin_tools.search_users),
            ("get_user", admin_tools.get_user),
            ("create_user", admin_tools.create_user),
            ("update_user", admin_tools.update_user),
            ("delete_user", admin_tools.delete_user),
            ("list_groups", admin_tools.list_groups),
            ("get_group", admin_tools.get_group),
            ("create_group", admin_tools.create_group),
            ("list_entities", admin_tools.list_entities),
            ("get_entity", admin_tools.get_entity),
            ("list_locations", admin_tools.list_locations),
            ("get_location", admin_tools.get_location)
        ]
        
        for name, method in admin_methods:
            tools[name] = {
                "name": name,
                "description": self._get_tool_description(name),
                "input_schema": self._get_tool_schema(name, "admin"),
                "handler": method,
                "category": "admin"
            }
        
        # ============= WEBHOOKS (12 tools) =============
        webhook_methods = [
            ("list_webhooks", webhook_tools.list_webhooks),
            ("get_webhook", webhook_tools.get_webhook),
            ("create_webhook", webhook_tools.create_webhook),
            ("update_webhook", webhook_tools.update_webhook),
            ("delete_webhook", webhook_tools.delete_webhook),
            ("test_webhook", webhook_tools.test_webhook),
            ("get_webhook_deliveries", webhook_tools.get_webhook_deliveries),
            ("trigger_webhook", webhook_tools.trigger_webhook),
            ("get_webhook_stats", webhook_tools.get_webhook_stats),
            ("enable_webhook", webhook_tools.enable_webhook),
            ("disable_webhook", webhook_tools.disable_webhook),
            ("retry_failed_deliveries", webhook_tools.retry_failed_deliveries)
        ]
        
        for name, method in webhook_methods:
            tools[name] = {
                "name": name,
                "description": self._get_tool_description(name),
                "input_schema": self._get_tool_schema(name, "webhook"),
                "handler": method,
                "category": "webhooks"
            }

        # ============= IA (3 tools principais RF06) =============
        ai_methods = [
            ("trigger_ai_analysis", ai_tools.trigger_ai_analysis),
            ("get_ai_analysis_result", ai_tools.get_ai_analysis_result),
            ("publish_ai_response", ai_tools.publish_ai_response)
        ]

        for name, method in ai_methods:
            tools[name] = {
                "name": name,
                "description": self._get_tool_description(name),
                "input_schema": {"type": "object"},
                "handler": method,
                "category": "ai"
            }

        # ============= PROMPTS (2 tools - sistema de prompts profissionais) =============
        # Importar catálogo de prompts
        from src.prompts_handlers.prompts import PROMPTS_CATALOG, handle_list_prompts, handle_get_prompt

        # Tool 1: prompts/list
        tools["prompts_list"] = {
            "name": "prompts_list",
            "description": "Lista todos os 15 prompts profissionais disponíveis para gestores e analistas. Retorna nome, descrição, categoria (gestao/suporte), audience (público-alvo) e argumentos de cada prompt. USE para descobrir quais prompts existem antes de executar",
            "input_schema": {"type": "object"},
            "handler": handle_list_prompts,
            "category": "prompts"
        }

        # Tool 2: prompts/get (executa prompt específico)
        tools["prompts_get"] = {
            "name": "prompts_get",
            "description": "Executa um prompt específico com argumentos. Retorna resultado em 2 formatos: 'compact' (10 linhas, ideal para WhatsApp/Teams) e 'detailed' (Markdown completo). Prompts disponíveis: glpi_sla_performance, glpi_ticket_trends, glpi_asset_roi, glpi_technician_productivity, glpi_cost_per_ticket, glpi_recurring_problems, glpi_client_satisfaction (gestão) | glpi_ticket_summary, glpi_user_ticket_history, glpi_asset_lookup, glpi_onboarding_checklist, glpi_incident_investigation, glpi_change_management, glpi_hardware_request, glpi_knowledge_base_search (suporte)",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Nome do prompt (ex: glpi_sla_performance)",
                        "enum": [p["name"] for p in PROMPTS_CATALOG]
                    },
                    "arguments": {
                        "type": "object",
                        "description": "Argumentos do prompt (varia por prompt - veja prompts_list para detalhes)"
                    }
                },
                "required": ["name", "arguments"]
            },
            "handler": handle_get_prompt,
            "category": "prompts"
        }

        logger.info(f"Registered {len(tools)} MCP tools across 6 categories (tickets, assets, admin, webhooks, ai, prompts)")
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
            "list_tickets": "Lista todos os tickets com filtros opcionais. Suporta entity_name para filtrar por cliente (ex: entity_name='GSM')",
            "get_ticket": "Obtém detalhes completos de um ticket específico por ID. Retorna: id, name (título), content (descrição), status (1=Novo, 2=Em Atendimento, 3=Pendente, 4=Solucionado, 5=Fechado), priority (1-5), urgency (1-5), date (abertura), solvedate, closedate, users_id_recipient (solicitante), entities_id, itilcategories_id, slas_id_ttr, time_to_resolve",
            "get_ticket_by_id": "Obtém detalhes completos de um ticket pelo ID numérico. Retorna os mesmos campos de get_ticket. USE quando tiver o ID do ticket (ex: 'detalhes do ticket 42')",
            "get_ticket_by_number": "Obtém detalhes de um ticket pelo NÚMERO (string). ATENÇÃO: Em alguns sistemas GLPI o número pode ser diferente do ID. USE quando o usuário mencionar 'ticket número X' ou 'chamado #X'",
            "create_ticket": "Cria um novo ticket. Parâmetros: title (obrigatório), description (obrigatório), priority (1-5, default 3), entity_id ou entity_name (cliente), category_id, requester_id. Retorna: id do ticket criado",
            "update_ticket": "Atualiza um ticket existente. Pode alterar: status, priority, assignee_id (técnico atribuído). Retorna ticket atualizado",
            "delete_ticket": "Deleta um ticket PERMANENTEMENTE. OPERAÇÃO DESTRUTIVA - use com cuidado. Requer ticket_id",
            "assign_ticket": "Atribui um ticket a um técnico específico. Parâmetros: ticket_id, user_id (ID do técnico). USE para distribuir tickets ou reatribuir",
            "close_ticket": "Fecha um ticket COM RESOLUÇÃO. Parâmetros: ticket_id, resolution (texto da solução). O ticket será marcado como fechado e a resolução ficará registrada",
            "find_similar_tickets": "Encontra tickets similares usando algoritmos de similaridade textual. Parâmetros: title (obrigatório), description (opcional), threshold (0-1, default 0.6). USE para encontrar tickets com problemas parecidos e reutilizar soluções",
            "search_similar_tickets": "Busca tickets similares por título e descrição. Versão simplificada de find_similar_tickets. Parâmetros: title (obrigatório), description (opcional)",
            "search_tickets": "Busca tickets por texto livre (busca no título e conteúdo). Parâmetros: query (mín 2 chars), entity_name (filtro cliente), limit, offset. USE para encontrar tickets por palavras-chave",
            "get_ticket_stats": "Obtém estatísticas agregadas de tickets: total, por status (abertos, pendentes, resolvidos, fechados), por prioridade, por entidade. Filtro opcional: entity_name. USE para relatórios e dashboards",
            "get_ticket_history": "Obtém histórico COMPLETO de alterações de um ticket: mudanças de status, atribuições, atualizações de campos, quem fez e quando. Parâmetro: ticket_id",
            "add_ticket_followup": "Adiciona acompanhamento/comentário a um ticket. Parâmetros: ticket_id, content (texto), is_private (true/false). USE para registrar interações, atualizações e comunicação",
            "post_private_note": "Adiciona nota PRIVADA a um ticket (visível apenas para técnicos). Parâmetros: ticket_id, content. USE para anotações internas que o solicitante não deve ver",
            "get_ticket_followups": "Obtém todos os acompanhamentos/comentários de um ticket. Parâmetro: ticket_id. Retorna lista com: id, content, date, users_id, is_private",
            "resolve_ticket": "Resolve um ticket adicionando uma SOLUÇÃO. Parâmetros: ticket_id, solution (texto da solução). O ticket será marcado como solucionado (status 4). Diferente de close_ticket que fecha (status 5)",

            # ============= ASSETS (20 tools) =============
            "list_assets": "Lista todos os assets (ativos de TI) com filtros. Parâmetros: asset_type (Computer, Monitor, Printer, NetworkEquipment, Phone, Peripheral), entity_name (cliente), limit, offset. Retorna lista básica de assets",
            "get_asset": "Obtém detalhes completos de um asset específico. Parâmetros: asset_type, asset_id. Retorna: id, name, serial, status, location, manufacturer, model, user responsável",
            "create_asset": "Cria um novo asset. Parâmetros: asset_type (obrigatório), name (obrigatório), serial_number, entity_id ou entity_name. Retorna asset criado com ID",
            "update_asset": "Atualiza um asset existente. Parâmetros: asset_type, asset_id, campos a atualizar (name, serial_number, status, etc)",
            "delete_asset": "Deleta um asset PERMANENTEMENTE. OPERAÇÃO DESTRUTIVA. Parâmetros: asset_type, asset_id",
            "search_assets": "Busca assets por texto livre com Smart Search v2.0. Busca em: Nome, Serial, Contact (Nome Alternativo do Usuário), e usuarios_id vinculados. FALLBACK AUTOMÁTICO: Se usuário foi DELETADO (sync LDAP), busca em deletados e retorna 'smart_search_warning'. Parâmetros: query (texto), asset_type, entity_name",
            "get_asset_reservations": "Obtém reservas de um asset específico. Parâmetros: asset_type, asset_id. Retorna lista de reservas com datas, usuário, comentário",
            "create_reservation": "Cria uma reserva para um asset. Parâmetros: asset_type, asset_id, start_date (YYYY-MM-DD HH:MM), end_date, comment. Valida conflitos automaticamente",
            "list_reservations": "Lista todas as reservas de assets. Parâmetros: entity_name (filtro), limit. Retorna reservas com: id, asset, usuário, período, status",
            "list_reservable_items": "Lista itens configurados como RESERVÁVEIS no GLPI. Nem todo asset é reservável - precisa ser habilitado. Parâmetros: entity_name, limit",
            "update_reservation": "Atualiza uma reserva existente. Parâmetros: reservation_id, start_date, end_date, comment",
            "get_asset_stats": "Estatísticas agregadas de assets: total por tipo (computadores, monitores, etc), por status, por localização, por fabricante. Filtro: entity_name",
            "list_computers": "Lista computadores COM DADOS ENRIQUECIDOS em uma única chamada. Retorna para CADA computador: id, name, serial, memory_info (ex: '16.0 GB'), cpu_info (ex: '1x Intel Core i7-8550U'), anydesk_id, contact (Nome Alternativo), last_inventory_update, users_id, user_info (nome completo, email), locations_id, manufacturers_id, models_id, types_id, states_id. USE ESTA TOOL para listar máquinas - NÃO use get_computer_details para cada uma! Para filtrar por memória (ex: <8GB), processe o campo memory_info do resultado. Filtros: entity_name, location_id, manufacturer_id, user_id/username, limit, offset",
            "get_computer_details": "Obtém detalhes GRANULARES de UM computador específico (por ID). Retorna: componentes individuais de memória (cada pente), processadores (cada core), discos (cada HD/SSD), placas de rede, sistema operacional (versão, arquitetura), software instalado (lista completa), histórico de alterações, remote_management (AnyDesk, TeamViewer). USE APENAS quando precisar de informações detalhadas de UMA máquina (ex: 'qual pente de RAM está no computador X?', 'quais softwares estão instalados?'). Para LISTAR múltiplos computadores, use list_computers",
            "list_monitors": "Lista monitores com filtros. Parâmetros: entity_name, limit, offset. Retorna: id, name, serial, manufacturer, model, size, entity",
            "get_monitor": "Obtém detalhes completos de um monitor por ID. Retorna: id, name, serial, manufacturer, model, size (polegadas), comment, entity, location, user",
            "list_software": "Lista softwares cadastrados no GLPI. Parâmetros: entity_name, limit. Retorna: id, name, publisher, is_valid (licença válida), installations_count",
            "get_software": "Obtém detalhes de um software por ID. Retorna: id, name, publisher, versions, installations, licenças vinculadas",
            "list_devices": "Lista dispositivos por tipo: NetworkEquipment (switches, roteadores), Phone (telefones), Peripheral (periféricos). Parâmetros: device_type, entity_name, limit",
            "get_device": "Obtém detalhes de um dispositivo por tipo e ID. Parâmetros: device_type, device_id. Retorna dados específicos do tipo de dispositivo",

            # ============= ADMIN/USERS (13 tools) =============
            "list_users": "Lista todos os usuários com filtros. Parâmetros: entity_name (cliente), group_id, profile_id, is_active (true/false), limit, offset. Retorna lista de usuários com: id, name (login), firstname, realname, email, is_active",
            "search_users": "Busca usuários por nome, sobrenome, email ou username. RETORNA TODOS OS 20+ CAMPOS: id, name (login), firstname, realname, email, phone, phone2, mobile, locations_id, usertitles_id (cargo), usercategories_id (categoria), entities_id, groups_id, profiles_id, comment, is_active, is_deleted. FALLBACK AUTOMÁTICO: Se nenhum ativo encontrado, busca em DELETADOS (ex: usuários removidos do AD/LDAP), retorna 'deleted_users_warning' e 'is_deleted: true'. USE para encontrar usuários por qualquer critério",
            "get_user": "Obtém detalhes completos de um usuário por ID. Retorna TODOS os campos: dados pessoais, contatos (phone, phone2, mobile), email, localização, cargo, categoria, entidade, grupo, perfil, status ativo/deletado, comentários",
            "create_user": "Cria novo usuário com todos os campos disponíveis. Parâmetros: name (login, obrigatório), password (se auth local), firstname, realname, email, phone, phone2, mobile, location_id, usertitle_id (cargo), usercategory_id, entity_id/entity_name, group_id, profile_id, authtype (1=Local, 2=Mail, 3=LDAP), is_active",
            "update_user": "Atualiza usuário existente. Parâmetros: user_id (obrigatório), campos a atualizar: firstname, realname, email, phone, phone2, mobile, location_id, usertitle_id, usercategory_id, comment, is_active",
            "delete_user": "Deleta ou desativa um usuário. Parâmetro: user_id. ATENÇÃO: Pode ser desativação lógica ou exclusão física dependendo da configuração GLPI",
            "list_groups": "Lista grupos de usuários. Parâmetros: entity_name (filtro cliente), limit, offset. Retorna: id, name, comment, entity, membros_count",
            "get_group": "Obtém detalhes de um grupo por ID. Retorna: id, name, comment, entity, membros (lista de usuários)",
            "create_group": "Cria novo grupo. Parâmetros: name (obrigatório), comment (descrição), entity_id/entity_name",
            "list_entities": "Lista entidades (clientes/organizações). Parâmetros: parent_id (filtrar sub-entidades), limit, offset. Retorna: id, name, completename (caminho completo), parent, address, phone",
            "get_entity": "Obtém detalhes de uma entidade por ID. Retorna: id, name, completename, parent, address, phone, email, website, configurações de SLA",
            "list_locations": "Lista localizações (escritórios, filiais). Parâmetros: entity_name (filtro), limit, offset. Retorna: id, name, completename, entity, address, building, room",
            "get_location": "Obtém detalhes de uma localização por ID. Retorna: id, name, completename, entity, address, latitude, longitude, building, room",

            # ============= WEBHOOKS (12 tools) =============
            "list_webhooks": "Lista todos os webhooks configurados. Parâmetros: is_active (filtro), limit. Retorna: id, name, url, event_type, is_active, last_delivery",
            "get_webhook": "Obtém detalhes de um webhook por ID. Retorna: id, name, url, event_type, secret, headers, is_active, delivery_stats",
            "create_webhook": "Cria novo webhook. Parâmetros: name, url (endpoint destino), event_type (ticket_created, ticket_updated, etc), secret (para assinatura)",
            "update_webhook": "Atualiza webhook existente. Parâmetros: webhook_id, name, url, is_active",
            "delete_webhook": "Deleta um webhook permanentemente. Parâmetro: webhook_id",
            "test_webhook": "Envia payload de TESTE para verificar se webhook está funcionando. Parâmetro: webhook_id. Retorna status da entrega",
            "get_webhook_deliveries": "Histórico de entregas de um webhook. Parâmetros: webhook_id, limit. Retorna: tentativas, status, response_code, erro (se houver)",
            "trigger_webhook": "Dispara webhook MANUALMENTE para um evento. Parâmetros: event_type, payload (dados customizados). USE para testes ou integrações manuais",
            "get_webhook_stats": "Estatísticas agregadas de webhooks: total configurados, ativos, entregas (sucesso/falha), latência média",
            "enable_webhook": "Ativa um webhook desativado. Parâmetro: webhook_id",
            "disable_webhook": "Desativa um webhook (para temporariamente). Parâmetro: webhook_id",
            "retry_failed_deliveries": "Re-tenta entregas FALHADAS de um webhook. Parâmetro: webhook_id. USE quando endpoint estava indisponível",

            # ============= AI TOOLS (3 tools) =============
            "trigger_ai_analysis": "Dispara análise de IA nos tickets pendentes. Analisa conteúdo, sugere categorização, prioridade e possíveis soluções baseado em histórico",
            "get_ai_analysis_result": "Obtém resultado da última análise de IA. Retorna: tickets analisados, sugestões de categorização, priorização, soluções similares",
            "publish_ai_response": "Publica resposta gerada por IA em um ticket. Adiciona como followup com marcação de origem IA",

            # ============= PROMPTS (2 tools - sistema de prompts profissionais) =============
            "prompts_list": "Lista todos os 15 prompts profissionais disponíveis para gestores e analistas. Retorna nome, descrição, categoria (gestao/suporte), audience (público-alvo) e argumentos de cada prompt. USE para descobrir quais prompts existem antes de executar",
            "prompts_get": "Executa um prompt específico com argumentos. Retorna resultado em 2 formatos: 'compact' (10 linhas, ideal para WhatsApp/Teams) e 'detailed' (Markdown completo). Prompts disponíveis: glpi_sla_performance, glpi_ticket_trends, glpi_asset_roi, glpi_technician_productivity, glpi_cost_per_ticket, glpi_recurring_problems, glpi_client_satisfaction (gestão) | glpi_ticket_summary, glpi_user_ticket_history, glpi_asset_lookup, glpi_onboarding_checklist, glpi_incident_investigation, glpi_change_management, glpi_hardware_request, glpi_knowledge_base_search (suporte)"
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
            "list_tickets": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filtrar por status (new, processing, pending, solved, closed)"},
                    "entity_id": {"type": "integer", "description": "ID da entidade/cliente"},
                    "entity_name": {"type": "string", "description": "Nome da entidade/cliente (ex: 'GSM', 'Skills IT')"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 50},
                    "offset": {"type": "integer", "minimum": 0, "default": 0}
                }
            },
            "get_ticket": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"}
                },
                "required": ["ticket_id"]
            },
            "get_ticket_by_id": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"}
                },
                "required": ["ticket_id"]
            },
            "get_ticket_by_number": {
                "type": "object",
                "properties": {
                    "ticket_number": {"type": "string", "description": "Número do ticket"}
                },
                "required": ["ticket_number"]
            },
            "create_ticket": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título do ticket"},
                    "description": {"type": "string", "description": "Descrição detalhada do problema"},
                    "priority": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
                    "entity_id": {"type": "integer", "description": "ID da entidade/cliente"},
                    "entity_name": {"type": "string", "description": "Nome da entidade/cliente"},
                    "category_id": {"type": "integer", "description": "ID da categoria"},
                    "requester_id": {"type": "integer", "description": "ID do solicitante"}
                },
                "required": ["title", "description"]
            },
            "update_ticket": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"},
                    "status": {"type": "string", "description": "Novo status"},
                    "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                    "assignee_id": {"type": "integer", "description": "ID do técnico atribuído"}
                },
                "required": ["ticket_id"]
            },
            "delete_ticket": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"}
                },
                "required": ["ticket_id"]
            },
            "assign_ticket": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"},
                    "user_id": {"type": "integer", "description": "ID do usuário/técnico para atribuir"}
                },
                "required": ["ticket_id", "user_id"]
            },
            "close_ticket": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"},
                    "resolution": {"type": "string", "description": "Texto da solução/resolução"}
                },
                "required": ["ticket_id", "resolution"]
            },
            "search_tickets": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Texto para buscar nos tickets (mínimo 2 caracteres)"},
                    "entity_id": {"type": "integer", "description": "ID da entidade/cliente"},
                    "entity_name": {"type": "string", "description": "Nome da entidade/cliente"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 50},
                    "offset": {"type": "integer", "minimum": 0, "default": 0}
                },
                "required": ["query"]
            },
            "find_similar_tickets": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título para buscar similares"},
                    "description": {"type": "string", "description": "Descrição para buscar similares"},
                    "threshold": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.6}
                },
                "required": ["title"]
            },
            "search_similar_tickets": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título para buscar similares"},
                    "description": {"type": "string", "description": "Descrição para buscar similares"}
                },
                "required": ["title"]
            },
            "get_ticket_stats": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer", "description": "ID da entidade/cliente"},
                    "entity_name": {"type": "string", "description": "Nome da entidade/cliente"}
                }
            },
            "get_ticket_history": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"}
                },
                "required": ["ticket_id"]
            },
            "add_ticket_followup": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"},
                    "content": {"type": "string", "description": "Conteúdo do acompanhamento"},
                    "is_private": {"type": "boolean", "default": False}
                },
                "required": ["ticket_id", "content"]
            },
            "post_private_note": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"},
                    "content": {"type": "string", "description": "Conteúdo da nota privada"}
                },
                "required": ["ticket_id", "content"]
            },
            "get_ticket_followups": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"}
                },
                "required": ["ticket_id"]
            },
            "resolve_ticket": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"},
                    "solution": {"type": "string", "description": "Texto da solução"}
                },
                "required": ["ticket_id", "solution"]
            },

            # ----- ASSETS -----
            "list_assets": {
                "type": "object",
                "properties": {
                    "asset_type": {"type": "string", "description": "Tipo: Computer, Monitor, Printer, NetworkEquipment, Phone, Peripheral"},
                    "entity_id": {"type": "integer", "description": "ID da entidade/cliente"},
                    "entity_name": {"type": "string", "description": "Nome da entidade/cliente"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 50},
                    "offset": {"type": "integer", "minimum": 0, "default": 0}
                }
            },
            "get_asset": {
                "type": "object",
                "properties": {
                    "asset_type": {"type": "string", "description": "Tipo do asset"},
                    "asset_id": {"type": "integer", "description": "ID do asset"}
                },
                "required": ["asset_type", "asset_id"]
            },
            "create_asset": {
                "type": "object",
                "properties": {
                    "asset_type": {"type": "string", "description": "Tipo do asset"},
                    "name": {"type": "string", "description": "Nome do asset"},
                    "serial_number": {"type": "string", "description": "Número de série"},
                    "entity_id": {"type": "integer", "description": "ID da entidade"},
                    "entity_name": {"type": "string", "description": "Nome da entidade"}
                },
                "required": ["asset_type", "name"]
            },
            "update_asset": {
                "type": "object",
                "properties": {
                    "asset_type": {"type": "string", "description": "Tipo do asset"},
                    "asset_id": {"type": "integer", "description": "ID do asset"},
                    "name": {"type": "string"},
                    "serial_number": {"type": "string"},
                    "status": {"type": "string"}
                },
                "required": ["asset_type", "asset_id"]
            },
            "delete_asset": {
                "type": "object",
                "properties": {
                    "asset_type": {"type": "string", "description": "Tipo do asset"},
                    "asset_id": {"type": "integer", "description": "ID do asset"}
                },
                "required": ["asset_type", "asset_id"]
            },
            "search_assets": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Texto para buscar (Nome, Serial, Contact/Nome Alternativo, ou Nome de Usuário associado). Aceita caracteres especiais como '.' e '@' (ex: joana.rodrigues@DOMINIO)"},
                    "asset_type": {"type": "string", "description": "Tipo do asset"},
                    "entity_id": {"type": "integer"},
                    "entity_name": {"type": "string"},
                    "limit": {"type": "integer", "default": 50}
                },
                "description": "Busca assets por texto livre com Smart Search v2.0: busca em múltiplos campos (Nome, Serial, Contact/Nome Alternativo, users_id). Se o usuário foi DELETADO (ex: removido do AD/LDAP), busca automaticamente nos deletados como fallback. Retorna 'smart_search_warning' quando encontrado via usuário deletado. Sempre retorna ID do asset.",
                "required": ["query"]
            },
            "list_computers": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer", "description": "ID da entidade/cliente"},
                    "entity_name": {"type": "string", "description": "Nome da entidade/cliente (ex: 'Ramada', 'Grupo Wink', 'GSM')"},
                    "location_id": {"type": "integer", "description": "Filtrar por localização"},
                    "manufacturer_id": {"type": "integer", "description": "Filtrar por fabricante"},
                    "user_id": {"type": "integer", "description": "Filtrar por ID do usuário responsável"},
                    "username": {"type": "string", "description": "Filtrar por nome do usuário"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 50},
                    "offset": {"type": "integer", "minimum": 0, "default": 0}
                },
                "description": "RETORNA DADOS ENRIQUECIDOS para cada computador: id, name, serial, memory_info (ex: '16.0 GB', '8.0 GB'), cpu_info (ex: '1x Intel Core i7-8550U'), anydesk_id, contact (Nome Alternativo), last_inventory_update, users_id, locations_id, manufacturers_id, models_id, types_id, states_id. NÃO USE get_computer_details para listar - esta tool já traz os dados necessários! Para filtrar por memória (ex: <8GB), processe o campo memory_info do resultado."
            },
            "get_computer_details": {
                "type": "object",
                "properties": {
                    "computer_id": {"type": "integer", "description": "ID do computador"}
                },
                "required": ["computer_id"]
            },
            "list_monitors": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer"},
                    "entity_name": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                    "offset": {"type": "integer", "default": 0}
                }
            },
            "get_monitor": {
                "type": "object",
                "properties": {
                    "monitor_id": {"type": "integer", "description": "ID do monitor"}
                },
                "required": ["monitor_id"]
            },
            "list_software": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer"},
                    "entity_name": {"type": "string"},
                    "limit": {"type": "integer", "default": 50}
                }
            },
            "get_software": {
                "type": "object",
                "properties": {
                    "software_id": {"type": "integer", "description": "ID do software"}
                },
                "required": ["software_id"]
            },
            "list_devices": {
                "type": "object",
                "properties": {
                    "device_type": {"type": "string", "description": "Tipo: NetworkEquipment, Phone, Peripheral"},
                    "entity_id": {"type": "integer"},
                    "entity_name": {"type": "string"},
                    "limit": {"type": "integer", "default": 50}
                }
            },
            "get_device": {
                "type": "object",
                "properties": {
                    "device_type": {"type": "string"},
                    "device_id": {"type": "integer"}
                },
                "required": ["device_type", "device_id"]
            },
            "get_asset_reservations": {
                "type": "object",
                "properties": {
                    "asset_type": {"type": "string"},
                    "asset_id": {"type": "integer"}
                },
                "required": ["asset_type", "asset_id"]
            },
            "create_reservation": {
                "type": "object",
                "properties": {
                    "asset_type": {"type": "string"},
                    "asset_id": {"type": "integer"},
                    "start_date": {"type": "string", "description": "Data início (YYYY-MM-DD HH:MM)"},
                    "end_date": {"type": "string", "description": "Data fim (YYYY-MM-DD HH:MM)"},
                    "comment": {"type": "string"}
                },
                "required": ["asset_type", "asset_id", "start_date", "end_date"]
            },
            "list_reservations": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer"},
                    "entity_name": {"type": "string"},
                    "limit": {"type": "integer", "default": 50}
                }
            },
            "list_reservable_items": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer"},
                    "entity_name": {"type": "string"},
                    "limit": {"type": "integer", "default": 50}
                }
            },
            "update_reservation": {
                "type": "object",
                "properties": {
                    "reservation_id": {"type": "integer"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "comment": {"type": "string"}
                },
                "required": ["reservation_id"]
            },
            "get_asset_stats": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer"},
                    "entity_name": {"type": "string"}
                }
            },

            # ----- ADMIN -----
            "list_users": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer", "description": "ID da entidade/cliente"},
                    "entity_name": {"type": "string", "description": "Nome da entidade/cliente"},
                    "group_id": {"type": "integer", "description": "ID do grupo"},
                    "profile_id": {"type": "integer", "description": "ID do perfil"},
                    "is_active": {"type": "boolean", "description": "Filtrar ativos/inativos"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 50},
                    "offset": {"type": "integer", "minimum": 0, "default": 0}
                }
            },
            "search_users": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Login/username do usuário"},
                    "firstname": {"type": "string", "description": "Nome"},
                    "realname": {"type": "string", "description": "Sobrenome"},
                    "email": {"type": "string", "description": "Email"},
                    "entity_name": {"type": "string", "description": "Nome da entidade/cliente para filtrar"},
                    "entity_id": {"type": "integer", "description": "ID da entidade para filtrar"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 250},
                    "offset": {"type": "integer", "minimum": 0, "default": 0}
                },
                "description": "Busca usuários por login, nome, sobrenome ou email. Retorna TODOS os campos: ID, nome completo, contatos, status ativo, localização, título, categoria, entidade, grupo, perfil, comentários, etc. FALLBACK AUTOMÁTICO: Se nenhum usuário ativo for encontrado, busca automaticamente nos DELETADOS (ex: removidos do AD/LDAP), retornando 'deleted_users_warning' e 'is_deleted: true' em cada usuário deletado."
            },
            "get_user": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer", "description": "ID do usuário"}
                },
                "required": ["user_id"]
            },
            "create_user": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Login do usuário"},
                    "password": {"type": "string", "description": "Senha (obrigatório para authtype=1)"},
                    "password2": {"type": "string", "description": "Confirmação da senha"},
                    "firstname": {"type": "string", "description": "Primeiro nome"},
                    "realname": {"type": "string", "description": "Sobrenome"},
                    "email": {"type": "string", "description": "Email"},
                    "phone": {"type": "string", "description": "Telefone principal"},
                    "phone2": {"type": "string", "description": "Telefone secundário"},
                    "mobile": {"type": "string", "description": "Celular"},
                    "location_id": {"type": "integer", "description": "ID da localização"},
                    "usertitle_id": {"type": "integer", "description": "ID do título/cargo"},
                    "usercategory_id": {"type": "integer", "description": "ID da categoria"},
                    "registration_number": {"type": "string", "description": "Número administrativo/matrícula"},
                    "comment": {"type": "string", "description": "Comentários"},
                    "entity_id": {"type": "integer", "description": "ID da entidade"},
                    "entity_name": {"type": "string", "description": "Nome da entidade/cliente"},
                    "profile_id": {"type": "integer", "description": "ID do perfil"},
                    "group_id": {"type": "integer", "description": "ID do grupo"},
                    "authtype": {"type": "integer", "description": "Tipo de autenticação (1=Local, 2=Mail, 3=LDAP)", "default": 1},
                    "is_active": {"type": "boolean", "description": "Status ativo", "default": True}
                },
                "required": ["name"]
            },
            "update_user": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer", "description": "ID do usuário"},
                    "firstname": {"type": "string", "description": "Primeiro nome"},
                    "realname": {"type": "string", "description": "Sobrenome"},
                    "email": {"type": "string", "description": "Email"},
                    "phone": {"type": "string", "description": "Telefone principal"},
                    "phone2": {"type": "string", "description": "Telefone secundário"},
                    "mobile": {"type": "string", "description": "Celular"},
                    "location_id": {"type": "integer", "description": "ID da localização"},
                    "usertitle_id": {"type": "integer", "description": "ID do título/cargo"},
                    "usercategory_id": {"type": "integer", "description": "ID da categoria"},
                    "registration_number": {"type": "string", "description": "Número administrativo/matrícula"},
                    "comment": {"type": "string", "description": "Comentários"},
                    "is_active": {"type": "boolean", "description": "Status ativo"}
                },
                "required": ["user_id"]
            },
            "delete_user": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer", "description": "ID do usuário"}
                },
                "required": ["user_id"]
            },
            "list_groups": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer"},
                    "entity_name": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                    "offset": {"type": "integer", "default": 0}
                }
            },
            "get_group": {
                "type": "object",
                "properties": {
                    "group_id": {"type": "integer", "description": "ID do grupo"}
                },
                "required": ["group_id"]
            },
            "create_group": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nome do grupo"},
                    "comment": {"type": "string", "description": "Descrição"},
                    "entity_id": {"type": "integer"},
                    "entity_name": {"type": "string"}
                },
                "required": ["name"]
            },
            "list_entities": {
                "type": "object",
                "properties": {
                    "parent_id": {"type": "integer", "description": "ID da entidade pai"},
                    "limit": {"type": "integer", "default": 50},
                    "offset": {"type": "integer", "default": 0}
                }
            },
            "get_entity": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer", "description": "ID da entidade"}
                },
                "required": ["entity_id"]
            },
            "list_locations": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer"},
                    "entity_name": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                    "offset": {"type": "integer", "default": 0}
                }
            },
            "get_location": {
                "type": "object",
                "properties": {
                    "location_id": {"type": "integer", "description": "ID da localização"}
                },
                "required": ["location_id"]
            },

            # ----- WEBHOOKS -----
            "list_webhooks": {
                "type": "object",
                "properties": {
                    "is_active": {"type": "boolean"},
                    "limit": {"type": "integer", "default": 50}
                }
            },
            "get_webhook": {
                "type": "object",
                "properties": {
                    "webhook_id": {"type": "string", "description": "ID do webhook"}
                },
                "required": ["webhook_id"]
            },
            "create_webhook": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nome do webhook"},
                    "url": {"type": "string", "description": "URL de destino"},
                    "event_type": {"type": "string", "description": "Tipo de evento"},
                    "secret": {"type": "string", "description": "Secret para assinatura"}
                },
                "required": ["name", "url", "event_type"]
            },
            "update_webhook": {
                "type": "object",
                "properties": {
                    "webhook_id": {"type": "string"},
                    "name": {"type": "string"},
                    "url": {"type": "string"},
                    "is_active": {"type": "boolean"}
                },
                "required": ["webhook_id"]
            },
            "delete_webhook": {
                "type": "object",
                "properties": {
                    "webhook_id": {"type": "string", "description": "ID do webhook"}
                },
                "required": ["webhook_id"]
            },
            "test_webhook": {
                "type": "object",
                "properties": {
                    "webhook_id": {"type": "string", "description": "ID do webhook"}
                },
                "required": ["webhook_id"]
            },
            "get_webhook_deliveries": {
                "type": "object",
                "properties": {
                    "webhook_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 50}
                },
                "required": ["webhook_id"]
            },
            "trigger_webhook": {
                "type": "object",
                "properties": {
                    "event_type": {"type": "string", "description": "Tipo de evento para disparar"},
                    "payload": {"type": "object", "description": "Dados do evento"}
                },
                "required": ["event_type"]
            },
            "get_webhook_stats": {
                "type": "object",
                "properties": {}
            },
            "enable_webhook": {
                "type": "object",
                "properties": {
                    "webhook_id": {"type": "string", "description": "ID do webhook"}
                },
                "required": ["webhook_id"]
            },
            "disable_webhook": {
                "type": "object",
                "properties": {
                    "webhook_id": {"type": "string", "description": "ID do webhook"}
                },
                "required": ["webhook_id"]
            },
            "retry_failed_deliveries": {
                "type": "object",
                "properties": {
                    "webhook_id": {"type": "string", "description": "ID do webhook"}
                },
                "required": ["webhook_id"]
            }
        }

        # Retornar schema específico ou genérico como fallback
        if tool_name in specific_schemas:
            return specific_schemas[tool_name]

        # Fallback para schemas genéricos por categoria (não recomendado)
        base_schemas = {
            "ticket": {"type": "object", "properties": {}},
            "asset": {"type": "object", "properties": {}},
            "admin": {"type": "object", "properties": {}},
            "webhook": {"type": "object", "properties": {}}
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
                tools_list.append({
                    "name": tool_info["name"],
                    "description": tool_info["description"],
                    "inputSchema": tool_info["input_schema"]
                })
            
            result = {
                "tools": tools_list,
                "total_count": len(tools_list),
                "categories": {
                    "tickets": len([t for t in self.tools.values() if t["category"] == "tickets"]),
                    "assets": len([t for t in self.tools.values() if t["category"] == "assets"]),
                    "admin": len([t for t in self.tools.values() if t["category"] == "admin"]),
                    "webhooks": len([t for t in self.tools.values() if t["category"] == "webhooks"])
                }
            }
            
            logger.info(f"tools/list completed: {len(tools_list)} tools returned")
            return result
            
        except Exception as e:
            logger.error(f"tools/list error: {e}")
            raise GLPIError(500, f"Failed to list tools: {str(e)}")
    
    async def handle_call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
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

            # MCP Protocol 2024-11-05: tools/call DEVE retornar content array
            # Formato: {"content": [{"type": "text", "text": "..."}]}
            wrapped_result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, ensure_ascii=False, default=str)
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
    
    def _validate_arguments(self, tool_name: str, arguments: Dict[str, Any], schema: Dict[str, Any]):
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
                # MCP Protocol initialization handshake (obrigatório para Claude Code)
                result = {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {
                        "name": "mcp-glpi",
                        "version": "1.0.0"
                    },
                    "capabilities": {
                        "tools": {},
                        "prompts": {}
                    }
                }
            elif method == "tools/list":
                result = await self.handle_list_tools()
            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})

                if not tool_name:
                    raise ValidationError("Tool name is required", "name")

                result = await self.handle_call_tool(tool_name, arguments)
            elif method == "prompts/list":
                # Redirecionar para o tool prompts_list e parsear resultado
                import json
                tool_result = await self.handle_call_tool("prompts_list", {})
                # tool_result é uma lista [{"type": "text", "text": "..."}]
                text_content = tool_result["content"][0]["text"]
                prompts_data = json.loads(text_content)
                result = {"prompts": prompts_data["prompts"]}
            elif method == "prompts/get":
                # Redirecionar para o tool prompts_get
                prompt_name = params.get("name")
                prompt_args = params.get("arguments", {})
                result = await self.handle_call_tool("prompts_get", {
                    "name": prompt_name,
                    "arguments": prompt_args
                })
            elif method == "notifications/initialized" or method == "initialized":
                # MCP Protocol: confirmação de inicialização (notificação, retorna vazio)
                result = {}
            else:
                raise MethodNotFoundError(method)
            
            # Construir resposta JSON-RPC 2.0
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }
            
            logger.info(f"MCP Handler: method {method} completed successfully")
            return response
            
        except (GLPIError, NotFoundError, ValidationError, SimilarityError, MethodNotFoundError) as e:
            # Erros esperados - mapear para JSON-RPC error
            error_response = {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {
                    "code": e.code if hasattr(e, 'code') and e.code < 0 else HTTP_TO_JSONRPC.get(e.code, -32603) if hasattr(e, 'code') else -32603,
                    "message": e.message,
                    "data": {
                        "type": type(e).__name__,
                        "details": str(e)
                    }
                }
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
                    "data": {
                        "type": "InternalServerError",
                        "details": str(e)
                    }
                }
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
            "last_updated": datetime.now().isoformat()
        }


# Instância global do handler MCP
mcp_handler = MCPHandler()

# Alias de compatibilidade legado
ToolHandler = MCPHandler
