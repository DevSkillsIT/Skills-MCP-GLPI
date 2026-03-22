"""
Asset Service - Conforme SPEC.md seção 4.3
Migrado e expandido de glpi_service.py existente
Implementa operações CRUD de assets + reservas + validação
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import asyncio

from src.services.glpi_client import glpi_client
from src.logger import logger
from src.models.exceptions import (
    NotFoundError,
    ValidationError,
    GLPIError
)


class AssetService:
    """
    Serviço de gerenciamento de assets GLPI.
    
    Funcionalidades:
    - CRUD completo de assets (Computers, Monitors, Printers, etc.)
    - Sistema de reservas de assets
    - Busca avançada com filtros
    - Validação de dados
    - Paginação inteligente
    """
    
    def __init__(self):
        """Inicializa o serviço de assets."""
        self.client = glpi_client
        
        # Tipos de assets suportados pelo GLPI
        self.asset_types = [
            "Computer", "Monitor", "Printer", "NetworkEquipment",
            "Peripheral", "Software", "Phone", "PassiveDCEquipment",
            "Rack", "Enclosure", "PDU", "Server", "Storage",
            "Appliance", "Cable", "Plug", "Line", "Certificate",
            "Database", "Domain", "Entity", "Group", "Location",
            "Profile", "User", "Ticket", "Problem", "Change",
            "Project", "ProjectTask", "Cost", "Budget", "Supplier",
            "Contact", "Contract", "Document", "KnowbaseItem",
            "KnowbaseCategory", "Reminder", "RSSFeed", "Tool",
            "Cluster", "CartridgeItem", "ConsumableItem", "Link",
            "SoftwareLicense", "SoftwareVersion", "OperatingSystem",
            "VirtualMachine", "Rule", "ImportExternal", "AuthLDAP",
            "AuthMail", "Entity", "Profile", "User", "Group",
            "SLA", "OLA", "LevelAgreement", "LevelAgreementLevel",
            "ITILCategory", "ITILFollowup", "ITILSolution", "ITILTask",
            "ITILTaskCategory", "ITILActor", "Calendar", "Holiday",
            "CalendarSegment", "CalendarHoliday", "Notification",
            "NotificationTemplate", "NotificationEvent", "QueuedNotification",
            "CronTask", "CronTaskLog", "Plugin", "Fieldblacklist",
            "Fieldunicity", "SsoVariable", "Lockedfield", "Device",
            "DeviceMemory", "DeviceProcessor", "DeviceHardDrive",
            "DeviceNetworkCard", "DeviceDrive", "DeviceGraphicCard",
            "DeviceSoundCard", "DeviceMotherboard", "DeviceControl",
            "DeviceCase", "DevicePowerSupply", "DevicePci",
            "DeviceFirmware", "DeviceSimcard", "DeviceSimcardType",
            "DeviceBattery", "DeviceCamera", "DeviceSpeaker",
            "DeviceHeadphone", "DeviceMicrophone", "DeviceRemote",
            "DeviceKeyboard", "DeviceMouse", "DeviceJoypad",
            "DeviceGamepad", "DeviceOther", "DeviceGeneric",
            "DeviceSpecific", "DeviceVirtual", "DevicePhysical",
            "DeviceLogical", "DeviceInternal", "DeviceExternal",
            "DeviceEmbedded", "DeviceRemovable", "DeviceFixed",
            "DeviceHotpluggable", "DeviceNonHotpluggable",
            "DeviceWired", "DeviceWireless", "DeviceBluetooth",
            "DeviceWifi", "DeviceCellular", "DeviceSatellite",
            "DeviceMicrowave", "DeviceRadio", "DeviceInfrared",
            "DeviceLaser", "DeviceUltrasonic", "DeviceMagnetic",
            "DeviceOptical", "DeviceElectrical", "DeviceMechanical",
            "DeviceChemical", "DeviceBiological", "DeviceNuclear"
        ]
        
        logger.info("AssetService initialized")
    
    async def list_assets(
        self,
        asset_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        location_id: Optional[int] = None,
        manufacturer_id: Optional[int] = None,
        model_id: Optional[int] = None,
        status: Optional[str] = None,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        is_template: Optional[bool] = None,
        limit: int = 250,
        offset: int = 0,
        use_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Lista assets com filtros avançados.

        IMPORTANTE: Quando há filtros (entity_id, location_id, etc.), usa o endpoint
        de busca /apirest.php/search/{type} que suporta criteria.
        Quando não há filtros, usa o endpoint simples /apirest.php/{type}.

        Args:
            asset_type: Tipo de asset (Computer, Monitor, etc.)
            entity_id: Filtrar por entidade/cliente
            location_id: Filtrar por localização
            manufacturer_id: Filtrar por fabricante
            model_id: Filtrar por modelo
            status: Filtrar por status
            user_id: Filtrar por ID do usuário responsável
            username: Filtrar por nome do usuário (requer resolução para ID)
            is_template: Filtrar templates
            limit: Limite de resultados
            offset: Offset para paginação
            use_cache: Usar cache

        Returns:
            Lista de assets
        """
        # Validar tipo de asset
        item_type = asset_type or "Computer"
        if item_type not in self.asset_types:
            raise ValidationError(
                f"Asset type must be one of: {self.asset_types[:10]}...",
                "asset_type"
            )

        # Construir critérios de busca no formato GLPI Search API
        # Referência campos: https://glpi-user-documentation.readthedocs.io/
        # Campo 80 = entities_id (Entity)
        # Campo 3 = locations_id (Location)
        # Campo 23 = manufacturers_id (Manufacturer)
        # Campo 40 = models_id (Model)
        # Campo 31 = states_id (Status)
        # Campo 70 = users_id (User)
        criteria = []

        if entity_id:
            criteria.append({
                "field": 80,  # Entity field ID na Search API
                "searchtype": "under",  # "under" busca na entidade E todas as sub-entidades (filhos)
                "value": entity_id
            })

        if location_id:
            criteria.append({
                "field": 3,  # Location field ID
                "searchtype": "equals",
                "value": location_id
            })

        if manufacturer_id:
            criteria.append({
                "field": 23,  # Manufacturer field ID
                "searchtype": "equals",
                "value": manufacturer_id
            })

        if model_id:
            criteria.append({
                "field": 40,  # Model field ID
                "searchtype": "equals",
                "value": model_id
            })

        if status:
            criteria.append({
                "field": 31,  # Status field ID
                "searchtype": "equals",
                "value": status
            })
            
        # Filtro por usuário
        target_user_id = user_id
        
        # Tentar resolver username se fornecido e user_id não
        if username and not target_user_id:
            # TODO: Implementar resolução de username via serviço de usuários
            # Por enquanto, logamos aviso. O ideal é o caller passar user_id.
            logger.warning(f"Filtering by username '{username}' requires resolving to ID first. Please provide user_id.")
            
        if target_user_id:
            criteria.append({
                "field": 70,  # User field ID
                "searchtype": "equals",
                "value": target_user_id
            })

        if is_template is not None:
            criteria.append({
                "field": 47,  # is_template field ID
                "searchtype": "equals",
                "value": 1 if is_template else 0
            })

        # Campos a exibir (IDs numéricos para Search API)
        # 1=name, 2=id, 5=serial, 6=otherserial, 31=states_id, 3=locations_id
        # 80=entities_id, 70=users_id, 71=groups_id, 23=manufacturers_id, 40=models_id
        forcedisplay_ids = [1, 2, 5, 6, 31, 3, 80, 70, 71, 23, 40, 19, 16, 4]

        try:
            # Se há filtros, usar Search API que suporta criteria
            if criteria:
                logger.info(f"Listing {item_type} assets with filters via Search API: entity_id={entity_id}, user_id={target_user_id}")
                result = await self.client.search(
                    item_type=item_type,
                    criteria=criteria,
                    forcedisplay=forcedisplay_ids,
                    range_limit=limit,
                    range_offset=offset,
                    is_recursive=entity_id is not None  # Buscar em sub-entidades quando filtrar por entity
                )
            else:
                # Sem filtros, usar endpoint simples (mais rápido)
                logger.info(f"Listing {item_type} assets without filters")
                params = {
                    "range": f"{offset}-{offset + limit - 1}"
                }
                endpoint = f"/apirest.php/{item_type}"
                result = await self.client.get(endpoint, params, use_cache)

            # API pode retornar lista diretamente ou dict com "data"
            if isinstance(result, list):
                assets = result
            elif isinstance(result, dict) and "data" in result:
                assets = result["data"]
            else:
                return []

            # Normalizar nomes de campos (Search API usa IDs numéricos)
            normalized_assets = []
            for asset in assets:
                # Se veio da Search API, os campos são numéricos
                if criteria and isinstance(asset, dict):
                    normalized = {
                        "id": asset.get("2") or asset.get("id"),
                        "name": asset.get("1") or asset.get("name"),
                        "serial": asset.get("5") or asset.get("serial"),
                        "otherserial": asset.get("6") or asset.get("otherserial"),
                        "states_id": asset.get("31") or asset.get("states_id"),
                        "locations_id": asset.get("3") or asset.get("locations_id"),
                        "entities_id": asset.get("80") or asset.get("entities_id"),
                        "users_id": asset.get("70") or asset.get("users_id"),
                        "groups_id": asset.get("71") or asset.get("groups_id"),
                        "manufacturers_id": asset.get("23") or asset.get("manufacturers_id"),
                        "models_id": asset.get("40") or asset.get("models_id"),
                        "date_mod": asset.get("19") or asset.get("date_mod"),
                        "comment": asset.get("16") or asset.get("comment"),
                        "types_id": asset.get("4") or asset.get("types_id"),
                        "asset_type": item_type
                    }
                    # Remover campos None
                    normalized = {k: v for k, v in normalized.items() if v is not None}
                    normalized_assets.append(normalized)
                else:
                    asset["asset_type"] = item_type
                    normalized_assets.append(asset)

            # Adicionar metadados de paginação (só disponível quando API retorna dict)
            if isinstance(result, dict) and "totalcount" in result:
                total_count = result["totalcount"]
                has_more = offset + limit < total_count
                next_offset = offset + limit if has_more else None
                
                # Se for computador, enriquecer com dados detalhados (CPU, RAM, AnyDesk)
                if item_type == "Computer" and normalized_assets:
                    logger.info(f"Enriching {len(normalized_assets)} computers with detailed info...")
                    normalized_assets = await self._enrich_computers(normalized_assets)

                # Retornar assets com metadados se houver muitos
                if total_count > limit:
                    return {
                        "assets": normalized_assets,
                        "pagination": {
                            "total": total_count,
                            "offset": offset,
                            "limit": limit,
                            "has_more": has_more,
                            "next_offset": next_offset
                        },
                        "filters_applied": {
                            "entity_id": entity_id,
                            "location_id": location_id,
                            "manufacturer_id": manufacturer_id,
                            "user_id": target_user_id
                        },
                        "hint": f"Use offset parameter to get more assets. Total: {total_count}"
                    }
            
            # Se for lista simples e for computador, também enriquecer
            if item_type == "Computer" and normalized_assets:
                logger.info(f"Enriching {len(normalized_assets)} computers with detailed info...")
                normalized_assets = await self._enrich_computers(normalized_assets)

            return normalized_assets

        except Exception as e:
            logger.error(f"Failed to list {item_type} assets: {e}")
            raise GLPIError(500, f"Failed to list assets: {str(e)}")

    async def _enrich_computers(self, computers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Enriquece lista de computadores com dados de subitens em paralelo.
        Busca: CPU, RAM, AnyDesk, Last Inventory.
        """
        tasks = []
        for comp in computers:
            tasks.append(self._enrich_single_computer(comp))
        
        # Executar todas as buscas em paralelo
        enriched_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filtrar resultados (ignorar falhas silenciosamente para não quebrar a lista)
        final_list = []
        for res in enriched_results:
            if isinstance(res, dict):
                final_list.append(res)
            else:
                # Se falhou, retorna o original (não perdemos o item) ou loga erro
                logger.warning(f"Enrichment failed for one item: {res}")
        
        # Se algo deu muito errado e a lista ficou vazia (improvável), retorne a original
        return final_list if final_list else computers

    async def _enrich_single_computer(self, comp: Dict[str, Any]) -> Dict[str, Any]:
        """Busca detalhes para um único computador, incluindo dados do usuário."""
        try:
            cid = comp.get("id")
            if not cid:
                return comp

            # Disparar chamadas em paralelo para este computador
            # 1. Detalhes gerais (para pegar last_inventory_update)
            # 2. Remote Management (AnyDesk)
            # 3. CPU
            # 4. Memória

            # OBS: get_item já retorna alguns dados, mas precisamos de subitens para CPU/RAM/AnyDesk
            # Para otimizar, não vamos chamar get_asset completo (que é muito pesado),
            # mas sim endpoints específicos ou reutilizar get_item leve.

            # Buscar item principal leve para pegar last_inventory_update e users_id
            task_details = self.client.get_item("Computer", cid, forcedisplay=["last_inventory_update", "contact", "contact_num", "users_id"])
            task_remote = self.client.get_subitems("Computer", cid, "Item_RemoteManagement")
            # Solicitar expansão de dropdowns para pegar o nome do processador
            task_cpu = self.client.get_subitems("Computer", cid, "Item_DeviceProcessor", params={"expand_dropdowns": "true"})
            task_mem = self.client.get_subitems("Computer", cid, "Item_DeviceMemory")

            # Await all
            details, remote_list, cpu_list, mem_list = await asyncio.gather(
                task_details, task_remote, task_cpu, task_mem, return_exceptions=True
            )
            
            # Processar Detalhes
            if isinstance(details, dict):
                comp["last_inventory_update"] = details.get("last_inventory_update")
                # Se o contato não veio na busca inicial, pega agora
                if "contact" not in comp and details.get("contact"):
                    comp["contact"] = details.get("contact")
                # Pegar users_id para enriquecer com dados do usuário
                if "users_id" not in comp and details.get("users_id"):
                    comp["users_id"] = details.get("users_id")

            # ============ ENRIQUECIMENTO DO USUÁRIO ============
            # Se temos users_id, buscar dados do usuário (nome, email, status deletado)
            user_id = comp.get("users_id")
            if user_id and str(user_id).isdigit():
                try:
                    user_data = await self.client.get_item("User", int(user_id),
                        forcedisplay=["id", "name", "firstname", "realname", "email", "is_active", "is_deleted"])

                    if isinstance(user_data, dict):
                        # Criar objeto user_info com dados enriquecidos
                        user_info = {
                            "id": user_data.get("id"),
                            "login": user_data.get("name"),
                            "firstname": user_data.get("firstname"),
                            "realname": user_data.get("realname"),
                            "fullname": f"{user_data.get('firstname', '')} {user_data.get('realname', '')}".strip(),
                            "email": user_data.get("email"),
                            "is_active": user_data.get("is_active", 1) == 1,
                            "is_deleted": user_data.get("is_deleted", 0) == 1
                        }
                        comp["user_info"] = user_info

                        # Alerta se usuário deletado
                        if user_info["is_deleted"]:
                            comp["user_warning"] = "USUÁRIO DELETADO - Este usuário foi removido do sistema (possivelmente sync LDAP)"

                except Exception as e:
                    logger.warning(f"Could not enrich user {user_id} for computer {cid}: {e}")
                    comp["user_info"] = {"id": user_id, "error": "Não foi possível obter dados do usuário"}
            
            # Processar AnyDesk (Remote Management)
            anydesk_id = "N/A"
            if isinstance(remote_list, list):
                for rm in remote_list:
                    # Tentar identificar AnyDesk pelo tipo ou assumir o ID remoto
                    # O campo 'type' pode ser 'anydesk' ou similar
                    r_type = str(rm.get("type", "")).lower()
                    if "anydesk" in r_type or "teamviewer" in r_type or rm.get("remoteid"):
                        anydesk_id = rm.get("remoteid")
                        if "anydesk" in r_type: # Prioridade para anydesk se houver múltiplos
                            break 
            comp["anydesk_id"] = anydesk_id
            
            # Processar CPU (Pegar o modelo do primeiro processador e a contagem)
            cpu_info = "N/A"
            if isinstance(cpu_list, list) and cpu_list:
                count = len(cpu_list)
                first_cpu = cpu_list[0]
                cpu_model = "Processor"
                
                # Com expand_dropdowns, o ID vira o nome (str)
                proc_id_val = first_cpu.get("deviceprocessors_id")
                if isinstance(proc_id_val, str):
                    cpu_model = proc_id_val
                elif first_cpu.get("designation"):
                    cpu_model = first_cpu.get("designation")
                
                freq = first_cpu.get('frequency', '')
                freq_str = f" @ {freq}MHz" if freq else ""
                
                cpu_info = f"{count}x {cpu_model}{freq_str}"
                
            comp["cpu_info"] = cpu_info

            # Processar Memória (Somar tamanho)
            total_mem = 0
            if isinstance(mem_list, list):
                for mem in mem_list:
                    try:
                        size = int(mem.get("size", 0))
                        total_mem += size
                    except:
                        pass
            
            # Converter MB para GB se > 1024
            if total_mem > 0:
                if total_mem >= 1024:
                    comp["memory_info"] = f"{total_mem/1024:.1f} GB"
                else:
                    comp["memory_info"] = f"{total_mem} MB"
            else:
                comp["memory_info"] = "N/A"

            return comp

        except Exception as e:
            logger.warning(f"Error enriching computer {comp.get('id')}: {e}")
            return comp

    
    async def get_asset(self, asset_type: str, asset_id: int) -> Dict[str, Any]:
        """
        Obtém detalhes completos de um asset.
        
        Args:
            asset_type: Tipo de asset
            asset_id: ID do asset
        
        Returns:
            Dados completos do asset
        """
        # Validar tipo de asset
        if asset_type not in self.asset_types:
            raise ValidationError(
                f"Asset type must be one of: {self.asset_types[:10]}...", 
                "asset_type"
            )
        
        try:
            logger.info(f"Getting {asset_type} {asset_id}")
            
            # Obter dados principais do asset
            asset = await self.client.get_item(
                asset_type,
                asset_id,
                forcedisplay=[
                    "id", "name", "serial", "otherserial", "status",
                    "states_id", "locations_id", "entities_id", "users_id",
                    "groups_id", "manufacturers_id", "models_id", "types_id",
                    "is_template", "template_name", "date_creation", "date_mod",
                    "comment", "contact", "contact_num", "user", "group",
                    "autoupdatesystems_id", "networks_id", "operatingsystems_id",
                    "operatingsystemversions_id", "domains_id", "uuid",
                    "last_inventory_update", "last_boot"
                ]
            )
            
            # Adicionar tipo do asset
            asset["asset_type"] = asset_type
            
            # Obter componentes relacionados se for Computer
            if asset_type == "Computer":
                try:
                    # Obter memória
                    memory_items = await self.client.get_subitems("Computer", asset_id, "Item_DeviceMemory")
                    asset["memory"] = memory_items
                    
                    # Obter processadores
                    cpu_items = await self.client.get_subitems("Computer", asset_id, "Item_DeviceProcessor")
                    asset["processors"] = cpu_items
                    
                    # Obter discos
                    disk_items = await self.client.get_subitems("Computer", asset_id, "Item_DeviceHardDrive")
                    asset["disks"] = disk_items
                    
                    # Obter placas de rede
                    network_items = await self.client.get_subitems("Computer", asset_id, "Item_DeviceNetworkCard")
                    asset["network_cards"] = network_items

                    # Obter sistema operacional
                    os_items = await self.client.get_subitems("Computer", asset_id, "Item_OperatingSystem")
                    asset["operating_system"] = os_items

                    # Obter software instalado
                    software_items = await self.client.get_subitems("Computer", asset_id, "Item_SoftwareVersion")
                    asset["software"] = software_items

                    # Obter gerenciamento remoto (ex: AnyDesk, TeamViewer)
                    remote_management_items = await self.client.get_subitems("Computer", asset_id, "Item_RemoteManagement")
                    asset["remote_management"] = remote_management_items
                    
                except Exception as e:
                    logger.warning(f"Failed to get components for {asset_type} {asset_id}: {e}")
                    asset["memory"] = []
                    asset["processors"] = []
                    asset["disks"] = []
                    asset["network_cards"] = []
                    asset["operating_system"] = []
                    asset["software"] = []
                    asset["remote_management"] = []
            
            # Obter histórico de alterações
            try:
                logs = await self.client.get_subitems(asset_type, asset_id, "Log")
                asset["history"] = logs
            except Exception:
                asset["history"] = []
            
            return asset
            
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to get {asset_type} {asset_id}: {e}")
            raise GLPIError(500, f"Failed to get asset: {str(e)}")
    
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
        comment: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Cria um novo asset com validação completa.
        
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
            **kwargs: Campos adicionais específicos do tipo
        
        Returns:
            Asset criado
        """
        # Validações conforme SPEC.md
        if asset_type not in self.asset_types:
            raise ValidationError(
                f"Asset type must be one of: {self.asset_types[:10]}...", 
                "asset_type"
            )
        
        if not name or len(name.strip()) < 2:
            raise ValidationError("Name must be at least 2 characters", "name")
        
        # Construir payload
        payload = {
            "name": name.strip(),
            "entities_id": entity_id or 0  # Entidade raiz se não especificado
        }
        
        # Campos opcionais
        if serial_number:
            payload["serial"] = serial_number.strip()
        
        if other_serial:
            payload["otherserial"] = other_serial.strip()
        
        if status:
            payload["states_id"] = status
        
        if location_id:
            payload["locations_id"] = location_id
        
        if manufacturer_id:
            payload["manufacturers_id"] = manufacturer_id
        
        if model_id:
            payload["models_id"] = model_id
        
        if user_id:
            payload["users_id"] = user_id
        
        if group_id:
            payload["groups_id"] = group_id
        
        if comment:
            payload["comment"] = comment.strip()
        
        # Adicionar campos específicos do tipo
        payload.update(kwargs)
        
        try:
            logger.info(f"Creating {asset_type}: {name}")
            result = await self.client.post(f"/apirest.php/{asset_type}", payload)
            
            if "id" not in result:
                raise GLPIError(500, f"Failed to create {asset_type} - no ID returned")
            
            # Retornar asset completo
            created_asset = await self.get_asset(asset_type, result["id"])
            
            logger.info(f"{asset_type} created successfully: ID {result['id']}")
            return created_asset
            
        except Exception as e:
            logger.error(f"Failed to create {asset_type}: {e}")
            raise GLPIError(500, f"Failed to create asset: {str(e)}")
    
    async def update_asset(
        self,
        asset_type: str,
        asset_id: int,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Atualiza um asset existente.
        
        Args:
            asset_type: Tipo de asset
            asset_id: ID do asset
            **kwargs: Campos para atualizar
        
        Returns:
            Asset atualizado
        """
        # Validar asset existe
        await self.get_asset(asset_type, asset_id)
        
        # Remover campos que não devem ser atualizados diretamente
        protected_fields = ["id", "asset_type", "date_creation", "date_mod"]
        update_payload = {k: v for k, v in kwargs.items() if k not in protected_fields}
        
        if not update_payload:
            raise ValidationError("No valid fields to update", "payload")
        
        try:
            logger.info(f"Updating {asset_type} {asset_id} with fields: {list(update_payload.keys())}")
            await self.client.put(f"/apirest.php/{asset_type}/{asset_id}", update_payload)
            
            # Retornar asset atualizado
            updated_asset = await self.get_asset(asset_type, asset_id)
            
            logger.info(f"{asset_type} {asset_id} updated successfully")
            return updated_asset
            
        except Exception as e:
            logger.error(f"Failed to update {asset_type} {asset_id}: {e}")
            raise GLPIError(500, f"Failed to update asset: {str(e)}")
    
    async def delete_asset(self, asset_type: str, asset_id: int) -> bool:
        """
        Deleta um asset permanentemente.
        
        Args:
            asset_type: Tipo de asset
            asset_id: ID do asset
        
        Returns:
            True se deletado com sucesso
        """
        # Validar asset existe
        await self.get_asset(asset_type, asset_id)
        
        try:
            logger.info(f"Deleting {asset_type} {asset_id}")
            await self.client.delete(f"/apirest.php/{asset_type}/{asset_id}")
            
            logger.info(f"{asset_type} {asset_id} deleted successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete {asset_type} {asset_id}: {e}")
            raise GLPIError(500, f"Failed to delete asset: {str(e)}")
    
    async def search_assets(
        self,
        query: str,
        asset_type: Optional[str] = None,
        entity_id: Optional[int] = None,
        fields: Optional[List[str]] = None,
        limit: int = 250,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Busca assets por texto livre com Smart Search otimizado.

        Lógica Smart Search v2.0:
        1. Busca direta no campo 'contact' (Nome Alternativo do Usuário) - texto livre
        2. Busca usuários que correspondam ao texto (login, firstname, realname)
        3. Combina TODOS os resultados (não para ao encontrar parciais)
        4. Busca em: Nome, Serial, Contact, users_id vinculados

        IMPORTANTE - Field IDs GLPI para Computer:
        - Field 1: name (Nome do Computador)
        - Field 2: id (ID)
        - Field 5: serial (Número de Série)
        - Field 6: otherserial (Número de Inventário)
        - Field 7: contact (Nome Alternativo do Usuário - TEXTO)
        - Field 8: contact_num (Número de Contato)
        - Field 70: users_id (Usuário - SELECT/FK)
        - Field 80: entities_id (Entidade)

        Args:
            query: Texto para buscar (Nome, Serial, Contact ou Nome do Usuário)
            asset_type: Tipo de asset específico
            entity_id: Filtrar por entidade/cliente
            fields: Campos específicos para retornar
            limit: Limite de resultados
            offset: Offset para paginação

        Returns:
            Assets que correspondem à busca (sempre incluindo ID)
        """
        try:
            logger.info(f"Smart Searching {asset_type or 'all'} assets with query: {query}, entity_id: {entity_id}")

            # 1. SMART SEARCH: Buscar IDs de usuários que dão match com a query
            # Inclui busca em ATIVOS e DELETADOS para cobrir usuários removidos via LDAP sync
            found_user_ids = []
            deleted_user_ids = []
            if len(query) > 2:
                try:
                    # Busca ampla de usuários (GLOBAL) - Removemos o filtro de entidade aqui
                    # Motivo: O usuário pode estar em uma sub-entidade profunda.
                    # Achamos TODOS os usuários "Werles" do sistema, pegamos seus IDs.
                    # O filtro de entidade será aplicado na busca final dos computadores (assets).
                    user_criteria = [
                        {"field": 1, "searchtype": "contains", "value": query}, # Login
                        {"link": "OR", "field": 9, "searchtype": "contains", "value": query}, # Firstname
                        {"link": "OR", "field": 34, "searchtype": "contains", "value": query} # Realname
                    ]

                    # Removido propositalmente: filtro de entidade na busca de USER.
                    # if entity_id: ...

                    user_results = await self.client.search(
                        item_type="User",
                        search_text=None,
                        criteria=user_criteria,
                        range_limit=50,
                        forcedisplay=[2] # Apenas ID
                    )

                    if isinstance(user_results, list):
                        for u in user_results:
                            uid = u.get("2") or u.get("id")
                            if uid: found_user_ids.append(uid)
                    elif isinstance(user_results, dict) and "data" in user_results:
                        for u in user_results["data"]:
                            uid = u.get("2") or u.get("id")
                            if uid: found_user_ids.append(uid)

                    if found_user_ids:
                        logger.info(f"Smart Search: Found {len(found_user_ids)} ACTIVE users matching '{query}': {found_user_ids}")

                    # ============ FALLBACK: BUSCAR USUÁRIOS DELETADOS ============
                    # Se não encontrou nenhum usuário ativo, buscar nos deletados
                    # NOTA: GLPI usa ?is_deleted=1 como parâmetro, não como critério de busca
                    if not found_user_ids:
                        logger.info(f"Smart Search: Nenhum usuário ativo encontrado para '{query}', buscando nos deletados...")

                        # Montar parâmetros manualmente para incluir is_deleted=1
                        deleted_params = {"is_deleted": 1, "range": "0-49"}
                        for i, crit in enumerate(user_criteria):
                            for key, value in crit.items():
                                deleted_params[f"criteria[{i}][{key}]"] = value
                        deleted_params["forcedisplay[0]"] = 2

                        deleted_results = await self.client.get("/apirest.php/search/User", deleted_params, use_cache=False)

                        if isinstance(deleted_results, list):
                            for u in deleted_results:
                                uid = u.get("2") or u.get("id")
                                if uid: deleted_user_ids.append(uid)
                        elif isinstance(deleted_results, dict) and "data" in deleted_results:
                            for u in deleted_results["data"]:
                                uid = u.get("2") or u.get("id")
                                if uid: deleted_user_ids.append(uid)

                        if deleted_user_ids:
                            logger.info(f"Smart Search: Found {len(deleted_user_ids)} DELETED users matching '{query}': {deleted_user_ids}")
                            # Usar os IDs deletados como se fossem ativos para a busca de assets
                            found_user_ids = deleted_user_ids

                except Exception as e:
                    logger.warning(f"Smart Search user lookup failed (ignoring): {e}")

            # 2. Construir Critérios do Asset
            criteria = []
            
            # Filtro de entidade (AND mandatório)
            if entity_id:
                criteria.append({
                    "field": 80, # Entity
                    "searchtype": "under", # Recursivo
                    "value": entity_id,
                    "link": "AND"
                })

            # ============ GRUPO OR PRINCIPAL - BUSCA MULTI-CAMPO ============
            # Busca com OR para máxima cobertura - não para ao encontrar parciais

            # Name (Field 1) - Nome do Computador
            criteria.append({
                "link": "AND" if entity_id else "",
                "field": 1,
                "searchtype": "contains",
                "value": query
            })

            # Serial (Field 5) - Número de Série
            criteria.append({
                "link": "OR",
                "field": 5,
                "searchtype": "contains",
                "value": query
            })

            # ============ NOVO: Contact (Field 7) - Nome Alternativo do Usuário ============
            # Campo de texto livre que pode conter: "joana.rodrigues@GRUPOWINK"
            # CRÍTICO: Permite encontrar computadores mesmo sem users_id vinculado
            criteria.append({
                "link": "OR",
                "field": 7,  # Contact = Nome Alternativo do Usuário (TEXTO)
                "searchtype": "contains",
                "value": query
            })

            # Se a query for numérica, tentar ID do ativo
            if query.isdigit():
                criteria.append({
                    "link": "OR",
                    "field": 2, # ID
                    "searchtype": "equals",
                    "value": query
                })

            # ============ SMART LINK: IDs de Usuários Encontrados ============
            # Adiciona busca por users_id (Field 70) para cada usuário encontrado
            # NOTA: Isso é ADICIONAL ao campo contact - ambos são pesquisados
            for uid in found_user_ids:
                criteria.append({
                    "link": "OR",
                    "field": 70, # User ID (SELECT/FK)
                    "searchtype": "equals",
                    "value": uid
                })

            # Executar busca final
            # forcedisplay inclui Field 7 (contact) e Field 8 (contact_num)
            result = await self.client.search(
                item_type=asset_type or "Computer",
                search_text=None,
                range_limit=limit,
                range_offset=offset,
                criteria=criteria,
                forcedisplay=fields or [1, 2, 5, 6, 7, 8, 31, 3, 80, 70, 71, 23, 40, 19, 16, 4]
                #                        ^name ^id ^serial ^other ^contact ^contact_num ...
            )

            # Processar resultados
            if isinstance(result, list):
                assets = result
            elif isinstance(result, dict) and "data" in result:
                assets = result["data"]
            else:
                return []

            # Normalizar resultados
            normalized_assets = []
            for asset in assets:
                # Extrair valores com fallback para ambos os formatos (Field ID ou nome)
                user_val = asset.get("70") or asset.get("users_id")
                contact_val = asset.get("7") or asset.get("contact")
                contact_num_val = asset.get("8") or asset.get("contact_num")

                normalized = {
                    "id": asset.get("2") or asset.get("id"),
                    "name": asset.get("1") or asset.get("name"),
                    "serial": asset.get("5") or asset.get("serial"),
                    "otherserial": asset.get("6") or asset.get("otherserial"),
                    # NOVO: Contact (Nome Alternativo do Usuário)
                    "contact": contact_val,
                    "contact_num": contact_num_val,
                    "status": asset.get("31") or asset.get("states_id"),
                    "locations_id": asset.get("3") or asset.get("locations_id"),
                    "manufacturers_id": asset.get("23") or asset.get("manufacturers_id"),
                    "models_id": asset.get("40") or asset.get("models_id"),
                    "entities_id": asset.get("80") or asset.get("entities_id"),
                    "users_id": user_val,
                    "groups_id": asset.get("71") or asset.get("groups_id"),
                    "date_mod": asset.get("19") or asset.get("date_mod"),
                    "comment": asset.get("16") or asset.get("comment"),
                    "types_id": asset.get("4") or asset.get("types_id"),
                    "asset_type": asset_type or "Computer"
                }
                # Remover chaves nulas para limpar o JSON
                normalized = {k: v for k, v in normalized.items() if v is not None}
                normalized_assets.append(normalized)
            
            # Hint de paginação
            if isinstance(result, dict) and "totalcount" in result and result["totalcount"] > limit:
                normalized_assets.append({
                    "search_hint": f"Found {result['totalcount']} total results. Use pagination to get more."
                })

            # Adicionar aviso se a busca foi feita via usuário deletado
            if deleted_user_ids and normalized_assets:
                normalized_assets.insert(0, {
                    "smart_search_warning": f"Assets encontrados via USUÁRIO DELETADO (IDs: {deleted_user_ids}). O usuário foi removido do sistema (possivelmente sync LDAP).",
                    "deleted_user_ids": deleted_user_ids
                })

            return normalized_assets
                
        except Exception as e:
            logger.error(f"Failed to search assets: {e}")
            raise GLPIError(500, f"Failed to search assets: {str(e)}")
    
    async def get_asset_reservations(
        self,
        asset_type: str,
        asset_id: int,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Obtém reservas de um asset.
        
        Args:
            asset_type: Tipo de asset
            asset_id: ID do asset
            date_from: Data inicial (YYYY-MM-DD)
            date_to: Data final (YYYY-MM-DD)
        
        Returns:
            Lista de reservas
        """
        try:
            logger.info(f"Getting reservations for {asset_type} {asset_id}")
            
            # Construir filtros de data
            criteria = [
                {
                    "field": "items_id",
                    "searchtype": "equals",
                    "value": asset_id
                },
                {
                    "field": "itemtype",
                    "searchtype": "equals",
                    "value": asset_type
                }
            ]
            
            if date_from:
                criteria.append({
                    "field": "begin",
                    "searchtype": "after",
                    "value": date_from + " 00:00:00"
                })
            
            if date_to:
                criteria.append({
                    "field": "end",
                    "searchtype": "before",
                    "value": date_to + " 23:59:59"
                })
            
            params = {
                "criteria": criteria,
                "forcedisplay": [
                    "id", "users_id", "items_id", "itemtype",
                    "begin", "end", "comment", "entities_id"
                ]
            }
            
            result = await self.client.get("/apirest.php/Reservation", params)
            
            # API pode retornar lista diretamente ou dict com "data"
            if isinstance(result, list):
                reservations = result
            elif isinstance(result, dict) and "data" in result:
                reservations = result["data"]
            else:
                return []
            
            # Enriquecer com dados dos usuários
            for reservation in reservations:
                try:
                    user_id = reservation.get("users_id")
                    if user_id:
                        user = await self.client.get_item("User", user_id, ["name", "realname", "email"])
                        reservation["user"] = user
                except Exception:
                    reservation["user"] = {"name": "Unknown"}
            
            return reservations
                
        except Exception as e:
            logger.error(f"Failed to get reservations for {asset_type} {asset_id}: {e}")
            raise GLPIError(500, f"Failed to get reservations: {str(e)}")

    async def list_reservable_items(
        self,
        entity_id: Optional[int] = None,
        is_active: Optional[bool] = None,
        itemtype: Optional[str] = None,
        limit: int = 250,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Lista todos os itens que podem ser reservados.
        
        No GLPI, um ReservationItem representa um item (Computer, Peripheral, etc)
        que foi configurado para ser reservável. A partir dele é possível criar
        reservas (Reservation).
        
        Args:
            entity_id: Filtrar por entidade
            is_active: Filtrar por status ativo (True=itens ativos para reserva)
            itemtype: Filtrar por tipo de item (Computer, Monitor, Peripheral, etc)
            limit: Limite de resultados (padrão: 50)
            offset: Offset para paginação (padrão: 0)
        
        Returns:
            Dict com lista de itens reserváveis e metadados
        """
        try:
            logger.info(f"Listing reservable items: entity={entity_id}, type={itemtype}")
            
            params = {
                "range": f"{offset}-{offset + limit - 1}",
                "expand_dropdowns": True
            }
            
            # Construir critérios de busca
            criteria = []
            
            if entity_id is not None:
                criteria.append({
                    "field": "entities_id",
                    "searchtype": "equals",
                    "value": entity_id
                })
            
            if is_active is not None:
                criteria.append({
                    "field": "is_active",
                    "searchtype": "equals",
                    "value": 1 if is_active else 0
                })
            
            if itemtype:
                criteria.append({
                    "field": "itemtype",
                    "searchtype": "equals",
                    "value": itemtype
                })
            
            if criteria:
                params["criteria"] = criteria
            
            result = await self.client.get("/apirest.php/ReservationItem", params)
            
            # Normalizar resposta
            if isinstance(result, list):
                items = result
            elif isinstance(result, dict) and "data" in result:
                items = result["data"]
            else:
                items = []
            
            # Enriquecer com informações do item real
            enriched_items = []
            for item in items:
                enriched = dict(item)
                
                # Buscar informações do item associado
                try:
                    item_type = item.get("itemtype")
                    items_id = item.get("items_id")
                    if item_type and items_id:
                        real_item = await self.client.get_item(item_type, items_id)
                        enriched["item_details"] = {
                            "id": real_item.get("id"),
                            "name": real_item.get("name"),
                            "serial": real_item.get("serial"),
                            "otherserial": real_item.get("otherserial"),
                            "itemtype": item_type
                        }
                except Exception as e:
                    logger.warning(f"Failed to get details for {item.get('itemtype')} {item.get('items_id')}: {e}")
                    enriched["item_details"] = None
                
                enriched_items.append(enriched)
            
            logger.info(f"Found {len(enriched_items)} reservable items")
            
            return {
                "reservable_items": enriched_items,
                "count": len(enriched_items),
                "pagination": {
                    "offset": offset,
                    "limit": limit
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to list reservable items: {e}")
            raise GLPIError(500, f"Failed to list reservable items: {str(e)}")

    async def list_reservations(self, limit: int = 250, offset: int = 0) -> List[Dict[str, Any]]:
        """Lista reservas de forma genérica."""
        params = {
            "range": f"{offset}-{offset + limit - 1}",
            "forcedisplay": [
                "id", "users_id", "items_id", "itemtype",
                "begin", "end", "comment", "entities_id"
            ]
        }
        result = await self.client.get("/apirest.php/Reservation", params)
        # API pode retornar lista diretamente ou dict com "data"
        if isinstance(result, list):
            return result
        elif isinstance(result, dict) and "data" in result:
            return result["data"]
        return []

    async def update_reservation(
        self,
        reservation_id: int,
        **kwargs
    ) -> Dict[str, Any]:
        """Atualiza uma reserva existente."""
        if reservation_id <= 0:
            raise ValidationError("reservation_id must be positive", "reservation_id")
        await self.client.put(f"/apirest.php/Reservation/{reservation_id}", kwargs)
        updated = await self.client.get_item("Reservation", reservation_id)
        return updated
    
    async def create_reservation(
        self,
        asset_type: str,
        asset_id: int,
        user_id: int,
        date_start: str,
        date_end: str,
        comment: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Cria uma reserva para um asset.
        
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
        # Validar asset existe
        await self.get_asset(asset_type, asset_id)
        
        # Validar datas
        try:
            start_dt = datetime.strptime(date_start, "%Y-%m-%d %H:%M:%S")
            end_dt = datetime.strptime(date_end, "%Y-%m-%d %H:%M:%S")
            
            if start_dt >= end_dt:
                raise ValidationError("End date must be after start date", "date_end")
            
            if start_dt < datetime.now():
                raise ValidationError("Start date cannot be in the past", "date_start")
            
        except ValueError:
            raise ValidationError("Invalid date format. Use YYYY-MM-DD HH:MM:SS", "date_format")
        
        # Verificar conflitos de reserva
        existing_reservations = await self.get_asset_reservations(
            asset_type, asset_id, date_start, date_end
        )
        
        if existing_reservations:
            raise ValidationError("Asset already reserved for this period", "reservation_conflict")
        
        # Construir payload
        payload = {
            "users_id": user_id,
            "items_id": asset_id,
            "itemtype": asset_type,
            "begin": date_start,
            "end": date_end
        }
        
        if comment:
            payload["comment"] = comment.strip()
        
        try:
            logger.info(f"Creating reservation for {asset_type} {asset_id}")
            result = await self.client.post("/apirest.php/Reservation", payload)
            
            if "id" not in result:
                raise GLPIError(500, "Failed to create reservation - no ID returned")
            
            # Obter reserva completa
            reservation_id = result["id"]
            reservation = await self.client.get_item("Reservation", reservation_id)
            
            logger.info(f"Reservation created successfully: ID {reservation_id}")
            return reservation
            
        except Exception as e:
            logger.error(f"Failed to create reservation: {e}")
            raise GLPIError(500, f"Failed to create reservation: {str(e)}")
    
    async def get_asset_stats(
        self,
        asset_type: Optional[str] = None,
        entity_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Obtém estatísticas de assets.
        
        Args:
            asset_type: Tipo de asset específico
            entity_id: Filtrar por entidade
        
        Returns:
            Estatísticas detalhadas
        """
        try:
            # Buscar todos os assets
            assets = await self.list_assets(
                asset_type=asset_type,
                entity_id=entity_id,
                limit=1000,  # Limite alto para estatísticas
                use_cache=False
            )
            
            if not assets:
                return {
                    "total_assets": 0,
                    "by_type": {},
                    "by_status": {},
                    "by_location": {},
                    "by_manufacturer": {},
                    "filters": {
                        "asset_type": asset_type,
                        "entity_id": entity_id
                    }
                }
            
            # Calcular estatísticas
            stats = {
                "total_assets": len(assets),
                "by_type": {},
                "by_status": {},
                "by_location": {},
                "by_manufacturer": {},
                "filters": {
                    "asset_type": asset_type,
                    "entity_id": entity_id
                }
            }
            
            for asset in assets:
                # Por tipo
                asset_type_name = asset.get("asset_type", "unknown")
                stats["by_type"][asset_type_name] = stats["by_type"].get(asset_type_name, 0) + 1
                
                # Por status
                status = asset.get("status", "unknown")
                stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
                
                # Por localização
                location = asset.get("locations_id", "unknown")
                stats["by_location"][location] = stats["by_location"].get(location, 0) + 1
                
                # Por fabricante
                manufacturer = asset.get("manufacturers_id", "unknown")
                stats["by_manufacturer"][manufacturer] = stats["by_manufacturer"].get(manufacturer, 0) + 1
            
            logger.info(f"Generated asset stats: {stats['total_assets']} assets analyzed")
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get asset stats: {e}")
            raise GLPIError(500, f"Failed to get asset stats: {str(e)}")


# Instância global do serviço de assets
asset_service = AssetService()
