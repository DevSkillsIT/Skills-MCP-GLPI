"""
Session Manager com Cache e Rate Limiting - Conforme SPEC.md RF01
Baseado em http_client.py existente + código fonte Docker
"""

import asyncio
import contextvars
import hashlib
import secrets
import time
from typing import Optional, Dict, Any, Tuple
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
        # @MX:ANCHOR: uma sessao so entra no pool se o GLPI a tiver aceitado.
        # @MX:WARN: nunca devolver o client quando o initSession falhar.
        # @MX:REASON: antes, a falha era apenas registrada em log e o client ia
        # para o pool assim mesmo. Como e a resolucao da sessao que autentica o
        # chamador, qualquer token — invalido, revogado, inventado — "passava"
        # na validacao. Combinado com o cache de leitura, um token qualquer
        # recebia dados ja carregados por outra pessoa, sem tocar o GLPI e sem
        # erro nenhum. Reproduzido: token aleatorio recebeu a lista de grupos
        # do cliente, servida do cache.
        session_token = None
        try:
            response = await client.get("/apirest.php/initSession")
            if response.status_code == 200:
                session_data = response.json()
                session_token = session_data.get("session_token")
                if session_token:
                    client.headers["Session-Token"] = session_token
                    logger.info(f"GLPI session created for user_token: {user_token[:10]}...")
            else:
                logger.error(
                    f"initSession FAILED user={user_token[:10]}... "
                    f"status={response.status_code} body={response.text[:300]}"
                )
        except Exception as e:
            logger.warning(f"Failed to init session for user_token: {e}", exc_info=True)

        if not session_token:
            await client.aclose()
            raise AuthenticationError(
                "Token de usuario do GLPI invalido ou expirado. Verifique o header "
                "X-GLPI-User-Token do cliente MCP."
            )

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
        Conforme SPEC.md: rate_limit_requests_per_minute por usuário.
        Localhost (127.0.0.1/::1) é isento para facilitar desenvolvimento e
        chamadas paralelas de LLM.
        """
        # Localhost bypass: user_key ends with ":127.0.0.1" or ":::127.0.0.1"
        # or ":::1". This keeps external clients rate-limited.
        if user_key.endswith(":127.0.0.1") or user_key.endswith(":::127.0.0.1") or user_key.endswith(":::1"):
            return True

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
        """Gera chave de cache por endpoint, parametros E identidade.

        @MX:ANCHOR: a identidade do chamador faz parte da chave de cache.
        @MX:REASON: a chave era global (endpoint + parametros). Como o GLPI
        aplica permissao e entidade por usuario, duas pessoas com escopos
        diferentes pedindo o mesmo endpoint compartilhavam a MESMA entrada:
        quem chegasse depois recebia o recorte de quem chegou antes, por ate
        uma hora. Num servidor que atende varios clientes, isso e exposicao
        entre clientes — e nao produz erro nenhum, so uma resposta plausivel.
        O token entra como digest, nunca em claro.
        """
        identity = self.get_current_user_token() or self._current_user_key.get() or "anonymous"
        identity_digest = hashlib.sha256(identity.encode()).hexdigest()[:16]
        cache_data = f"{identity_digest}:{endpoint}:{sorted(params.items())}"
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
    
    # ------------------------------------------------------------------
    # Unified request path
    # ------------------------------------------------------------------

    async def _backoff(self, attempt: int, retry_after: Optional[float] = None) -> None:
        """Wait before the next attempt.

        Honours the server's Retry-After when it sent one; otherwise grows
        exponentially with full jitter, so concurrent callers recovering from
        the same outage do not resynchronise into a thundering herd.
        """
        if retry_after is not None and retry_after > 0:
            delay = min(retry_after, settings.retry_backoff_cap)
        else:
            base = min(
                settings.retry_backoff_base ** attempt, settings.retry_backoff_cap
            )
            delay = base + secrets.SystemRandom().uniform(0.0, base / 2)
        await asyncio.sleep(delay)

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
        """Parse the Retry-After header when the server sends a delay in seconds."""
        raw = response.headers.get("retry-after")
        if not raw:
            return None
        try:
            return float(raw.strip())
        except (TypeError, ValueError):
            # The header also allows an HTTP date. Falling back to our own
            # backoff is safer than parsing a date format we cannot trust.
            return None

    async def _ensure_session(self, user_id: str) -> httpx.AsyncClient:
        """Resolve the caller's session and charge the rate limit.

        @MX:ANCHOR: every request path must pass through here before touching
        data — including cache hits.
        @MX:REASON: resolving the session is what validates the caller's token.
        Serving a cached read without it would hand data to an unauthenticated
        caller, and because the cache key is global that data can belong to a
        different tenant.
        """
        user_token = self.get_current_user_token()
        client = await self._get_session_for_user(user_token)

        if client is None:
            raise GLPIError(500, "Client not connected")

        key = user_id if user_id != "default" else self._current_user_key.get()
        self._check_rate_limit(key)
        return client

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        user_id: str = "default",
        client: Optional[httpx.AsyncClient] = None,
    ) -> httpx.Response:
        """Execute one GLPI call, with retries, re-auth and error mapping.

        @MX:ANCHOR: single execution point for every GLPI HTTP call.
        @MX:REASON: the four verbs used to duplicate client resolution, rate
        limiting, 401 handling and error mapping. Fixing any of them meant
        fixing four places, and the 401 retry was the only recovery the client
        had: a restarting GLPI or a rate-limit response surfaced to the user as
        a hard failure.

        @MX:WARN: writes are NOT retried once the server has answered.
        @MX:REASON: GLPI may have applied the write before failing, so a retry
        would create a second ticket or a duplicate followup. Only failures
        that provably happened before the request left the client (connection
        refused, connect timeout) and explicit throttling (429, which means the
        server rejected without processing) are safe to repeat.
        """
        user_token = self.get_current_user_token()
        if client is None:
            client = await self._ensure_session(user_id)

        is_read = method == "GET"
        max_retries = max(int(settings.max_retries), 0)
        attempt = 0
        reauth_attempted = False

        while True:
            try:
                response = await client.request(
                    method, endpoint, params=params, json=json_body
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                # The request never reached GLPI, so repeating it is safe even
                # for writes.
                if attempt < max_retries:
                    logger.warning(
                        f"{method} {endpoint} connection failure ({exc}), "
                        f"retrying (attempt {attempt + 1}/{max_retries})"
                    )
                    await self._backoff(attempt)
                    attempt += 1
                    continue
                raise GLPIError(503, f"Nao foi possivel conectar ao GLPI: {exc}")
            except httpx.TimeoutException:
                # Read/write timeouts happen after the request was sent: GLPI
                # may have processed it. Only reads may be repeated.
                if is_read and attempt < max_retries:
                    logger.warning(
                        f"GET {endpoint} timed out, "
                        f"retrying (attempt {attempt + 1}/{max_retries})"
                    )
                    await self._backoff(attempt)
                    attempt += 1
                    continue
                raise GLPITimeoutError(f"Request timeout for {endpoint}")

            status = response.status_code

            # Expired session: refresh credentials once and replay.
            if status == 401 and not reauth_attempted:
                reauth_attempted = True
                logger.warning(
                    f"{method} {endpoint} returned 401 - reinitialising session"
                )
                if user_token:
                    self._user_sessions.pop(user_token, None)
                    client = await self._get_session_for_user(user_token)
                    if client is None:
                        raise AuthenticationError("Invalid credentials")
                else:
                    await self._init_session()
                continue

            # Throttled: the server refused without doing the work, so even a
            # write can be replayed.
            if status == 429 and attempt < max_retries:
                retry_after = self._retry_after_seconds(response)
                logger.warning(
                    f"{method} {endpoint} rate-limited by GLPI, "
                    f"retrying (attempt {attempt + 1}/{max_retries})"
                )
                await self._backoff(attempt, retry_after)
                attempt += 1
                continue

            # Server-side failure: safe to repeat for reads only.
            if status >= 500 and is_read and attempt < max_retries:
                logger.warning(
                    f"GET {endpoint} returned {status}, "
                    f"retrying (attempt {attempt + 1}/{max_retries})"
                )
                await self._backoff(attempt)
                attempt += 1
                continue

            if status >= 400:
                raise self._map_error(status, endpoint, response)

            return response

    @staticmethod
    def _map_error(status: int, endpoint: str, response: httpx.Response) -> Exception:
        """Translate an HTTP failure into the project's exception vocabulary."""
        if status == 401:
            return AuthenticationError("Invalid credentials")
        if status == 404:
            resource = endpoint.replace("/apirest.php/", "").strip("/")
            return GLPIError(404, f"Recurso nao encontrado no GLPI: {resource}")
        if status == 429:
            return RateLimitError(
                "Limite de requisicoes do GLPI atingido. Tente novamente em instantes."
            )
        return GLPIError(status, f"HTTP error: {response.text}")

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
        params = params or {}

        # Validar a sessão ANTES de olhar o cache: é a resolução da sessão que
        # autentica o chamador, e a chave de cache é global (não inclui o
        # token). Servir um cache hit sem isso entregaria dados de um tenant a
        # quem não deveria vê-los.
        client = await self._ensure_session(user_id)

        cache_key = None
        if use_cache:
            cache_key = self._get_cache_key(endpoint, params)
            cached_data = self._get_from_cache(cache_key)
            if cached_data is not None:
                return cached_data

        logger.debug(f"GET {endpoint} with params: {params}")
        response = await self._request(
            "GET", endpoint, params=params, user_id=user_id, client=client
        )

        try:
            data = response.json()
        except ValueError as exc:
            raise GLPIError(500, f"Resposta invalida do GLPI: {exc}")

        if use_cache and cache_key is not None:
            self._save_to_cache(cache_key, data)

        return data

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
        # GLPI API espera dados no formato {"input": {...}}
        payload = {"input": data} if data else {}

        logger.debug(f"POST {endpoint} with data: {list(data.keys())}")
        response = await self._request(
            "POST", endpoint, json_body=payload, user_id=user_id
        )

        # @MX:NOTE: invalida o cache de leitura apos qualquer escrita bem-sucedida.
        # @MX:REASON: GET tem TTL longo; sem isto, get_followups/get_history/listas
        # retornam dados pre-escrita e o LLM duplica acoes (ex: followups repetidos).
        self.clear_cache()

        text = response.text.strip()
        if not text:
            return {"success": True}
        return response.json()


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
        # GLPI API espera dados no formato {"input": {...}}
        payload = {"input": data} if data else {}

        logger.debug(f"PUT {endpoint} with data: {list(data.keys())}")
        response = await self._request(
            "PUT", endpoint, json_body=payload, user_id=user_id
        )

        # @MX:NOTE: invalida cache de leitura apos escrita (ver post()).
        self.clear_cache()

        # GLPI API pode retornar 200 OK com body vazio para updates
        text = response.text.strip()
        if not text:
            return {"success": True}
        return response.json()


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
        logger.debug(f"DELETE {endpoint}")
        response = await self._request("DELETE", endpoint, user_id=user_id)

        # @MX:NOTE: invalida cache de leitura apos escrita (ver post()).
        self.clear_cache()

        text = response.text.strip()
        if not text:
            return {"success": True}
        return response.json()


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
