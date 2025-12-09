"""
MCP Tools - Assets (12 tools)
Conforme SPEC.md seção 4.2 - Matriz de Tools MCP
Wrappers para asset_service com validação e tratamento de erros
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

from src.services.asset_service import asset_service
from src.models.exceptions import (
    NotFoundError,
    ValidationError,
    GLPIError
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


class AssetTools:
    """
    Collection de 12 tools MCP para gerenciamento de assets.
    Implementadas conforme matriz SPEC.md seção 4.2
    """
    
    async def list_assets(
        self,
        asset_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        entity_name: Optional[str] = None,
        location_id: Optional[int] = None,
        manufacturer_id: Optional[int] = None,
        model_id: Optional[int] = None,
        status: Optional[str] = None,
        limit: int = 250,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Tool MCP: list_assets
        Lista todos os assets com filtros opcionais

        Args:
            asset_type: Tipo de asset (Computer, Monitor, Printer, etc.)
            entity_id: Filtrar por entidade (ID numérico)
            entity_name: Filtrar por nome da entidade/cliente (ex: "GSM Transportes", "Skills IT")
            location_id: Filtrar por localização
            manufacturer_id: Filtrar por fabricante
            model_id: Filtrar por modelo
            status: Filtrar por status
            limit: Número máximo de resultados (padrão: 50)
            offset: Deslocamento para paginação (padrão: 0)

        Returns:
            Lista de assets com metadados de paginação

        Note:
            Se entity_name for fornecido, será resolvido para entity_id automaticamente.
            entity_name tem prioridade sobre entity_id se ambos forem fornecidos.
        """
        try:
            logger.info(f"MCP Tool: list_assets type={asset_type}, entity_name={entity_name}, limit={limit}")

            # Resolver entity_name para entity_id se fornecido
            if entity_name:
                resolved_id = await entity_resolver.resolve_entity_name(entity_name)
                if resolved_id:
                    entity_id = resolved_id
                    logger.info(f"list_assets: entity_name '{entity_name}' resolvido para ID {entity_id}")
                else:
                    # Entidade não encontrada - retornar erro amigável com lista de entidades
                    available = await entity_resolver.list_available_entities()
                    raise ValidationError(
                        f"Entidade '{entity_name}' não encontrada. Entidades disponíveis: {[e['name'] for e in available[:10]]}",
                        "entity_name"
                    )

            # Sanitizar inputs
            if asset_type:
                asset_type = input_sanitizer.sanitize_string(asset_type)
            
            # Validar paginação
            offset, limit = PaginationHelper.validate_pagination_params(offset, limit)
            
            # Buscar assets
            assets = await asset_service.list_assets(
                asset_type=asset_type,
                entity_id=entity_id,
                location_id=location_id,
                manufacturer_id=manufacturer_id,
                model_id=model_id,
                status=status,
                limit=limit,
                offset=offset,
                use_cache=True
            )
            
            # Truncar resposta se necessário
            if isinstance(assets, dict) and "assets" in assets:
                assets["assets"] = response_truncator.truncate_json_response(assets["assets"])
            else:
                assets = response_truncator.truncate_json_response(assets)
            
            logger.info(f"list_assets completed: {len(assets) if isinstance(assets, list) else 'paginated'} assets")
            return assets
            
        except ValidationError as e:
            logger.error(f"list_assets validation error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"list_assets unexpected error: {e}")
            raise GLPIError(500, f"Failed to list assets: {str(e)}")
    
    async def list_software(self, **kwargs) -> Dict[str, Any]:
        """Tool MCP: list_software."""
        return await self.list_assets(asset_type="Software", **kwargs)

    async def list_devices(
        self, 
        device_type: str = "NetworkEquipment",
        limit: int = 250,
        offset: int = 0,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Tool MCP: list_devices
        Lista dispositivos de rede, periféricos, etc.
        
        Args:
            device_type: Tipo de dispositivo (NetworkEquipment, Peripheral, Phone, etc.)
            limit: Número máximo de resultados
            offset: Deslocamento para paginação
        """
        return await self.list_assets(asset_type=device_type, limit=limit, offset=offset, **kwargs)
    
    async def get_asset(self, asset_type: str, asset_id: int) -> Dict[str, Any]:
        """
        Tool MCP: get_asset
        Obtém detalhes completos de um asset específico
        
        Args:
            asset_type: Tipo de asset
            asset_id: ID do asset
        
        Returns:
            Dados completos do asset
        """
        try:
            logger.info(f"MCP Tool: get_asset {asset_type} {asset_id}")
            
            # Validar inputs
            if not asset_type or len(asset_type.strip()) < 2:
                raise ValidationError("Asset type must be at least 2 characters", "asset_type")
            
            if not isinstance(asset_id, int) or asset_id <= 0:
                raise ValidationError("Asset ID must be a positive integer", "asset_id")
            
            asset_type = input_sanitizer.sanitize_string(asset_type)
            
            asset = await asset_service.get_asset(asset_type, asset_id)
            
            # Truncar resposta se necessário
            asset = response_truncator.truncate_json_response(asset)
            
            logger.info(f"get_asset completed: {asset_type} {asset_id}")
            return asset
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"get_asset error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"get_asset unexpected error: {e}")
            raise GLPIError(500, f"Failed to get asset: {str(e)}")
    
    async def get_software(self, software_id: int) -> Dict[str, Any]:
        """Tool MCP: get_software."""
        return await self.get_asset("Software", software_id)

    async def get_device(
        self, 
        device_type: str,
        device_id: int
    ) -> Dict[str, Any]:
        """
        Tool MCP: get_device
        Obtém detalhes de um dispositivo de rede, periférico, etc.
        
        Args:
            device_type: Tipo de dispositivo (NetworkEquipment, Peripheral, Phone, etc.)
            device_id: ID do dispositivo
        """
        return await self.get_asset(device_type, device_id)

    async def get_monitor(self, monitor_id: int) -> Dict[str, Any]:
        """Tool MCP: get_monitor."""
        return await self.get_asset("Monitor", monitor_id)
    
    async def create_asset(
        self,
        asset_type: str,
        name: str,
        serial_number: Optional[str] = None,
        other_serial: Optional[str] = None,
        status: Optional[int] = None,
        entity_id: Optional[int] = None,
        location_id: Optional[int] = None,
        manufacturer_id: Optional[int] = None,
        model_id: Optional[int] = None,
        user_id: Optional[int] = None,
        group_id: Optional[int] = None,
        comment: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Tool MCP: create_asset
        Cria um novo asset
        
        Args:
            asset_type: Tipo de asset
            name: Nome do asset (mínimo 2 caracteres)
            serial_number: Número de série
            other_serial: Outro número de série
            status: ID do status
            entity_id: ID da entidade
            location_id: ID da localização
            manufacturer_id: ID do fabricante
            model_id: ID do modelo
            user_id: ID do usuário responsável
            group_id: ID do grupo responsável
            comment: Comentários
        
        Returns:
            Asset criado
        """
        try:
            logger.info(f"MCP Tool: create_asset {asset_type} - {name}")
            
            # Sanitizar inputs
            asset_type = input_sanitizer.sanitize_string(asset_type)
            name = input_sanitizer.sanitize_string(name)
            
            if serial_number:
                serial_number = input_sanitizer.sanitize_string(serial_number)
            
            if comment:
                comment = input_sanitizer.sanitize_string(comment)
            
            # Criar asset
            asset = await asset_service.create_asset(
                asset_type=asset_type,
                name=name,
                serial_number=serial_number,
                other_serial=other_serial,
                status=status,
                entity_id=entity_id,
                location_id=location_id,
                manufacturer_id=manufacturer_id,
                model_id=model_id,
                user_id=user_id,
                group_id=group_id,
                comment=comment
            )
            
            # Truncar resposta se necessário
            asset = response_truncator.truncate_json_response(asset)
            
            logger.info(f"create_asset completed: {asset_type} {asset.get('id')}")
            return asset
            
        except ValidationError as e:
            logger.error(f"create_asset validation error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"create_asset unexpected error: {e}")
            raise GLPIError(500, f"Failed to create asset: {str(e)}")
    
    async def update_asset(
        self,
        asset_type: str,
        asset_id: int,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Tool MCP: update_asset
        Atualiza um asset existente
        
        Args:
            asset_type: Tipo de asset
            asset_id: ID do asset
            **kwargs: Campos para atualizar
        
        Returns:
            Asset atualizado
        """
        try:
            logger.info(f"MCP Tool: update_asset {asset_type} {asset_id}")
            
            # Validar inputs
            if not asset_type or len(asset_type.strip()) < 2:
                raise ValidationError("Asset type must be at least 2 characters", "asset_type")
            
            if not isinstance(asset_id, int) or asset_id <= 0:
                raise ValidationError("Asset ID must be a positive integer", "asset_id")
            
            asset_type = input_sanitizer.sanitize_string(asset_type)
            
            # Sanitizar campos de texto
            update_data = {}
            for key, value in kwargs.items():
                if isinstance(value, str):
                    update_data[key] = input_sanitizer.sanitize_string(value)
                else:
                    update_data[key] = value
            
            # Atualizar asset
            asset = await asset_service.update_asset(asset_type, asset_id, **update_data)
            
            # Truncar resposta se necessário
            asset = response_truncator.truncate_json_response(asset)
            
            logger.info(f"update_asset completed: {asset_type} {asset_id}")
            return asset
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"update_asset error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"update_asset unexpected error: {e}")
            raise GLPIError(500, f"Failed to update asset: {str(e)}")
    
    async def delete_asset(
        self,
        asset_type: str,
        asset_id: int,
        confirmationToken: Optional[str] = None,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Tool MCP: delete_asset
        Deleta um asset permanentemente
        
        ATENÇÃO: Operação destrutiva! Quando MCP_SAFETY_GUARD=true:
        - Requer confirmationToken válido (igual ao MCP_SAFETY_TOKEN)
        - Requer reason com pelo menos 10 caracteres
        
        Args:
            asset_type: Tipo de asset
            asset_id: ID do asset
            confirmationToken: Token de confirmação (quando safety guard ativado)
            reason: Motivo da deleção (quando safety guard ativado, mín. 10 chars)
        
        Returns:
            Confirmação da deleção
        """
        try:
            logger.info(f"MCP Tool: delete_asset {asset_type} {asset_id}")
            
            # Validar inputs
            if not asset_type or len(asset_type.strip()) < 2:
                raise ValidationError("Asset type must be at least 2 characters", "asset_type")
            
            if not isinstance(asset_id, int) or asset_id <= 0:
                raise ValidationError("Asset ID must be a positive integer", "asset_id")
            
            asset_type = input_sanitizer.sanitize_string(asset_type)
            
            # Verificar safety guard
            require_safety_confirmation(
                "delete_asset",
                confirmation_token=confirmationToken,
                reason=reason,
                target_id=asset_id,
                target_type=asset_type
            )
            
            success = await asset_service.delete_asset(asset_type, asset_id)
            
            result = {
                "success": success,
                "asset_type": asset_type,
                "asset_id": asset_id,
                "message": f"Asset {asset_type} {asset_id} deleted successfully"
            }
            
            logger.info(f"delete_asset completed: {asset_type} {asset_id}")
            return result
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"delete_asset error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"delete_asset unexpected error: {e}")
            raise GLPIError(500, f"Failed to delete asset: {str(e)}")
    
    async def search_assets(
        self,
        query: str,
        asset_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        entity_name: Optional[str] = None,
        fields: Optional[List[str]] = None,
        limit: int = 250,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Tool MCP: search_assets
        Busca assets por texto livre

        Args:
            query: Texto para buscar
            asset_type: Tipo de asset específico
            entity_id: Filtrar por entidade (ID numérico)
            entity_name: Filtrar por nome da entidade/cliente (ex: "GSM Transportes")
            fields: Campos específicos para retornar
            limit: Limite de resultados
            offset: Offset para paginação

        Returns:
            Assets que correspondem à busca

        Note:
            Se entity_name for fornecido, será resolvido para entity_id automaticamente.
        """
        try:
            logger.info(f"MCP Tool: search_assets - {query}, entity_name={entity_name}")

            # Resolver entity_name para entity_id se fornecido
            if entity_name:
                resolved_id = await entity_resolver.resolve_entity_name(entity_name)
                if resolved_id:
                    entity_id = resolved_id
                    logger.info(f"search_assets: entity_name '{entity_name}' resolvido para ID {entity_id}")
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

            if asset_type:
                asset_type = input_sanitizer.sanitize_string(asset_type)

            # Validar paginação
            offset, limit = PaginationHelper.validate_pagination_params(offset, limit)

            assets = await asset_service.search_assets(
                query=query,
                asset_type=asset_type,
                entity_id=entity_id,
                fields=fields,
                limit=limit,
                offset=offset
            )
            
            # Truncar resposta se necessário
            assets = response_truncator.truncate_json_response(assets)
            
            logger.info(f"search_assets completed: {len(assets) if isinstance(assets, list) else 'paginated'} assets")
            return assets
            
        except ValidationError as e:
            logger.error(f"search_assets validation error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"search_assets unexpected error: {e}")
            raise GLPIError(500, f"Failed to search assets: {str(e)}")
    
    async def get_asset_reservations(
        self,
        asset_type: str,
        asset_id: int,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Tool MCP: get_asset_reservations
        Obtém reservas de um asset
        
        Args:
            asset_type: Tipo de asset
            asset_id: ID do asset
            date_from: Data inicial (YYYY-MM-DD)
            date_to: Data final (YYYY-MM-DD)
        
        Returns:
            Lista de reservas
        """
        try:
            logger.info(f"MCP Tool: get_asset_reservations {asset_type} {asset_id}")
            
            # Validar inputs
            if not asset_type or len(asset_type.strip()) < 2:
                raise ValidationError("Asset type must be at least 2 characters", "asset_type")
            
            if not isinstance(asset_id, int) or asset_id <= 0:
                raise ValidationError("Asset ID must be a positive integer", "asset_id")
            
            asset_type = input_sanitizer.sanitize_string(asset_type)
            
            # Validar datas
            if date_from or date_to:
                date_from, date_to = DateTimeHelper.parse_date_range(date_from, date_to)
            
            reservations = await asset_service.get_asset_reservations(
                asset_type, asset_id, date_from, date_to
            )
            
            # Truncar resposta se necessário
            reservations = response_truncator.truncate_json_response(reservations)
            
            logger.info(f"get_asset_reservations completed: {len(reservations)} reservations")
            return {
                "asset_type": asset_type,
                "asset_id": asset_id,
                "reservations": reservations,
                "count": len(reservations)
            }
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"get_asset_reservations error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"get_asset_reservations unexpected error: {e}")
            raise GLPIError(500, f"Failed to get asset reservations: {str(e)}")
    
    async def list_reservable_items(
        self,
        entity_id: Optional[int] = None,
        entity_name: Optional[str] = None,
        is_active: Optional[bool] = None,
        itemtype: Optional[str] = None,
        limit: int = 250,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Tool MCP: list_reservable_items
        Lista todos os itens configurados como reserváveis no GLPI.

        Um ReservationItem é um item (Computer, Monitor, Peripheral, etc) que foi
        configurado para permitir reservas. Use esta tool para descobrir quais itens
        podem ser reservados antes de criar uma reserva com create_reservation.

        Args:
            entity_id: Filtrar por entidade específica (ID numérico)
            entity_name: Filtrar por nome da entidade/cliente (ex: "GSM Transportes")
            is_active: Filtrar por status ativo (True=disponíveis para reserva)
            itemtype: Filtrar por tipo (Computer, Monitor, Peripheral, etc)
            limit: Número máximo de resultados (padrão: 50)
            offset: Deslocamento para paginação (padrão: 0)

        Returns:
            Dict com:
                - reservable_items: Lista de itens reserváveis com detalhes
                - count: Quantidade de itens retornados
                - pagination: Informações de paginação
        """
        try:
            logger.info(f"MCP Tool: list_reservable_items entity_name={entity_name}, type={itemtype}")

            # Resolver entity_name para entity_id se fornecido
            if entity_name:
                resolved_id = await entity_resolver.resolve_entity_name(entity_name)
                if resolved_id:
                    entity_id = resolved_id
                    logger.info(f"list_reservable_items: entity_name '{entity_name}' resolvido para ID {entity_id}")
                else:
                    available = await entity_resolver.list_available_entities()
                    raise ValidationError(
                        f"Entidade '{entity_name}' não encontrada. Entidades disponíveis: {[e['name'] for e in available[:10]]}",
                        "entity_name"
                    )
            
            # Validar paginação
            offset, limit = PaginationHelper.validate_pagination_params(offset, limit)
            
            # Sanitizar inputs
            if itemtype:
                itemtype = input_sanitizer.sanitize_string(itemtype)
            
            # Buscar itens reserváveis
            result = await asset_service.list_reservable_items(
                entity_id=entity_id,
                is_active=is_active,
                itemtype=itemtype,
                limit=limit,
                offset=offset
            )
            
            # Truncar resposta se necessário
            if "reservable_items" in result:
                result["reservable_items"] = response_truncator.truncate_json_response(
                    result["reservable_items"]
                )
            
            logger.info(f"list_reservable_items completed: {result['count']} items")
            return result
            
        except ValidationError as e:
            logger.error(f"list_reservable_items validation error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"list_reservable_items unexpected error: {e}")
            raise GLPIError(500, f"Failed to list reservable items: {str(e)}")
    
    async def list_reservations(self, limit: int = 250, offset: int = 0) -> Dict[str, Any]:
        """Tool MCP: list_reservations."""
        try:
            logger.info(f"MCP Tool: list_reservations limit={limit} offset={offset}")
            reservations = await asset_service.list_reservations(limit=limit, offset=offset)
            return response_truncator.truncate_json_response(reservations)
        except Exception as e:
            logger.error(f"list_reservations unexpected error: {e}")
            raise GLPIError(500, f"Failed to list reservations: {str(e)}")

    async def update_reservation(self, reservation_id: int, **kwargs) -> Dict[str, Any]:
        """Tool MCP: update_reservation."""
        try:
            logger.info(f"MCP Tool: update_reservation {reservation_id}")
            updated = await asset_service.update_reservation(reservation_id, **kwargs)
            return response_truncator.truncate_json_response(updated)
        except (ValidationError, GLPIError) as e:
            logger.error(f"update_reservation error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"update_reservation unexpected error: {e}")
            raise GLPIError(500, f"Failed to update reservation: {str(e)}")
    
    async def create_reservation(
        self,
        asset_type: str,
        asset_id: int,
        user_id: int,
        date_start: str,  # Match service parameter name
        date_end: str,    # Match service parameter name
        comment: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Tool MCP: create_reservation
        Cria uma reserva para um asset
        
        Args:
            asset_type: Tipo de asset
            asset_id: ID do asset
            user_id: ID do usuário
            date_start: Data/hora início (YYYY-MM-DD HH:MM:SS)
            date_end: Data/hora fim (YYYY-MM-DD HH:MM:SS)
            comment: Comentário da reserva
        
        Returns:
            Reserva criada
        """
        try:
            logger.info(f"MCP Tool: create_reservation {asset_type} {asset_id}")
            
            # Validar inputs
            if not asset_type or len(asset_type.strip()) < 2:
                raise ValidationError("Asset type must be at least 2 characters", "asset_type")
            
            if not isinstance(asset_id, int) or asset_id <= 0:
                raise ValidationError("Asset ID must be a positive integer", "asset_id")
            
            if not isinstance(user_id, int) or user_id <= 0:
                raise ValidationError("User ID must be a positive integer", "user_id")
            
            asset_type = input_sanitizer.sanitize_string(asset_type)
            
            if comment:
                comment = input_sanitizer.sanitize_string(comment)
            
            # Criar reserva
            reservation = await asset_service.create_reservation(
                asset_type=asset_type,
                asset_id=asset_id,
                user_id=user_id,
                date_start=date_start,
                date_end=date_end,
                comment=comment
            )
            
            # Truncar resposta se necessário
            reservation = response_truncator.truncate_json_response(reservation)
            
            logger.info(f"create_reservation completed: reservation {reservation.get('id')}")
            return reservation
            
        except ValidationError as e:
            logger.error(f"create_reservation validation error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"create_reservation unexpected error: {e}")
            raise GLPIError(500, f"Failed to create reservation: {str(e)}")
    
    async def get_asset_stats(
        self,
        asset_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        entity_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Tool MCP: get_asset_stats
        Obtém estatísticas de assets

        Args:
            asset_type: Tipo de asset específico
            entity_id: Filtrar por entidade (ID numérico)
            entity_name: Filtrar por nome da entidade/cliente (ex: "GSM Transportes")

        Returns:
            Estatísticas detalhadas
        """
        try:
            logger.info(f"MCP Tool: get_asset_stats entity_name={entity_name}")

            # Resolver entity_name para entity_id se fornecido
            if entity_name:
                resolved_id = await entity_resolver.resolve_entity_name(entity_name)
                if resolved_id:
                    entity_id = resolved_id
                    logger.info(f"get_asset_stats: entity_name '{entity_name}' resolvido para ID {entity_id}")
                else:
                    available = await entity_resolver.list_available_entities()
                    raise ValidationError(
                        f"Entidade '{entity_name}' não encontrada. Entidades disponíveis: {[e['name'] for e in available[:10]]}",
                        "entity_name"
                    )

            if asset_type:
                asset_type = input_sanitizer.sanitize_string(asset_type)

            stats = await asset_service.get_asset_stats(
                asset_type=asset_type,
                entity_id=entity_id
            )
            
            logger.info(f"get_asset_stats completed: {stats['total_assets']} assets analyzed")
            return stats
            
        except Exception as e:
            logger.error(f"get_asset_stats unexpected error: {e}")
            raise GLPIError(500, f"Failed to get asset stats: {str(e)}")
    
    async def list_computers(
        self,
        entity_id: Optional[int] = None,
        entity_name: Optional[str] = None,
        location_id: Optional[int] = None,
        manufacturer_id: Optional[int] = None,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        limit: int = 250,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Tool MCP: list_computers
        Lista computadores com filtros específicos

        Args:
            entity_id: Filtrar por entidade (ID numérico)
            entity_name: Filtrar por nome da entidade/cliente (ex: "GSM Transportes", "Skills IT")
            location_id: Filtrar por localização
            manufacturer_id: Filtrar por fabricante
            user_id: Filtrar por ID do usuário responsável
            username: Filtrar por nome do usuário (exige user_id preferencialmente)
            limit: Limite de resultados
            offset: Offset para paginação

        Returns:
            Lista de computadores

        Note:
            Se entity_name for fornecido, será resolvido para entity_id automaticamente.
            Exemplo: list_computers(entity_name="GSM") retorna computadores da entidade GSM.
        """
        try:
            logger.info(f"MCP Tool: list_computers entity_name={entity_name}, user_id={user_id}")

            # Resolver entity_name para entity_id se fornecido
            if entity_name:
                resolved_id = await entity_resolver.resolve_entity_name(entity_name)
                if resolved_id:
                    entity_id = resolved_id
                    logger.info(f"list_computers: entity_name '{entity_name}' resolvido para ID {entity_id}")
                else:
                    available = await entity_resolver.list_available_entities()
                    raise ValidationError(
                        f"Entidade '{entity_name}' não encontrada. Entidades disponíveis: {[e['name'] for e in available[:10]]}",
                        "entity_name"
                    )

            # Validar paginação
            offset, limit = PaginationHelper.validate_pagination_params(offset, limit)

            computers = await asset_service.list_assets(
                asset_type="Computer",
                entity_id=entity_id,
                location_id=location_id,
                manufacturer_id=manufacturer_id,
                user_id=user_id,
                username=username,
                limit=limit,
                offset=offset,
                use_cache=True
            )
            
            # Truncar resposta se necessário
            if isinstance(computers, dict) and "assets" in computers:
                computers["assets"] = response_truncator.truncate_json_response(computers["assets"])
            else:
                computers = response_truncator.truncate_json_response(computers)
            
            logger.info(f"list_computers completed: {len(computers) if isinstance(computers, list) else 'paginated'} computers")
            return computers
            
        except Exception as e:
            logger.error(f"list_computers unexpected error: {e}")
            raise GLPIError(500, f"Failed to list computers: {str(e)}")
    
    async def get_computer_details(self, computer_id: int) -> Dict[str, Any]:
        """
        Tool MCP: get_computer_details
        Obtém detalhes completos de um computador incluindo componentes
        
        Args:
            computer_id: ID do computador
        
        Returns:
            Detalhes completos do computador
        """
        try:
            logger.info(f"MCP Tool: get_computer_details {computer_id}")
            
            if not isinstance(computer_id, int) or computer_id <= 0:
                raise ValidationError("Computer ID must be a positive integer", "computer_id")
            
            computer = await asset_service.get_asset("Computer", computer_id)
            
            # Truncar resposta se necessário
            computer = response_truncator.truncate_json_response(computer)
            
            logger.info(f"get_computer_details completed: computer {computer_id}")
            return computer
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"get_computer_details error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"get_computer_details unexpected error: {e}")
            raise GLPIError(500, f"Failed to get computer details: {str(e)}")
    
    async def list_monitors(
        self,
        entity_id: Optional[int] = None,
        entity_name: Optional[str] = None,
        location_id: Optional[int] = None,
        manufacturer_id: Optional[int] = None,
        limit: int = 250,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Tool MCP: list_monitors
        Lista monitores com filtros específicos

        Args:
            entity_id: Filtrar por entidade (ID numérico)
            entity_name: Filtrar por nome da entidade/cliente (ex: "GSM Transportes", "Skills IT")
            location_id: Filtrar por localização
            manufacturer_id: Filtrar por fabricante
            limit: Limite de resultados
            offset: Offset para paginação

        Returns:
            Lista de monitores

        Note:
            Se entity_name for fornecido, será resolvido para entity_id automaticamente.
        """
        try:
            logger.info(f"MCP Tool: list_monitors entity_name={entity_name}")

            # Resolver entity_name para entity_id se fornecido
            if entity_name:
                resolved_id = await entity_resolver.resolve_entity_name(entity_name)
                if resolved_id:
                    entity_id = resolved_id
                    logger.info(f"list_monitors: entity_name '{entity_name}' resolvido para ID {entity_id}")
                else:
                    available = await entity_resolver.list_available_entities()
                    raise ValidationError(
                        f"Entidade '{entity_name}' não encontrada. Entidades disponíveis: {[e['name'] for e in available[:10]]}",
                        "entity_name"
                    )

            # Validar paginação
            offset, limit = PaginationHelper.validate_pagination_params(offset, limit)

            monitors = await asset_service.list_assets(
                asset_type="Monitor",
                entity_id=entity_id,
                location_id=location_id,
                manufacturer_id=manufacturer_id,
                limit=limit,
                offset=offset,
                use_cache=True
            )
            
            # Truncar resposta se necessário
            if isinstance(monitors, dict) and "assets" in monitors:
                monitors["assets"] = response_truncator.truncate_json_response(monitors["assets"])
            else:
                monitors = response_truncator.truncate_json_response(monitors)
            
            logger.info(f"list_monitors completed: {len(monitors) if isinstance(monitors, list) else 'paginated'} monitors")
            return monitors
            
        except Exception as e:
            logger.error(f"list_monitors unexpected error: {e}")
            raise GLPIError(500, f"Failed to list monitors: {str(e)}")


# Instância global das tools de assets
asset_tools = AssetTools()
