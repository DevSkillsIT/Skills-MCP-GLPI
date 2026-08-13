"""
GLPI Client Service - Conforme SPEC.md seção 4.3
Cliente HTTP otimizado para comunicação com GLPI API
Baseado em http_client.py existente + melhorias SPEC
"""

from typing import Optional, Dict, Any, List, Union
from datetime import datetime

from src.config import settings
from src.logger import logger
from src.models.exceptions import (
    NotFoundError
)
from src.auth.session_manager import session_manager


def emit_criteria(
    params: Dict[str, Any],
    criteria: List[Dict[str, Any]],
    prefix: str = "criteria",
    start_index: int = 0,
) -> int:
    """Public entry point for callers that build their own request params.

    @MX:NOTE: the count probes assemble `range=0-0` requests by hand and used to
    serialise criteria themselves, reading `criterion["field"]` directly.
    @MX:REASON: that copy cannot express a group — a group carries `criteria`
    and no `field`, so the hand-rolled loop raises KeyError the moment any
    filter nests. Counting must serialise exactly like listing, or the count
    stops describing the list it is supposed to summarise.
    """
    return _emit_criteria(params, criteria, prefix, start_index)


def _emit_criteria(
    params: Dict[str, Any],
    criteria: List[Dict[str, Any]],
    prefix: str,
    start_index: int = 0,
) -> int:
    """Flatten a criteria tree into the parameter names the Search API expects.

    @MX:ANCHOR: the only place that serialises search criteria.
    @MX:REASON: GLPI evaluates a flat criteria list left to right, with no
    precedence between AND and OR. So "manufacturer AND (name OR serial)"
    cannot be expressed as a flat list — appending the AND after an OR chain
    silently widens the result instead of narrowing it. The API's answer is
    nesting: a criterion carrying its own `criteria` list becomes a group, and
    the group as a whole is joined by its `link`.

    A criterion is a group when it has a `criteria` key; otherwise it must
    carry `field` and `value`.

    Returns the next free index, so callers can keep appending.
    """
    index = start_index
    for position, crit in enumerate(criteria):
        base = f"{prefix}[{index}]"

        # The first criterion of a list has nothing to join to.
        link = crit.get("link")
        if index > 0 and position >= 0 and link:
            params[f"{base}[link]"] = link
        elif index > 0 and not link:
            params[f"{base}[link]"] = "AND"

        nested = crit.get("criteria")
        if nested:
            _emit_criteria(params, nested, f"{base}[criteria]", 0)
            index += 1
            continue

        params[f"{base}[field]"] = crit["field"]
        params[f"{base}[searchtype]"] = crit.get("searchtype", "equals")
        params[f"{base}[value]"] = crit["value"]
        index += 1

    return index


