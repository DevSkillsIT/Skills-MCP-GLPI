"""Modo credencial-por-requisição (processo multiempresa atrás do ContextForge).

Regra de todo MCP atrás do ContextForge (27/09/2026):
- ``initialize``, ``ping``, notificações, listas e ``prompts/get`` respondem SEM credencial de cliente;
- o token do NOSSO MCP (``Authorization: Bearer``) é exigido em tudo que passa por ``/mcp``;
- método que lê ou grava dado exige ``x-glpi-url`` + ``x-glpi-app-token`` + ``x-glpi-user-token``
  naquela requisição e nunca cai para uma credencial guardada no processo.
"""
from __future__ import annotations

import asyncio
import contextvars
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import src.main as main_mod
from src.auth.session_manager import session_manager
from src.config import settings
from src.models.exceptions import AuthenticationError

TOKEN_OK = "tok-do-nosso-mcp-0001"
URL_OK = "https://suporte.meucomputador.com.br"
CRED = {
    "x-glpi-url": URL_OK,
    "x-glpi-app-token": "APP-DO-CLIENTE",
    "x-glpi-user-token": "USER-DO-CLIENTE",
}
# Valores guardados no processo: se aparecerem numa sessão, houve fallback.
GUARDADO = {
    "glpi_base_url": "https://glpi-do-processo.example",
    "glpi_app_token": "APP-GUARDADO-NO-PROCESSO",
    "glpi_user_token": "USER-GUARDADO-NO-PROCESSO",
}


@pytest.fixture
def modo(monkeypatch):
    """Processo em modo credencial-por-requisição, com credencial guardada de propósito."""
    for k, v in {**GUARDADO, "credencial_por_requisicao": True, "mcp_auth_tokens": TOKEN_OK}.items():
        monkeypatch.setitem(settings.__dict__, k, v)
    fake = AsyncMock(side_effect=lambda req: {"jsonrpc": "2.0", "id": req.get("id"), "result": {"ok": True}})
    monkeypatch.setattr(main_mod.mcp_handler, "handle_request", fake)
    return fake


@pytest.fixture
def client():
    return TestClient(main_mod.app)


def rpc(method: str, params: dict | None = None) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}


def bearer(tok: str = TOKEN_OK) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# ---------------------------------------------------------------- (a) credencial completa
@pytest.mark.parametrize("falta", ["x-glpi-url", "x-glpi-app-token", "x-glpi-user-token"])
def test_tools_call_sem_um_dos_tres_headers_e_recusado(modo, client, falta):
    hs = {**bearer(), **{k: v for k, v in CRED.items() if k != falta}}
    r = client.post("/mcp", json=rpc("tools/call", {"name": "glpi_search_admin_resources"}), headers=hs)
    assert r.status_code == 400
    msg = r.json()["error"]["message"]
    assert falta in msg and "x-glpi-url" in msg
    for valor in CRED.values():  # a resposta nunca ecoa a credencial
        assert valor not in r.text
    modo.assert_not_called()


def test_tools_call_sem_nenhum_header_e_recusado(modo, client):
    r = client.post("/mcp", json=rpc("tools/call", {"name": "glpi_search_admin_resources"}), headers=bearer())
    assert r.status_code == 400
    modo.assert_not_called()


@pytest.mark.parametrize("metodo", ["resources/read", "completion/complete", "metodo/inventado"])
def test_outros_metodos_de_dado_exigem_credencial(modo, client, metodo):
    r = client.post("/mcp", json=rpc(metodo, {"uri": "glpi://x"}), headers=bearer())
    assert r.status_code == 400
    modo.assert_not_called()


def test_tools_call_com_os_tres_headers_passa(modo, client):
    r = client.post("/mcp", json=rpc("tools/call", {"name": "x"}), headers={**bearer(), **CRED})
    assert r.status_code == 200
    modo.assert_called_once()


def test_x_glpi_url_fora_da_allowlist_continua_403(modo, client):
    hs = {**bearer(), **CRED, "x-glpi-url": "https://glpi-intruso.example"}
    r = client.post("/mcp", json=rpc("tools/call", {"name": "x"}), headers=hs)
    assert r.status_code == 403
    modo.assert_not_called()


def test_instancia_do_processo_nao_entra_na_allowlist(modo, client):
    hs = {**bearer(), **CRED, "x-glpi-url": GUARDADO["glpi_base_url"]}
    r = client.post("/mcp", json=rpc("tools/call", {"name": "x"}), headers=hs)
    assert r.status_code == 403
    modo.assert_not_called()


def _no_contexto(fn):
    return contextvars.copy_context().run(fn)


def test_sem_headers_o_tenant_nao_cai_na_credencial_do_processo(modo):
    def run():
        session_manager.set_current_tenant("", "")
        return session_manager.get_current_tenant()
    assert _no_contexto(run) == ("", "")


