"""
Definição de todas as 48 tools do MCP GLPI.
"""

from typing import List, Dict, Any
from src.models import Tool


def get_all_tools() -> List[Tool]:
    """Retorna lista completa de todas as tools do MCP."""

    tools = [
        # ===== TICKETS (12 tools) =====
        Tool(
            name="list_tickets",
            description="Lista todos os tickets com filtros opcionais (status, limite)",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filtrar por status (new, assigned, planned, pending, solved, closed)"},
                    "limit": {"type": "integer", "description": "Número máximo de resultados (padrão: 50)"},
                    "offset": {"type": "integer", "description": "Deslocamento para paginação (padrão: 0)"}
                }
            }
        ),
        Tool(
            name="get_ticket",
            description="Obtém detalhes completos de um ticket específico",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"}
                },
                "required": ["ticket_id"]
            }
        ),
        Tool(
            name="create_ticket",
            description="Cria um novo ticket",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Título do ticket (mínimo 3 caracteres)"},
                    "description": {"type": "string", "description": "Descrição detalhada do problema"},
                    "priority": {"type": "integer", "description": "Prioridade 1-5 (padrão: 3)"},
                    "requesters": {"type": "array", "items": {"type": "integer"}, "description": "IDs dos solicitantes"}
                },
                "required": ["title", "description"]
            }
        ),
        Tool(
            name="update_ticket",
            description="Atualiza um ticket existente",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"},
                    "title": {"type": "string", "description": "Novo título"},
                    "description": {"type": "string", "description": "Nova descrição"},
                    "status": {"type": "string", "description": "Novo status"},
                    "priority": {"type": "integer", "description": "Nova prioridade (1-5)"}
                },
                "required": ["ticket_id"]
            }
        ),
        Tool(
            name="delete_ticket",
            description="Deleta um ticket (move para lixo)",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"}
                },
                "required": ["ticket_id"]
            }
        ),
        Tool(
            name="assign_ticket",
            description="Atribui um ticket a um usuário",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"},
                    "user_id": {"type": "integer", "description": "ID do usuário para atribuição"}
                },
                "required": ["ticket_id", "user_id"]
            }
        ),
        Tool(
            name="close_ticket",
            description="Fecha um ticket com resolução opcional",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"},
                    "resolution": {"type": "string", "description": "Descrição da resolução"}
                },
                "required": ["ticket_id"]
            }
        ),
        Tool(
            name="search_tickets",
            description="Busca tickets por palavra-chave no título ou descrição",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Termo de busca"},
                    "limit": {"type": "integer", "description": "Número máximo de resultados"}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="add_ticket_comment",
            description="Adiciona um comentário a um ticket",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"},
                    "comment": {"type": "string", "description": "Texto do comentário"}
                },
                "required": ["ticket_id", "comment"]
            }
        ),
        Tool(
            name="list_ticket_comments",
            description="Lista todos os comentários de um ticket",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "ID do ticket"}
                },
                "required": ["ticket_id"]
            }
        ),
        Tool(
            name="get_ticket_status_options",
            description="Retorna opções de status disponíveis para tickets",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="bulk_update_tickets",
            description="Atualiza múltiplos tickets em uma operação",
            inputSchema={
                "type": "object",
                "properties": {
                    "ticket_ids": {"type": "array", "items": {"type": "integer"}, "description": "IDs dos tickets"},
                    "status": {"type": "string", "description": "Novo status para todos"},
                    "priority": {"type": "integer", "description": "Nova prioridade para todos"}
                },
                "required": ["ticket_ids"]
            }
        ),

        # ===== ASSETS (12 tools) =====
        Tool(
            name="list_computers",
            description="Lista todos os computadores",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Número máximo de resultados"},
                    "offset": {"type": "integer", "description": "Deslocamento para paginação"}
                }
            }
        ),
        Tool(
            name="get_computer",
            description="Obtém detalhes de um computador específico",
            inputSchema={
                "type": "object",
                "properties": {
                    "computer_id": {"type": "integer", "description": "ID do computador"}
                },
                "required": ["computer_id"]
            }
        ),
        Tool(
            name="create_computer",
            description="Cria um novo computador/asset",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nome do computador"},
                    "serial_number": {"type": "string", "description": "Número de série"},
                    "model": {"type": "string", "description": "Modelo"},
                    "manufacturer": {"type": "string", "description": "Fabricante"}
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="update_computer",
            description="Atualiza informações de um computador",
            inputSchema={
                "type": "object",
                "properties": {
                    "computer_id": {"type": "integer", "description": "ID do computador"},
                    "name": {"type": "string", "description": "Novo nome"},
                    "status": {"type": "string", "description": "Novo status"}
                },
                "required": ["computer_id"]
            }
        ),
        Tool(
            name="delete_computer",
            description="Deleta um computador",
            inputSchema={
                "type": "object",
                "properties": {
                    "computer_id": {"type": "integer", "description": "ID do computador"}
                },
                "required": ["computer_id"]
            }
        ),
        Tool(
            name="list_monitors",
            description="Lista todos os monitores",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"}
                }
            }
        ),
        Tool(
            name="list_printers",
            description="Lista todas as impressoras",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"}
                }
            }
        ),
        Tool(
            name="list_network_equipment",
            description="Lista equipamentos de rede (switches, roteadores)",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"}
                }
            }
        ),
        Tool(
            name="search_assets",
            description="Busca assets por nome ou série",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Termo de busca"},
                    "asset_type": {"type": "string", "description": "Tipo de asset a buscar"}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_asset_history",
            description="Obtém histórico de movimentações de um asset",
            inputSchema={
                "type": "object",
                "properties": {
                    "asset_id": {"type": "integer", "description": "ID do asset"},
                    "asset_type": {"type": "string", "description": "Tipo do asset"}
                },
                "required": ["asset_id", "asset_type"]
            }
        ),
        Tool(
            name="assign_asset_to_user",
            description="Atribui um asset a um usuário",
            inputSchema={
                "type": "object",
                "properties": {
                    "asset_id": {"type": "integer", "description": "ID do asset"},
                    "asset_type": {"type": "string", "description": "Tipo do asset"},
                    "user_id": {"type": "integer", "description": "ID do usuário"}
                },
                "required": ["asset_id", "asset_type", "user_id"]
            }
        ),

        # ===== USERS & GROUPS (12 tools) =====
        Tool(
            name="list_users",
            description="Lista todos os usuários",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"}
                }
            }
        ),
        Tool(
            name="get_user",
            description="Obtém detalhes de um usuário específico",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer", "description": "ID do usuário"}
                },
                "required": ["user_id"]
            }
        ),
        Tool(
            name="create_user",
            description="Cria um novo usuário",
            inputSchema={
                "type": "object",
                "properties": {
                    "firstname": {"type": "string", "description": "Primeiro nome"},
                    "lastname": {"type": "string", "description": "Último nome"},
                    "email": {"type": "string", "description": "Email"},
                    "phone": {"type": "string", "description": "Telefone"}
                },
                "required": ["firstname", "lastname"]
            }
        ),
        Tool(
            name="update_user",
            description="Atualiza informações de um usuário",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer", "description": "ID do usuário"},
                    "firstname": {"type": "string"},
                    "lastname": {"type": "string"},
                    "email": {"type": "string"},
                    "phone": {"type": "string"}
                },
                "required": ["user_id"]
            }
        ),
        Tool(
            name="delete_user",
            description="Deleta um usuário",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer", "description": "ID do usuário"}
                },
                "required": ["user_id"]
            }
        ),
        Tool(
            name="list_groups",
            description="Lista todos os grupos",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"}
                }
            }
        ),
        Tool(
            name="get_group",
            description="Obtém detalhes de um grupo",
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {"type": "integer", "description": "ID do grupo"}
                },
                "required": ["group_id"]
            }
        ),
        Tool(
            name="create_group",
            description="Cria um novo grupo",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nome do grupo"},
                    "comment": {"type": "string", "description": "Comentário/descrição"}
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="update_group",
            description="Atualiza um grupo",
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {"type": "integer", "description": "ID do grupo"},
                    "name": {"type": "string"},
                    "comment": {"type": "string"}
                },
                "required": ["group_id"]
            }
        ),
        Tool(
            name="delete_group",
            description="Deleta um grupo",
            inputSchema={
                "type": "object",
                "properties": {
                    "group_id": {"type": "integer", "description": "ID do grupo"}
                },
                "required": ["group_id"]
            }
        ),
        Tool(
            name="add_user_to_group",
            description="Adiciona um usuário a um grupo",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer", "description": "ID do usuário"},
                    "group_id": {"type": "integer", "description": "ID do grupo"}
                },
                "required": ["user_id", "group_id"]
            }
        ),
        Tool(
            name="remove_user_from_group",
            description="Remove um usuário de um grupo",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer", "description": "ID do usuário"},
                    "group_id": {"type": "integer", "description": "ID do grupo"}
                },
                "required": ["user_id", "group_id"]
            }
        ),

        # ===== ENTITIES & LOCATIONS (12 tools) =====
        Tool(
            name="list_entities",
            description="Lista todas as entidades/organizações",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"}
                }
            }
        ),
        Tool(
            name="get_entity",
            description="Obtém detalhes de uma entidade",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer", "description": "ID da entidade"}
                },
                "required": ["entity_id"]
            }
        ),
        Tool(
            name="create_entity",
            description="Cria uma nova entidade/organização",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nome da entidade"},
                    "entity_type": {"type": "string", "description": "Tipo (Fornecedor, Cliente, etc)"},
                    "phone": {"type": "string", "description": "Telefone"}
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="update_entity",
            description="Atualiza uma entidade",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer", "description": "ID da entidade"},
                    "name": {"type": "string"},
                    "entity_type": {"type": "string"},
                    "phone": {"type": "string"}
                },
                "required": ["entity_id"]
            }
        ),
        Tool(
            name="delete_entity",
            description="Deleta uma entidade",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer", "description": "ID da entidade"}
                },
                "required": ["entity_id"]
            }
        ),
        Tool(
            name="list_locations",
            description="Lista todas as localizações/filiais",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"}
                }
            }
        ),
        Tool(
            name="get_location",
            description="Obtém detalhes de uma localização",
            inputSchema={
                "type": "object",
                "properties": {
                    "location_id": {"type": "integer", "description": "ID da localização"}
                },
                "required": ["location_id"]
            }
        ),
        Tool(
            name="create_location",
            description="Cria uma nova localização/filial",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nome da localização"},
                    "address": {"type": "string", "description": "Endereço"},
                    "phone": {"type": "string", "description": "Telefone"}
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="update_location",
            description="Atualiza uma localização",
            inputSchema={
                "type": "object",
                "properties": {
                    "location_id": {"type": "integer", "description": "ID da localização"},
                    "name": {"type": "string"},
                    "address": {"type": "string"},
                    "phone": {"type": "string"}
                },
                "required": ["location_id"]
            }
        ),
        Tool(
            name="delete_location",
            description="Deleta uma localização",
            inputSchema={
                "type": "object",
                "properties": {
                    "location_id": {"type": "integer", "description": "ID da localização"}
                },
                "required": ["location_id"]
            }
        ),
        Tool(
            name="list_locations_by_entity",
            description="Lista localizações de uma entidade específica",
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_id": {"type": "integer", "description": "ID da entidade"}
                },
                "required": ["entity_id"]
            }
        ),
    ]

    return tools
