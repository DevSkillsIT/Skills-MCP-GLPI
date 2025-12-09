"""
MCP Tools - Admin (12 tools)
Conforme SPEC.md seção 4.2 - Matriz de Tools MCP
Wrappers para admin_service com validação e tratamento de erros
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import json

from src.services.admin_service import admin_service
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
    entity_resolver
)
from src.utils.safety_guard import require_safety_confirmation


class AdminTools:
    """
    Collection de 12 tools MCP para administração GLPI.
    Implementadas conforme matriz SPEC.md seção 4.2
    """
    
    async def list_users(
        self,
        entity_id: Optional[int] = None,
        entity_name: Optional[str] = None,
        group_id: Optional[int] = None,
        profile_id: Optional[int] = None,
        is_active: Optional[bool] = None,
        limit: int = 250,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Tool MCP: list_users
        Lista todos os usuários com filtros opcionais

        Args:
            entity_id: Filtrar por entidade (ID numérico)
            entity_name: Filtrar por nome da entidade/cliente (ex: "GSM Transportes", "Skills IT")
            group_id: Filtrar por grupo
            profile_id: Filtrar por perfil
            is_active: Filtrar por status ativo
            limit: Número máximo de resultados (padrão: 50)
            offset: Deslocamento para paginação (padrão: 0)

        Returns:
            Lista de usuários com metadados de paginação

        Note:
            Se entity_name for fornecido, será resolvido para entity_id automaticamente.
            Exemplo: list_users(entity_name="GSM") retorna usuários do cliente GSM.
        """
        try:
            logger.info(f"MCP Tool: list_users with filters, entity_name={entity_name}, limit={limit}")

            # Resolver entity_name para entity_id se fornecido
            if entity_name:
                resolved_id = await entity_resolver.resolve_entity_name(entity_name)
                if resolved_id:
                    entity_id = resolved_id
                    logger.info(f"list_users: entity_name '{entity_name}' resolvido para ID {entity_id}")
                else:
                    available = await entity_resolver.list_available_entities()
                    raise ValidationError(
                        f"Entidade '{entity_name}' não encontrada. Entidades disponíveis: {[e['name'] for e in available[:10]]}",
                        "entity_name"
                    )
            
            # Validar paginação
            offset, limit = PaginationHelper.validate_pagination_params(offset, limit)
            
            # Buscar usuários
            users = await admin_service.list_users(
                entity_id=entity_id,
                group_id=group_id,
                profile_id=profile_id,
                is_active=is_active,
                limit=limit,
                offset=offset,
                use_cache=True
            )
            
            # Truncar resposta se necessário
            if isinstance(users, dict) and "users" in users:
                users["users"] = response_truncator.truncate_json_response(users["users"])
            else:
                users = response_truncator.truncate_json_response(users)
            
            logger.info(f"list_users completed: {len(users) if isinstance(users, list) else 'paginated'} users")
            return users
            
        except ValidationError as e:
            logger.error(f"list_users validation error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"list_users unexpected error: {e}")
            raise GLPIError(500, f"Failed to list users: {str(e)}")
    
    async def get_user(self, user_id: int) -> Dict[str, Any]:
        """
        Tool MCP: get_user
        Obtém detalhes completos de um usuário específico
        
        Args:
            user_id: ID do usuário
        
        Returns:
            Dados completos do usuário
        """
        try:
            logger.info(f"MCP Tool: get_user {user_id}")
            
            if not isinstance(user_id, int) or user_id <= 0:
                raise ValidationError("User ID must be a positive integer", "user_id")
            
            user = await admin_service.get_user(user_id)
            
            # Truncar resposta se necessário
            user = response_truncator.truncate_json_response(user)
            
            logger.info(f"get_user completed: user {user_id}")
            return user
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"get_user error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"get_user unexpected error: {e}")
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
        entity_name: Optional[str] = None,
        profile_id: Optional[int] = None,
        group_id: Optional[int] = None,
        location_id: Optional[int] = None,
        usertitle_id: Optional[int] = None,
        usercategory_id: Optional[int] = None,
        registration_number: Optional[str] = None,
        comment: Optional[str] = None,
        authtype: int = 1,
        is_active: bool = True
    ) -> Dict[str, Any]:
        """
        Tool MCP: create_user
        Cria um novo usuário com TODOS os campos disponíveis

        Args:
            name: Nome de usuário (login)
            password: Senha do usuário (obrigatório para authtype=1, usuários locais)
            password2: Confirmação da senha (deve ser igual a password)
            firstname: Primeiro nome
            realname: Sobrenome completo
            email: Email
            phone: Telefone principal
            phone2: Telefone secundário
            mobile: Celular
            entity_id: ID da entidade padrão (numérico)
            entity_name: Nome da entidade/cliente (ex: "GSM Transportes", "Skills IT")
            profile_id: ID do perfil padrão
            group_id: ID do grupo padrão
            location_id: ID da localização
            usertitle_id: ID do título/cargo
            usercategory_id: ID da categoria de usuário
            registration_number: Número administrativo/matrícula
            comment: Comentários
            authtype: Tipo de autenticação (1=Local, 2=Mail, 3=LDAP)
            is_active: Status ativo (True=ativo, False=inativo)

        Returns:
            Usuário criado com todos os campos

        Note:
            Se entity_name for fornecido, será resolvido para entity_id automaticamente.
        """
        try:
            logger.info(f"MCP Tool: create_user - {name}")

            # Resolver entity_name para entity_id se fornecido
            if entity_name:
                resolved_id = await entity_resolver.resolve_entity_name(entity_name)
                if resolved_id:
                    entity_id = resolved_id
                    logger.info(f"create_user: entity_name '{entity_name}' resolvido para ID {entity_id}")
                else:
                    available = await entity_resolver.list_available_entities()
                    raise ValidationError(
                        f"Entidade '{entity_name}' não encontrada. Entidades disponíveis: {[e['name'] for e in available[:10]]}",
                        "entity_name"
                    )

            # Sanitizar inputs
            name = input_sanitizer.sanitize_string(name)
            
            # Validar senha se fornecida
            if password:
                if len(password) < 6:
                    raise ValidationError("Password must be at least 6 characters", "password")
                if password2 and password != password2:
                    raise ValidationError("Passwords do not match", "password2")
            
            if email and not input_sanitizer.validate_email(email):
                raise ValidationError("Invalid email format", "email")
            
            if firstname:
                firstname = input_sanitizer.sanitize_string(firstname)
            
            if realname:
                realname = input_sanitizer.sanitize_string(realname)
            
            if phone:
                phone = input_sanitizer.validate_phone(phone)
            
            if comment:
                comment = input_sanitizer.sanitize_string(comment)
            
            if registration_number:
                registration_number = input_sanitizer.sanitize_string(registration_number)
            
            # Criar usuário com TODOS os campos
            user = await admin_service.create_user(
                name=name,
                password=password,
                password2=password2,
                firstname=firstname,
                realname=realname,
                email=email,
                phone=phone,
                phone2=phone2,
                mobile=mobile,
                entity_id=entity_id,
                profile_id=profile_id,
                group_id=group_id,
                location_id=location_id,
                usertitle_id=usertitle_id,
                usercategory_id=usercategory_id,
                registration_number=registration_number,
                comment=comment,
                authtype=authtype,
                is_active=is_active
            )
            
            # Truncar resposta se necessário
            user = response_truncator.truncate_json_response(user)
            
            logger.info(f"create_user completed: user {user.get('id')}")
            return user
            
        except ValidationError as e:
            logger.error(f"create_user validation error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"create_user unexpected error: {e}")
            raise GLPIError(500, f"Failed to create user: {str(e)}")
    
    async def update_user(self, user_id: int, **kwargs) -> Dict[str, Any]:
        """
        Tool MCP: update_user
        Atualiza um usuário existente com TODOS os campos disponíveis
        
        Args:
            user_id: ID do usuário
            **kwargs: Campos para atualizar, incluindo:
                - firstname: Primeiro nome
                - realname: Sobrenome
                - email: Email
                - phone: Telefone principal
                - phone2: Telefone secundário
                - mobile: Celular
                - location_id: ID da localização
                - usertitle_id: ID do título/cargo
                - usercategory_id: ID da categoria
                - registration_number: Número administrativo/matrícula
                - comment: Comentários
                - is_active: Status ativo (1=ativo, 0=inativo)
                - entity_id: ID da entidade
                - profile_id: ID do perfil
                - group_id: ID do grupo
        
        Returns:
            Usuário atualizado com todos os campos
        """
        try:
            logger.info(f"MCP Tool: update_user {user_id}")
            
            if not isinstance(user_id, int) or user_id <= 0:
                raise ValidationError("User ID must be a positive integer", "user_id")
            
            # Sanitizar campos de texto
            update_data = {}
            for key, value in kwargs.items():
                if isinstance(value, str):
                    update_data[key] = input_sanitizer.sanitize_string(value)
                else:
                    update_data[key] = value
            
            # Validar email se fornecido
            if "email" in update_data and update_data["email"]:
                if not input_sanitizer.validate_email(update_data["email"]):
                    raise ValidationError("Invalid email format", "email")
            
            # Atualizar usuário
            user = await admin_service.update_user(user_id, **update_data)
            
            # Truncar resposta se necessário
            user = response_truncator.truncate_json_response(user)
            
            logger.info(f"update_user completed: user {user_id}")
            return user
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"update_user error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"update_user unexpected error: {e}")
            raise GLPIError(500, f"Failed to update user: {str(e)}")
    
    async def delete_user(
        self,
        user_id: int,
        purge: bool = False,
        confirmationToken: Optional[str] = None,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Tool MCP: delete_user
        Deleta ou desativa um usuário
        
        ATENÇÃO: Operação destrutiva! Quando MCP_SAFETY_GUARD=true:
        - Requer confirmationToken válido (igual ao MCP_SAFETY_TOKEN)
        - Requer reason com pelo menos 10 caracteres
        
        Args:
            user_id: ID do usuário
            purge: Se True, deleta permanentemente; se False, apenas desativa
            confirmationToken: Token de confirmação (quando safety guard ativado)
            reason: Motivo da deleção (quando safety guard ativado, mín. 10 chars)
        
        Returns:
            Confirmação da operação
        """
        try:
            logger.info(f"MCP Tool: delete_user {user_id} (purge={purge})")
            
            if not isinstance(user_id, int) or user_id <= 0:
                raise ValidationError("User ID must be a positive integer", "user_id")
            
            # Verificar safety guard
            require_safety_confirmation(
                "delete_user",
                confirmation_token=confirmationToken,
                reason=reason,
                target_id=user_id,
                target_type="User"
            )
            
            success = await admin_service.delete_user(user_id, purge)
            
            result = {
                "success": success,
                "user_id": user_id,
                "purged": purge,
                "message": f"User {user_id} {'purged' if purge else 'deactivated'} successfully"
            }
            
            logger.info(f"delete_user completed: user {user_id}")
            return result
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"delete_user error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"delete_user unexpected error: {e}")
            raise GLPIError(500, f"Failed to delete user: {str(e)}")
    
    async def list_groups(
        self,
        entity_id: Optional[int] = None,
        entity_name: Optional[str] = None,
        is_user_group: Optional[bool] = None,
        is_technical_group: Optional[bool] = None,
        limit: int = 250,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Tool MCP: list_groups
        Lista todos os grupos com filtros opcionais

        Args:
            entity_id: Filtrar por entidade (ID numérico)
            entity_name: Filtrar por nome da entidade/cliente (ex: "GSM Transportes", "Skills IT")
            is_user_group: Filtrar grupos de usuários
            is_technical_group: Filtrar grupos técnicos
            limit: Número máximo de resultados (padrão: 50)
            offset: Deslocamento para paginação (padrão: 0)

        Returns:
            Lista de grupos com metadados de paginação

        Note:
            Se entity_name for fornecido, será resolvido para entity_id automaticamente.
            Exemplo: list_groups(entity_name="GSM") retorna grupos do cliente GSM.
        """
        try:
            logger.info(f"MCP Tool: list_groups with filters, entity_name={entity_name}, limit={limit}")

            # Resolver entity_name para entity_id se fornecido
            if entity_name:
                resolved_id = await entity_resolver.resolve_entity_name(entity_name)
                if resolved_id:
                    entity_id = resolved_id
                    logger.info(f"list_groups: entity_name '{entity_name}' resolvido para ID {entity_id}")
                else:
                    available = await entity_resolver.list_available_entities()
                    raise ValidationError(
                        f"Entidade '{entity_name}' não encontrada. Entidades disponíveis: {[e['name'] for e in available[:10]]}",
                        "entity_name"
                    )

            # Validar paginação
            offset, limit = PaginationHelper.validate_pagination_params(offset, limit)
            
            groups = await admin_service.list_groups(
                entity_id=entity_id,
                is_user_group=is_user_group,
                is_technical_group=is_technical_group,
                limit=limit,
                offset=offset,
                use_cache=True
            )
            
            # Truncar resposta se necessário
            groups = response_truncator.truncate_json_response(groups)
            
            logger.info(f"list_groups completed: {len(groups) if isinstance(groups, list) else 'paginated'} groups")
            return groups
            
        except Exception as e:
            logger.error(f"list_groups unexpected error: {e}")
            raise GLPIError(500, f"Failed to list groups: {str(e)}")
    
    async def get_group(self, group_id: int) -> Dict[str, Any]:
        """
        Tool MCP: get_group
        Obtém detalhes completos de um grupo específico
        
        Args:
            group_id: ID do grupo
        
        Returns:
            Dados completos do grupo
        """
        try:
            logger.info(f"MCP Tool: get_group {group_id}")
            
            if not isinstance(group_id, int) or group_id <= 0:
                raise ValidationError("Group ID must be a positive integer", "group_id")
            
            group = await admin_service.get_group(group_id)
            
            # Truncar resposta se necessário
            group = response_truncator.truncate_json_response(group)
            
            logger.info(f"get_group completed: group {group_id}")
            return group
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"get_group error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"get_group unexpected error: {e}")
            raise GLPIError(500, f"Failed to get group: {str(e)}")
    
    async def create_group(
        self,
        name: str,
        entity_id: Optional[int] = None,
        entity_name: Optional[str] = None,
        comment: Optional[str] = None,
        is_user_group: bool = True,
        is_technical_group: bool = False,
        is_requester: bool = True,
        is_assign: bool = True,
        is_notify: bool = True
    ) -> Dict[str, Any]:
        """
        Tool MCP: create_group
        Cria um novo grupo

        Args:
            name: Nome do grupo
            entity_id: ID da entidade (numérico)
            entity_name: Nome da entidade/cliente (ex: "GSM Transportes", "Skills IT")
            comment: Comentários
            is_user_group: Se é grupo de usuários
            is_technical_group: Se é grupo técnico
            is_requester: Pode ser solicitante
            is_assign: Pode ser responsável
            is_notify: Recebe notificações

        Returns:
            Grupo criado

        Note:
            Se entity_name for fornecido, será resolvido para entity_id automaticamente.
        """
        try:
            logger.info(f"MCP Tool: create_group - {name}")

            # Resolver entity_name para entity_id se fornecido
            if entity_name:
                resolved_id = await entity_resolver.resolve_entity_name(entity_name)
                if resolved_id:
                    entity_id = resolved_id
                    logger.info(f"create_group: entity_name '{entity_name}' resolvido para ID {entity_id}")
                else:
                    available = await entity_resolver.list_available_entities()
                    raise ValidationError(
                        f"Entidade '{entity_name}' não encontrada. Entidades disponíveis: {[e['name'] for e in available[:10]]}",
                        "entity_name"
                    )

            # Sanitizar inputs
            name = input_sanitizer.sanitize_string(name)

            if comment:
                comment = input_sanitizer.sanitize_string(comment)
            
            group = await admin_service.create_group(
                name=name,
                entity_id=entity_id,
                comment=comment,
                is_user_group=is_user_group,
                is_technical_group=is_technical_group,
                is_requester=is_requester,
                is_assign=is_assign,
                is_notify=is_notify
            )
            
            # Truncar resposta se necessário
            group = response_truncator.truncate_json_response(group)
            
            logger.info(f"create_group completed: group {group.get('id')}")
            return group
            
        except ValidationError as e:
            logger.error(f"create_group validation error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"create_group unexpected error: {e}")
            raise GLPIError(500, f"Failed to create group: {str(e)}")
    
    async def list_entities(
        self,
        parent_entity_id: Optional[int] = None,
        is_recursive: Optional[bool] = None,
        limit: int = 250,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Tool MCP: list_entities
        Lista todas as entidades com filtros opcionais
        
        Args:
            parent_entity_id: Filtrar por entidade pai
            is_recursive: Filtrar entidades recursivas
            limit: Número máximo de resultados (padrão: 50)
            offset: Deslocamento para paginação (padrão: 0)
        
        Returns:
            Lista de entidades com metadados de paginação
        """
        try:
            logger.info(f"MCP Tool: list_entities with filters, limit={limit}")
            
            # Validar paginação
            offset, limit = PaginationHelper.validate_pagination_params(offset, limit)
            
            entities = await admin_service.list_entities(
                parent_entity_id=parent_entity_id,
                is_recursive=is_recursive,
                limit=limit,
                offset=offset,
                use_cache=True
            )
            
            # Truncar resposta se necessário
            entities = response_truncator.truncate_json_response(entities)
            
            logger.info(f"list_entities completed: {len(entities) if isinstance(entities, list) else 'paginated'} entities")
            return entities
            
        except Exception as e:
            logger.error(f"list_entities unexpected error: {e}")
            raise GLPIError(500, f"Failed to list entities: {str(e)}")
    
    async def get_entity(self, entity_id: int) -> Dict[str, Any]:
        """
        Tool MCP: get_entity
        Obtém detalhes completos de uma entidade específica
        
        Args:
            entity_id: ID da entidade (0 é válido - entidade raiz)
        
        Returns:
            Dados completos da entidade
        """
        try:
            logger.info(f"MCP Tool: get_entity {entity_id}")
            
            # ID 0 é válido (entidade raiz do GLPI)
            if not isinstance(entity_id, int) or entity_id < 0:
                raise ValidationError("Entity ID must be a non-negative integer", "entity_id")
            
            entity = await admin_service.get_entity(entity_id)
            
            # Truncar resposta se necessário
            entity = response_truncator.truncate_json_response(entity)
            
            logger.info(f"get_entity completed: entity {entity_id}")
            return entity
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"get_entity error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"get_entity unexpected error: {e}")
            raise GLPIError(500, f"Failed to get entity: {str(e)}")
    
    async def list_locations(
        self,
        parent_location_id: Optional[int] = None,
        entity_id: Optional[int] = None,
        entity_name: Optional[str] = None,
        limit: int = 250,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Tool MCP: list_locations
        Lista todas as localizações com filtros opcionais

        Args:
            parent_location_id: Filtrar por localização pai
            entity_id: Filtrar por entidade (ID numérico)
            entity_name: Filtrar por nome da entidade/cliente (ex: "GSM Transportes", "Skills IT")
            limit: Número máximo de resultados (padrão: 50)
            offset: Deslocamento para paginação (padrão: 0)

        Returns:
            Lista de localizações com metadados de paginação

        Note:
            Se entity_name for fornecido, será resolvido para entity_id automaticamente.
            Exemplo: list_locations(entity_name="GSM") retorna localizações do cliente GSM.
        """
        try:
            logger.info(f"MCP Tool: list_locations with filters, entity_name={entity_name}, limit={limit}")

            # Resolver entity_name para entity_id se fornecido
            if entity_name:
                resolved_id = await entity_resolver.resolve_entity_name(entity_name)
                if resolved_id:
                    entity_id = resolved_id
                    logger.info(f"list_locations: entity_name '{entity_name}' resolvido para ID {entity_id}")
                else:
                    available = await entity_resolver.list_available_entities()
                    raise ValidationError(
                        f"Entidade '{entity_name}' não encontrada. Entidades disponíveis: {[e['name'] for e in available[:10]]}",
                        "entity_name"
                    )

            # Validar paginação
            offset, limit = PaginationHelper.validate_pagination_params(offset, limit)
            
            locations = await admin_service.list_locations(
                parent_location_id=parent_location_id,
                entity_id=entity_id,
                limit=limit,
                offset=offset,
                use_cache=True
            )
            
            # Truncar resposta se necessário
            locations = response_truncator.truncate_json_response(locations)
            
            logger.info(f"list_locations completed: {len(locations) if isinstance(locations, list) else 'paginated'} locations")
            return locations
            
        except Exception as e:
            logger.error(f"list_locations unexpected error: {e}")
            raise GLPIError(500, f"Failed to list locations: {str(e)}")
    
    async def get_location(self, location_id: int) -> Dict[str, Any]:
        """
        Tool MCP: get_location
        Obtém detalhes completos de uma localização específica
        
        Args:
            location_id: ID da localização
        
        Returns:
            Dados completos da localização
        """
        try:
            logger.info(f"MCP Tool: get_location {location_id}")
            
            if not isinstance(location_id, int) or location_id <= 0:
                raise ValidationError("Location ID must be a positive integer", "location_id")
            
            location = await admin_service.get_location(location_id)
            
            # Truncar resposta se necessário
            location = response_truncator.truncate_json_response(location)
            
            logger.info(f"get_location completed: location {location_id}")
            return location
            
        except (NotFoundError, ValidationError) as e:
            logger.error(f"get_location error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"get_location unexpected error: {e}")
            raise GLPIError(500, f"Failed to get location: {str(e)}")
    
    async def create_location(
        self,
        name: str,
        entity_id: Optional[int] = None,
        entity_name: Optional[str] = None,
        parent_location_id: Optional[int] = None,
        building: Optional[str] = None,
        room: Optional[str] = None,
        town: Optional[str] = None,
        address: Optional[str] = None,
        comment: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Tool MCP: create_location
        Cria uma nova localização

        Args:
            name: Nome da localização
            entity_id: ID da entidade (numérico)
            entity_name: Nome da entidade/cliente (ex: "GSM Transportes", "Skills IT")
            parent_location_id: ID da localização pai
            building: Prédio
            room: Sala
            town: Cidade
            address: Endereço
            comment: Comentários

        Returns:
            Localização criada

        Note:
            Se entity_name for fornecido, será resolvido para entity_id automaticamente.
        """
        try:
            logger.info(f"MCP Tool: create_location - {name}")

            # Resolver entity_name para entity_id se fornecido
            if entity_name:
                resolved_id = await entity_resolver.resolve_entity_name(entity_name)
                if resolved_id:
                    entity_id = resolved_id
                    logger.info(f"create_location: entity_name '{entity_name}' resolvido para ID {entity_id}")
                else:
                    available = await entity_resolver.list_available_entities()
                    raise ValidationError(
                        f"Entidade '{entity_name}' não encontrada. Entidades disponíveis: {[e['name'] for e in available[:10]]}",
                        "entity_name"
                    )

            # Sanitizar inputs
            name = input_sanitizer.sanitize_string(name)
            
            if building:
                building = input_sanitizer.sanitize_string(building)
            
            if room:
                room = input_sanitizer.sanitize_string(room)
            
            if town:
                town = input_sanitizer.sanitize_string(town)
            
            if address:
                address = input_sanitizer.sanitize_string(address)
            
            if comment:
                comment = input_sanitizer.sanitize_string(comment)
            
            location = await admin_service.create_location(
                name=name,
                entity_id=entity_id,
                parent_location_id=parent_location_id,
                building=building,
                room=room,
                town=town,
                address=address,
                comment=comment
            )
            
            # Truncar resposta se necessário
            location = response_truncator.truncate_json_response(location)
            
            logger.info(f"create_location completed: location {location.get('id')}")
            return location
            
        except ValidationError as e:
            logger.error(f"create_location validation error: {e.message}")
            raise
        except Exception as e:
            logger.error(f"create_location unexpected error: {e}")
            raise GLPIError(500, f"Failed to create location: {str(e)}")
    
    async def get_admin_stats(
        self,
        entity_id: Optional[int] = None,
        entity_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Tool MCP: get_admin_stats
        Obtém estatísticas administrativas

        Args:
            entity_id: Filtrar por entidade (ID numérico)
            entity_name: Filtrar por nome da entidade/cliente (ex: "GSM Transportes", "Skills IT")

        Returns:
            Estatísticas detalhadas

        Note:
            Se entity_name for fornecido, será resolvido para entity_id automaticamente.
            Exemplo: get_admin_stats(entity_name="GSM") retorna estatísticas do cliente GSM.
        """
        try:
            logger.info(f"MCP Tool: get_admin_stats, entity_name={entity_name}")

            # Resolver entity_name para entity_id se fornecido
            if entity_name:
                resolved_id = await entity_resolver.resolve_entity_name(entity_name)
                if resolved_id:
                    entity_id = resolved_id
                    logger.info(f"get_admin_stats: entity_name '{entity_name}' resolvido para ID {entity_id}")
                else:
                    available = await entity_resolver.list_available_entities()
                    raise ValidationError(
                        f"Entidade '{entity_name}' não encontrada. Entidades disponíveis: {[e['name'] for e in available[:10]]}",
                        "entity_name"
                    )

            stats = await admin_service.get_admin_stats(entity_id=entity_id)
            
            logger.info(f"get_admin_stats completed: {stats['total_users']} users analyzed")
            return stats
            
        except Exception as e:
            logger.error(f"get_admin_stats unexpected error: {e}")
            raise GLPIError(500, f"Failed to get admin stats: {str(e)}")

    async def search_users(
        self,
        name: Optional[str] = None,
        firstname: Optional[str] = None,
        realname: Optional[str] = None,
        email: Optional[str] = None,
        entity_name: Optional[str] = None,
        entity_id: Optional[int] = None,
        limit: int = 250,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Tool MCP: search_users
        Busca usuários por login, nome, sobrenome ou email usando /search/User
        
        Retorna TODOS os campos do usuário incluindo:
        - ID, Login, Nome, Sobrenome, Email
        - Telefones (phone, phone2, mobile)
        - Status (ativo/inativo)
        - Localização, Título, Categoria
        - Entidade, Grupo, Perfil
        - Comentários, Número administrativo

        Args:
            name: Buscar por login/username
            firstname: Buscar por nome
            realname: Buscar por sobrenome  
            email: Buscar por email
            entity_name: Filtrar por nome da entidade (cliente)
            entity_id: Filtrar por ID da entidade
            limit: Número máximo de resultados
            offset: Deslocamento para paginação

        Returns:
            Lista completa de usuários com todos os campos

        Example:
            search_users(firstname="Wilka", entity_name="Grupo Wink")
            search_users(realname="Ferreira")
        """
        try:
            from src.services.glpi_client import glpi_client
            
            logger.info(f"MCP Tool: search_users name={name}, firstname={firstname}, entity={entity_name}")

            # Resolver entity_name para entity_id se fornecido
            if entity_name:
                resolved_id = await entity_resolver.resolve_entity_name(entity_name)
                if resolved_id:
                    entity_id = resolved_id
                    logger.info(f"search_users: entity_name '{entity_name}' resolvido para ID {entity_id}")
                else:
                    available = await entity_resolver.list_available_entities()
                    raise ValidationError(
                        f"Entidade '{entity_name}' não encontrada. Entidades disponíveis: {[e['name'] for e in available[:10]]}",
                        "entity_name"
                    )
            
            # Field IDs CORRETOS do GLPI para User (fonte: forum.glpi-project.org/viewtopic.php?id=285693):
            # 1 = name (login)
            # 9 = firstname (nome)
            # 34 = realname (sobrenome)  
            # 5 = email
            # 2 = id
            # 3 = is_active (ativo)
            # 6 = phone
            # 7 = phone2
            # 8 = mobile
            # 11 = registration_number (número administrativo)
            # 12 = locations_id (localização)
            # 13 = usertitles_id (título)
            # 14 = usercategories_id (categoria)
            # 16 = comment (comentários)
            # 80 = entities_id (entidade)
            # 82 = groups_id (grupo)
            # 20 = profiles_id (perfil)
            
            criteria = []
            
            if name:
                criteria.append({
                    "field": 1,
                    "searchtype": "contains",
                    "value": name
                })
            
            if firstname:
                criteria.append({
                    "field": 9,
                    "searchtype": "contains",
                    "value": firstname
                })
            
            if realname:
                criteria.append({
                    "field": 34,
                    "searchtype": "contains", 
                    "value": realname
                })
            
            if email:
                criteria.append({
                    "field": 5,
                    "searchtype": "contains",
                    "value": email
                })

            if entity_id:
                criteria.append({
                    "field": 80,
                    "searchtype": "under", # Busca recursiva na entidade e filhas
                    "value": entity_id
                })
            
            if not criteria:
                raise ValidationError("Pelo menos um critério de busca deve ser fornecido")
            
            params = {
                "range": f"{offset}-{offset + limit - 1}",
            }
            
            # forcedisplay: TODOS os campos importantes do usuário (IDs corretos)
            # Usar formato de array PHP para garantir que a API aceite
            params["forcedisplay[0]"] = 2   # id
            params["forcedisplay[1]"] = 1   # name (login)
            params["forcedisplay[2]"] = 9   # firstname (nome)
            params["forcedisplay[3]"] = 34  # realname (sobrenome)
            params["forcedisplay[4]"] = 5   # email
            params["forcedisplay[5]"] = 6   # phone
            params["forcedisplay[6]"] = 7   # phone2
            params["forcedisplay[7]"] = 8   # mobile
            params["forcedisplay[8]"] = 3   # is_active (ativo)
            params["forcedisplay[9]"] = 11  # registration_number
            params["forcedisplay[10]"] = 12 # locations_id (localização)
            params["forcedisplay[11]"] = 13 # usertitles_id (título)
            params["forcedisplay[12]"] = 14 # usercategories_id (categoria)
            params["forcedisplay[13]"] = 16 # comment
            params["forcedisplay[14]"] = 80 # entities_id (entidade)
            params["forcedisplay[15]"] = 82 # groups_id (grupo)
            params["forcedisplay[16]"] = 20 # profiles_id (perfil)
            params["forcedisplay[17]"] = 17 # last_login
            params["forcedisplay[18]"] = 15 # date_mod
            params["forcedisplay[19]"] = 121 # date_creation
            
            # Adicionar critérios
            for i, crit in enumerate(criteria):
                for key, value in crit.items():
                    params[f"criteria[{i}][{key}]"] = value
                # Adicionar link AND entre critérios (exceto o primeiro)
                if i > 0:
                    params[f"criteria[{i}][link]"] = "AND"
            
            # Fazer requisição
            result = await glpi_client.get("/apirest.php/search/User", params, use_cache=False)
            
            # Processar resultado
            users = []
            if isinstance(result, dict) and "data" in result:
                data = result["data"]
                # data é uma lista de dicionários com índices numéricos das colunas
                if isinstance(data, list):
                    for item in data:
                        user = {
                            # Dados básicos (CONFIRMADOS)
                            "id": item.get("2", ""),  # Campo 2 = ID ✅
                            "name": item.get("1", ""),  # Campo 1 = Login ✅
                            "firstname": item.get("9", ""),  # Campo 9 = Firstname ✅
                            "realname": item.get("34", ""),  # Campo 34 = Realname ✅
                            
                            # Contatos (CONFIRMADOS)
                            "email": item.get("5", ""),  # Campo 5 = Email ✅
                            "phone": item.get("6", ""),  # Campo 6 = Phone ✅
                            "phone2": item.get("7", ""),  # Campo 7 = Phone2 (não veio no exemplo)
                            "mobile": item.get("11", ""),  # Campo 11 = Mobile ✅ (NÃO é 8!)
                            
                            # Status (CAMPO 8 = is_active conforme visto)
                            "is_active": item.get("8", ""),  # Campo 8 = is_active ✅
                            
                            # Campo 3 = Localização (não is_active!)
                            "location": item.get("3", ""),  # Campo 3 = Location ✅
                            
                            # Número administrativo
                            "registration_number": item.get("12", ""),  # Campo 12 - tentativa
                            
                            # Categoria e título
                            "title": item.get("13", ""),  # Campo 13 ✅ (null no exemplo)
                            "category": item.get("14", ""),  # Campo 14 ✅ (null no exemplo)
                            "comment": item.get("16", ""),  # Campo 16 = Comment ✅
                            
                            # Entidade e grupos (CONFIRMADOS)
                            "entity": item.get("80", ""),  # Campo 80 = Entity ✅
                            "group": item.get("82", ""),  # Campo 82 = Group ✅
                            "profile": item.get("20", ""),  # Campo 20 = Profile ✅
                            
                            # Datas (CONFIRMADAS)
                            "last_login": item.get("17", ""),  # Campo 17 (null no exemplo)
                            "date_mod": item.get("15", ""),  # Campo 15 ✅
                            "date_creation": item.get("121", "")  # Campo 121 ✅
                        }
                        users.append(user)
            
            total = result.get("totalcount", len(users)) if isinstance(result, dict) else len(users)

            # ============ FALLBACK PARA USUÁRIOS DELETADOS ============
            # Se não encontrou nenhum usuário ativo, buscar nos deletados como fallback
            # NOTA: GLPI usa ?is_deleted=1 como parâmetro de query, NÃO como critério de busca
            deleted_users = []
            if len(users) == 0:
                logger.info("search_users: Nenhum usuário ativo encontrado, buscando nos deletados...")
                try:
                    deleted_params = dict(params)  # Cópia dos parâmetros
                    deleted_params["is_deleted"] = 1  # Parâmetro de query para buscar deletados

                    # Manter os critérios originais (não adicionar novo critério)
                    for i, crit in enumerate(criteria):
                        for key, value in crit.items():
                            deleted_params[f"criteria[{i}][{key}]"] = value
                        if i > 0:
                            deleted_params[f"criteria[{i}][link]"] = "AND"

                    deleted_result = await glpi_client.get("/apirest.php/search/User", deleted_params, use_cache=False)

                    if isinstance(deleted_result, dict) and "data" in deleted_result:
                        deleted_data = deleted_result["data"]
                        if isinstance(deleted_data, list):
                            for item in deleted_data:
                                user = {
                                    "id": item.get("2", ""),
                                    "name": item.get("1", ""),
                                    "firstname": item.get("9", ""),
                                    "realname": item.get("34", ""),
                                    "email": item.get("5", ""),
                                    "phone": item.get("6", ""),
                                    "phone2": item.get("7", ""),
                                    "mobile": item.get("11", ""),
                                    "is_active": item.get("8", ""),
                                    "location": item.get("3", ""),
                                    "registration_number": item.get("12", ""),
                                    "title": item.get("13", ""),
                                    "category": item.get("14", ""),
                                    "comment": item.get("16", ""),
                                    "entity": item.get("80", ""),
                                    "group": item.get("82", ""),
                                    "profile": item.get("20", ""),
                                    "last_login": item.get("17", ""),
                                    "date_mod": item.get("15", ""),
                                    "date_creation": item.get("121", ""),
                                    # FLAG ESPECIAL para indicar usuário deletado
                                    "is_deleted": True,
                                    "deletion_warning": "USUÁRIO DELETADO - Removido do sistema (possivelmente sync LDAP)"
                                }
                                deleted_users.append(user)

                            if deleted_users:
                                logger.info(f"search_users: Encontrados {len(deleted_users)} usuários DELETADOS como fallback")

                except Exception as e:
                    logger.warning(f"search_users: Fallback para deletados falhou: {e}")

            # Combinar resultados (ativos primeiro, deletados depois)
            all_users = users + deleted_users
            total = total + len(deleted_users)

            response = {
                "users": all_users,
                "pagination": {
                    "total": total,
                    "offset": offset,
                    "limit": limit,
                    "has_more": total > (offset + len(all_users))
                }
            }

            # Adicionar aviso se retornou apenas deletados
            if len(deleted_users) > 0 and len(users) == 0:
                response["warning"] = f"Apenas usuários DELETADOS encontrados ({len(deleted_users)}). Estes usuários foram removidos do sistema."

            logger.info(f"search_users completed: found {len(users)} ativos + {len(deleted_users)} deletados")
            return response
            
        except ValidationError:
            raise
        except Exception as e:
            logger.error(f"search_users error: {e}")
            raise GLPIError(500, f"Erro ao buscar usuários: {str(e)}")


# Instância global das tools de administração
admin_tools = AdminTools()
