"""
Session Manager com Cache e Rate Limiting - Conforme SPEC.md RF01
Baseado em http_client.py existente + código fonte Docker
"""

import asyncio
import contextvars
import hashlib
import time
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta
import httpx
from src.config import settings
from src.logger import logger
from src.models.exceptions import (
    AuthenticationError,
    TimeoutError as GLPITimeoutError,
    RateLimitError,
    GLPIError
)


class SessionManager:
    """
    Gerenciador de sessões GLPI com cache e rate limiting robusto.
    
    Funcionalidades:
    - Cache de sessão com TTL configurável
    - Rate limiting por usuário (60 req/min padrão)
    - Pool de conexões reutilizáveis por user_token
    - Timeout configurável
    - Auto-recuperação de sessão expirada
    - Suporte a múltiplos user_tokens (cada cliente MCP envia seu token)
    """
    
    def __init__(self):
        """Inicializa o session manager."""
        self._client: Optional[httpx.AsyncClient] = None
        self._session_token: Optional[str] = None
        self._session_cache: Dict[str, Any] = {}
        self._rate_limits: Dict[str, Tuple[int, float]] = {}  # user_id -> (count, last_reset)
        self._cache_ttl: int = settings.session_cache_ttl
        self._rate_limit_per_minute: int = settings.rate_limit_requests_per_minute
        self._current_user_key: contextvars.ContextVar[str] = contextvars.ContextVar(
            "current_user_key", default="default"
        )
        # Pool de sessões por user_token: {user_token: {client, session_token, last_used}}
        self._user_sessions: Dict[str, Dict[str, Any]] = {}
        # ContextVar para user_token do request atual
        self._current_user_token: contextvars.ContextVar[str] = contextvars.ContextVar(
            "current_user_token", default=""
        )
        
        logger.info(f"SessionManager initialized: TTL={self._cache_ttl}s, RateLimit={self._rate_limit_per_minute}/min")
    
    async def __aenter__(self):
        """Context manager entry."""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        await self.disconnect()
    
    async def connect(self):
        """Estabelece conexão com GLPI e inicializa sessão."""
        if self._client is None:
            logger.info(f"Connecting to GLPI at {settings.glpi_base_url}")
            
            # Configurar cliente HTTP com otimizações
            self._client = httpx.AsyncClient(
                base_url=settings.glpi_base_url,
                headers=settings.glpi_headers,
                timeout=httpx.Timeout(settings.request_timeout),  # Timeout default
                limits=httpx.Limits(
                    max_keepalive_connections=10,
                    max_connections=20
                )
            )
            
            # Inicializar sessão GLPI se necessário
            await self._init_session()
    
    async def disconnect(self):
        """Fecha conexão com GLPI e limpa cache."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self._session_token = None
            self._session_cache.clear()
            self._rate_limits.clear()
            logger.info("Disconnected from GLPI, cache cleared")
    
    async def _init_session(self):
        """Inicializa sessão GLPI com tokens do .env (sessão padrão)."""
        try:
            # Validar tokens com requisição simples
            response = await self._client.get("/apirest.php/initSession")
            
            if response.status_code == 200:
                session_data = response.json()
                self._session_token = session_data.get("session_token")
                
                if self._session_token:
                    # Atualizar headers com token da sessão
                    self._client.headers["Session-Token"] = self._session_token
                    logger.info("GLPI session initialized successfully")
                else:
                    logger.warning("No session token received, using app token only")
            else:
                logger.warning(f"Session init failed: {response.status_code}, using app token")
                
        except Exception as e:
            logger.error(f"Failed to initialize GLPI session: {e}")
            # Continuar com app token se falhar sessão

    async def _get_session_for_user(self, user_token: str) -> httpx.AsyncClient:
        """
        Obtém ou cria uma sessão GLPI para o user_token específico.
        Cada usuário do cliente MCP terá sua própria sessão.

        IMPORTANTE: O user_token deve ser fornecido pelo cliente MCP via header X-GLPI-User-Token.
        Isso garante que cada usuário opere com suas próprias permissões GLPI.
        """
        if not user_token:
            # Sem user_token do cliente, verificar se tem fallback no .env
            fallback_token = settings.glpi_user_token
            if fallback_token:
                logger.warning("Using fallback user_token from .env (development mode)")
                user_token = fallback_token
            else:
                # Sem token algum - não é possível autenticar
                raise AuthenticationError(
                    "GLPI user_token required. Configure X-GLPI-User-Token header in your MCP client. "
                    "Each user must provide their own GLPI user_token to ensure proper permissions. "
                    "Get your token from GLPI: Administration > Users > [your user] > Remote access keys"
                )
        
        # Verificar se já existe sessão para este user_token
        if user_token in self._user_sessions:
            session_info = self._user_sessions[user_token]
            session_info["last_used"] = time.time()
            return session_info["client"]
        
        # Criar nova sessão para este user_token
        logger.info(f"Creating new GLPI session for user_token: {user_token[:10]}...")
        
        # Headers específicos para este usuário
        user_headers = {
            "Content-Type": "application/json",
            "App-Token": settings.glpi_app_token,
            "Authorization": f"user_token {user_token}"
        }
        
        # Criar cliente HTTP
        client = httpx.AsyncClient(
            base_url=settings.glpi_base_url,
            headers=user_headers,
            timeout=httpx.Timeout(settings.request_timeout),
            limits=httpx.Limits(
                max_keepalive_connections=5,
                max_connections=10
            )
        )
        
        # Inicializar sessão GLPI para este usuário
        try:
            response = await client.get("/apirest.php/initSession")
            if response.status_code == 200:
                session_data = response.json()
                session_token = session_data.get("session_token")
                if session_token:
                    client.headers["Session-Token"] = session_token
                    logger.info(f"GLPI session created for user_token: {user_token[:10]}...")
        except Exception as e:
            logger.warning(f"Failed to init session for user_token: {e}")
        
        # Salvar no pool
        self._user_sessions[user_token] = {
            "client": client,
            "last_used": time.time()
        }
        
        return client
    
    def _compose_user_key(self, headers: dict, client_ip: str) -> str:
        """
        Compose composite user key for rate limiting.
        Conforme auditoria: URL + app_token + user_token + IP
        """
        return f"{headers.get('X-GLPI-URL','')}:{headers.get('X-GLPI-App-Token','')}:{headers.get('X-GLPI-User-Token','')}:{client_ip}"

    def set_current_user_key(self, user_key: str):
        """Define a chave composta do usuário para uso em chamadas subsequentes."""
        self._current_user_key.set(user_key or "default")

    def set_current_user_token(self, user_token: str):
        """Define o user_token do request atual (vindo do cliente MCP)."""
        self._current_user_token.set(user_token or "")

    def get_current_user_token(self) -> str:
        """Obtém o user_token do request atual ou fallback do .env."""
        try:
            token = self._current_user_token.get()
            if token:
                logger.debug(f"get_current_user_token: Got from context: {token[:10]}...")
                return token
        except LookupError:
            logger.warning("get_current_user_token: No context - using fallback")
        
        # Fallback para token do .env (para testes/desenvolvimento)
        token = settings.glpi_user_token
        if token:
            logger.debug(f"get_current_user_token: Using .env fallback: {token[:10]}...")
        else:
            logger.error("get_current_user_token: NO TOKEN AVAILABLE!")
        return token

    def _check_rate_limit(self, user_key: str) -> bool:
        """
        Verifica rate limiting por usuário.
        Conforme SPEC.md: 60 requisições por minuto por usuário.
        """
        now = time.time()
        
        if user_key not in self._rate_limits:
            self._rate_limits[user_key] = (0, now)
            return True
        
        count, last_reset = self._rate_limits[user_key]
        
        # Resetar contador se passou 1 minuto
        if now - last_reset > 60:
            self._rate_limits[user_key] = (0, now)
            return True
        
        # Verificar se excedeu limite
        if count >= self._rate_limit_per_minute:
            logger.warning(f"Rate limit exceeded for user {user_key}: {count}/{self._rate_limit_per_minute}")
            raise RateLimitError(f"Rate limit exceeded: {self._rate_limit_per_minute} requests per minute")
        
        # Incrementar contador
        self._rate_limits[user_key] = (count + 1, last_reset)
        return True
    
    def _get_cache_key(self, endpoint: str, params: Dict[str, Any]) -> str:
        """Gera chave de cache baseada em endpoint e parâmetros."""
        cache_data = f"{endpoint}:{sorted(params.items())}"
        return hashlib.md5(cache_data.encode()).hexdigest()
    
    def _get_from_cache(self, cache_key: str) -> Optional[Any]:
        """Obtém dados do cache se ainda válidos."""
        if cache_key in self._session_cache:
            data, timestamp = self._session_cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                logger.debug(f"Cache hit for key: {cache_key}")
                return data
            else:
                # Remover cache expirado
                del self._session_cache[cache_key]
        return None
    
    def _save_to_cache(self, cache_key: str, data: Any):
        """Salva dados no cache com timestamp."""
        self._session_cache[cache_key] = (data, time.time())
        logger.debug(f"Saved to cache: {cache_key}")
    
    async def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None, 
                  use_cache: bool = True, user_id: str = "default") -> Any:
        """
        Requisição GET com cache e rate limiting.
        Usa sessão específica do user_token quando fornecido pelo cliente MCP.
        
        Args:
            endpoint: Endpoint da API GLPI
            params: Parâmetros da requisição
            use_cache: Se deve usar cache (default: True)
            user_id: ID do usuário para rate limiting
        
        Returns:
            Dados da resposta JSON
        """
        # Obter cliente HTTP correto (por user_token ou padrão)
        # SEMPRE chamar _get_session_for_user para validar autenticação
        user_token = self.get_current_user_token()
        client = await self._get_session_for_user(user_token)
        
        if client is None:
            raise GLPIError(500, "Client not connected")
        
        params = params or {}
        
        # Verificar rate limiting
        key = user_id if user_id != "default" else self._current_user_key.get()
        self._check_rate_limit(key)
        
        # Tentar cache primeiro (cache é global, independente do user)
        if use_cache:
            cache_key = self._get_cache_key(endpoint, params)
            cached_data = self._get_from_cache(cache_key)
            if cached_data is not None:
                return cached_data
        
        try:
            logger.debug(f"GET {endpoint} with params: {params}")
            response = await client.get(endpoint, params=params)
            
            # Verificar autenticação
            if response.status_code == 401:
                logger.error("Authentication failed - attempting session reinit")
                if user_token:
                    # Remover sessão inválida e recriar
                    if user_token in self._user_sessions:
                        del self._user_sessions[user_token]
                    client = await self._get_session_for_user(user_token)
                else:
                    await self._init_session()
                # Tentar novamente uma vez
                response = await client.get(endpoint, params=params)
            
            response.raise_for_status()
            data = response.json()
            
            # Salvar no cache se sucesso
            if use_cache:
                self._save_to_cache(cache_key, data)
            
            return data
            
        except httpx.TimeoutException:
            raise GLPITimeoutError(f"Request timeout for {endpoint}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid credentials")
            elif e.response.status_code == 404:
                raise GLPIError(404, f"Endpoint not found: {endpoint}")
            else:
                raise GLPIError(e.response.status_code, f"HTTP error: {e.response.text}")
        except Exception as e:
            logger.error(f"GET request failed: {e}")
            raise GLPIError(500, f"Request failed: {str(e)}")
    
    async def post(self, endpoint: str, data: Dict[str, Any], 
                   user_id: str = "default") -> Any:
        """
        Requisição POST com rate limiting.
        Usa sessão específica do user_token quando fornecido pelo cliente MCP.
        
        Args:
            endpoint: Endpoint da API GLPI
            data: Dados para enviar
            user_id: ID do usuário para rate limiting
        
        Returns:
            Dados da resposta JSON
        """
        # Obter cliente HTTP correto (por user_token ou padrão)
        # SEMPRE chamar _get_session_for_user para validar autenticação
        user_token = self.get_current_user_token()
        client = await self._get_session_for_user(user_token)
        
        if client is None:
            raise GLPIError(500, "Client not connected")
        
        # Verificar rate limiting
        key = user_id if user_id != "default" else self._current_user_key.get()
        self._check_rate_limit(key)
        
        # GLPI API espera dados no formato {"input": {...}}
        payload = {"input": data} if data else {}
        
        try:
            logger.debug(f"POST {endpoint} with data: {list(data.keys())}")
            response = await client.post(endpoint, json=payload)
            
            # Verificar autenticação
            if response.status_code == 401:
                logger.error("Authentication failed - attempting session reinit")
                if user_token and user_token in self._user_sessions:
                    del self._user_sessions[user_token]
                    client = await self._get_session_for_user(user_token)
                else:
                    await self._init_session()
                response = await client.post(endpoint, json=payload)
            
            response.raise_for_status()
            return response.json()
            
        except httpx.TimeoutException:
            raise GLPITimeoutError(f"Request timeout for {endpoint}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid credentials")
            elif e.response.status_code == 404:
                raise GLPIError(404, f"Endpoint not found: {endpoint}")
            else:
                raise GLPIError(e.response.status_code, f"HTTP error: {e.response.text}")
        except Exception as e:
            logger.error(f"POST request failed: {e}")
            raise GLPIError(500, f"Request failed: {str(e)}")
    
    async def put(self, endpoint: str, data: Dict[str, Any], 
                  user_id: str = "default") -> Any:
        """
        Requisição PUT com rate limiting.
        Usa sessão específica do user_token quando fornecido pelo cliente MCP.
        
        Args:
            endpoint: Endpoint da API GLPI
            data: Dados para atualizar
            user_id: ID do usuário para rate limiting
        
        Returns:
            Dados da resposta JSON
        """
        # Obter cliente HTTP correto (por user_token ou padrão)
        # SEMPRE chamar _get_session_for_user para validar autenticação
        user_token = self.get_current_user_token()
        client = await self._get_session_for_user(user_token)
        
        if client is None:
            raise GLPIError(500, "Client not connected")
        
        # Verificar rate limiting
        key = user_id if user_id != "default" else self._current_user_key.get()
        self._check_rate_limit(key)
        
        # GLPI API espera dados no formato {"input": {...}}
        payload = {"input": data} if data else {}
        
        try:
            logger.debug(f"PUT {endpoint} with data: {list(data.keys())}")
            response = await client.put(endpoint, json=payload)
            
            # Verificar autenticação
            if response.status_code == 401:
                logger.error("Authentication failed - attempting session reinit")
                if user_token and user_token in self._user_sessions:
                    del self._user_sessions[user_token]
                    client = await self._get_session_for_user(user_token)
                else:
                    await self._init_session()
                response = await client.put(endpoint, json=payload)
            
            response.raise_for_status()
            
            # GLPI API pode retornar 200 OK com body vazio para updates
            text = response.text.strip()
            if not text:
                return {"success": True}
            return response.json()
            
        except httpx.TimeoutException:
            raise GLPITimeoutError(f"Request timeout for {endpoint}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid credentials")
            elif e.response.status_code == 404:
                raise GLPIError(404, f"Endpoint not found: {endpoint}")
            else:
                raise GLPIError(e.response.status_code, f"HTTP error: {e.response.text}")
        except Exception as e:
            logger.error(f"PUT request failed: {e}")
            raise GLPIError(500, f"Request failed: {str(e)}")
    
    async def delete(self, endpoint: str, user_id: str = "default") -> Any:
        """
        Requisição DELETE com rate limiting.
        Usa sessão específica do user_token quando fornecido pelo cliente MCP.
        
        Args:
            endpoint: Endpoint da API GLPI
            user_id: ID do usuário para rate limiting
        
        Returns:
            Dados da resposta JSON
        """
        # Obter cliente HTTP correto (por user_token ou padrão)
        # SEMPRE chamar _get_session_for_user para validar autenticação
        user_token = self.get_current_user_token()
        client = await self._get_session_for_user(user_token)
        
        if client is None:
            raise GLPIError(500, "Client not connected")
        
        # Verificar rate limiting
        key = user_id if user_id != "default" else self._current_user_key.get()
        self._check_rate_limit(key)
        
        try:
            logger.debug(f"DELETE {endpoint}")
            response = await client.delete(endpoint)
            
            # Verificar autenticação
            if response.status_code == 401:
                logger.error("Authentication failed - attempting session reinit")
                if user_token and user_token in self._user_sessions:
                    del self._user_sessions[user_token]
                    client = await self._get_session_for_user(user_token)
                else:
                    await self._init_session()
                response = await client.delete(endpoint)
            
            response.raise_for_status()
            return response.json()
            
        except httpx.TimeoutException:
            raise GLPITimeoutError(f"Request timeout for {endpoint}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid credentials")
            elif e.response.status_code == 404:
                raise GLPIError(404, f"Endpoint not found: {endpoint}")
            else:
                raise GLPIError(e.response.status_code, f"HTTP error: {e.response.text}")
        except Exception as e:
            logger.error(f"DELETE request failed: {e}")
            raise GLPIError(500, f"Request failed: {str(e)}")
    
    def clear_cache(self):
        """Limpa todo o cache de sessão."""
        self._session_cache.clear()
        logger.info("Session cache cleared")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas do cache e rate limiting."""
        return {
            "cache_size": len(self._session_cache),
            "cached_keys": list(self._session_cache.keys()),
            "rate_limits": {
                user: {"count": count, "last_reset": last_reset}
                for user, (count, last_reset) in self._rate_limits.items()
            },
            "session_active": self._session_token is not None,
            "user_sessions_count": len(self._user_sessions),
            "user_sessions": [
                {"token_prefix": token[:10] + "...", "last_used": info["last_used"]}
                for token, info in self._user_sessions.items()
            ]
        }


# Instância global do session manager
session_manager = SessionManager()
