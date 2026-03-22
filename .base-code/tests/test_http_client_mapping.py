"""
Testes para o HTTPClient._handle_response mapeando erros HTTP.
"""

import pytest
import httpx

from src.http_client import HTTPClient
from src.utils.helpers import logger as app_logger


class DummyLogger:
    """Logger dummy para aceitar chamadas com múltiplos argumentos."""
    def debug(self, *args, **kwargs):
        pass
    def error(self, *args, **kwargs):
        pass


dummy_logger = DummyLogger()
from src.models import AuthenticationError, GLPIError


def test_handle_response_success(monkeypatch):
    monkeypatch.setattr("src.http_client.logger", dummy_logger, raising=False)
    resp = httpx.Response(200, json={"ok": True})
    result = HTTPClient._handle_response(resp)
    assert result == {"ok": True}


def test_handle_response_auth_error(monkeypatch):
    monkeypatch.setattr("src.http_client.logger", dummy_logger, raising=False)
    resp = httpx.Response(401, text="Unauthorized")
    with pytest.raises(AuthenticationError):
        HTTPClient._handle_response(resp)


def test_handle_response_not_found(monkeypatch):
    monkeypatch.setattr("src.http_client.logger", dummy_logger, raising=False)
    resp = httpx.Response(404, text="Not found")
    with pytest.raises(GLPIError) as exc:
        HTTPClient._handle_response(resp)
    assert exc.value.code == 404


def test_handle_response_server_error(monkeypatch):
    monkeypatch.setattr("src.http_client.logger", dummy_logger, raising=False)
    resp = httpx.Response(500, text="Boom")
    with pytest.raises(GLPIError) as exc:
        HTTPClient._handle_response(resp)
    assert exc.value.code == 500
