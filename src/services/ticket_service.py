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


# GLPI ticket status string -> internal integer code.
# Used for both list filters (Search API field 12) and update PUT payloads.
STATUS_MAP = {
    "new": 1,
    "assigned": 2,
    "planned": 3,
    "pending": 4,
    "solved": 5,
    "closed": 6,
}

# GLPI Search API field IDs for Ticket.
# Ref: https://glpi-developer-documentation.readthedocs.io (search options)
TICKET_FIELD = {
    "name": 1,
    "id": 2,
    "priority": 3,
    "status": 12,
    "type": 14,
    "date": 15,       # opening date
    "date_mod": 19,   # last update
    "entities_id": 80,
}

# Fields requested from the Search API so the normalized result keeps the
# same shape the formatters expect from the getAllItems endpoint.
TICKET_FORCEDISPLAY = [
    TICKET_FIELD["name"],
    TICKET_FIELD["id"],
    TICKET_FIELD["priority"],
    TICKET_FIELD["status"],
    TICKET_FIELD["type"],
    TICKET_FIELD["date"],
    TICKET_FIELD["date_mod"],
    TICKET_FIELD["entities_id"],
]


def _normalize_search_ticket(row: Dict[str, Any]) -> Dict[str, Any]:
    """Map a GLPI Search API ticket row (numeric field keys) to named keys.

    The Search API returns ``{"1": "...", "12": 2, ...}`` while the getAllItems
    endpoint returns ``{"name": "...", "status": 2, ...}``. Normalizing here lets
    the same formatters handle both code paths.
    """
    f = TICKET_FIELD
    normalized = {
        "id": row.get(str(f["id"])) or row.get("id"),
        "name": row.get(str(f["name"])) or row.get("name"),
        "status": row.get(str(f["status"])) if row.get(str(f["status"])) is not None else row.get("status"),
        "priority": row.get(str(f["priority"])) if row.get(str(f["priority"])) is not None else row.get("priority"),
        "type": row.get(str(f["type"])) if row.get(str(f["type"])) is not None else row.get("type"),
        "date": row.get(str(f["date"])) or row.get("date"),
        "date_mod": row.get(str(f["date_mod"])) or row.get("date_mod"),
        "entities_id": row.get(str(f["entities_id"])) if row.get(str(f["entities_id"])) is not None else row.get("entities_id"),
    }
    return {k: v for k, v in normalized.items() if v is not None}