def test_sem_user_token_nao_usa_o_token_guardado(modo):
    def run():
        session_manager.set_current_user_token("")
        return session_manager.get_current_user_token()
    assert _no_contexto(run) == ""


async def test_sessao_sem_user_token_recusa_em_vez_de_usar_o_guardado(modo, monkeypatch):
    import src.auth.session_manager as sm_mod

    criados: list[dict] = []

    class ClienteQueNaoSai:
        """Nunca vai à rede: registra os headers com que a sessão seria aberta."""
        def __init__(self, *a, headers=None, **kw):
            criados.append(dict(headers or {}))
            self.headers = dict(headers or {})
        async def get(self, *a, **kw):
            raise sm_mod.httpx.ConnectError("sem rede no teste")
        async def aclose(self):
            pass

    monkeypatch.setattr(sm_mod.httpx, "AsyncClient", ClienteQueNaoSai)

    async def run():
        session_manager.set_current_tenant(URL_OK, "APP-DO-CLIENTE")
        with pytest.raises(AuthenticationError):
            await session_manager._get_session_for_user("")
    await asyncio.get_running_loop().create_task(run(), context=contextvars.copy_context())
    assert not any(GUARDADO["glpi_user_token"] in h.get("Authorization", "") for h in criados), \
        "abriu sessão com o user_token guardado no processo"


# ---------------------------------------------------------------- (b) token do nosso MCP
@pytest.mark.parametrize("hs", [{}, {"Authorization": "Bearer errado"}, {"Authorization": "Basic YTpi"},
                                {"Authorization": TOKEN_OK}])
@pytest.mark.parametrize("metodo", ["initialize", "tools/list", "prompts/get", "tools/call"])
def test_post_sem_token_ou_token_errado_da_401(modo, client, hs, metodo):
    r = client.post("/mcp", json=rpc(metodo), headers={**hs, **CRED})
    assert r.status_code == 401
    assert TOKEN_OK not in r.text
    modo.assert_not_called()


@pytest.mark.parametrize("verbo", ["get", "delete"])
def test_get_e_delete_da_sessao_exigem_token(modo, client, monkeypatch, verbo):
    class SessoesQueEsquecem(dict):
        """Faz o SSE sair do laço de keepalive: sem isso, um GET aceito nunca termina no teste."""
        def __contains__(self, _k):
            return False
    monkeypatch.setattr(main_mod, "mcp_sessions", SessoesQueEsquecem())
    r = getattr(client, verbo)("/mcp", headers={"Authorization": "Bearer errado"})
    assert r.status_code == 401


def test_health_continua_publico(modo, client):
    assert client.get("/health").status_code == 200


def test_modo_sem_lista_de_tokens_falha_fechado(modo, client, monkeypatch):
    monkeypatch.setitem(settings.__dict__, "mcp_auth_tokens", "")
    r = client.post("/mcp", json=rpc("initialize"), headers=bearer())
    assert r.status_code == 401
    modo.assert_not_called()


def test_lista_com_varios_tokens(modo, client, monkeypatch):
    monkeypatch.setitem(settings.__dict__, "mcp_auth_tokens", f"outro-token, {TOKEN_OK} ,")
    r = client.post("/mcp", json=rpc("initialize"), headers=bearer())
    assert r.status_code == 200


# ---------------------------------------------------------------- (c) handshake e catálogo
@pytest.mark.parametrize("metodo", ["initialize", "ping", "notifications/initialized", "tools/list",
                                    "prompts/list", "prompts/get", "resources/list",
                                    "resources/templates/list"])
def test_handshake_e_catalogo_com_token_e_sem_credencial(modo, client, metodo):
    r = client.post("/mcp", json=rpc(metodo, {"name": "glpi_sla_performance"}), headers=bearer())
    assert r.status_code == 200, r.text
    modo.assert_called_once()


def test_ping_responde_objeto_vazio():
    resp = asyncio.run(main_mod.mcp_handler.handle_request(rpc("ping")))
    assert resp.get("error") is None and resp["result"] == {}


# ---------------------------------------------------------------- fora do modo: nada muda
def test_fora_do_modo_comportamento_antigo(client, monkeypatch):
    monkeypatch.setitem(settings.__dict__, "credencial_por_requisicao", False)
    monkeypatch.setitem(settings.__dict__, "mcp_auth_tokens", "")
    fake = AsyncMock(side_effect=lambda req: {"jsonrpc": "2.0", "id": 1, "result": {}})
    monkeypatch.setattr(main_mod.mcp_handler, "handle_request", fake)
    r = client.post("/mcp", json=rpc("tools/call", {"name": "x"}))
    assert r.status_code == 200
    fake.assert_called_once()
