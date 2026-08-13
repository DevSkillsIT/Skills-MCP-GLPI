"""
MCP Tools - Assets (12 tools)
Conforme SPEC.md seção 4.2 - Matriz de Tools MCP
Wrappers para asset_service com validação e tratamento de erros
"""

from typing import Dict, Any, List, Optional

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


#: SoftwareVersion id -> software name, kept for the process lifetime.
#
# @MX:NOTE: um software instalado nao carrega o proprio nome.
# @MX:REASON: `Item_SoftwareVersion` devolve apenas `softwareversions_id` (a
# versao) mesmo com expand_dropdowns; o nome mora em SoftwareVersion.softwares_id,
# um salto adiante. Sem resolver, a coluna "Software" saia inteira em branco e a
# lista de programas instalados nao respondia a unica pergunta que se faz dela.
# O cache evita repetir o salto: as mesmas versoes se repetem em todo o parque.
_SOFTWARE_NAME_CACHE: Dict[str, str] = {}

#: Teto de resolucoes por chamada. Uma maquina tem dezenas de programas e um
#: GET por versao transformaria uma tela em dezenas de round-trips.
_SOFTWARE_RESOLVE_CAP = 40


def _subitem_link_id(item: Dict[str, Any], rel: str) -> Optional[str]:
    """Extract a related record's id from the `links` array GLPI attaches."""
    for link in item.get("links") or []:
        if link.get("rel") == rel:
            href = str(link.get("href") or "")
            tail = href.rstrip("/").rsplit("/", 1)[-1]
            if tail.isdigit():
                return tail
    return None


async def _resolve_software_names(client, software: List[Dict[str, Any]]) -> None:
    """Fill each installed-software row with the program's name, in place."""
    if not software:
        return

    pending = []
    for row in software:
        version_id = _subitem_link_id(row, "SoftwareVersion")
        if not version_id:
            continue
        row["_software_version_id"] = version_id
        if version_id not in _SOFTWARE_NAME_CACHE and version_id not in pending:
            pending.append(version_id)

    import asyncio as _asyncio

    async def _fetch(version_id: str):
        try:
            record = await client.get(
                f"/apirest.php/SoftwareVersion/{int(version_id)}",
                params={"expand_dropdowns": "true"},
            )
            if isinstance(record, dict):
                name = record.get("softwares_id")
                if name and not str(name).isdigit():
                    _SOFTWARE_NAME_CACHE[version_id] = str(name)
        except Exception as exc:  # noqa: BLE001 -- nome e enfeite, nao bloqueia
            logger.warning(f"software name lookup failed for {version_id}: {exc}")

    if pending:
        await _asyncio.gather(*(_fetch(v) for v in pending[:_SOFTWARE_RESOLVE_CAP]))

    for row in software:
        name = _SOFTWARE_NAME_CACHE.get(row.get("_software_version_id") or "")
        if name:
            row["softwares_id"] = name


#: Colunas que so a Search API resolve, com o id do campo em Computer.
#
# @MX:ANCHOR: o IP de uma maquina nao e coluna da tabela de computadores.
# @MX:REASON: o endereco vive tres saltos adiante (NetworkPort -> NetworkName
# -> IPAddress), entao o GET do ativo nunca o traz e "qual o IP dessa maquina"
# ficava sem resposta em qualquer tela. A Search API ja resolve o join no campo
# 126; uma consulta por id custa um round-trip e responde. O mesmo vale para o
# tipo de disco (116) e o tipo de memoria (110), que o agente de inventario
# preenche em algumas maquinas e o GET tambem nao alcanca.
_SEARCH_ONLY_COLUMNS = {
    "126": "ip_addresses",
    "116": "harddrive_type",
    "110": "memory_type",
}


