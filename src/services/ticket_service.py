"""
Serviço de gerenciamento de tickets GLPI - Integração Real
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

from src.services.glpi_client import glpi_client
from src.services.similarity_service import similarity_service
from src.models.exceptions import (
    GLPIError, 
    NotFoundError, 
    ValidationError,
    AuthenticationError
)
from src.utils.helpers import logger


class TicketService:
    """Serviço de gerenciamento de tickets GLPI - Integração Real."""
    
    def __init__(self):
        """Inicializa o serviço de tickets."""
        logger.info("TicketService initialized")
    
    async def list_tickets(self, **kwargs) -> List[Dict[str, Any]]:
        """Lista tickets com filtros."""
        criteria_idx = 0
        params = {
            "range": f"0-{kwargs.get('limit', 50)}",
            "sort": kwargs.get("sort", "date_mod"),
            "order": kwargs.get("order", "DESC")
        }

        # Adicionar filtros se fornecidos
        if "status" in kwargs:
            params[f"criteria[{criteria_idx}][field]"] = "12"
            params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
            params[f"criteria[{criteria_idx}][value]"] = kwargs["status"]
            criteria_idx += 1

        # Filtrar por entity_id (com busca recursiva em sub-entidades)
        entity_id = kwargs.get("entity_id")
        if entity_id:
            if criteria_idx > 0:
                params[f"criteria[{criteria_idx}][link]"] = "AND"
            params[f"criteria[{criteria_idx}][field]"] = "80"  # Entity field
            params[f"criteria[{criteria_idx}][searchtype]"] = "under"  # "under" busca na entidade E sub-entidades
            params[f"criteria[{criteria_idx}][value]"] = entity_id

        result = await glpi_client.get("/apirest.php/Ticket", params=params)
        return result.get("data", []) if isinstance(result, dict) else (result or [])
    
    async def get_ticket(self, ticket_id: int) -> Dict[str, Any]:
        """Obtém um ticket específico."""
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        result = await glpi_client.get(f"/apirest.php/Ticket/{ticket_id}")
        if not result or "id" not in result:
            raise NotFoundError("Ticket", ticket_id)
        return result
    
    async def get_ticket_by_number(self, ticket_number: str) -> Optional[Dict[str, Any]]:
        """Busca ticket por número/nome."""
        if not ticket_number or not ticket_number.strip():
            raise ValidationError("ticket_number is required", "ticket_number")
        params = {
            "criteria[0][field]": "1",  # name/number
            "criteria[0][searchtype]": "equals",
            "criteria[0][value]": ticket_number.strip(),
            "range": "0-0"
        }
        result = await glpi_client.get("/apirest.php/Ticket", params=params)
        if isinstance(result, dict) and result.get("data"):
            return result["data"][0]
        return None
    
    async def create_ticket(self, title: str, description: str, **kwargs) -> Dict[str, Any]:
        """Cria um novo ticket."""
        if not title or not description:
            raise ValidationError("title and description are required")
        
        data = {
            "name": title,
            "content": description,
            "entities_id": kwargs.get("entity_id", 0),
            "users_id_recipient": kwargs.get("requester_id", 0),
            "users_id_assign": kwargs.get("assignee_id", 0),
            "priority": kwargs.get("priority", 3),
            "urgency": kwargs.get("urgency", 3),
            "impact": kwargs.get("impact", 3),
            "itilcategories_id": kwargs.get("category_id", 0),
            "type": kwargs.get("type", 1)  # 1 = Incident, 2 = Request
        }
        
        result = await glpi_client.post("/apirest.php/Ticket", data=data)
        if not result or "id" not in result:
            raise GLPIError(500, "Failed to create ticket")
        return result
    
    async def update_ticket(self, ticket_id: int, **kwargs) -> Dict[str, Any]:
        """Atualiza um ticket existente."""
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        
        # Verificar se ticket existe
        ticket = await self.get_ticket(ticket_id)
        
        data = {}
        if "title" in kwargs:
            data["name"] = kwargs["title"]
        if "description" in kwargs:
            data["content"] = kwargs["description"]
        if "status" in kwargs:
            data["status"] = kwargs["status"]
        if "priority" in kwargs:
            data["priority"] = kwargs["priority"]
        if "urgency" in kwargs:
            data["urgency"] = kwargs["urgency"]
        if "assignee_id" in kwargs:
            data["users_id_assign"] = kwargs["assignee_id"]
        
        if not data:
            raise ValidationError("No valid fields to update")
        
        # GLPI API PUT retorna 200 OK com body vazio em sucesso
        await glpi_client.put(f"/apirest.php/Ticket/{ticket_id}", data=data)
        
        # Retornar ticket atualizado
        return await self.get_ticket(ticket_id)
    
    async def delete_ticket(self, ticket_id: int) -> bool:
        """Remove um ticket."""
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        
        # Verificar se ticket existe
        await self.get_ticket(ticket_id)
        
        await glpi_client.delete(f"/apirest.php/Ticket/{ticket_id}")
        return True
    
    async def assign_ticket(self, ticket_id: int, assignee_id: int) -> Dict[str, Any]:
        """Atribui um ticket a um usuário como técnico."""
        if ticket_id <= 0 or assignee_id <= 0:
            raise ValidationError("ticket_id and assignee_id must be positive")
        
        # No GLPI, técnicos são atribuídos via Ticket_User com type=2 (assigned)
        # Referência: https://github.com/glpi-project/glpi/blob/main/apirest.md#add-items
        ticket_user_data = {
            "tickets_id": ticket_id,
            "users_id": assignee_id,
            "type": 2,  # 2 = Técnico atribuído (assigned)
            "use_notification": 1
        }
        
        await glpi_client.post("/apirest.php/Ticket_User", data=ticket_user_data)
        
        # Retornar ticket atualizado
        return await self.get_ticket(ticket_id)
    
    async def close_ticket(self, ticket_id: int, resolution: str, **kwargs) -> Dict[str, Any]:
        """Fecha um ticket com resolução."""
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        if not resolution:
            raise ValidationError("resolution is required")
        
        data = {
            "status": 6,  # Closed
            "content": resolution,
            "solutiontypes_id": kwargs.get("solution_type", 5)
        }
        
        result = await glpi_client.put(f"/apirest.php/Ticket/{ticket_id}", data=data)
        # PUT pode retornar vazio (200 OK) ou {"success": True, "id": ...}
        if not result:
            return {"id": ticket_id, "closed": True, "status": 6}
        return result
    
    async def find_similar_tickets(self, ticket_id: int, **kwargs) -> List[Dict[str, Any]]:
        """
        Encontra tickets similares usando SimilarityService.
        Integração requerida pela SPEC (RF03 / AC06).
        """
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        
        reference = await self.get_ticket(ticket_id)
        
        # Buscar candidatos (limitados para performance)
        candidates = await self.list_tickets(limit=kwargs.get("max_items", 200))
        
        similar = await similarity_service.find_similar_tickets(
            target_ticket={
                "id": reference.get("id"),
                "title": reference.get("name", ""),
                "content": reference.get("content", "")
            },
            candidate_tickets=[
                {
                    "id": t.get("id"),
                    "title": t.get("name", ""),
                    "content": t.get("content", "")
                }
                for t in candidates if t.get("id") != ticket_id
            ],
            threshold=kwargs.get("threshold", 0.3),
            max_results=kwargs.get("max_results", 10)
        )
        
        return similar
    
    async def search_tickets(self, query: str, **kwargs) -> List[Dict[str, Any]]:
        """Busca tickets por texto."""
        if not query or len(query.strip()) < 2:
            raise ValidationError("Search query must be at least 2 characters")

        criteria_idx = 0
        params = {
            f"criteria[{criteria_idx}][field]": "1",  # Name field
            f"criteria[{criteria_idx}][searchtype]": "contains",
            f"criteria[{criteria_idx}][value]": query.strip(),
            "range": f"0-{kwargs.get('limit', 50)}"
        }

        # Adicionar filtro de entity se fornecido (com busca recursiva em sub-entidades)
        entity_id = kwargs.get("entity_id")
        if entity_id:
            criteria_idx += 1
            params[f"criteria[{criteria_idx}][link]"] = "AND"
            params[f"criteria[{criteria_idx}][field]"] = "80"  # Entity field
            params[f"criteria[{criteria_idx}][searchtype]"] = "under"  # "under" busca na entidade E sub-entidades
            params[f"criteria[{criteria_idx}][value]"] = entity_id

        result = await glpi_client.get("/apirest.php/Ticket", params=params)
        return result.get("data", []) if isinstance(result, dict) else (result or [])
    
    async def get_ticket_stats(self, **kwargs) -> Dict[str, Any]:
        """Obtém estatísticas de tickets."""
        params = {
            "is_deleted": 0,
            "range": "0-0"  # Apenas contagem
        }
        
        result = await glpi_client.get("/apirest.php/Ticket", params=params)
        total = result.get("totalcount", 0) if isinstance(result, dict) else 0
        
        return {
            "total_tickets": total,
            "open_tickets": 0,  # TODO: Implementar filtros por status
            "closed_tickets": 0,
            "entity_id": kwargs.get("entity_id", 0)
        }
    
    async def get_ticket_history(self, ticket_id: int) -> List[Dict[str, Any]]:
        """Obtém histórico de alterações de um ticket."""
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        
        result = await glpi_client.get(f"/apirest.php/Ticket/{ticket_id}/Log")
        return result if isinstance(result, list) else (result.get("data", []) if isinstance(result, dict) else [])
    
    async def add_ticket_followup(self, ticket_id: int, content: str, **kwargs) -> Dict[str, Any]:
        """Adiciona um acompanhamento a um ticket."""
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        if not content:
            raise ValidationError("content is required")
        
        # Verificar se ticket existe
        await self.get_ticket(ticket_id)
        
        data = {
            "items_id": ticket_id,
            "itemtype": "Ticket",
            "content": content,
            "is_private": kwargs.get("is_private", 0)
        }
        
        result = await glpi_client.post("/apirest.php/TicketFollowup", data=data)
        # POST pode retornar {"id": ...} ou array com ids
        if not result:
            raise GLPIError(500, "Failed to add followup")
        # Se result é lista com ids
        if isinstance(result, list) and len(result) > 0:
            return {"id": result[0], "ticket_id": ticket_id, "created": True}
        # Se result já tem id
        if isinstance(result, dict) and "id" in result:
            return result
        # Fallback
        return {"ticket_id": ticket_id, "created": True}

    async def post_private_note(self, ticket_id: int, text: str) -> Dict[str, Any]:
        """Cria uma nota privada (followup is_private=1)."""
        return await self.add_ticket_followup(ticket_id, text, is_private=1)

    async def get_ticket_followups(self, ticket_id: int) -> List[Dict[str, Any]]:
        """Lista followups de um ticket."""
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        result = await glpi_client.get_subitems("Ticket", ticket_id, "TicketFollowup")
        return result if isinstance(result, list) else (result.get("data", []) if isinstance(result, dict) else [])

    async def resolve_ticket(self, ticket_id: int, solution: str, **kwargs) -> Dict[str, Any]:
        """Marca ticket como resolvido (status 5) com solução."""
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        if not solution:
            raise ValidationError("solution is required", "solution")
        data = {
            "status": 5,  # solved
            "content": solution,
            "solutiontypes_id": kwargs.get("solution_type", 5)
        }
        result = await glpi_client.put(f"/apirest.php/Ticket/{ticket_id}", data=data)
        # PUT pode retornar vazio (200 OK) ou {"success": True, "id": ...}
        if not result:
            return {"id": ticket_id, "resolved": True, "status": 5}
        return result


# Instância global do serviço de tickets
ticket_service = TicketService()
