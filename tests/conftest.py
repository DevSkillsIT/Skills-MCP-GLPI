"""
Configurações e fixtures para testes.
"""

import pytest
import os
from unittest.mock import MagicMock, AsyncMock, patch
from src.config.settings import Settings


@pytest.fixture
def mock_settings():
    """Fixture com configurações mockadas."""
    return Settings(
        glpi_base_url="https://test.glpi.local",
        glpi_app_token="test-token-123",
        glpi_user_token="",
        mcp_port=8824,
        mcp_host="0.0.0.0",
        log_level="DEBUG",
        connection_timeout=30,
        request_timeout=60,
        pool_workers=2
    )


@pytest.fixture
def mock_http_client():
    """Fixture com cliente HTTP mockado."""
    client = AsyncMock()
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.put = AsyncMock()
    client.delete = AsyncMock()
    client.patch = AsyncMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    return client


@pytest.fixture
def mock_logger():
    """Fixture com logger mockado."""
    logger = MagicMock()
    logger.debug = MagicMock()
    logger.info = MagicMock()
    logger.warning = MagicMock()
    logger.error = MagicMock()
    logger.critical = MagicMock()
    return logger


@pytest.fixture
async def http_client_context(mock_http_client):
    """Fixture com contexto do cliente HTTP."""
    with patch("src.http_client.http_client", mock_http_client):
        yield mock_http_client
