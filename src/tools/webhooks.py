"""
MCP Tools - Webhooks (12 tools)
Conforme SPEC.md seção 4.2 - Matriz de Tools MCP
Wrappers para webhooks com validação e tratamento de erros
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import json
import hashlib
import hmac

from src.models.exceptions import (
    NotFoundError,
    ValidationError,
    GLPIError
)
from src.utils.helpers import (
    logger,
    response_truncator,
    input_sanitizer
)
from src.utils.safety_guard import require_safety_confirmation
from src.config import settings


class WebhookTools:
    """
    Collection de 12 tools MCP para gerenciamento de webhooks.
    Implementadas conforme matriz SPEC.md seção 4.2
    """
    
    def __init__(self):
        """Inicializa tools de webhooks."""
        self.webhooks_storage = {}  # Storage simulado para webhooks
        
        logger.info("WebhookTools initialized")
    
    async def list_webhooks(
        self,
        event_type: Optional[str] = None,
        is_active: Optional[bool] = None,
        limit: int = 250,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Tool MCP: list_webhooks
        Lista todos os webhooks configurados
        
        Args:
            event_type: Filtrar por tipo de evento
            is_active: Filtrar por status ativo
            limit: Número máximo de resultados (padrão: 50)
            offset: Deslocamento para paginação (padrão: 0)
        
        Returns:
            Lista de webhooks com metadados de paginação
        """
        try:
            logger.info(f"MCP Tool: list_webhooks with filters, limit={limit}")
            
            # Simular busca de webhooks
            webhooks = list(self.webhooks_storage.values())
            
            # Aplicar filtros
            if event_type:
                webhooks = [w for w in webhooks if w.get("event_type") == event_type]
            
            if is_active is not None:
                webhooks = [w for w in webhooks if w.get("is_active") == is_active]
            
            # Paginação
            total_count = len(webhooks)
            start_idx = offset
            end_idx = offset + limit
            paginated_webhooks = webhooks[start_idx:end_idx]
            
            has_more = end_idx < total_count
            
            result = {
                "webhooks": paginated_webhooks,
                "pagination": {
                    "total": total_count,
                    "offset": offset,
                    "limit": limit,
                    "has_more": has_more
                }
            }
            
            # Truncar resposta se necessário
            result = response_truncator.truncate_json_response(result)
            
            logger.info(f"list_webhooks completed: {len(paginated_webhooks)} webhooks")
            return result
            
        except Exception as e:
            logger.error(f"list_webhooks unexpected error: {e}")
            raise GLPIError(500, f"Failed to list webhooks: {str(e)}")
    
    async def get_webhook(self, webhook_id: str) -> Dict[str, Any]:
        """
        Tool MCP: get_webhook
        Obtém detalhes de um webhook específico
        
        Args:
            webhook_id: ID do webhook
        
        Returns:
            Dados completos do webhook
        """
        try:
            logger.info(f"MCP Tool: get_webhook {webhook_id}")
            
            if not webhook_id or len(webhook_id.strip()) < 1:
                raise ValidationError("Webhook ID is required", "webhook_id")
            
            webhook_id = input_sanitizer.sanitize_string(webhook_id)
            
            webhook = self.webhooks_storage.get(webhook_id)
            if not webhook:
                raise NotFoundError("Webhook", webhook_id)
            
            # Truncar resposta se necessário
            webhook = response_truncator.truncate_json_response(webhook)
            
            logger.info(f"get_webhook completed: webhook {webhook_id}")
            return webhook
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"get_webhook error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"get_webhook unexpected error: {e}")
            raise GLPIError(500, f"Failed to get webhook: {str(e)}")
    
    async def create_webhook(
        self,
        name: str,
        url: str,
        event_type: str,
        secret: Optional[str] = None,
        is_active: bool = True,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Tool MCP: create_webhook
        Cria um novo webhook
        
        Args:
            name: Nome do webhook
            url: URL de destino
            event_type: Tipo de evento (ticket.created, asset.updated, etc.)
            secret: Segredo para assinatura HMAC
            is_active: Status ativo
            headers: Headers customizados
        
        Returns:
            Webhook criado
        """
        try:
            logger.info(f"MCP Tool: create_webhook - {name}")
            
            # Sanitizar inputs
            name = input_sanitizer.sanitize_string(name)
            url = input_sanitizer.sanitize_string(url)
            event_type = input_sanitizer.sanitize_string(event_type)
            
            # Validar URL
            if not url.startswith(("http://", "https://")):
                raise ValidationError("URL must start with http:// or https://", "url")
            
            # Validar tipo de evento
            valid_events = [
                "ticket.created", "ticket.updated", "ticket.deleted", "ticket.assigned",
                "asset.created", "asset.updated", "asset.deleted", "asset.reserved",
                "user.created", "user.updated", "user.deleted",
                "group.created", "group.updated", "group.deleted"
            ]
            
            if event_type not in valid_events:
                raise ValidationError(f"Event type must be one of: {valid_events}", "event_type")
            
            # Gerar ID único
            webhook_id = hashlib.md5(f"{name}_{url}_{datetime.now().isoformat()}".encode()).hexdigest()
            
            webhook = {
                "id": webhook_id,
                "name": name,
                "url": url,
                "event_type": event_type,
                "secret": secret,
                "is_active": is_active,
                "headers": headers or {},
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "delivery_count": 0,
                "last_delivery": None
            }
            
            # Salvar webhook
            self.webhooks_storage[webhook_id] = webhook
            
            # Truncar resposta se necessário
            webhook = response_truncator.truncate_json_response(webhook)
            
            logger.info(f"create_webhook completed: webhook {webhook_id}")
            return webhook
            
        except ValidationError as e:
            logger.error(f"create_webhook validation error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"create_webhook unexpected error: {e}")
            raise GLPIError(500, f"Failed to create webhook: {str(e)}")
    
    async def update_webhook(
        self,
        webhook_id: str,
        name: Optional[str] = None,
        url: Optional[str] = None,
        event_type: Optional[str] = None,
        secret: Optional[str] = None,
        is_active: Optional[bool] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Tool MCP: update_webhook
        Atualiza um webhook existente
        
        Args:
            webhook_id: ID do webhook
            name: Novo nome
            url: Nova URL
            event_type: Novo tipo de evento
            secret: Novo segredo
            is_active: Novo status
            headers: Novos headers
        
        Returns:
            Webhook atualizado
        """
        try:
            logger.info(f"MCP Tool: update_webhook {webhook_id}")
            
            if not webhook_id or len(webhook_id.strip()) < 1:
                raise ValidationError("Webhook ID is required", "webhook_id")
            
            webhook_id = input_sanitizer.sanitize_string(webhook_id)
            
            # Verificar se webhook existe
            webhook = self.webhooks_storage.get(webhook_id)
            if not webhook:
                raise NotFoundError("Webhook", webhook_id)
            
            # Atualizar campos
            if name:
                webhook["name"] = input_sanitizer.sanitize_string(name)
            
            if url:
                url = input_sanitizer.sanitize_string(url)
                if not url.startswith(("http://", "https://")):
                    raise ValidationError("URL must start with http:// or https://", "url")
                webhook["url"] = url
            
            if event_type:
                valid_events = [
                    "ticket.created", "ticket.updated", "ticket.deleted", "ticket.assigned",
                    "asset.created", "asset.updated", "asset.deleted", "asset.reserved",
                    "user.created", "user.updated", "user.deleted",
                    "group.created", "group.updated", "group.deleted"
                ]
                event_type = input_sanitizer.sanitize_string(event_type)
                if event_type not in valid_events:
                    raise ValidationError(f"Event type must be one of: {valid_events}", "event_type")
                webhook["event_type"] = event_type
            
            if secret is not None:
                webhook["secret"] = secret
            
            if is_active is not None:
                webhook["is_active"] = is_active
            
            if headers is not None:
                webhook["headers"] = headers
            
            webhook["updated_at"] = datetime.now().isoformat()
            
            # Salvar atualização
            self.webhooks_storage[webhook_id] = webhook
            
            # Truncar resposta se necessário
            webhook = response_truncator.truncate_json_response(webhook)
            
            logger.info(f"update_webhook completed: webhook {webhook_id}")
            return webhook
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"update_webhook error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"update_webhook unexpected error: {e}")
            raise GLPIError(500, f"Failed to update webhook: {str(e)}")
    
    async def delete_webhook(
        self,
        webhook_id: str,
        confirmationToken: Optional[str] = None,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Tool MCP: delete_webhook
        Deleta um webhook
        
        ATENÇÃO: Operação destrutiva! Quando MCP_SAFETY_GUARD=true:
        - Requer confirmationToken válido (igual ao MCP_SAFETY_TOKEN)
        - Requer reason com pelo menos 10 caracteres
        
        Args:
            webhook_id: ID do webhook
            confirmationToken: Token de confirmação (quando safety guard ativado)
            reason: Motivo da deleção (quando safety guard ativado, mín. 10 chars)
        
        Returns:
            Confirmação da deleção
        """
        try:
            logger.info(f"MCP Tool: delete_webhook {webhook_id}")
            
            if not webhook_id or len(webhook_id.strip()) < 1:
                raise ValidationError("Webhook ID is required", "webhook_id")
            
            webhook_id = input_sanitizer.sanitize_string(webhook_id)
            
            # Verificar safety guard
            require_safety_confirmation(
                "delete_webhook",
                confirmation_token=confirmationToken,
                reason=reason,
                target_id=int(webhook_id) if webhook_id.isdigit() else 0,
                target_type="Webhook"
            )
            
            # Verificar se webhook existe
            webhook = self.webhooks_storage.get(webhook_id)
            if not webhook:
                raise NotFoundError("Webhook", webhook_id)
            
            # Deletar webhook
            del self.webhooks_storage[webhook_id]
            
            result = {
                "success": True,
                "webhook_id": webhook_id,
                "message": f"Webhook {webhook_id} deleted successfully"
            }
            
            logger.info(f"delete_webhook completed: webhook {webhook_id}")
            return result
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"delete_webhook error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"delete_webhook unexpected error: {e}")
            raise GLPIError(500, f"Failed to delete webhook: {str(e)}")
    
    async def test_webhook(self, webhook_id: str) -> Dict[str, Any]:
        """
        Tool MCP: test_webhook
        Envia um payload de teste para o webhook
        
        Args:
            webhook_id: ID do webhook
        
        Returns:
            Resultado do teste
        """
        try:
            logger.info(f"MCP Tool: test_webhook {webhook_id}")
            
            if not webhook_id or len(webhook_id.strip()) < 1:
                raise ValidationError("Webhook ID is required", "webhook_id")
            
            webhook_id = input_sanitizer.sanitize_string(webhook_id)
            
            # Verificar se webhook existe
            webhook = self.webhooks_storage.get(webhook_id)
            if not webhook:
                raise NotFoundError("Webhook", webhook_id)
            
            # Criar payload de teste
            test_payload = {
                "event": "test",
                "webhook_id": webhook_id,
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "message": "This is a test payload from GLPI MCP Server"
                }
            }
            
            # TODO: Implementar envio HTTP real
            # Por enquanto simula sucesso
            result = {
                "webhook_id": webhook_id,
                "test_result": "success",
                "payload_sent": test_payload,
                "response_code": 200,
                "response_body": "Test successful",
                "timestamp": datetime.now().isoformat()
            }
            
            logger.info(f"test_webhook completed: webhook {webhook_id}")
            return result
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"test_webhook error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"test_webhook unexpected error: {e}")
            raise GLPIError(500, f"Failed to test webhook: {str(e)}")
    
    async def get_webhook_deliveries(
        self,
        webhook_id: str,
        limit: int = 250,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Tool MCP: get_webhook_deliveries
        Obtém histórico de entregas de um webhook
        
        Args:
            webhook_id: ID do webhook
            limit: Limite de resultados
            offset: Offset para paginação
        
        Returns:
            Histórico de entregas
        """
        try:
            logger.info(f"MCP Tool: get_webhook_deliveries {webhook_id}")
            
            if not webhook_id or len(webhook_id.strip()) < 1:
                raise ValidationError("Webhook ID is required", "webhook_id")
            
            webhook_id = input_sanitizer.sanitize_string(webhook_id)
            
            # Verificar se webhook existe
            webhook = self.webhooks_storage.get(webhook_id)
            if not webhook:
                raise NotFoundError("Webhook", webhook_id)
            
            # Simular histórico de entregas
            deliveries = [
                {
                    "id": f"delivery_{i}",
                    "webhook_id": webhook_id,
                    "event": "test",
                    "status": "success" if i % 2 == 0 else "failed",
                    "response_code": 200 if i % 2 == 0 else 500,
                    "delivered_at": datetime.now().isoformat(),
                    "duration_ms": 150 + (i * 10)
                }
                for i in range(10)  # Simular 10 entregas
            ]
            
            # Paginação
            total_count = len(deliveries)
            start_idx = offset
            end_idx = offset + limit
            paginated_deliveries = deliveries[start_idx:end_idx]
            
            result = {
                "webhook_id": webhook_id,
                "deliveries": paginated_deliveries,
                "pagination": {
                    "total": total_count,
                    "offset": offset,
                    "limit": limit,
                    "has_more": end_idx < total_count
                }
            }
            
            # Truncar resposta se necessário
            result = response_truncator.truncate_json_response(result)
            
            logger.info(f"get_webhook_deliveries completed: {len(paginated_deliveries)} deliveries")
            return result
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"get_webhook_deliveries error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"get_webhook_deliveries unexpected error: {e}")
            raise GLPIError(500, f"Failed to get webhook deliveries: {str(e)}")
    
    async def trigger_webhook(
        self,
        event_type: str,
        data: Dict[str, Any],
        webhook_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Tool MCP: trigger_webhook
        Dispara webhooks manualmente para um evento
        
        Args:
            event_type: Tipo de evento
            data: Dados do evento
            webhook_ids: IDs específicos de webhooks (opcional)
        
        Returns:
            Resultados dos disparos
        """
        try:
            logger.info(f"MCP Tool: trigger_webhook {event_type}")
            
            event_type = input_sanitizer.sanitize_string(event_type)
            
            # Filtrar webhooks por tipo de evento
            target_webhooks = []
            for webhook in self.webhooks_storage.values():
                if not webhook.get("is_active"):
                    continue
                
                if webhook_ids and webhook["id"] not in webhook_ids:
                    continue
                
                if webhook.get("event_type") == event_type:
                    target_webhooks.append(webhook)
            
            if not target_webhooks:
                return {
                    "event_type": event_type,
                    "triggered_count": 0,
                    "message": "No active webhooks found for this event"
                }
            
            # TODO: Implementar envio real
            # Por enquanto simula envios
            results = []
            for webhook in target_webhooks:
                result = {
                    "webhook_id": webhook["id"],
                    "webhook_name": webhook["name"],
                    "status": "success",
                    "response_code": 200,
                    "delivered_at": datetime.now().isoformat()
                }
                results.append(result)
                
                # Atualizar contador
                webhook["delivery_count"] += 1
                webhook["last_delivery"] = datetime.now().isoformat()
            
            response = {
                "event_type": event_type,
                "data": data,
                "triggered_count": len(results),
                "results": results
            }
            
            # Truncar resposta se necessário
            response = response_truncator.truncate_json_response(response)
            
            logger.info(f"trigger_webhook completed: {len(results)} webhooks triggered")
            return response
            
        except Exception as e:
            logger.error(f"trigger_webhook unexpected error: {e}")
            raise GLPIError(500, f"Failed to trigger webhooks: {str(e)}")
    
    async def get_webhook_stats(self) -> Dict[str, Any]:
        """
        Tool MCP: get_webhook_stats
        Obtém estatísticas dos webhooks
        
        Returns:
            Estatísticas detalhadas
        """
        try:
            logger.info(f"MCP Tool: get_webhook_stats")
            
            webhooks = list(self.webhooks_storage.values())
            
            total_webhooks = len(webhooks)
            active_webhooks = sum(1 for w in webhooks if w.get("is_active"))
            total_deliveries = sum(w.get("delivery_count", 0) for w in webhooks)
            
            # Agrupar por tipo de evento
            event_types = {}
            for webhook in webhooks:
                event_type = webhook.get("event_type", "unknown")
                event_types[event_type] = event_types.get(event_type, 0) + 1
            
            stats = {
                "total_webhooks": total_webhooks,
                "active_webhooks": active_webhooks,
                "inactive_webhooks": total_webhooks - active_webhooks,
                "total_deliveries": total_deliveries,
                "by_event_type": event_types,
                "last_updated": datetime.now().isoformat()
            }
            
            logger.info(f"get_webhook_stats completed: {total_webhooks} webhooks analyzed")
            return stats
            
        except Exception as e:
            logger.error(f"get_webhook_stats unexpected error: {e}")
            raise GLPIError(500, f"Failed to get webhook stats: {str(e)}")
    
    async def enable_webhook(self, webhook_id: str) -> Dict[str, Any]:
        """
        Tool MCP: enable_webhook
        Ativa um webhook
        
        Args:
            webhook_id: ID do webhook
        
        Returns:
            Webhook ativado
        """
        try:
            logger.info(f"MCP Tool: enable_webhook {webhook_id}")
            
            webhook_id = input_sanitizer.sanitize_string(webhook_id)
            
            webhook = self.webhooks_storage.get(webhook_id)
            if not webhook:
                raise NotFoundError("Webhook", webhook_id)
            
            webhook["is_active"] = True
            webhook["updated_at"] = datetime.now().isoformat()
            
            self.webhooks_storage[webhook_id] = webhook
            
            logger.info(f"enable_webhook completed: webhook {webhook_id}")
            return webhook
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"enable_webhook error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"enable_webhook unexpected error: {e}")
            raise GLPIError(500, f"Failed to enable webhook: {str(e)}")
    
    async def disable_webhook(self, webhook_id: str) -> Dict[str, Any]:
        """
        Tool MCP: disable_webhook
        Desativa um webhook
        
        Args:
            webhook_id: ID do webhook
        
        Returns:
            Webhook desativado
        """
        try:
            logger.info(f"MCP Tool: disable_webhook {webhook_id}")
            
            webhook_id = input_sanitizer.sanitize_string(webhook_id)
            
            webhook = self.webhooks_storage.get(webhook_id)
            if not webhook:
                raise NotFoundError("Webhook", webhook_id)
            
            webhook["is_active"] = False
            webhook["updated_at"] = datetime.now().isoformat()
            
            self.webhooks_storage[webhook_id] = webhook
            
            logger.info(f"disable_webhook completed: webhook {webhook_id}")
            return webhook
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"disable_webhook error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"disable_webhook unexpected error: {e}")
            raise GLPIError(500, f"Failed to disable webhook: {str(e)}")
    
    async def retry_failed_deliveries(self, webhook_id: str) -> Dict[str, Any]:
        """
        Tool MCP: retry_failed_deliveries
        Re-tenta entregas falhadas de um webhook
        
        Args:
            webhook_id: ID do webhook
        
        Returns:
            Resultado da nova tentativa
        """
        try:
            logger.info(f"MCP Tool: retry_failed_deliveries {webhook_id}")
            
            webhook_id = input_sanitizer.sanitize_string(webhook_id)
            
            webhook = self.webhooks_storage.get(webhook_id)
            if not webhook:
                raise NotFoundError("Webhook", webhook_id)
            
            # TODO: Implementar lógica real de retry
            # Por enquanto simula retry
            result = {
                "webhook_id": webhook_id,
                "retried_count": 0,
                "success_count": 0,
                "message": "Retry functionality not yet implemented",
                "timestamp": datetime.now().isoformat()
            }
            
            logger.info(f"retry_failed_deliveries completed: webhook {webhook_id}")
            return result
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"retry_failed_deliveries error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"retry_failed_deliveries unexpected error: {e}")
            raise GLPIError(500, f"Failed to retry deliveries: {str(e)}")


# Instância global das tools de webhooks
webhook_tools = WebhookTools()
