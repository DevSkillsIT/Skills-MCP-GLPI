"""
Testes adicionais para SessionManager cobrindo cache e rate limit.
"""

import asyncio
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
    mock_client.get.return_value = response
    manager._client = mock_client

    # primeira chamada popula cache
    data1 = await manager.get("/api/test", params={"a": 1}, use_cache=True, user_id="u1")
    # segunda chamada deve vir do cache (sem novo GET)
    data2 = await manager.get("/api/test", params={"a": 1}, use_cache=True, user_id="u1")

    assert data1 == {"ok": True}
    assert data2 == {"ok": True}
    assert mock_client.get.call_count == 1


def test_rate_limit_blocks_when_exceeded():
    """Deve lançar RateLimitError ao exceder limite por chave."""
    manager = SessionManager()
    key = "u1"
    # Simula 60 requisições já feitas no último minuto
    manager._rate_limits[key] = (manager._rate_limit_per_minute, time.time())
    with pytest.raises(RateLimitError):
        manager._check_rate_limit(key)
