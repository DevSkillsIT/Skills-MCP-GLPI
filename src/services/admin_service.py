"""
Admin Service - Conforme SPEC.md seção 4.3
Migrado e expandido de glpi_service.py existente
Implementa operações CRUD de usuários, grupos, entidades, localizações
"""

import asyncio
from typing import Optional, List, Dict, Any

from src.services.glpi_client import glpi_client
from src.services.dropdown_cache import dropdown_cache
from src.services.search_options import search_options_cache
from src.logger import logger
from src.utils.search_criteria import normalize_order, resolve_sort_field
from src.models.exceptions import (
    NotFoundError,
    ValidationError,
    GLPIError
)


# GLPI Search API field IDs per admin resource, used only for ordering.
# The User ids are the ones already confirmed live against /search/User (see
# AdminTools.search_users); groups, entities and locations use the CommonDBTM
# defaults, stable across GLPI 9/10/11.
# Search API field ids for User, validated against a live instance.
#
# @MX:ANCHOR: one map feeds both the forcedisplay request and the response
# parsing in the user search.
# @MX:REASON: those two used to carry independent comment blocks that
# contradicted each other — the request assumed 3=is_active, 8=mobile,
# 12=registration_number, while the parsing read 3=location, 8=is_active,
# 11=mobile after being corrected against a real instance. Asking for one set
# of columns and reading another is invisible in the response: every field
# still comes back populated, just with the wrong content. A single map cannot
# disagree with itself.
USER_FIELD = {
    "id": 2,
    "name": 1,             # login
    "firstname": 9,
    "realname": 34,
    "email": 5,
    "phone": 6,
    "phone2": 10,          # NOT 7 — 7 nao existe no catalogo
    "mobile": 11,          # NOT 8 — confirmed live
    "is_active": 8,        # NOT 3 — confirmed live
    "location": 3,         # NOT is_active — confirmed live
    "registration_number": 22,  # NOT 12 — 12 nao existe no catalogo
    "title": 81,                # NOT 13 — 13 e "Grupos"
    "category": 82,             # NOT 14 — 14 e "Ultima autenticacao"
    "comment": 16,
    "last_login": 14,           # NOT 17 — 17 e "Idioma"
    "date_mod": 19,             # NOT 15 — 15 e "Autenticacao"
    "profile": 20,
    "entity": 80,
    "group": 13,                # NOT 82 — 82 e "Categoria"
    "date_creation": 121,
}

#: Colunas da propria tabela de usuarios, para a reconciliacao corrigir.
#
# @MX:ANCHOR: o mapa de usuarios e reconciliado como os demais.
# @MX:REASON: sete ids estavam trocados entre si e nada avisava, porque o
# pedido (forcedisplay) e a leitura usam o MESMO dicionario — concordavam um
# com o outro e discordavam do GLPI. Medido na instancia de referencia:
# 13="Grupos" era lido como 'title', 14="Ultima autenticacao" como 'category',
# 17="Idioma" como 'last_login'. Ordenar por ultimo acesso ordenava por idioma,
# e cada linha trazia a coluna errada sob o nome certo. Chamados, ativos e
# registros ITIL ja passavam por esta rede de seguranca; usuarios, nao.
_USER_UID_HINTS = {
    "name": "User.name",
    "id": "User.id",
    "firstname": "User.firstname",
    "realname": "User.realname",
    "phone": "User.phone",
    "phone2": "User.phone2",
    "mobile": "User.mobile",
    "is_active": "User.is_active",
    "registration_number": "User.registration_number",
    "comment": "User.comment",
    "last_login": "User.last_login",
    "date_mod": "User.date_mod",
    "date_creation": "User.date_creation",
}

_user_field_sync_done = False
_user_field_sync_lock = asyncio.Lock()


async def ensure_user_field_map_synced() -> None:
    """Correct USER_FIELD against the instance's own catalogue, once.

    Same safety net the ticket, asset and ITIL paths already use: ids move
    across GLPI versions, profiles and plugins, and a stale id keeps returning
    rows -- just from another column.
    """
    global _user_field_sync_done
    if _user_field_sync_done:
        return

    async with _user_field_sync_lock:
        if _user_field_sync_done:
            return
        try:
            await search_options_cache.reconcile("User", USER_FIELD, _USER_UID_HINTS)
        except Exception as exc:  # noqa: BLE001 -- never block a search
            logger.warning(f"User field reconciliation skipped: {exc}")
        finally:
            _user_field_sync_done = True