class TicketService:
    """Serviço de gerenciamento de tickets GLPI - Integração Real."""

    def __init__(self):
        """Inicializa o serviço de tickets."""
        logger.info("TicketService initialized")

    async def list_tickets(self, **kwargs) -> List[Dict[str, Any]]:
        """Lista tickets com filtros.

        Quando há filtros (status/priority/entity/date), usa a Search API
        (/apirest.php/search/Ticket), que é o único endpoint que processa
        ``criteria[]``. Sem filtros, usa o endpoint getAllItems (mais leve),
        que já retorna campos nomeados.

        @MX:ANCHOR: list_tickets é a base de search_tickets e find_similar.
        @MX:REASON: O endpoint getAllItems IGNORA criteria[] — usar /search.
        """
        limit = max(int(kwargs.get("limit", 50)), 1)
        offset = max(int(kwargs.get("offset", 0)), 0)

        # Build advanced criteria for the Search API
        criteria: List[Dict[str, Any]] = []

        status = kwargs.get("status")
        if status:
            # Accept both string ("pending") and int code; Search API needs int.
            status_code = STATUS_MAP.get(status, status) if isinstance(status, str) else status
            criteria.append({"field": TICKET_FIELD["status"], "searchtype": "equals", "value": status_code})

        priority = kwargs.get("priority")
        if priority:
            criteria.append({"field": TICKET_FIELD["priority"], "searchtype": "equals", "value": priority})

        entity_id = kwargs.get("entity_id")
        if entity_id is not None:
            criteria.append({"field": TICKET_FIELD["entities_id"], "searchtype": "under", "value": entity_id})

        date_after = kwargs.get("date_created_after")
        if date_after:
            criteria.append({"field": TICKET_FIELD["date"], "searchtype": "morethan", "value": date_after})
        date_before = kwargs.get("date_created_before")
        if date_before:
            criteria.append({"field": TICKET_FIELD["date"], "searchtype": "lessthan", "value": date_before})

        if criteria:
            result = await glpi_client.search(
                item_type="Ticket",
                criteria=criteria,
                forcedisplay=TICKET_FORCEDISPLAY,
                range_limit=limit,
                range_offset=offset,
                is_recursive=entity_id is not None,
            )
            rows = result.get("data", []) if isinstance(result, dict) else (result or [])
            return [_normalize_search_ticket(r) for r in rows]

        # No filters: lighter getAllItems endpoint (already named fields).
        params = {
            "range": f"{offset}-{offset + limit - 1}",
            "sort": kwargs.get("sort", "date_mod"),
            "order": kwargs.get("order", "DESC"),
        }
        result = await glpi_client.get(
            "/apirest.php/Ticket", params=params, use_cache=kwargs.get("use_cache", True)
        )
        return result.get("data", []) if isinstance(result, dict) else (result or [])
    
    async def get_ticket(self, ticket_id: int) -> Dict[str, Any]:
        """Obtém um ticket específico.

        @MX:NOTE: use_cache=False — detalhe de ticket precisa refletir escritas
        recentes (update/resolve/assign). Com cache, retornava estado obsoleto.
        """
        if ticket_id <= 0:
            raise ValidationError("ticket_id must be positive", "ticket_id")
        result = await glpi_client.get(
            f"/apirest.php/Ticket/{ticket_id}", use_cache=False
        )
        if not result or "id" not in result:
            raise NotFoundError("Ticket", ticket_id)
        return result
    
    async def get_ticket_by_number(self, ticket_number: str) -> Optional[Dict[str, Any]]:
        """Busca ticket por número público.

        In stock GLPI, the ticket "number" is the same as the numeric id.
        Some installs use a custom number (e.g. formatnumber plugin), which
        is typically stored in the ticket name/title. Strategy:
        1. If ticket_number is numeric, try direct id lookup.
        2. Fall back to a /search/Ticket on field 1 (name) contains match.
        """
        if not ticket_number or not ticket_number.strip():
            raise ValidationError("ticket_number is required", "ticket_number")

        number = ticket_number.strip()

        # Strategy 1: numeric → direct /Ticket/{id}
        if number.isdigit():
            try:
                ticket = await glpi_client.get(f"/apirest.php/Ticket/{int(number)}")
                if ticket and ticket.get("id"):
                    return ticket
            except NotFoundError:
                pass
            except GLPIError as e:
                if getattr(e, "code", 0) not in (404,):
                    logger.warning(f"get_ticket_by_number direct id lookup failed: {e}")

        # Strategy 2: /search/Ticket on title (field 1)
        params = {
            "criteria[0][field]": "1",
            "criteria[0][searchtype]": "contains",
            "criteria[0][value]": number,
            "range": "0-0",
        }
        result = await glpi_client.get("/apirest.php/search/Ticket", params=params)
        if isinstance(result, dict) and result.get("data"):
            hit = result["data"][0]
            if hit.get("2") or hit.get("id"):
                # Re-fetch full ticket for consistent shape
                return await self.get_ticket(int(hit.get("2") or hit.get("id")))
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
            # GLPI stores status as int. Accept the string enum from the schema
            # ("pending") and map to the code (4). Passing the raw string causes
            # a MySQL "Incorrect integer value" error.
            raw_status = kwargs["status"]
            data["status"] = STATUS_MAP.get(raw_status, raw_status) if isinstance(raw_status, str) else raw_status
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
        
        try:
            await glpi_client.post("/apirest.php/Ticket_User", data=ticket_user_data)
        except GLPIError as e:
            # GLPI rejeita vinculo Ticket_User duplicado com ERROR_GLPI_ADD e detalhe
            # vazio. Traduz para mensagem acionavel em vez de repassar o codigo cru.
            if "ERROR_GLPI_ADD" in str(e):
                raise GLPIError(
                    409,
                    f"Nao foi possivel atribuir o tecnico {assignee_id} ao ticket {ticket_id}: "
                    f"o tecnico ja esta atribuido a este chamado ou o ID de usuario e invalido. "
                    f"Use glpi_search_admin_resources(resource='users') para obter IDs de tecnicos validos."
                ) from e
            raise

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

        # Index candidates by id so we can re-attach displayable fields
        # (name/status/date) to the similarity scores afterwards.
        cand_by_id = {t.get("id"): t for t in candidates if t.get("id") != ticket_id}

        scored = await similarity_service.find_similar_tickets(
            target_ticket={
                "id": reference.get("id"),
                "title": reference.get("name", ""),
                "content": reference.get("content", ""),
            },
            candidate_tickets=[
                {"id": cid, "title": t.get("name", ""), "content": t.get("content", "")}
                for cid, t in cand_by_id.items()
            ],
            threshold=kwargs.get("threshold", 0.3),
            max_results=kwargs.get("max_results", 10),
        )

        # Map similarity results back to ticket-shaped dicts the formatter
        # understands (id/name/status/date/score). The raw scorer only returns
        # {id1, id2, combined, ...}.
        results: List[Dict[str, Any]] = []
        for s in scored:
            cid = s.get("id2")
            cand = cand_by_id.get(cid, {})
            results.append({
                "id": cid,
                "name": cand.get("name", ""),
                "status": cand.get("status"),
                "date": cand.get("date"),
                "score": round(float(s.get("combined", 0.0)), 3),
            })
        return results
    
    async def search_tickets(self, query: str, **kwargs) -> List[Dict[str, Any]]:
        """Busca textual de tickets (título + conteúdo) via Search API.

        Usa /apirest.php/search/Ticket, que processa ``criteria[]``. O endpoint
        getAllItems NÃO suporta busca textual, por isso o filtro era ignorado.
        """
        if not query or len(query.strip()) < 2:
            raise ValidationError("Search query must be at least 2 characters")

        limit = max(int(kwargs.get("limit", 50)), 1)
        offset = max(int(kwargs.get("offset", 0)), 0)

        # Field 1 = title (name). searchtype "contains" também varre o conteúdo
        # indexado pelo GLPI para o ticket.
        criteria: List[Dict[str, Any]] = [
            {"field": TICKET_FIELD["name"], "searchtype": "contains", "value": query.strip()},
        ]

        entity_id = kwargs.get("entity_id")
        if entity_id is not None:
            criteria.append({"field": TICKET_FIELD["entities_id"], "searchtype": "under", "value": entity_id})

        result = await glpi_client.search(
            item_type="Ticket",
            criteria=criteria,
            forcedisplay=TICKET_FORCEDISPLAY,
            range_limit=limit,
            range_offset=offset,
            is_recursive=entity_id is not None,
        )
        rows = result.get("data", []) if isinstance(result, dict) else (result or [])
        return [_normalize_search_ticket(r) for r in rows]
    
    async def get_ticket_stats(self, **kwargs) -> Dict[str, Any]:
        """Obtém estatísticas de tickets agregadas por status.

        GLPI ticket status codes:
            1 = new, 2 = assigned, 3 = planned, 4 = pending,
            5 = solved, 6 = closed
        Uses /search/Ticket with range=0-0 to fetch only totalcount per status.
        """
        entity_id = kwargs.get("entity_id")
        date_from = kwargs.get("date_from")
        date_to = kwargs.get("date_to")

        async def _count(extra_criteria: Optional[List[Dict[str, Any]]] = None) -> int:
            params: Dict[str, Any] = {"range": "0-0"}
            idx = 0
            criteria = list(extra_criteria or [])
            if entity_id is not None:
                criteria.append(
                    {"field": 80, "searchtype": "under", "value": entity_id}
                )
            if date_from:
                criteria.append(
                    {"field": 15, "searchtype": "morethan", "value": date_from}
                )
            if date_to:
                criteria.append(
                    {"field": 15, "searchtype": "lessthan", "value": date_to}
                )
            for c in criteria:
                if idx > 0:
                    params[f"criteria[{idx}][link]"] = "AND"
                params[f"criteria[{idx}][field]"] = c["field"]
                params[f"criteria[{idx}][searchtype]"] = c["searchtype"]
                params[f"criteria[{idx}][value]"] = c["value"]
                idx += 1
            # @MX:NOTE: Propaga erro em vez de retornar 0 silenciosamente.
            # @MX:REASON: Bug #2 — zeros silenciosos enganavam o LLM quando auth/API falhava.
            result = await glpi_client.get(
                "/apirest.php/search/Ticket", params=params, use_cache=False
            )
            if isinstance(result, dict):
                return int(result.get("totalcount", 0) or 0)
            return 0

        # Status 12 is the GLPI search field id for "status"
        status_map = {
            "new": 1,
            "assigned": 2,
            "planned": 3,
            "pending": 4,
            "solved": 5,
            "closed": 6,
        }

        total = await _count()
        by_status = {}
        for label, code in status_map.items():
            by_status[label] = await _count(
                [{"field": 12, "searchtype": "equals", "value": code}]
            )

        open_tickets = by_status["new"] + by_status["assigned"] + by_status["planned"] + by_status["pending"]
        closed_tickets = by_status["solved"] + by_status["closed"]

        return {
            "total_tickets": total,
            "open_tickets": open_tickets,
            "closed_tickets": closed_tickets,
            "by_status": by_status,
            "entity_id": entity_id if entity_id is not None else "all",
            "date_from": date_from,
            "date_to": date_to,
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
