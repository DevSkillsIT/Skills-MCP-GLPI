"""
MCP Tools - Tickets (12 tools)
Conforme SPEC.md seção 4.2 - Matriz de Tools MCP
Wrappers para ticket_service com validação e tratamento de erros
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

from src.services.ticket_service import ticket_service
from src.models.exceptions import (
    NotFoundError,
    ValidationError,
    GLPIError,
    SimilarityError
)
from src.utils.helpers import (
    logger,
    response_truncator,
    input_sanitizer,
    PaginationHelper,
    DateTimeHelper,
    entity_resolver
)
from src.utils.safety_guard import require_safety_confirmation


class TicketTools:
    """
    Collection de 12 tools MCP para gerenciamento de tickets.
    Implementadas conforme matriz SPEC.md seção 4.2
    """
    
    async def get_ticket_by_id(self, ticket_id: int) -> Dict[str, Any]:
        """Alias SPEC: get_ticket_by_id."""
        return await self.get_ticket(ticket_id)

    async def search_similar_tickets(self, ticket_id: int, **kwargs) -> Dict[str, Any]:
        """Alias SPEC: search_similar_tickets -> find_similar_tickets."""
        return await self.find_similar_tickets(ticket_id, **kwargs)
    
    async def list_tickets(
        self,
        status: Optional[str] = None,
        priority: Optional[int] = None,
        entity_id: Optional[int] = None,
        entity_name: Optional[str] = None,
        requester_id: Optional[int] = None,
        assignee_id: Optional[int] = None,
        date_created_after: Optional[str] = None,
        date_created_before: Optional[str] = None,
        limit: int = 250,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Tool MCP: list_tickets
        Lista todos os tickets com filtros opcionais (status, limite)

        Args:
            status: Filtrar por status (new, assigned, planned, pending, solved, closed)
            priority: Filtrar por prioridade (1-5)
            entity_id: Filtrar por entidade (ID numérico)
            entity_name: Filtrar por nome da entidade/cliente (ex: "GSM Transportes", "Skills IT")
            requester_id: Filtrar por solicitante
            assignee_id: Filtrar por responsável
            date_created_after: Data de criação a partir de (YYYY-MM-DD)
            date_created_before: Data de criação até (YYYY-MM-DD)
            limit: Número máximo de resultados (padrão: 50)
            offset: Deslocamento para paginação (padrão: 0)

        Returns:
            Lista de tickets com metadados de paginação

        Note:
            Se entity_name for fornecido, será resolvido para entity_id automaticamente.
            Exemplo: list_tickets(entity_name="GSM") retorna tickets do cliente GSM.
        """
        try:
            logger.info(f"MCP Tool: list_tickets with filters status={status}, entity_name={entity_name}, limit={limit}")

            # Resolver entity_name para entity_id se fornecido
            if entity_name:
                resolved_id = await entity_resolver.resolve_entity_name(entity_name)
                if resolved_id:
                    entity_id = resolved_id
                    logger.info(f"list_tickets: entity_name '{entity_name}' resolvido para ID {entity_id}")
                else:
                    available = await entity_resolver.list_available_entities()
                    raise ValidationError(
                        f"Entidade '{entity_name}' não encontrada. Entidades disponíveis: {[e['name'] for e in available[:10]]}",
                        "entity_name"
                    )

            # Validar e sanitizar inputs
            if status:
                status = input_sanitizer.sanitize_string(status)
                valid_statuses = ["new", "assigned", "planned", "pending", "solved", "closed"]
                if status not in valid_statuses:
                    raise ValidationError(f"Status must be one of: {valid_statuses}", "status")
            
            if priority is not None:
                if not isinstance(priority, int) or priority < 1 or priority > 5:
                    raise ValidationError("Priority must be integer between 1 and 5", "priority")
            
            # Validar datas
            if date_created_after or date_created_before:
                date_created_after, date_created_before = DateTimeHelper.parse_date_range(
                    date_created_after, date_created_before
                )
            
            # Validar paginação
            offset, limit = PaginationHelper.validate_pagination_params(offset, limit)
            
            # Buscar tickets
            tickets = await ticket_service.list_tickets(
                status=status,
                priority=priority,
                entity_id=entity_id,
                requester_id=requester_id,
                assignee_id=assignee_id,
                date_created_after=date_created_after,
                date_created_before=date_created_before,
                limit=limit,
                offset=offset,
                use_cache=True
            )
            
            # Truncar resposta se necessário (RNF01)
            if isinstance(tickets, dict) and "tickets" in tickets:
                # Resposta com paginação
                tickets["tickets"] = response_truncator.truncate_json_response(tickets["tickets"])
            else:
                # Resposta simples
                tickets = response_truncator.truncate_json_response(tickets)
            
            logger.info(f"list_tickets completed: {len(tickets) if isinstance(tickets, list) else 'paginated'} tickets")
            return tickets
            
        except (ValidationError, GLPIError) as e:
            logger.error(f"list_tickets validation error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"list_tickets unexpected error: {e}")
            raise GLPIError(500, f"Failed to list tickets: {str(e)}")
    
    async def get_ticket(self, ticket_id: int) -> Dict[str, Any]:
        """
        Tool MCP: get_ticket
        Obtém detalhes completos de um ticket específico
        
        Args:
            ticket_id: ID do ticket
        
        Returns:
            Dados completos do ticket
        """
        try:
            logger.info(f"MCP Tool: get_ticket {ticket_id}")
            
            if not isinstance(ticket_id, int) or ticket_id <= 0:
                raise ValidationError("Ticket ID must be a positive integer", "ticket_id")
            
            ticket = await ticket_service.get_ticket(ticket_id)
            
            # Truncar resposta se necessário
            ticket = response_truncator.truncate_json_response(ticket)
            
            logger.info(f"get_ticket completed: ticket {ticket_id}")
            return ticket
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"get_ticket error: {e.message}")
            raise
        except (GLPIError, NotFoundError, ValidationError, SimilarityError) as e:
            logger.error(f"get_ticket service error: {e.message}")
            raise  # Preserve original error code
        except Exception as e:
            logger.error(f"get_ticket unexpected error: {e}")
            raise GLPIError(500, f"Failed to get ticket: {str(e)}")
    
    async def get_ticket_by_number(self, ticket_number: str) -> Dict[str, Any]:
        """Tool MCP: get_ticket_by_number."""
        try:
            logger.info(f"MCP Tool: get_ticket_by_number {ticket_number}")
            if not ticket_number or not ticket_number.strip():
                raise ValidationError("ticket_number is required", "ticket_number")
            ticket = await ticket_service.get_ticket_by_number(ticket_number)
            return ticket or {}
        except (ValidationError, GLPIError) as e:
            logger.error(f"get_ticket_by_number error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"get_ticket_by_number unexpected error: {e}")
            raise GLPIError(500, f"Failed to get ticket by number: {str(e)}")
    
    async def create_ticket(
        self,
        title: str,
        description: str,
        priority: int = 3,
        urgency: Optional[int] = None,
        type: str = "incident",
        category_id: Optional[int] = None,
        entity_id: Optional[int] = None,
        entity_name: Optional[str] = None,
        requester_id: Optional[int] = None,
        assignee_id: Optional[int] = None,
        location_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Tool MCP: create_ticket
        Cria um novo ticket

        Args:
            title: Título do ticket (mínimo 3 caracteres)
            description: Descrição detalhada do problema
            priority: Prioridade 1-5 (padrão: 3)
            urgency: Urgência 1-5 (opcional)
            type: Tipo (incident, request, change)
            category_id: ID da categoria
            entity_id: ID da entidade (numérico)
            entity_name: Nome da entidade/cliente (ex: "GSM Transportes", "Skills IT")
            requester_id: ID do solicitante
            assignee_id: ID do responsável
            location_id: ID da localização

        Returns:
            Ticket criado

        Note:
            Se entity_name for fornecido, será resolvido para entity_id automaticamente.
            Exemplo: create_ticket(title="...", entity_name="GSM") cria o ticket no cliente GSM.
        """
        try:
            logger.info(f"MCP Tool: create_ticket - {title}")

            # Resolver entity_name para entity_id se fornecido
            if entity_name:
                resolved_id = await entity_resolver.resolve_entity_name(entity_name)
                if resolved_id:
                    entity_id = resolved_id
                    logger.info(f"create_ticket: entity_name '{entity_name}' resolvido para ID {entity_id}")
                else:
                    available = await entity_resolver.list_available_entities()
                    raise ValidationError(
                        f"Entidade '{entity_name}' não encontrada. Entidades disponíveis: {[e['name'] for e in available[:10]]}",
                        "entity_name"
                    )
            
            # Sanitizar inputs
            title = input_sanitizer.sanitize_string(title)
            description = input_sanitizer.sanitize_string(description)
            
            # Converter tipo string para inteiro (GLPI usa 1=Incident, 2=Request)
            type_map = {"incident": 1, "request": 2, "change": 3}
            type_int = type_map.get(type.lower(), 1) if isinstance(type, str) else type
            
            # Criar ticket
            ticket = await ticket_service.create_ticket(
                title=title,
                description=description,
                priority=priority,
                urgency=urgency,
                type=type_int,
                category_id=category_id,
                entity_id=entity_id,
                requester_id=requester_id,
                assignee_id=assignee_id,
                location_id=location_id
            )
            
            # Truncar resposta se necessário
            ticket = response_truncator.truncate_json_response(ticket)
            
            logger.info(f"create_ticket completed: ticket {ticket.get('id')}")
            return ticket
            
        except ValidationError as e:
            logger.error(f"create_ticket validation error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"create_ticket unexpected error: {e}")
            raise GLPIError(500, f"Failed to create ticket: {str(e)}")
    
    async def update_ticket(
        self,
        ticket_id: int,
        title: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        priority: Optional[int] = None,
        urgency: Optional[int] = None,
        category_id: Optional[int] = None,
        assignee_id: Optional[int] = None,
        solution: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Tool MCP: update_ticket
        Atualiza um ticket existente
        
        Args:
            ticket_id: ID do ticket
            title: Novo título
            description: Nova descrição
            status: Novo status
            priority: Nova prioridade
            urgency: Nova urgência
            category_id: Nova categoria
            assignee_id: Novo responsável
            solution: Solução (para fechamento)
        
        Returns:
            Ticket atualizado
        """
        try:
            logger.info(f"MCP Tool: update_ticket {ticket_id}")
            
            # Sanitizar inputs
            update_data = {}
            if title:
                update_data["title"] = input_sanitizer.sanitize_string(title)
            if description:
                update_data["description"] = input_sanitizer.sanitize_string(description)
            if solution:
                update_data["solution"] = input_sanitizer.sanitize_string(solution)
            
            # Adicionar outros campos
            if status:
                update_data["status"] = status
            if priority:
                update_data["priority"] = priority
            if urgency:
                update_data["urgency"] = urgency
            if category_id:
                update_data["category_id"] = category_id
            if assignee_id:
                update_data["assignee_id"] = assignee_id
            
            # Atualizar ticket
            ticket = await ticket_service.update_ticket(ticket_id, **update_data)
            
            # Truncar resposta se necessário
            ticket = response_truncator.truncate_json_response(ticket)
            
            logger.info(f"update_ticket completed: ticket {ticket_id}")
            return ticket
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"update_ticket error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"update_ticket unexpected error: {e}")
            raise GLPIError(500, f"Failed to update ticket: {str(e)}")
    
    async def delete_ticket(
        self,
        ticket_id: int,
        confirmationToken: Optional[str] = None,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Tool MCP: delete_ticket
        Deleta um ticket permanentemente
        
        ATENÇÃO: Operação destrutiva! Quando MCP_SAFETY_GUARD=true:
        - Requer confirmationToken válido (igual ao MCP_SAFETY_TOKEN)
        - Requer reason com pelo menos 10 caracteres
        
        Args:
            ticket_id: ID do ticket
            confirmationToken: Token de confirmação (quando safety guard ativado)
            reason: Motivo da deleção (quando safety guard ativado, mín. 10 chars)
        
        Returns:
            Confirmação da deleção
        """
        try:
            logger.info(f"MCP Tool: delete_ticket {ticket_id}")
            
            if not isinstance(ticket_id, int) or ticket_id <= 0:
                raise ValidationError("Ticket ID must be a positive integer", "ticket_id")
            
            # Verificar safety guard
            require_safety_confirmation(
                "delete_ticket",
                confirmation_token=confirmationToken,
                reason=reason,
                target_id=ticket_id,
                target_type="Ticket"
            )
            
            success = await ticket_service.delete_ticket(ticket_id)
            
            result = {
                "success": success,
                "ticket_id": ticket_id,
                "message": f"Ticket {ticket_id} deleted successfully"
            }
            
            logger.info(f"delete_ticket completed: ticket {ticket_id}")
            return result
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"delete_ticket error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"delete_ticket unexpected error: {e}")
            raise GLPIError(500, f"Failed to delete ticket: {str(e)}")
    
    async def assign_ticket(self, ticket_id: int, user_id: int) -> Dict[str, Any]:
        """
        Tool MCP: assign_ticket
        Atribui um ticket a um usuário
        
        Args:
            ticket_id: ID do ticket
            user_id: ID do usuário
        
        Returns:
            Ticket atualizado
        """
        try:
            logger.info(f"MCP Tool: assign_ticket {ticket_id} to user {user_id}")
            
            if not isinstance(ticket_id, int) or ticket_id <= 0:
                raise ValidationError("Ticket ID must be a positive integer", "ticket_id")
            
            if not isinstance(user_id, int) or user_id <= 0:
                raise ValidationError("User ID must be a positive integer", "user_id")
            
            ticket = await ticket_service.assign_ticket(ticket_id, user_id)
            
            # Truncar resposta se necessário
            ticket = response_truncator.truncate_json_response(ticket)
            
            logger.info(f"assign_ticket completed: ticket {ticket_id} assigned to user {user_id}")
            return ticket
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"assign_ticket error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"assign_ticket unexpected error: {e}")
            raise GLPIError(500, f"Failed to assign ticket: {str(e)}")
    
    async def close_ticket(
        self,
        ticket_id: int,
        resolution: str = "",
        solution_type: int = 5
    ) -> Dict[str, Any]:
        """
        Tool MCP: close_ticket
        Fecha um ticket com resolução
        
        Args:
            ticket_id: ID do ticket
            resolution: Texto da resolução
            solution_type: Tipo de solução (default: 5 = manual)
        
        Returns:
            Ticket fechado
        """
        try:
            logger.info(f"MCP Tool: close_ticket {ticket_id}")
            
            if not isinstance(ticket_id, int) or ticket_id <= 0:
                raise ValidationError("Ticket ID must be a positive integer", "ticket_id")
            
            # Sanitizar resolução
            resolution = input_sanitizer.sanitize_string(resolution)
            
            ticket = await ticket_service.close_ticket(ticket_id, resolution, solution_type=solution_type)
            
            # Truncar resposta se necessário
            ticket = response_truncator.truncate_json_response(ticket)
            
            logger.info(f"close_ticket completed: ticket {ticket_id}")
            return ticket
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"close_ticket error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"close_ticket unexpected error: {e}")
            raise GLPIError(500, f"Failed to close ticket: {str(e)}")
    
    async def find_similar_tickets(
        self,
        ticket_id: int,
        threshold: float = 0.3,
        max_results: int = 10
    ) -> Dict[str, Any]:
        """
        Tool MCP: find_similar_tickets
        Encontra tickets similares usando algoritmos de similaridade
        
        Args:
            ticket_id: ID do ticket de referência
            threshold: Limiar mínimo de similaridade (0.0-1.0)
            max_results: Número máximo de resultados
        
        Returns:
            Lista de tickets similares com scores
        """
        try:
            logger.info(f"MCP Tool: find_similar_tickets for {ticket_id}")
            
            if not isinstance(ticket_id, int) or ticket_id <= 0:
                raise ValidationError("Ticket ID must be a positive integer", "ticket_id")
            
            if not isinstance(threshold, (int, float)) or threshold < 0 or threshold > 1:
                raise ValidationError("Threshold must be number between 0.0 and 1.0", "threshold")
            
            if not isinstance(max_results, int) or max_results <= 0 or max_results > 50:
                raise ValidationError("Max results must be integer between 1 and 50", "max_results")
            
            similar_tickets = await ticket_service.find_similar_tickets(
                ticket_id=ticket_id,
                threshold=threshold,
                max_results=max_results
            )
            
            # Truncar resposta se necessário
            similar_tickets = response_truncator.truncate_json_response(similar_tickets)
            
            logger.info(f"find_similar_tickets completed: {len(similar_tickets)} similar tickets")
            return {
                "ticket_id": ticket_id,
                "threshold": threshold,
                "similar_tickets": similar_tickets,
                "count": len(similar_tickets)
            }
            
        except (NotFoundError, ValidationError, SimilarityError) as e:
            logger.error(f"find_similar_tickets error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"find_similar_tickets unexpected error: {e}")
            raise GLPIError(500, f"Failed to find similar tickets: {str(e)}")
    
    async def search_tickets(
        self,
        query: str,
        entity_id: Optional[int] = None,
        entity_name: Optional[str] = None,
        fields: Optional[List[str]] = None,
        limit: int = 250,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Tool MCP: search_tickets
        Busca tickets por texto livre

        Args:
            query: Texto para buscar
            entity_id: Filtrar por entidade (ID numérico)
            entity_name: Filtrar por nome da entidade/cliente (ex: "GSM Transportes", "Skills IT")
            fields: Campos específicos para retornar
            limit: Limite de resultados
            offset: Offset para paginação

        Returns:
            Tickets que correspondem à busca

        Note:
            Se entity_name for fornecido, será resolvido para entity_id automaticamente.
            Exemplo: search_tickets(query="impressora", entity_name="GSM") busca tickets do cliente GSM.
        """
        try:
            logger.info(f"MCP Tool: search_tickets - {query}, entity_name={entity_name}")

            # Resolver entity_name para entity_id se fornecido
            if entity_name:
                resolved_id = await entity_resolver.resolve_entity_name(entity_name)
                if resolved_id:
                    entity_id = resolved_id
                    logger.info(f"search_tickets: entity_name '{entity_name}' resolvido para ID {entity_id}")
                else:
                    available = await entity_resolver.list_available_entities()
                    raise ValidationError(
                        f"Entidade '{entity_name}' não encontrada. Entidades disponíveis: {[e['name'] for e in available[:10]]}",
                        "entity_name"
                    )

            # Sanitizar query
            query = input_sanitizer.sanitize_search_query(query)

            if not query or len(query) < 2:
                raise ValidationError("Search query must be at least 2 characters", "query")

            # Validar paginação
            offset, limit = PaginationHelper.validate_pagination_params(offset, limit)

            tickets = await ticket_service.search_tickets(
                query=query,
                entity_id=entity_id,
                fields=fields,
                limit=limit,
                offset=offset
            )
            
            # Truncar resposta se necessário
            tickets = response_truncator.truncate_json_response(tickets)
            
            logger.info(f"search_tickets completed: {len(tickets) if isinstance(tickets, list) else 'paginated'} tickets")
            return tickets
            
        except ValidationError as e:
            logger.error(f"search_tickets validation error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"search_tickets unexpected error: {e}")
            raise GLPIError(500, f"Failed to search tickets: {str(e)}")
    
    async def get_ticket_stats(
        self,
        entity_id: Optional[int] = None,
        entity_name: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Tool MCP: get_ticket_stats
        Obtém estatísticas de tickets

        Args:
            entity_id: Filtrar por entidade (ID numérico)
            entity_name: Filtrar por nome da entidade/cliente (ex: "GSM Transportes", "Skills IT")
            date_from: Data inicial (YYYY-MM-DD)
            date_to: Data final (YYYY-MM-DD)

        Returns:
            Estatísticas detalhadas

        Note:
            Se entity_name for fornecido, será resolvido para entity_id automaticamente.
            Exemplo: get_ticket_stats(entity_name="GSM") retorna estatísticas do cliente GSM.
        """
        try:
            logger.info(f"MCP Tool: get_ticket_stats, entity_name={entity_name}")

            # Resolver entity_name para entity_id se fornecido
            if entity_name:
                resolved_id = await entity_resolver.resolve_entity_name(entity_name)
                if resolved_id:
                    entity_id = resolved_id
                    logger.info(f"get_ticket_stats: entity_name '{entity_name}' resolvido para ID {entity_id}")
                else:
                    available = await entity_resolver.list_available_entities()
                    raise ValidationError(
                        f"Entidade '{entity_name}' não encontrada. Entidades disponíveis: {[e['name'] for e in available[:10]]}",
                        "entity_name"
                    )

            # Validar datas
            if date_from or date_to:
                date_from, date_to = DateTimeHelper.parse_date_range(date_from, date_to)

            stats = await ticket_service.get_ticket_stats(
                entity_id=entity_id,
                date_from=date_from,
                date_to=date_to
            )
            
            logger.info(f"get_ticket_stats completed: {stats['total_tickets']} tickets analyzed")
            return stats
            
        except ValidationError as e:
            logger.error(f"get_ticket_stats validation error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"get_ticket_stats unexpected error: {e}")
            raise GLPIError(500, f"Failed to get ticket stats: {str(e)}")
    
    async def get_ticket_history(self, ticket_id: int) -> Dict[str, Any]:
        """
        Tool MCP: get_ticket_history
        Obtém histórico de alterações de um ticket
        
        Args:
            ticket_id: ID do ticket
        
        Returns:
            Histórico de alterações
        """
        try:
            logger.info(f"MCP Tool: get_ticket_history {ticket_id}")
            
            if not isinstance(ticket_id, int) or ticket_id <= 0:
                raise ValidationError("Ticket ID must be a positive integer", "ticket_id")
            
            # Obter ticket completo (já inclui history)
            ticket = await ticket_service.get_ticket(ticket_id)
            
            history = ticket.get("history", [])
            
            # Truncar resposta se necessário
            history = response_truncator.truncate_json_response(history)
            
            logger.info(f"get_ticket_history completed: {len(history)} history entries")
            return {
                "ticket_id": ticket_id,
                "history": history,
                "count": len(history)
            }
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"get_ticket_history error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"get_ticket_history unexpected error: {e}")
            raise GLPIError(500, f"Failed to get ticket history: {str(e)}")
    
    async def add_ticket_followup(
        self,
        ticket_id: int,
        content: str,
        is_private: bool = False
    ) -> Dict[str, Any]:
        """
        Tool MCP: add_ticket_followup
        Adiciona acompanhamento a um ticket
        
        Args:
            ticket_id: ID do ticket
            content: Conteúdo do acompanhamento
            is_private: Se é privado
        
        Returns:
            Acompanhamento adicionado
        """
        try:
            logger.info(f"MCP Tool: add_ticket_followup {ticket_id}")
            
            if not isinstance(ticket_id, int) or ticket_id <= 0:
                raise ValidationError("Ticket ID must be a positive integer", "ticket_id")
            
            # Sanitizar conteúdo
            content = input_sanitizer.sanitize_string(content)
            
            if not content or len(content) < 5:
                raise ValidationError("Content must be at least 5 characters", "content")
            
            result = await ticket_service.add_ticket_followup(
                ticket_id=ticket_id,
                content=content,
                is_private=is_private
            )
            result = response_truncator.truncate_json_response(result)
            
            logger.info(f"add_ticket_followup completed: ticket {ticket_id}")
            return result
            
        except ValidationError as e:
            logger.error(f"add_ticket_followup validation error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"add_ticket_followup unexpected error: {e}")
            raise GLPIError(500, f"Failed to add followup: {str(e)}")

    async def post_private_note(self, ticket_id: int, text: str) -> Dict[str, Any]:
        """Tool MCP: post_private_note (nota privada)."""
        try:
            logger.info(f"MCP Tool: post_private_note {ticket_id}")
            result = await ticket_service.post_private_note(ticket_id, text)
            return response_truncator.truncate_json_response(result)
        except (ValidationError, GLPIError) as e:
            logger.error(f"post_private_note error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"post_private_note unexpected error: {e}")
            raise GLPIError(500, f"Failed to post private note: {str(e)}")

    async def get_ticket_followups(self, ticket_id: int) -> Dict[str, Any]:
        """Tool MCP: get_ticket_followups."""
        try:
            logger.info(f"MCP Tool: get_ticket_followups {ticket_id}")
            followups = await ticket_service.get_ticket_followups(ticket_id)
            return response_truncator.truncate_json_response(followups)
        except (ValidationError, GLPIError) as e:
            logger.error(f"get_ticket_followups error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"get_ticket_followups unexpected error: {e}")
            raise GLPIError(500, f"Failed to get ticket followups: {str(e)}")

    async def resolve_ticket(self, ticket_id: int, solution: str, **kwargs) -> Dict[str, Any]:
        """Tool MCP: resolve_ticket."""
        try:
            logger.info(f"MCP Tool: resolve_ticket {ticket_id}")
            result = await ticket_service.resolve_ticket(ticket_id, solution, **kwargs)
            return response_truncator.truncate_json_response(result)
        except (ValidationError, GLPIError) as e:
            logger.error(f"resolve_ticket error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"resolve_ticket unexpected error: {e}")
            raise GLPIError(500, f"Failed to resolve ticket: {str(e)}")


# Instância global das tools de tickets
ticket_tools = TicketTools()