def reset_user_field_sync() -> None:
    """Forget the reconciliation (tests and cache invalidation)."""
    global _user_field_sync_done
    _user_field_sync_done = False

ADMIN_SORT_FIELDS = {
    "users": {
        "name": USER_FIELD["name"],
        "id": USER_FIELD["id"],
        "location": USER_FIELD["location"],
        "email": USER_FIELD["email"],
        "firstname": USER_FIELD["firstname"],
        "realname": USER_FIELD["realname"],
        "last_login": USER_FIELD["last_login"],
        "date_mod": USER_FIELD["date_mod"],
        "date_creation": USER_FIELD["date_creation"],
        "entity": USER_FIELD["entity"],
    },
    "groups": {
        "name": 1,
        "id": 2,
        "comment": 16,
        "date_mod": 19,
        "date_creation": 121,
        "entity": 80,
    },
    "entities": {
        "name": 1,
        "id": 2,
        "comment": 16,
        "date_mod": 19,
        "date_creation": 121,
    },
    "locations": {
        "name": 1,
        "id": 2,
        "comment": 16,
        "date_mod": 19,
        "date_creation": 121,
        "entity": 80,
    },
}

# Fallback column for sorting: every admin resource has a name.
ADMIN_DEFAULT_SORT_FIELD = 1

# Search API field ids used when a listing has to go through /search instead of
# getAllItems. Keys are the column names the callers already use as filters.
GROUP_SEARCH_FIELD = {
    "entities_id": 80,
    "is_user_group": 15,
    "is_technician_group": 16,
}

LOCATION_SEARCH_FIELD = {
    "entities_id": 80,
    "locations_id": 3,
}

# Columns brought back by those searches, so the response keeps the same shape
# the getAllItems path produces.
_ADMIN_SEARCH_COLUMNS = {
    "Group": {2: "id", 1: "name", 16: "comment", 80: "entities_id"},
    "Location": {2: "id", 1: "name", 16: "comment", 80: "entities_id"},
}


