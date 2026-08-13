"""
Testes adicionais para SessionManager cobrindo cache e rate limit.
"""

import time
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.auth.session_manager import SessionManager
from src.models.exceptions import RateLimitError


@pytest.mark.asyncio
async def test_get_uses_cache_and_rate_limit():
    """Deve usar cache após primeira chamada e não repetir requisição."""
    manager = SessionManager()
    mock_client = AsyncMock()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"ok": True}
    response.raise_for_status.return_value = None
    # Todos os verbos passam pelo ponto unico client.request(method, ...).
    mock_client.request.return_value = response
    # GLPI 11 auth: o client agora vem do pool por user_token (não mais de
    # um _client único). Fornecemos um token e injetamos o client mockado
    # via _get_session_for_user para isolar o teste de cache/rate-limit.
    manager.set_current_user_token("test-token")
    manager._get_session_for_user = AsyncMock(return_value=mock_client)

    # primeira chamada popula cache
    data1 = await manager.get("/api/test", params={"a": 1}, use_cache=True, user_id="u1")
    # segunda chamada deve vir do cache (sem novo GET)
    data2 = await manager.get("/api/test", params={"a": 1}, use_cache=True, user_id="u1")

    assert data1 == {"ok": True}
    assert data2 == {"ok": True}
    assert mock_client.request.call_count == 1


@pytest.mark.asyncio
async def test_write_invalidates_read_cache():
    """Regressao #7: apos um POST bem-sucedido o cache de GET deve ser
    invalidado, para que a proxima leitura reflita a escrita (ex: followup
    recem-criado) em vez de devolver dados pre-escrita."""
    manager = SessionManager()

    get_resp = MagicMock()
    get_resp.status_code = 200
    get_resp.raise_for_status.return_value = None
    # 1a leitura devolve estado antigo; 2a (pos-escrita) devolve novo estado.
    get_resp.json.side_effect = [{"v": "old"}, {"v": "new"}]

    post_resp = MagicMock()
    post_resp.status_code = 201
    post_resp.raise_for_status.return_value = None
    post_resp.text = '{"id": 999}'
    post_resp.json.return_value = {"id": 999}

    mock_client = AsyncMock()

    # Leitura e escrita compartilham client.request(method, ...); despacha pelo
    # verbo para manter as respostas distintas.
    async def _dispatch(method, *args, **kwargs):
        return get_resp if method == "GET" else post_resp

    mock_client.request.side_effect = _dispatch

    manager.set_current_user_token("test-token")
    manager._get_session_for_user = AsyncMock(return_value=mock_client)

    # leitura inicial popula o cache
    first = await manager.get("/Ticket/1/TicketFollowup", params={}, use_cache=True, user_id="u1")
    assert first == {"v": "old"}
    assert mock_client.request.call_count == 1

    # escrita deve invalidar o cache
    await manager.post("/TicketFollowup", data={"content": "x"}, user_id="u1")
    assert len(manager._session_cache) == 0

    # leitura seguinte NAO pode vir do cache: refaz o GET e ve o novo estado
    second = await manager.get("/Ticket/1/TicketFollowup", params={}, use_cache=True, user_id="u1")
    assert second == {"v": "new"}
    assert mock_client.request.call_count == 3  # GET, POST, GET


def test_rate_limit_blocks_when_exceeded():
    """Deve lançar RateLimitError ao exceder limite por chave."""
    manager = SessionManager()
    key = "u1"
    # Simula 60 requisições já feitas no último minuto
    manager._rate_limits[key] = (manager._rate_limit_per_minute, time.time())
    with pytest.raises(RateLimitError):
        manager._check_rate_limit(key)