async def _attach_search_only_columns(
    client, asset_id: int, asset: Any, item_type: str = "Computer"
) -> None:
    """Add join-only columns to an asset fetched through the item endpoint.

    @MX:NOTE: vale para qualquer tipo de ativo, nao so Computer.
    @MX:REASON: o campo 126 (IP) existe identicamente em Monitor, Printer,
    NetworkEquipment, Phone e Peripheral -- verificado no catalogo da
    instancia. Fixar "Computer" aqui deixava o endereco de um switch ou de uma
    impressora de rede inalcancavel, que e justamente onde alguem pergunta o IP.
    """
    if not isinstance(asset, dict):
        return
    try:
        result = await client.search(
            item_type=item_type,
            criteria=[{"field": 2, "searchtype": "equals", "value": asset_id}],
            forcedisplay=list(_SEARCH_ONLY_COLUMNS.keys()),
            range_limit=1,
            expand_dropdowns=True,
        )
    except Exception as exc:  # noqa: BLE001 -- enriquecimento nunca bloqueia
        logger.warning(
            f"search-only columns failed for {item_type} {asset_id}: {exc}"
        )
        return

    rows = result.get("data", []) if isinstance(result, dict) else (result or [])
    if not rows or not isinstance(rows[0], dict):
        return
    for field_id, key in _SEARCH_ONLY_COLUMNS.items():
        value = rows[0].get(field_id)
        if isinstance(value, list):
            # Um equipamento com varias interfaces devolve uma lista.
            value = ", ".join(str(v) for v in value if v)
        if value not in (None, "", 0, "0", []):
            asset[key] = value


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
        offset: int = 0,
        assigned_user: Optional[Any] = None,
        sort_by: Optional[Any] = None,
        order: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Tool MCP: list_assets
        Lista todos os assets com filtros opcionais

        Args:
            asset_type: Tipo de asset (Computer, Monitor, Printer, etc.)
            entity_id: Filtrar por entidade (ID numérico)
            entity_name: Filtrar por nome da entidade/cliente (ex: "Acme Corp", "Example Client")
            location_id: Filtrar por localização
            manufacturer_id: Filtrar por fabricante
            model_id: Filtrar por modelo
            status: Filtrar por status
            limit: Número máximo de resultados (padrão: 50)
            offset: Deslocamento para paginação (padrão: 0)
            assigned_user: Filtrar por responsável (NOME ou ID numérico)
            sort_by: Coluna de ordenação (nome amigável ou ID do campo GLPI)
            order: Direção da ordenação (asc/desc)

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
                if resolved_id is not None:
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
                use_cache=True,
                assigned_user=assigned_user,
                sort_by=sort_by,
                order=order
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

            # IP e demais colunas que so a Search API resolve, para QUALQUER
            # tipo de ativo — impressora de rede e switch inclusive.
            from src.services.glpi_client import glpi_client as _gc
            await _attach_search_only_columns(_gc, asset_id, asset, asset_type)

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
                comment = input_sanitizer.sanitize_string(comment, allow_html=True)
            
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
        offset: int = 0,
        sort_by: Optional[Any] = None,
        order: Optional[str] = None,
        location_id: Optional[int] = None,
        manufacturer_id: Optional[int] = None,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        status: Optional[str] = None,
        assigned_user: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Tool MCP: search_assets
        Busca assets por texto livre, com os MESMOS filtros da listagem

        Args:
            query: Texto para buscar
            asset_type: Tipo de asset específico
            entity_id: Filtrar por entidade (ID numérico)
            entity_name: Filtrar por nome da entidade/cliente (ex: "Acme Corp")
            fields: Campos específicos para retornar
            limit: Limite de resultados
            offset: Offset para paginação
            sort_by: Coluna de ordenação (nome amigável ou ID do campo GLPI)
            order: Direção da ordenação (asc/desc)

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
                if resolved_id is not None:
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
                offset=offset,
                sort_by=sort_by,
                order=order,
                location_id=location_id,
                manufacturer_id=manufacturer_id,
                user_id=user_id,
                username=username,
                status=status,
                assigned_user=assigned_user,
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
            entity_name: Filtrar por nome da entidade/cliente (ex: "Acme Corp")
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
                if resolved_id is not None:
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
                comment = input_sanitizer.sanitize_string(comment, allow_html=True)
            
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
            entity_name: Filtrar por nome da entidade/cliente (ex: "Acme Corp")

        Returns:
            Estatísticas detalhadas
        """
        try:
            logger.info(f"MCP Tool: get_asset_stats entity_name={entity_name}")

            # Resolver entity_name para entity_id se fornecido
            if entity_name:
                resolved_id = await entity_resolver.resolve_entity_name(entity_name)
                if resolved_id is not None:
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
        offset: int = 0,
        assigned_user: Optional[Any] = None,
        sort_by: Optional[Any] = None,
        order: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Tool MCP: list_computers
        Lista computadores com filtros específicos

        Args:
            entity_id: Filtrar por entidade (ID numérico)
            entity_name: Filtrar por nome da entidade/cliente (ex: "Acme Corp", "Example Client")
            location_id: Filtrar por localização
            manufacturer_id: Filtrar por fabricante
            user_id: Filtrar por ID do usuário responsável
            username: Filtrar por nome do usuário (exige user_id preferencialmente)
            limit: Limite de resultados
            offset: Offset para paginação
            assigned_user: Filtrar por responsável (NOME ou ID numérico)
            sort_by: Coluna de ordenação (nome amigável ou ID do campo GLPI)
            order: Direção da ordenação (asc/desc)

        Returns:
            Lista de computadores

        Note:
            Se entity_name for fornecido, será resolvido para entity_id automaticamente.
            Exemplo: list_computers(entity_name="Acme") retorna computadores da entidade Acme.
        """
        try:
            logger.info(f"MCP Tool: list_computers entity_name={entity_name}, user_id={user_id}")

            # Resolver entity_name para entity_id se fornecido
            if entity_name:
                resolved_id = await entity_resolver.resolve_entity_name(entity_name)
                if resolved_id is not None:
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
                use_cache=True,
                assigned_user=assigned_user,
                sort_by=sort_by,
                order=order
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
        Obtém detalhes completos de um computador incluindo sub-items:
        sistema operacional, discos, processadores, memórias, software e itens
        de rede (se disponíveis). Falhas de sub-item não abortam a consulta.

        Args:
            computer_id: ID do computador

        Returns:
            Dict com chaves: asset, operating_systems, disks, processors,
            memories, networks, software. Cada sub-item é uma lista (ou []).
        """
        try:
            logger.info(f"MCP Tool: get_computer_details {computer_id}")

            if not isinstance(computer_id, int) or computer_id <= 0:
                raise ValidationError("Computer ID must be a positive integer", "computer_id")

            computer = await asset_service.get_asset("Computer", computer_id)

            # Fetch sub-items in parallel — each one wrapped so one failure
            # does not abort the whole enrichment.
            from src.services.glpi_client import glpi_client as _gc

            # @MX:WARN: expand_dropdowns e obrigatorio aqui, nao um detalhe.
            # @MX:REASON: sem ele os sub-itens vinham como chaves estrangeiras
            # cruas e a tela dizia "CPU ID 109", "Mem ID 98" e software com
            # coluna de nome vazia. Um tecnico atendendo um chamado precisa do
            # modelo do processador e do tipo da memoria (DDR3/DDR4, UDIMM/
            # SODIMM) — um id nao responde nada, e a tela parecia preenchida.
            async def _safe_subitems(subtype: str):
                try:
                    return await _gc.get_subitems(
                        "Computer",
                        computer_id,
                        subtype,
                        params={"expand_dropdowns": "true"},
                    )
                except Exception as e:
                    logger.warning(
                        f"get_computer_details: subitems {subtype} failed: {e}"
                    )
                    return []

            import asyncio as _asyncio
            (
                operating_systems,
                disks,
                processors,
                memories,
                networks,
                software,
                drives,
                graphics,
                batteries,
                firmwares,
                antivirus,
                infocom,
            ) = await _asyncio.gather(
                _safe_subitems("Item_OperatingSystem"),
                _safe_subitems("Item_Disk"),
                _safe_subitems("Item_DeviceProcessor"),
                _safe_subitems("Item_DeviceMemory"),
                _safe_subitems("NetworkPort"),
                _safe_subitems("Item_SoftwareVersion"),
                # Disco FISICO: e aqui que mora SSD vs HDD e a capacidade real.
                # Item_Disk sao volumes logicos (C:, D:) — outra pergunta.
                _safe_subitems("Item_DeviceHardDrive"),
                _safe_subitems("Item_DeviceGraphicCard"),
                # Bateria: em notebook, "quanto tempo dura" e chamado recorrente.
                _safe_subitems("Item_DeviceBattery"),
                # Firmware/BIOS: versao de BIOS entra em diagnostico e em
                # requisito de atualizacao.
                _safe_subitems("Item_DeviceFirmware"),
                _safe_subitems("ComputerAntivirus"),
                # Infocom: garantia, data de compra, fornecedor — decide se o
                # reparo e por contrato ou por conta da empresa.
                _safe_subitems("Infocom"),
            )

            await _resolve_software_names(_gc, software or [])
            await _attach_search_only_columns(_gc, computer_id, computer)

            enriched = {
                "asset": computer,
                "operating_systems": operating_systems or [],
                "disks": disks or [],
                "processors": processors or [],
                "memories": memories or [],
                "networks": networks or [],
                "software": software or [],
                "drives": drives or [],
                "graphics": graphics or [],
                "batteries": batteries or [],
                "firmwares": firmwares or [],
                "antivirus": antivirus or [],
                "infocom": infocom or [],
            }

            # NOTE: Do NOT apply response_truncator.truncate_json_response here.
            # The truncator serializes nested dicts > 1000 chars into stringified
            # placeholders, which would destroy the {asset, disks, ...} shape
            # expected by format_computer_details_enriched. If the response is
            # actually too large, cap sub-lists at their source instead.
            logger.info(
                f"get_computer_details completed: computer {computer_id}, "
                f"os={len(enriched.get('operating_systems', []))}, "
                f"disks={len(enriched.get('disks', []))}, "
                f"cpus={len(enriched.get('processors', []))}, "
                f"mem={len(enriched.get('memories', []))}"
            )
            return enriched

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
        offset: int = 0,
        assigned_user: Optional[Any] = None,
        sort_by: Optional[Any] = None,
        order: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Tool MCP: list_monitors
        Lista monitores com filtros específicos

        Args:
            entity_id: Filtrar por entidade (ID numérico)
            entity_name: Filtrar por nome da entidade/cliente (ex: "Acme Corp", "Example Client")
            location_id: Filtrar por localização
            manufacturer_id: Filtrar por fabricante
            limit: Limite de resultados
            offset: Offset para paginação
            assigned_user: Filtrar por responsável (NOME ou ID numérico)
            sort_by: Coluna de ordenação (nome amigável ou ID do campo GLPI)
            order: Direção da ordenação (asc/desc)

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
                if resolved_id is not None:
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
                use_cache=True,
                assigned_user=assigned_user,
                sort_by=sort_by,
                order=order
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