def resolve_admin_sort(resource: str, sort_by: Any = None, order: Any = None) -> tuple:
    """Resolve sort_by/order into the (field_id, direction) the API expects.

    Shared by every admin listing: users are searched from the tools layer and
    the other resources from this service, so both resolve here instead of
    keeping two tables that could drift apart.

    Returns (None, None) when the caller asked for nothing, so a legacy call
    produces the exact request it produced before sorting existed. A field the
    resource does not expose falls back to the name column with a warning —
    an unusable sort key must never fail the whole listing.
    """
    if sort_by is None and order is None:
        return None, None

    fields = ADMIN_SORT_FIELDS.get(resource, ADMIN_SORT_FIELDS["users"])
    sort_field = resolve_sort_field(
        sort_by,
        fields,
        ADMIN_DEFAULT_SORT_FIELD,
        context=f"search_admin[{resource}]",
    )
    direction = normalize_order(order, default="ASC")

    return sort_field, direction


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

    async def _search_admin_items(
        self,
        itemtype: str,
        field_map: Dict[str, int],
        filters: Dict[str, Any],
        limit: int,
        offset: int,
    ) -> List[Dict[str, Any]]:
        """Run a filtered listing through the Search API and normalise it back.

        @MX:ANCHOR: the only filtered path for admin listings.
        @MX:REASON: getAllItems accepts a criteria payload and quietly ignores
        it, so every filtered listing silently returned everything. Filters
        have to travel as numeric search options, which is what this does; the
        result is mapped back to named keys so callers and formatters keep
        working unchanged.
        """
        criteria = []
        for column, value in filters.items():
            field_id = field_map.get(column)
            if field_id is None:
                logger.warning(
                    f"_search_admin_items: filtro '{column}' nao mapeado para "
                    f"{itemtype}; ignorado para nao filtrar a coluna errada"
                )
                continue
            criteria.append({
                "field": field_id,
                # Entity filtering is recursive: a parent entity must include
                # its children, same contract used for tickets and assets.
                "searchtype": "under" if column == "entities_id" else "equals",
                "value": value,
            })

        if not criteria:
            return []

        columns = _ADMIN_SEARCH_COLUMNS.get(itemtype, {})
        result = await self.client.search(
            item_type=itemtype,
            criteria=criteria,
            forcedisplay=list(columns) or None,
            range_limit=limit,
            range_offset=offset,
            expand_dropdowns=True,
        )

        rows = result.get("data", []) if isinstance(result, dict) else (result or [])
        normalised = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            item = {name: row.get(str(fid)) for fid, name in columns.items()}
            # Preserve anything else the API returned under its raw key.
            for key, value in row.items():
                item.setdefault(key, value)
            normalised.append(item)
        return normalised
    
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
        await ensure_user_field_map_synced()

        # Construir filtros para busca GLPI
        filters = {}
        
        # @MX:WARN: comparar com None, nunca por veracidade.
        # @MX:REASON: a entidade raiz tem id 0, que e falso em Python. Com
        # o teste por veracidade, filtrar pela raiz era silenciosamente
        # ignorado e a busca devolvia registros de TODAS as entidades —
        # confirmado ao vivo pedindo grupos da entidade 0 e recebendo os
        # de outra. Mesmo defeito ja corrigido no lado de ativos.
        if entity_id is not None:
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
            # expand_dropdowns: entities_id/profiles_id voltam como NOME, nao ID.
            "expand_dropdowns": 1,
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
    
    async def _set_user_email(self, user_id: int, email: str) -> None:
        """Grava o email do usuário na tabela glpi_useremails (itemtype UserEmail).

        @MX:REASON: o campo email do payload User é ignorado pelo GLPI; emails
        vivem em UserEmail. Atualiza o email default existente ou cria um novo.
        """
        email = email.strip()
        try:
            existing = await self.client.get_subitems("User", user_id, "UserEmail")
        except Exception:  # noqa: BLE001
            existing = []

        default = next(
            (e for e in (existing or []) if str(e.get("is_default")) in ("1", "True")),
            None,
        )
        target = default or (existing[0] if existing else None)

        if target and target.get("id"):
            await self.client.put(
                f"/apirest.php/UserEmail/{target['id']}",
                {"email": email, "is_default": 1},
            )
        else:
            await self.client.post(
                "/apirest.php/UserEmail",
                {"users_id": user_id, "email": email, "is_default": 1},
            )

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
            
            # @MX:ANCHOR: os tres subitens abaixo custam uma chamada HTTP cada e
            # precisam chegar ao formatter como NOMES.
            # @MX:REASON: groups/profiles/entities eram buscados e depois
            # descartados — a ficha do usuario imprimia so `Grupos | 8`, uma
            # contagem nua que se le como "grupo 8", e perfis/entidades nao
            # apareciam em lugar nenhum. Perfil e justamente o campo que explica
            # um ERROR_RIGHT_MISSING: pagar a chamada e jogar a resposta fora
            # deixa quem diagnostica sem a unica informacao que importa.
            # Falha na resolucao degrada para os IDs, nunca para silencio.
            for key, subitem, dropdown, fk in (
                ("groups", "Group_User", "Group", "groups_id"),
                ("profiles", "Profile_User", "Profile", "profiles_id"),
                ("entities", "Entity_User", "Entity", "entities_id"),
            ):
                try:
                    items = await self.client.get_subitems("User", user_id, subitem)
                    user[key] = items or []
                except Exception as e:
                    logger.warning(
                        f"get_user({user_id}): subitem {subitem} indisponivel: {e}"
                    )
                    user[key] = []

                ids = [
                    int(item[fk])
                    for item in user[key]
                    if isinstance(item, dict) and str(item.get(fk, "")).isdigit()
                ]
                names: List[str] = []
                if ids:
                    try:
                        resolved = await dropdown_cache.get_many_names(dropdown, ids)
                        names = [str(resolved.get(i) or i) for i in ids]
                    except Exception as e:
                        logger.warning(
                            f"get_user({user_id}): nomes de {dropdown} nao resolvidos: {e}"
                        )
                        names = [str(i) for i in ids]
                user[f"{key}_names"] = names

            # @MX:NOTE: GLPI guarda emails na tabela glpi_useremails (itemtype
            # UserEmail), NAO no objeto User. O campo "email" do User vem vazio.
            # @MX:REASON: get_user reportava Email N/A mesmo apos create/update
            # com email -> success masking. Lemos o email real do subitem.
            try:
                emails = await self.client.get_subitems("User", user_id, "UserEmail")
                user["emails"] = emails or []
                default_email = next(
                    (e.get("email") for e in emails if str(e.get("is_default")) in ("1", "True")),
                    None,
                )
                resolved = default_email or (emails[0].get("email") if emails else None)
                if resolved:
                    user["email"] = resolved
            except Exception:
                user.setdefault("emails", [])

            # Resolve IDs -> nomes humanos (best-effort, cacheado) para o detalhe.
            try:
                ent = user.get("entities_id")
                if ent not in (None, "", 0, "0"):
                    user["entities_name"] = await dropdown_cache.get_name("Entity", ent, fallback=str(ent))
                sup = user.get("users_id_supervisor")
                if sup not in (None, "", 0, "0"):
                    user["supervisor_name"] = await dropdown_cache.get_name("User", sup, fallback=str(sup))
                loc = user.get("locations_id")
                if loc not in (None, "", 0, "0"):
                    user["locations_name"] = await dropdown_cache.get_name("Location", loc, fallback=str(loc))
            except Exception as e:  # noqa: BLE001 — enriquecimento best-effort
                logger.debug(f"get_user name enrichment failed for {user_id}: {e}")

            return user
            
        except NotFoundError:
            raise
        except GLPIError as e:
            # 404 from the GLPI API means the user doesn't exist — surface a
            # clean NotFoundError instead of wrapping into a 500 with a doubled
            # "Failed to get user" prefix.
            if getattr(e, "code", None) == 404:
                raise NotFoundError("User", user_id)
            logger.error(f"Failed to get user {user_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to get user {user_id}: {e}")
            raise GLPIError(500, f"Failed to get user {user_id}: {str(e)}")
    
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

        # @MX:NOTE: email NAO entra no payload do User (GLPI ignora); gravado
        # via _set_user_email apos a criacao (tabela glpi_useremails).
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

            # Gravar email na tabela glpi_useremails (nao persiste via payload User)
            if email:
                try:
                    await self._set_user_email(result["id"], email)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"Failed to set email for user {result['id']}: {e}")

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
        # email é tratado à parte (tabela glpi_useremails), não vai no PUT do User
        email = kwargs.get("email")
        if email and "@" not in str(email):
            raise ValidationError("Invalid email format", "email")
        update_payload = {
            k: v for k, v in kwargs.items()
            if k not in protected_fields and k != "email"
        }

        if not update_payload and not email:
            raise ValidationError("No valid fields to update", "payload")

        try:
            if update_payload:
                logger.info(f"Updating user {user_id} with fields: {list(update_payload.keys())}")
                await self.client.put(f"/apirest.php/User/{user_id}", update_payload)

            # Email persistido via glpi_useremails (não persiste via PUT do User)
            if email:
                await self._set_user_email(user_id, str(email))

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
        use_cache: bool = True,
        sort_by: Optional[Any] = None,
        order: Optional[str] = None
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
            sort_by: Coluna de ordenação (nome amigável ou ID do campo GLPI)
            order: Direção da ordenação (ASC/DESC)

        Returns:
            Lista de grupos
        """
        # Construir filtros
        filters = {}
        
        # @MX:WARN: comparar com None, nunca por veracidade.
        # @MX:REASON: a entidade raiz tem id 0, que e falso em Python. Com
        # o teste por veracidade, filtrar pela raiz era silenciosamente
        # ignorado e a busca devolvia registros de TODAS as entidades —
        # confirmado ao vivo pedindo grupos da entidade 0 e recebendo os
        # de outra. Mesmo defeito ja corrigido no lado de ativos.
        if entity_id is not None:
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

        sort_field, sort_order = resolve_admin_sort("groups", sort_by, order)
        if sort_field is not None:
            params["sort"] = sort_field
            params["order"] = sort_order

        try:
            logger.info(f"Listing groups with filters: {filters}")

            if criteria:
                # @MX:WARN: com filtro, a busca TEM de ir pela Search API.
                # @MX:REASON: /apirest.php/Group e o endpoint getAllItems, que
                # IGNORA criteria[] silenciosamente. Pedir grupos de uma
                # entidade devolvia os grupos de TODAS as entidades — num
                # servidor multi-tenant, isso e exposicao entre clientes.
                # Confirmado ao vivo: filtrando pela entidade 4, vieram grupos
                # da entidade 1. Mesmo motivo ja documentado em list_tickets.
                result = await self._search_admin_items("Group", GROUP_SEARCH_FIELD, filters, limit, offset)
            else:
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
    
    async def delete_group(self, group_id: int, purge: bool = True) -> bool:
        """
        Deleta (ou purga) um grupo.
        Por padrão purge=True (remoção definitiva). Sem purge o GLPI apenas
        envia o registro para a lixeira e o grupo ainda aparece em get_group.

        Args:
            group_id: ID do grupo
            purge: Se True, força remoção definitiva (default True).

        Returns:
            True se deletado com sucesso
        """
        await self.get_group(group_id)

        try:
            logger.info(f"Deleting group {group_id} (purge={purge})")
            endpoint = f"/apirest.php/Group/{group_id}"
            if purge:
                endpoint += "?force_purge=true"
            await self.client.delete(endpoint)

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
        use_cache: bool = True,
        sort_by: Optional[Any] = None,
        order: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Lista entidades com filtros avançados.

        Args:
            parent_entity_id: Filtrar por entidade pai
            is_recursive: Filtrar entidades recursivas
            limit: Limite de resultados
            offset: Offset para paginação
            use_cache: Usar cache
            sort_by: Coluna de ordenação (nome amigável ou ID do campo GLPI)
            order: Direção da ordenação (ASC/DESC)

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

        sort_field, sort_order = resolve_admin_sort("entities", sort_by, order)
        if sort_field is not None:
            params["sort"] = sort_field
            params["order"] = sort_order

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
        use_cache: bool = True,
        sort_by: Optional[Any] = None,
        order: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Lista localizações com filtros avançados.

        Args:
            parent_location_id: Filtrar por localização pai
            entity_id: Filtrar por entidade
            limit: Limite de resultados
            offset: Offset para paginação
            use_cache: Usar cache
            sort_by: Coluna de ordenação (nome amigável ou ID do campo GLPI)
            order: Direção da ordenação (ASC/DESC)

        Returns:
            Lista de localizações
        """
        filters = {}
        
        if parent_location_id:
            filters["locations_id"] = parent_location_id
        
        # @MX:WARN: comparar com None, nunca por veracidade.
        # @MX:REASON: a entidade raiz tem id 0, que e falso em Python. Com
        # o teste por veracidade, filtrar pela raiz era silenciosamente
        # ignorado e a busca devolvia registros de TODAS as entidades —
        # confirmado ao vivo pedindo grupos da entidade 0 e recebendo os
        # de outra. Mesmo defeito ja corrigido no lado de ativos.
        if entity_id is not None:
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

        sort_field, sort_order = resolve_admin_sort("locations", sort_by, order)
        if sort_field is not None:
            params["sort"] = sort_field
            params["order"] = sort_order

        if criteria:
            params["criteria"] = criteria

        try:
            logger.info(f"Listing locations with filters: {filters}")

            if criteria:
                # Mesmo motivo de list_groups: getAllItems ignora criteria[].
                result = await self._search_admin_items(
                    "Location", LOCATION_SEARCH_FIELD, filters, limit, offset
                )
            else:
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

    async def update_location(self, location_id: int, **kwargs) -> Dict[str, Any]:
        """
        Update an existing Location.

        Accepts: name, comment, building, room, town, address, postcode,
        state, country, latitude, longitude, altitude, locations_id
        (parent), entities_id.
        """
        try:
            logger.info(f"Updating location {location_id}")
            if not isinstance(location_id, int) or location_id <= 0:
                raise ValidationError("location_id must be a positive integer", "location_id")

            allowed = (
                "name", "comment", "building", "room", "town", "address",
                "postcode", "state", "country", "latitude", "longitude",
                "altitude", "locations_id", "entities_id",
            )
            payload = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
            if not payload:
                raise ValidationError("No valid fields to update for location")

            await self.client.put(f"/apirest.php/Location/{location_id}", data=payload)
            return await self.get_location(location_id)
        except (NotFoundError, ValidationError):
            raise
        except Exception as e:
            logger.error(f"Failed to update location {location_id}: {e}")
            raise GLPIError(500, f"Failed to update location: {str(e)}")

    async def delete_location(self, location_id: int, purge: bool = False) -> bool:
        """Delete (or purge) a Location."""
        try:
            logger.info(f"Deleting location {location_id} (purge={purge})")
            if not isinstance(location_id, int) or location_id <= 0:
                raise ValidationError("location_id must be a positive integer", "location_id")
            endpoint = f"/apirest.php/Location/{location_id}"
            if purge:
                endpoint += "?force_purge=true"
            await self.client.delete(endpoint)
            return True
        except (NotFoundError, ValidationError):
            raise
        except Exception as e:
            logger.error(f"Failed to delete location {location_id}: {e}")
            raise GLPIError(500, f"Failed to delete location: {str(e)}")

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
