"""
Admin Service - Conforme SPEC.md seção 4.3
Migrado e expandido de glpi_service.py existente
Implementa operações CRUD de usuários, grupos, entidades, localizações
"""

from typing import Optional, List, Dict, Any
from datetime import datetime

from src.services.glpi_client import glpi_client
from src.logger import logger
from src.models.exceptions import (
    NotFoundError,
    ValidationError,
    GLPIError
)


class AdminService:
    """
    Serviço de administração GLPI.
    
    Funcionalidades:
    - CRUD completo de usuários, grupos, entidades, localizações
    - Gerenciamento de permissões e hierarquias
    - Busca avançada com filtros
    - Validação de dados
    - Paginação inteligente
    """
    
    def __init__(self):
        """Inicializa o serviço de administração."""
        self.client = glpi_client
        
        logger.info("AdminService initialized")
    
    # ============= USUÁRIOS =============
    
    async def list_users(
        self,
        entity_id: Optional[int] = None,
        group_id: Optional[int] = None,
        profile_id: Optional[int] = None,
        is_active: Optional[bool] = None,
        is_deleted: Optional[bool] = False,
        limit: int = 250,
        offset: int = 0,
        use_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Lista usuários com filtros avançados.
        
        Args:
            entity_id: Filtrar por entidade
            group_id: Filtrar por grupo
            profile_id: Filtrar por perfil
            is_active: Filtrar por status ativo
            is_deleted: Incluir usuários deletados
            limit: Limite de resultados
            offset: Offset para paginação
            use_cache: Usar cache
        
        Returns:
            Lista de usuários
        """
        # Construir filtros para busca GLPI
        filters = {}
        
        if entity_id:
            filters["entities_id"] = entity_id
        
        if group_id:
            filters["groups_id"] = group_id
        
        if profile_id:
            filters["profiles_id"] = profile_id
        
        if is_active is not None:
            filters["is_active"] = int(is_active)
        
        if is_deleted is not None:
            filters["is_deleted"] = int(is_deleted)
        
        # Construir critérios de busca
        criteria = []
        
        if filters:
            for field, value in filters.items():
                criteria.append({
                    "field": field,
                    "searchtype": "equals",
                    "value": value
                })
        
        params = {
            "range": f"{offset}-{offset + limit - 1}",
            "forcedisplay": [
                "id", "name", "realname", "firstname", "email", "phone",
                "phone2", "mobile", "registration_number", "comment",
                "entities_id", "profiles_id", "users_id_supervisor",
                "is_active", "is_deleted", "date_creation", "date_mod",
                "authtype", "auths_id", "default_language", "timezone"
            ]
        }
        
        if criteria:
            params["criteria"] = criteria
        
        try:
            logger.info(f"Listing users with filters: {filters}")
            result = await self.client.get("/apirest.php/User", params, use_cache)
            
            # GLPI API retorna array diretamente ou dict com "data"
            if isinstance(result, list):
                users = result
            elif isinstance(result, dict) and "data" in result:
                users = result["data"]
            else:
                users = []
            
            # Se houver usuários, retornar com metadados
            if users:
                return {
                    "users": users,
                    "pagination": {
                        "total": len(users),
                        "offset": offset,
                        "limit": limit,
                        "has_more": len(users) >= limit
                    }
                }
            
            return {"users": [], "pagination": {"total": 0, "offset": offset, "limit": limit, "has_more": False}}
                
        except Exception as e:
            logger.error(f"Failed to list users: {e}")
            raise GLPIError(500, f"Failed to list users: {str(e)}")
    
    async def get_user(self, user_id: int) -> Dict[str, Any]:
        """
        Obtém detalhes completos de um usuário.
        
        Args:
            user_id: ID do usuário
        
        Returns:
            Dados completos do usuário
        """
        try:
            logger.info(f"Getting user {user_id}")
            
            # Obter dados principais do usuário
            user = await self.client.get_item(
                "User",
                user_id,
                forcedisplay=[
                    "id", "name", "realname", "firstname", "email", "phone",
                    "phone2", "mobile", "registration_number", "comment",
                    "entities_id", "profiles_id", "users_id_supervisor",
                    "is_active", "is_deleted", "date_creation", "date_mod",
                    "authtype", "auths_id", "default_language", "timezone",
                    "user_dn", "synchro_ddate", "picture", "location"
                ]
            )
            
            # Obter grupos do usuário
            try:
                groups = await self.client.get_subitems("User", user_id, "Group_User")
                user["groups"] = groups
            except Exception:
                user["groups"] = []
            
            # Obter perfis do usuário
            try:
                profiles = await self.client.get_subitems("User", user_id, "Profile_User")
                user["profiles"] = profiles
            except Exception:
                user["profiles"] = []
            
            # Obter entidades do usuário
            try:
                entities = await self.client.get_subitems("User", user_id, "Entity_User")
                user["entities"] = entities
            except Exception:
                user["entities"] = []
            
            return user
            
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to get user {user_id}: {e}")
            raise GLPIError(500, f"Failed to get user: {str(e)}")
    
    async def create_user(
        self,
        name: str,
        password: Optional[str] = None,
        password2: Optional[str] = None,
        firstname: Optional[str] = None,
        realname: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        phone2: Optional[str] = None,
        mobile: Optional[str] = None,
        entity_id: Optional[int] = None,
        profile_id: Optional[int] = None,
        group_id: Optional[int] = None,
        location_id: Optional[int] = None,
        usertitle_id: Optional[int] = None,
        usercategory_id: Optional[int] = None,
        registration_number: Optional[str] = None,
        comment: Optional[str] = None,
        authtype: int = 1,  # Local
        is_active: bool = True
    ) -> Dict[str, Any]:
        """
        Cria um novo usuário com TODOS os campos disponíveis.
        
        Args:
            name: Nome de usuário (login)
            password: Senha do usuário
            password2: Confirmação da senha
            firstname: Primeiro nome
            realname: Sobrenome completo
            email: Email
            phone: Telefone principal
            phone2: Telefone secundário
            mobile: Celular
            entity_id: ID da entidade padrão
            profile_id: ID do perfil padrão
            group_id: ID do grupo padrão
            location_id: ID da localização
            usertitle_id: ID do título/cargo
            usercategory_id: ID da categoria de usuário
            registration_number: Número administrativo/matrícula
            comment: Comentários
            authtype: Tipo de autenticação (1=Local, 2=Mail, 3=LDAP)
            is_active: Status ativo
        
        Returns:
            Usuário criado com todos os campos
        """
        # Validações conforme SPEC.md
        if not name or len(name.strip()) < 2:
            raise ValidationError("Username must be at least 2 characters", "name")
        
        if email and "@" not in email:
            raise ValidationError("Invalid email format", "email")
        
        # Construir payload
        payload = {
            "name": name.strip(),
            "authtype": authtype,
            "is_active": int(is_active),
            "entities_id": entity_id or 0  # Entidade raiz se não especificado
        }
        
        # Adicionar senha se fornecida
        if password:
            payload["password"] = password
            # GLPI requer password2 para confirmação
            payload["password2"] = password2 if password2 else password
        
        # Campos opcionais
        if firstname:
            payload["firstname"] = firstname.strip()
        
        if realname:
            payload["realname"] = realname.strip()
        
        if email:
            payload["email"] = email.strip()
        
        if phone:
            payload["phone"] = phone.strip()
        
        if phone2:
            payload["phone2"] = phone2.strip()
        
        if mobile:
            payload["mobile"] = mobile.strip()
        
        if location_id:
            payload["locations_id"] = location_id
        
        if usertitle_id:
            payload["usertitles_id"] = usertitle_id
        
        if usercategory_id:
            payload["usercategories_id"] = usercategory_id
        
        if registration_number:
            payload["registration_number"] = registration_number.strip()
        
        if profile_id:
            payload["profiles_id"] = profile_id
        
        if comment:
            payload["comment"] = comment.strip()
        
        try:
            logger.info(f"Creating user: {name}")
            result = await self.client.post("/apirest.php/User", payload)
            
            if "id" not in result:
                raise GLPIError(500, "Failed to create user - no ID returned")
            
            # Adicionar ao grupo se especificado
            if group_id:
                try:
                    group_payload = {
                        "users_id": result["id"],
                        "groups_id": group_id
                    }
                    await self.client.post("/apirest.php/Group_User", group_payload)
                except Exception as e:
                    logger.warning(f"Failed to add user {result['id']} to group {group_id}: {e}")
            
            # Retornar usuário completo
            created_user = await self.get_user(result["id"])
            
            logger.info(f"User created successfully: ID {result['id']}")
            return created_user
            
        except Exception as e:
            logger.error(f"Failed to create user: {e}")
            raise GLPIError(500, f"Failed to create user: {str(e)}")
    
    async def update_user(self, user_id: int, **kwargs) -> Dict[str, Any]:
        """
        Atualiza um usuário existente.
        
        Args:
            user_id: ID do usuário
            **kwargs: Campos para atualizar
        
        Returns:
            Usuário atualizado
        """
        # Validar usuário existe
        await self.get_user(user_id)
        
        # Remover campos que não devem ser atualizados diretamente
        protected_fields = ["id", "date_creation", "date_mod"]
        update_payload = {k: v for k, v in kwargs.items() if k not in protected_fields}
        
        if not update_payload:
            raise ValidationError("No valid fields to update", "payload")
        
        try:
            logger.info(f"Updating user {user_id} with fields: {list(update_payload.keys())}")
            await self.client.put(f"/apirest.php/User/{user_id}", update_payload)
            
            # Retornar usuário atualizado
            updated_user = await self.get_user(user_id)
            
            logger.info(f"User {user_id} updated successfully")
            return updated_user
            
        except Exception as e:
            logger.error(f"Failed to update user {user_id}: {e}")
            raise GLPIError(500, f"Failed to update user: {str(e)}")
    
    async def delete_user(self, user_id: int, purge: bool = False) -> bool:
        """
        Deleta ou desativa um usuário.
        
        Args:
            user_id: ID do usuário
            purge: Se True, deleta permanentemente; se False, apenas desativa
        
        Returns:
            True se operação bem-sucedida
        """
        # Validar usuário existe
        await self.get_user(user_id)
        
        try:
            if purge:
                logger.info(f"Purging user {user_id}")
                await self.client.delete(f"/apirest.php/User/{user_id}")
            else:
                logger.info(f"Deactivating user {user_id}")
                await self.client.put(f"/apirest.php/User/{user_id}", {"is_active": 0})
            
            logger.info(f"User {user_id} {'purged' if purge else 'deactivated'} successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to {'purge' if purge else 'deactivate'} user {user_id}: {e}")
            raise GLPIError(500, f"Failed to delete user: {str(e)}")
    
    # ============= GRUPOS =============
    
    async def list_groups(
        self,
        entity_id: Optional[int] = None,
        is_user_group: Optional[bool] = None,
        is_technical_group: Optional[bool] = None,
        limit: int = 250,
        offset: int = 0,
        use_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Lista grupos com filtros avançados.
        
        Args:
            entity_id: Filtrar por entidade
            is_user_group: Filtrar grupos de usuários
            is_technical_group: Filtrar grupos técnicos
            limit: Limite de resultados
            offset: Offset para paginação
            use_cache: Usar cache
        
        Returns:
            Lista de grupos
        """
        # Construir filtros
        filters = {}
        
        if entity_id:
            filters["entities_id"] = entity_id
        
        if is_user_group is not None:
            filters["is_user_group"] = int(is_user_group)
        
        if is_technical_group is not None:
            filters["is_technician_group"] = int(is_technical_group)
        
        # Construir critérios de busca
        criteria = []
        
        if filters:
            for field, value in filters.items():
                criteria.append({
                    "field": field,
                    "searchtype": "equals",
                    "value": value
                })
        
        params = {
            "range": f"{offset}-{offset + limit - 1}",
            "forcedisplay": [
                "id", "name", "comment", "entities_id", "is_user_group",
                "is_technician_group", "is_requester", "is_assign",
                "is_notify", "is_itemgroup", "can_priority", "date_creation",
                "date_mod", "users_id"
            ]
        }
        
        if criteria:
            params["criteria"] = criteria
        
        try:
            logger.info(f"Listing groups with filters: {filters}")
            result = await self.client.get("/apirest.php/Group", params, use_cache)
            
            # API pode retornar lista diretamente ou dict com "data"
            if isinstance(result, list):
                groups = result
            elif isinstance(result, dict) and "data" in result:
                groups = result["data"]
            else:
                return []
            
            # Adicionar metadados de paginação
            if isinstance(result, dict) and "count" in result and result["count"] > limit:
                groups.append({
                    "pagination_hint": f"Found {result['count']} total groups. Use pagination to get more."
                })
            
            return groups
                
        except Exception as e:
            logger.error(f"Failed to list groups: {e}")
            raise GLPIError(500, f"Failed to list groups: {str(e)}")
    
    async def get_group(self, group_id: int) -> Dict[str, Any]:
        """
        Obtém detalhes completos de um grupo.
        
        Args:
            group_id: ID do grupo
        
        Returns:
            Dados completos do grupo
        """
        try:
            logger.info(f"Getting group {group_id}")
            
            group = await self.client.get_item(
                "Group",
                group_id,
                forcedisplay=[
                    "id", "name", "comment", "entities_id", "is_user_group",
                    "is_technician_group", "is_requester", "is_assign",
                    "is_notify", "is_itemgroup", "can_priority", "date_creation",
                    "date_mod", "users_id"
                ]
            )
            
            # Obter membros do grupo
            try:
                members = await self.client.get_subitems("Group", group_id, "Group_User")
                group["members"] = members
            except Exception:
                group["members"] = []
            
            return group
            
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to get group {group_id}: {e}")
            raise GLPIError(500, f"Failed to get group: {str(e)}")
    
    async def create_group(
        self,
        name: str,
        entity_id: Optional[int] = None,
        comment: Optional[str] = None,
        is_user_group: bool = True,
        is_technical_group: bool = False,
        is_requester: bool = True,
        is_assign: bool = True,
        is_notify: bool = True
    ) -> Dict[str, Any]:
        """
        Cria um novo grupo.
        
        Args:
            name: Nome do grupo
            entity_id: ID da entidade
            comment: Comentários
            is_user_group: Se é grupo de usuários
            is_technical_group: Se é grupo técnico
            is_requester: Pode ser solicitante
            is_assign: Pode ser responsável
            is_notify: Recebe notificações
        
        Returns:
            Grupo criado
        """
        if not name or len(name.strip()) < 2:
            raise ValidationError("Group name must be at least 2 characters", "name")
        
        payload = {
            "name": name.strip(),
            "entities_id": entity_id or 0,
            "is_user_group": int(is_user_group),
            "is_technician_group": int(is_technical_group),
            "is_requester": int(is_requester),
            "is_assign": int(is_assign),
            "is_notify": int(is_notify)
        }
        
        if comment:
            payload["comment"] = comment.strip()
        
        try:
            logger.info(f"Creating group: {name}")
            result = await self.client.post("/apirest.php/Group", payload)
            
            if "id" not in result:
                raise GLPIError(500, "Failed to create group - no ID returned")
            
            created_group = await self.get_group(result["id"])
            
            logger.info(f"Group created successfully: ID {result['id']}")
            return created_group
            
        except Exception as e:
            logger.error(f"Failed to create group: {e}")
            raise GLPIError(500, f"Failed to create group: {str(e)}")
    
    async def update_group(self, group_id: int, **kwargs) -> Dict[str, Any]:
        """
        Atualiza um grupo existente.
        
        Args:
            group_id: ID do grupo
            **kwargs: Campos para atualizar
        
        Returns:
            Grupo atualizado
        """
        await self.get_group(group_id)
        
        protected_fields = ["id", "date_creation", "date_mod"]
        update_payload = {k: v for k, v in kwargs.items() if k not in protected_fields}
        
        if not update_payload:
            raise ValidationError("No valid fields to update", "payload")
        
        try:
            logger.info(f"Updating group {group_id} with fields: {list(update_payload.keys())}")
            await self.client.put(f"/apirest.php/Group/{group_id}", update_payload)
            
            updated_group = await self.get_group(group_id)
            
            logger.info(f"Group {group_id} updated successfully")
            return updated_group
            
        except Exception as e:
            logger.error(f"Failed to update group {group_id}: {e}")
            raise GLPIError(500, f"Failed to update group: {str(e)}")
    
    async def delete_group(self, group_id: int) -> bool:
        """
        Deleta um grupo.
        
        Args:
            group_id: ID do grupo
        
        Returns:
            True se deletado com sucesso
        """
        await self.get_group(group_id)
        
        try:
            logger.info(f"Deleting group {group_id}")
            await self.client.delete(f"/apirest.php/Group/{group_id}")
            
            logger.info(f"Group {group_id} deleted successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete group {group_id}: {e}")
            raise GLPIError(500, f"Failed to delete group: {str(e)}")
    
    # ============= ENTIDADES =============
    
    async def list_entities(
        self,
        parent_entity_id: Optional[int] = None,
        is_recursive: Optional[bool] = None,
        limit: int = 250,
        offset: int = 0,
        use_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Lista entidades com filtros avançados.
        
        Args:
            parent_entity_id: Filtrar por entidade pai
            is_recursive: Filtrar entidades recursivas
            limit: Limite de resultados
            offset: Offset para paginação
            use_cache: Usar cache
        
        Returns:
            Lista de entidades
        """
        filters = {}
        
        if parent_entity_id:
            filters["entities_id"] = parent_entity_id
        
        if is_recursive is not None:
            filters["is_recursive"] = int(is_recursive)
        
        criteria = []
        
        if filters:
            for field, value in filters.items():
                criteria.append({
                    "field": field,
                    "searchtype": "equals",
                    "value": value
                })
        
        params = {
            "range": f"{offset}-{offset + limit - 1}",
            "forcedisplay": [
                "id", "name", "comment", "entities_id", "level",
                "completename", "is_recursive", "address", "postcode",
                "town", "state", "country", "website", "phonenumber",
                "fax", "email", "notification", "admin_email",
                "admin_email_name", "date_creation", "date_mod"
            ]
        }
        
        if criteria:
            params["criteria"] = criteria
        
        try:
            logger.info(f"Listing entities with filters: {filters}")
            result = await self.client.get("/apirest.php/Entity", params, use_cache)
            
            # API pode retornar lista diretamente ou dict com "data"
            if isinstance(result, list):
                entities = result
            elif isinstance(result, dict) and "data" in result:
                entities = result["data"]
            else:
                return []
            
            # Adicionar metadados de paginação
            if isinstance(result, dict) and "count" in result and result["count"] > limit:
                entities.append({
                    "pagination_hint": f"Found {result['count']} total entities. Use pagination to get more."
                })
            
            return entities
                
        except Exception as e:
            logger.error(f"Failed to list entities: {e}")
            raise GLPIError(500, f"Failed to list entities: {str(e)}")
    
    async def get_entity(self, entity_id: int) -> Dict[str, Any]:
        """
        Obtém detalhes completos de uma entidade.
        
        Args:
            entity_id: ID da entidade
        
        Returns:
            Dados completos da entidade
        """
        try:
            logger.info(f"Getting entity {entity_id}")
            
            entity = await self.client.get_item(
                "Entity",
                entity_id,
                forcedisplay=[
                    "id", "name", "comment", "entities_id", "level",
                    "completename", "is_recursive", "address", "postcode",
                    "town", "state", "country", "website", "phonenumber",
                    "fax", "email", "notification", "admin_email",
                    "admin_email_name", "date_creation", "date_mod"
                ]
            )
            
            return entity
            
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to get entity {entity_id}: {e}")
            raise GLPIError(500, f"Failed to get entity: {str(e)}")
    
    # ============= LOCALIZAÇÕES =============
    
    async def list_locations(
        self,
        parent_location_id: Optional[int] = None,
        entity_id: Optional[int] = None,
        limit: int = 250,
        offset: int = 0,
        use_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Lista localizações com filtros avançados.
        
        Args:
            parent_location_id: Filtrar por localização pai
            entity_id: Filtrar por entidade
            limit: Limite de resultados
            offset: Offset para paginação
            use_cache: Usar cache
        
        Returns:
            Lista de localizações
        """
        filters = {}
        
        if parent_location_id:
            filters["locations_id"] = parent_location_id
        
        if entity_id:
            filters["entities_id"] = entity_id
        
        criteria = []
        
        if filters:
            for field, value in filters.items():
                criteria.append({
                    "field": field,
                    "searchtype": "equals",
                    "value": value
                })
        
        params = {
            "range": f"{offset}-{offset + limit - 1}",
            "forcedisplay": [
                "id", "name", "comment", "locations_id", "level",
                "completename", "building", "room", "place",
                "town", "postcode", "address", "latitude",
                "longitude", "altitude", "entities_id",
                "date_creation", "date_mod"
            ]
        }
        
        if criteria:
            params["criteria"] = criteria
        
        try:
            logger.info(f"Listing locations with filters: {filters}")
            result = await self.client.get("/apirest.php/Location", params, use_cache)
            
            # API pode retornar lista diretamente ou dict com "data"
            if isinstance(result, list):
                locations = result
            elif isinstance(result, dict) and "data" in result:
                locations = result["data"]
            else:
                return []
            
            # Adicionar metadados de paginação
            if isinstance(result, dict) and "count" in result and result["count"] > limit:
                locations.append({
                    "pagination_hint": f"Found {result['count']} total locations. Use pagination to get more."
                })
            
            return locations
                
        except Exception as e:
            logger.error(f"Failed to list locations: {e}")
            raise GLPIError(500, f"Failed to list locations: {str(e)}")
    
    async def get_location(self, location_id: int) -> Dict[str, Any]:
        """
        Obtém detalhes completos de uma localização.
        
        Args:
            location_id: ID da localização
        
        Returns:
            Dados completos da localização
        """
        try:
            logger.info(f"Getting location {location_id}")
            
            location = await self.client.get_item(
                "Location",
                location_id,
                forcedisplay=[
                    "id", "name", "comment", "locations_id", "level",
                    "completename", "building", "room", "place",
                    "town", "postcode", "address", "latitude",
                    "longitude", "altitude", "entities_id",
                    "date_creation", "date_mod"
                ]
            )
            
            return location
            
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to get location {location_id}: {e}")
            raise GLPIError(500, f"Failed to get location: {str(e)}")
    
    async def create_location(
        self,
        name: str,
        entity_id: Optional[int] = None,
        parent_location_id: Optional[int] = None,
        building: Optional[str] = None,
        room: Optional[str] = None,
        town: Optional[str] = None,
        address: Optional[str] = None,
        comment: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Cria uma nova localização.
        
        Args:
            name: Nome da localização
            entity_id: ID da entidade
            parent_location_id: ID da localização pai
            building: Prédio
            room: Sala
            town: Cidade
            address: Endereço
            comment: Comentários
        
        Returns:
            Localização criada
        """
        if not name or len(name.strip()) < 2:
            raise ValidationError("Location name must be at least 2 characters", "name")
        
        payload = {
            "name": name.strip(),
            "entities_id": entity_id or 0
        }
        
        if parent_location_id:
            payload["locations_id"] = parent_location_id
        
        if building:
            payload["building"] = building.strip()
        
        if room:
            payload["room"] = room.strip()
        
        if town:
            payload["town"] = town.strip()
        
        if address:
            payload["address"] = address.strip()
        
        if comment:
            payload["comment"] = comment.strip()
        
        try:
            logger.info(f"Creating location: {name}")
            result = await self.client.post("/apirest.php/Location", payload)
            
            if "id" not in result:
                raise GLPIError(500, "Failed to create location - no ID returned")
            
            created_location = await self.get_location(result["id"])
            
            logger.info(f"Location created successfully: ID {result['id']}")
            return created_location
            
        except Exception as e:
            logger.error(f"Failed to create location: {e}")
            raise GLPIError(500, f"Failed to create location: {str(e)}")
    
    async def get_admin_stats(self, entity_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Obtém estatísticas administrativas.
        
        Args:
            entity_id: Filtrar por entidade
        
        Returns:
            Estatísticas detalhadas
        """
        try:
            # Buscar dados em paralelo para performance
            users = await self.list_users(entity_id=entity_id, limit=1000, use_cache=False)
            groups = await self.list_groups(entity_id=entity_id, limit=1000, use_cache=False)
            entities = await self.list_entities(limit=1000, use_cache=False)
            locations = await self.list_locations(entity_id=entity_id, limit=1000, use_cache=False)
            
            stats = {
                "total_users": len(users) if isinstance(users, list) else 0,
                "total_groups": len(groups) if isinstance(groups, list) else 0,
                "total_entities": len(entities) if isinstance(entities, list) else 0,
                "total_locations": len(locations) if isinstance(locations, list) else 0,
                "filters": {
                    "entity_id": entity_id
                }
            }
            
            # Estatísticas de usuários
            if isinstance(users, list):
                active_users = sum(1 for u in users if u.get("is_active"))
                stats["active_users"] = active_users
                stats["inactive_users"] = stats["total_users"] - active_users
            
            # Estatísticas de grupos
            if isinstance(groups, list):
                user_groups = sum(1 for g in groups if g.get("is_user_group"))
                tech_groups = sum(1 for g in groups if g.get("is_technician_group"))
                stats["user_groups"] = user_groups
                stats["technical_groups"] = tech_groups
            
            logger.info(f"Generated admin stats for entity {entity_id or 'all'}")
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get admin stats: {e}")
            raise GLPIError(500, f"Failed to get admin stats: {str(e)}")


# Instância global do serviço de administração
admin_service = AdminService()
