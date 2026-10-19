"""
MCP GLPI - Servidor FastAPI principal.
Suporta Streamable HTTP Transport (Claude + Gemini).
"""

from fastapi import FastAPI, Request, Depends, Response
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
from datetime import datetime
import asyncio
import logging
import re
import uuid
import uvicorn

from fastapi import HTTPException

from src import __version__
from src.config import settings
from src.logger import logger
from src.utils.helpers import response_truncator
from src.models import MCPRequest, MCPResponse
from src.handlers import mcp_handler  # exportar mcp_handler no módulo handlers
from src.http_client import http_client
from src.middleware.webhook_auth import verify_webhook_signature
from src.services.ai_integration import ai_integration
from src.auth.session_manager import session_manager
from src.models.exceptions import HTTP_TO_JSONRPC, RateLimitError

# Header names whose value must never be logged in full.
_SENSITIVE_HEADER = re.compile(
    r"token|authorization|api[-_]?key|cookie|secret|password", re.IGNORECASE
)

# ============= STREAMABLE HTTP SESSION MANAGEMENT =============
# Armazena sessões ativas para Streamable HTTP (Gemini requirement)
mcp_sessions: dict[str, dict] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Context manager para gerenciar ciclo de vida da aplicação."""
    # Startup
    logger.info("MCP GLPI starting...")
    try:
        await http_client.connect()
        await session_manager.connect()  # Conectar session_manager para os services
        logger.info("Connected to GLPI successfully")
    except Exception as e:
        logger.error(f"Failed to connect to GLPI: {e}")
        # Continuar mesmo sem conexão - pode ser apenas de testes

    yield

    # Shutdown
    logger.info("MCP GLPI shutting down...")
    await session_manager.disconnect()


# Criar aplicação FastAPI
app = FastAPI(
    title="MCP GLPI Server",
    description="MCP (Model Context Protocol) server for GLPI integration",
    version=__version__,
    lifespan=lifespan
)


@app.middleware("http")
async def bearer_auth_middleware(request: Request, call_next):
    """
    Bearer token authentication middleware.
    Protects all /mcp endpoints when MCP_AUTH_TOKEN is set.
    /health is excluded to allow liveness probes without auth.
    """
    auth_token = settings.mcp_auth_token
    if auth_token and request.url.path.startswith("/mcp"):
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            logger.warning(f"Missing Bearer token from {request.client.host}")
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "error_description": "Missing Bearer token"}
            )
        provided_token = authorization.removeprefix("Bearer ").strip()
        if provided_token != auth_token:
            logger.warning(f"Invalid Bearer token from {request.client.host}")
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content={"error": "invalid_token", "error_description": "Invalid or expired Bearer token"}
            )
    return await call_next(request)


@app.get("/health", tags=["Health"])
async def health_check():
    """Endpoint de verificação de saúde."""
    logger.debug("Health check requested")
    return {
        "status": "healthy",
        "service": "mcp-glpi",
        "version": __version__,
        "timestamp": datetime.utcnow().isoformat(),
        "transport": "streamable-http"
    }


# ============= STREAMABLE HTTP ENDPOINTS (Claude + Gemini) =============

@app.get("/mcp", tags=["MCP"])
async def mcp_sse_endpoint(request: Request):
    """
    SSE endpoint para notificações server-to-client.
    Gemini CLI conecta aqui primeiro para estabelecer sessão.
    Suporta Streamable HTTP Transport conforme MCP Protocol 2024-11-05.
    """
    session_id = request.headers.get("mcp-session-id") or str(uuid.uuid4())

    logger.info(f"SSE connection opened: session_id={session_id}")

    # Registrar sessão
    mcp_sessions[session_id] = {"created_at": datetime.utcnow(), "active": True}

    async def event_generator():
        """Gera eventos SSE para o cliente."""
        try:
            # Enviar evento inicial de endpoint
            yield "event: endpoint\ndata: /mcp\n\n"

            # Keepalive loop
            while True:
                if await request.is_disconnected():
                    break

                # Verificar se sessão ainda está ativa
                if session_id not in mcp_sessions:
                    break

                # Enviar keepalive
                yield ":keepalive\n\n"
                await asyncio.sleep(30)

        except asyncio.CancelledError:
            pass
        finally:
            # Cleanup da sessão
            if session_id in mcp_sessions:
                del mcp_sessions[session_id]
            logger.info(f"SSE connection closed: session_id={session_id}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Mcp-Session-Id": session_id
        }
    )


@app.delete("/mcp", tags=["MCP"])
async def mcp_session_terminate(request: Request):
    """
    Encerra sessão MCP.
    Gemini CLI chama para terminar sessão gracefully.
    """
    session_id = request.headers.get("mcp-session-id")

    if session_id and session_id in mcp_sessions:
        del mcp_sessions[session_id]
        logger.info(f"Session terminated: session_id={session_id}")

    return {"status": "session_terminated", "session_id": session_id}


def _rate_limited_response(mcp_request: MCPRequest, exc: RateLimitError):
    """Rate limit hit before dispatch: readable text instead of an unhandled 500.

    ``tools/call`` gets a tool result with ``isError`` (HTTP 200) so the text reaches the agent
    through gateways; any other method gets HTTP 429 with a JSON-RPC error.
    """
    from fastapi.responses import JSONResponse
    from src.handlers import tool_error_result

    if mcp_request.method == "tools/call":
        return JSONResponse(content={"jsonrpc": "2.0", "id": mcp_request.id,
                                     "result": tool_error_result(exc.message)})
    return JSONResponse(status_code=429, content={"jsonrpc": "2.0", "id": mcp_request.id,
                                                  "error": {"code": HTTP_TO_JSONRPC[429], "message": exc.message}})


@app.post("/mcp", tags=["MCP"], response_model_exclude_none=True)
async def mcp_handler_http(request: Request, mcp_request: MCPRequest) -> MCPResponse:
    """
    Handler JSON-RPC do protocolo MCP.
    Recebe requisições e roteia para handlers apropriados via mcp_handler.handle_request.
    Conforme auditoria GAP-CRIT-01: Rate limit com chave composta headers+IP.
    
    Headers esperados do cliente MCP:
    - X-GLPI-User-Token: Token do usuário GLPI (obrigatório em produção)
    """
    logger.info(f"MCP request: method={mcp_request.method}")

    # GAP-CRIT-01: Extrair headers e IP para rate limit com chave composta
    client_ip = request.scope.get("client")[0] if request.scope.get("client") else "0.0.0.0"
    headers_dict = dict(request.headers)
    
    # Diagnostic header dump. DEBUG level: this fires on every request (including
    # the token-less `initialize` handshake), so higher levels flood the log and
    # bury real errors.
    if logger.get_logger().isEnabledFor(logging.DEBUG):
        logger.debug("=" * 80)
        logger.debug("HEADERS RECEBIDOS DO CLIENTE MCP:")
        for key, value in headers_dict.items():
            # Mask any credential-bearing header, not just *token* ones.
            if _SENSITIVE_HEADER.search(key):
                logger.debug(f"  {key}: {value[:10]}..." if len(value) > 10 else f"  {key}: {value}")
            else:
                logger.debug(f"  {key}: {value}")
        logger.debug("=" * 80)
    
    user_key = session_manager._compose_user_key(headers_dict, client_ip)
    session_manager.set_current_user_key(user_key)
    try:
        session_manager._check_rate_limit(user_key)
    except RateLimitError as exc:
        # Unhandled, this became "500 Internal Server Error" with no text (measured 28/09/2026).
        return _rate_limited_response(mcp_request, exc)

    # Extrair user_token do header do cliente MCP (cada usuário envia seu próprio token)
    # Fallback para GLPI_USER_TOKEN do .env quando o header não está presente
    user_token = headers_dict.get("x-glpi-user-token", "") or settings.glpi_user_token
    session_manager.set_current_user_token(user_token)
    if user_token and headers_dict.get("x-glpi-user-token"):
        logger.debug(f"USER TOKEN ENCONTRADO (header): {user_token[:10]}...")
    elif user_token:
        logger.debug(f"USER TOKEN ENCONTRADO (fallback .env): {user_token[:10]}...")
    else:
        # Not an error: `initialize` / `notifications/initialized` legitimately
        # carry no user token. Calls that actually need it fail later, explicitly.
        logger.debug("USER TOKEN ausente nos headers (esperado no handshake MCP)")

    # Streamable HTTP: Manage session ID per MCP protocol spec
    session_id = request.headers.get("mcp-session-id") or str(uuid.uuid4())
    if session_id not in mcp_sessions:
        mcp_sessions[session_id] = {"created_at": datetime.utcnow(), "active": True}

    # Delegar para mcp_handler.handle_request conforme auditoria BUG-CRIT-01
    response = await mcp_handler.handle_request(mcp_request.model_dump())
    result = response.get("result")
    if result is not None:
        result = response_truncator.truncate_json_response(result)
    mcp_response = MCPResponse(
        jsonrpc=response.get("jsonrpc", "2.0"),
        result=result,
        error=response.get("error"),
        id=response.get("id")
    )
    # Return with Mcp-Session-Id header (required for Streamable HTTP transport)
    from fastapi.responses import JSONResponse
    return JSONResponse(
        content=mcp_response.model_dump(exclude_none=True),
        headers={"Mcp-Session-Id": session_id},
    )


# ============= WEBHOOKS (BUG-CRIT-02) =============

def _webhook_reply(ticket_id, analysis=None, **extra):
    """Reply for an inbound ticket webhook.

    @MX:NOTE: `analysis` states what the server did with the event.
    @MX:REASON: with ENABLE_AI_ANALYSIS=false the handlers still called the
    in-memory AI stub and answered "received" plus a job_id, so the sender
    believed an analysis was queued. "received" only means the event was
    authenticated and read; `analysis` is "queued" (a job exists), "disabled"
    (ENABLE_AI_ANALYSIS=false, nothing was queued) and absent for events that
    never trigger analysis.
    """
    reply = {"status": "received", "ticket_id": ticket_id}
    if analysis is not None:
        reply["analysis"] = analysis
    reply.update(extra)
    return reply


def _analysis_flag():
    """"disabled" when AI analysis is switched off, otherwise None."""
    return None if settings.enable_ai_analysis else "disabled"


@app.post("/webhooks/ticket/created", tags=["Webhooks"])
async def webhook_ticket_created(request: Request, _=Depends(verify_webhook_signature)):
    """
    Webhook para ticket criado.
    Conforme auditoria BUG-CRIT-02: Implementar webhooks com HMAC.
    """
    payload = await request.json()
    ticket_id = payload.get("ticket_id")
    
    if not settings.enable_ai_analysis:
        logger.info(f"Webhook ticket/created: ticket_id={ticket_id}, AI analysis disabled, no job queued")
        return _webhook_reply(ticket_id, "disabled")

    if ticket_id:
        job_id = await ai_integration.trigger_analysis(ticket_id)
        logger.info(f"Webhook ticket/created: ticket_id={ticket_id}, job_id={job_id}")
        return _webhook_reply(ticket_id, "queued", job_id=job_id)

    return _webhook_reply(None)


@app.post("/webhooks/ticket/updated", tags=["Webhooks"])
async def webhook_ticket_updated(request: Request, _=Depends(verify_webhook_signature)):
    """
    Webhook para ticket atualizado.
    Conforme auditoria BUG-CRIT-02.
    """
    payload = await request.json()
    ticket_id = payload.get("ticket_id")
    logger.info(f"Webhook ticket/updated: ticket_id={ticket_id}")
    return _webhook_reply(ticket_id, _analysis_flag())


@app.post("/webhooks/ticket/closed", tags=["Webhooks"])
async def webhook_ticket_closed(request: Request, _=Depends(verify_webhook_signature)):
    """
    Webhook para ticket fechado.
    Conforme auditoria BUG-CRIT-02.
    """
    payload = await request.json()
    ticket_id = payload.get("ticket_id")
    logger.info(f"Webhook ticket/closed: ticket_id={ticket_id}")
    return _webhook_reply(ticket_id, _analysis_flag())


@app.post("/webhooks/ticket/followup", tags=["Webhooks"])
async def webhook_ticket_followup(request: Request, _=Depends(verify_webhook_signature)):
    """
    Webhook para novo followup em ticket.
    Conforme SPEC RF06 (followup).
    """
    payload = await request.json()
    ticket_id = payload.get("ticket_id")
    logger.info(f"Webhook ticket/followup: ticket_id={ticket_id}")
    return _webhook_reply(ticket_id, _analysis_flag())


# ============= METRICS (GAP-CRIT-02) =============

try:
    from prometheus_client import Histogram, Counter, generate_latest, CONTENT_TYPE_LATEST
    
    TOOL_DURATION = Histogram(
        "mcp_tool_duration_seconds", 
        "Latência de tools MCP", 
        ["tool"]
    )
    REQUEST_COUNT = Counter(
        "mcp_requests_total",
        "Total de requisições MCP",
        ["method"]
    )
    
    @app.get("/metrics", tags=["Observability"])
    def metrics():
        """
        Endpoint Prometheus /metrics.
        Conforme auditoria GAP-CRIT-02.
        """
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
    
    PROMETHEUS_AVAILABLE = True
except ImportError:
    logger.warning("prometheus_client not installed, /metrics endpoint disabled")
    PROMETHEUS_AVAILABLE = False


if __name__ == "__main__":
    uvicorn.run(
        "src.main:app",
        host=settings.mcp_host,
        port=settings.mcp_port,
        reload=True,
        log_level="info"
    )