class GLPIClient:
    """
    Cliente GLPI otimizado com session management e cache robusto.
    
    Funcionalidades:
    - Integração com SessionManager para autenticação e cache
    - Rate limiting automático
    - Retry automático em falhas de autenticação
    - Paginação inteligente
    - Tratamento de erros padronizado
    """
    
    def __init__(self):
        """Inicializa o cliente GLPI."""
        self.session = session_manager
        self.base_url = settings.glpi_base_url
        self.default_page_size = settings.default_page_size
        
        logger.info(f"GLPIClient initialized: {self.base_url}")
    
    # @MX:NOTE: response handling and HTTP error mapping live in the session
    # manager's single request path, not here.
    # @MX:REASON: this class used to carry its own _handle_response with a full
    # status mapping that was never called. Reading it suggested that rate
    # limiting was handled at this layer when nothing here ever ran, which cost
    # real time during a diagnosis. Removed rather than kept as documentation.

    async def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        use_cache: bool = True,
        paginate: bool = False,
        max_items: Optional[int] = None
    ) -> Union[Any, List[Any]]:
        """
        Requisição GET com paginação e cache.
        
        Args:
            endpoint: Endpoint da API GLPI (ex: "/apirest.php/Ticket")
            params: Parâmetros da requisição
            use_cache: Se deve usar cache
            paginate: Se deve aplicar paginação automática
            max_items: Número máximo de itens para retornar
        
        Returns:
            Dados da resposta ou lista paginada
        """
        params = params or {}
        
        # Configurar paginação se solicitado
        if paginate:
            limit = params.get("range_limit", self.default_page_size)
            offset = params.get("range_offset", 0)
            
            if "range" not in params:
                params["range"] = f"{offset}-{offset + limit - 1}"
            
            if max_items and limit > max_items:
                params["range"] = f"{offset}-{offset + max_items - 1}"
        
        try:
            result = await self.session.get(endpoint, params, use_cache)
            
            # Extrair dados paginados se necessário
            if paginate and isinstance(result, dict) and "data" in result:
                return result["data"]
            elif paginate and isinstance(result, list):
                return result
            else:
                return result
                
        except Exception as e:
            logger.error(f"GET request failed for {endpoint}: {e}")
            raise
    
    async def get_with_pagination(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        page_size: Optional[int] = None,
        max_pages: int = 10
    ) -> List[Any]:
        """
        GET com paginação automática para grandes conjuntos de dados.
        
        Args:
            endpoint: Endpoint da API GLPI
            params: Parâmetros base da requisição
            page_size: Tamanho da página (default: settings.default_page_size)
            max_pages: Número máximo de páginas para evitar loops infinitos
        
        Returns:
            Lista completa de todos os itens
        """
        params = params or {}
        page_size = page_size or self.default_page_size
        
        all_items = []
        offset = 0
        page = 0
        
        while page < max_pages:
            # Configurar range para página atual
            params["range"] = f"{offset}-{offset + page_size - 1}"
            
            try:
                result = await self.session.get(endpoint, params, use_cache=False)
                
                if isinstance(result, dict) and "data" in result:
                    items = result["data"]
                    all_items.extend(items)
                    
                    # Verificar se há mais páginas
                    if len(items) < page_size:
                        break
                    
                    offset += page_size
                    page += 1
                else:
                    # Se não for paginado, retornar como está
                    if isinstance(result, list):
                        all_items.extend(result)
                    break
                    
            except Exception as e:
                logger.error(f"Pagination failed for {endpoint} page {page}: {e}")
                break
        
        logger.info(f"Retrieved {len(all_items)} items from {endpoint} in {page + 1} pages")
        return all_items
    
    async def post(self, endpoint: str, data: Dict[str, Any]) -> Any:
        """
        Requisição POST para criar recursos.
        
        Args:
            endpoint: Endpoint da API GLPI
            data: Dados para criar
        
        Returns:
            Dados da resposta
        """
        try:
            result = await self.session.post(endpoint, data)
            
            # Extrair ID do recurso criado se disponível
            if isinstance(result, dict) and "id" in result:
                logger.info(f"Resource created with ID: {result['id']}")
            
            return result
            
        except Exception as e:
            logger.error(f"POST request failed for {endpoint}: {e}")
            raise
    
    async def put(self, endpoint: str, data: Dict[str, Any]) -> Any:
        """
        Requisição PUT para atualizar recursos.
        
        Args:
            endpoint: Endpoint da API GLPI
            data: Dados para atualizar
        
        Returns:
            Dados da resposta
        """
        try:
            result = await self.session.put(endpoint, data)
            
            logger.info(f"Resource updated: {endpoint}")
            return result
            
        except Exception as e:
            logger.error(f"PUT request failed for {endpoint}: {e}")
            raise
    
    async def delete(self, endpoint: str) -> Any:
        """
        Requisição DELETE para remover recursos.
        
        Args:
            endpoint: Endpoint da API GLPI
        
        Returns:
            Dados da resposta
        """
        try:
            result = await self.session.delete(endpoint)
            
            logger.info(f"Resource deleted: {endpoint}")
            return result
            
        except Exception as e:
            logger.error(f"DELETE request failed for {endpoint}: {e}")
            raise
    
    async def search(
        self,
        item_type: str,
        search_text: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        criteria: Optional[List[Dict[str, Any]]] = None,
        forcedisplay: Optional[List[Any]] = None,
        range_limit: Optional[int] = None,
        range_offset: int = 0,
        is_recursive: bool = False,
        sort: Optional[int] = None,
        order: Optional[str] = None,
        expand_dropdowns: bool = False,
    ) -> Any:
        """
        Busca avançada GLPI com filtros múltiplos.

        Args:
            item_type: Tipo de item (ex: "Ticket", "User", "Computer")
            search_text: Texto para busca livre
            filters: Filtros específicos (ex: {"status": "new"})
            criteria: Lista de critérios de busca avançados no formato GLPI
                      Ex: [{"field": 80, "searchtype": "equals", "value": 74}]
            forcedisplay: Campos para retornar (IDs numéricos dos campos GLPI)
            range_limit: Limite de resultados
            range_offset: Offset para paginação
            is_recursive: Se True, busca também nas sub-entidades (filhos)

        Returns:
            Resultados da busca
        """
        # GLPI Search API requires flat params like criteria[0][field]=1
        params = {}
        criteria_idx = 0

        if search_text:
            params[f"criteria[{criteria_idx}][field]"] = 1  # Campo de busca livre
            params[f"criteria[{criteria_idx}][searchtype]"] = "contains"
            params[f"criteria[{criteria_idx}][value]"] = search_text
            criteria_idx += 1

        # Adicionar filtros específicos (formato simples campo=valor)
        if filters:
            for field, value in filters.items():
                if criteria_idx > 0:
                    params[f"criteria[{criteria_idx}][link]"] = "AND"
                params[f"criteria[{criteria_idx}][field]"] = field
                params[f"criteria[{criteria_idx}][searchtype]"] = "equals"
                params[f"criteria[{criteria_idx}][value]"] = value
                criteria_idx += 1

        # Adicionar critérios avançados (formato completo GLPI)
        if criteria:
            criteria_idx = _emit_criteria(params, criteria, "criteria", criteria_idx)

        # Campos para exibir
        if forcedisplay:
            for i, field in enumerate(forcedisplay):
                params[f"forcedisplay[{i}]"] = field

        # Paginação
        if range_limit:
            params["range"] = f"{range_offset}-{range_offset + range_limit - 1}"

        # Ordenação (ex: sort=19 date_mod, order=DESC) — usado pela listagem
        # para trazer os tickets mais recentes primeiro.
        if sort is not None:
            params["sort"] = sort
        if order is not None:
            params["order"] = order

        # Resolve FKs (solicitante/tecnico/categoria) para NOME em vez de ID.
        if expand_dropdowns:
            params["expand_dropdowns"] = 1

        # Busca recursiva em sub-entidades (filhos)
        if is_recursive:
            params["is_recursive"] = 1

        endpoint = f"/apirest.php/search/{item_type}"

        try:
            result = await self.get(endpoint, params)
            return result

        except Exception as e:
            logger.error(f"Search failed for {item_type}: {e}")
            raise
    
    async def get_item(
        self,
        item_type: str,
        item_id: int,
        forcedisplay: Optional[List[str]] = None
    ) -> Any:
        """
        Obtém item específico por ID e tipo.
        
        Args:
            item_type: Tipo de item (ex: "Ticket", "User", "Computer")
            item_id: ID do item
            forcedisplay: Campos para retornar
        
        Returns:
            Dados do item
        """
        params = {}
        
        if forcedisplay:
            params["forcedisplay"] = forcedisplay
        
        endpoint = f"/apirest.php/{item_type}/{item_id}"
        
        try:
            result = await self.get(endpoint, params)
            
            if not result or (isinstance(result, dict) and not result.get("id")):
                raise NotFoundError(item_type, item_id)
            
            return result
            
        except NotFoundError:
            raise
        except Exception as e:
            logger.error(f"Get item failed for {item_type}/{item_id}: {e}")
            raise
    
    async def get_subitems(
        self,
        item_type: str,
        item_id: int,
        subitem_type: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Obtém subitens de um item (ex: anexos de ticket).
        
        Args:
            item_type: Tipo do item principal
            item_id: ID do item principal
            subitem_type: Tipo do subitem
            params: Parâmetros adicionais
        
        Returns:
            Lista de subitens
        """
        endpoint = f"/apirest.php/{item_type}/{item_id}/{subitem_type}"
        
        try:
            result = await self.get(endpoint, params or {})
            return result
            
        except Exception as e:
            logger.error(f"Get subitems failed for {item_type}/{item_id}/{subitem_type}: {e}")
            raise
    
    async def get_health_status(self) -> Dict[str, Any]:
        """
        Verifica status de saúde da conexão GLPI.
        
        Returns:
            Status detalhado da conexão
        """
        try:
            # Testar endpoint básico
            await self.get("/apirest.php/initSession", use_cache=False)
            
            # Obter estatísticas do session manager
            cache_stats = self.session.get_cache_stats()
            
            return {
                "status": "healthy",
                "glpi_url": self.base_url,
                "session_active": cache_stats["session_active"],
                "cache_size": cache_stats["cache_size"],
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "glpi_url": self.base_url,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }


# Instância global do cliente GLPI
glpi_client = GLPIClient()
