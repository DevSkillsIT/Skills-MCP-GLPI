"""O agente precisa LER o motivo de uma falha — e nunca receber zero no lugar de "nao consegui".

## Os defeitos, medidos em 28/09/2026 atras do ContextForge v1.0.11

1. ``tools/call`` que falhava devolvia ERRO JSON-RPC (``-32004``, ``-32602``,
   ``-32099``). O MCP trata erro de protocolo e erro de execucao da tool como coisas
   diferentes: o de execucao vai DENTRO do resultado (``isError: true``) para o
   modelo ler e corrigir a chamada. Um gateway (ContextForge) transforma erro
   JSON-RPC do upstream em ``unhandled errors in a TaskGroup`` — o agente via isso
   para "chamado 999999999 nao existe", "limit deve ser inteiro" e "argumento
   campo_inexistente nao existe". O Omie ja devolvia ``isError`` e o texto chegava.
2. O limite de chamadas por minuto (``RateLimitError``) escapava sem tratamento na
   entrada HTTP e virava ``500 Internal Server Error`` sem texto nenhum.
3. Prompts de dados engoliam a falha da consulta PRINCIPAL e seguiam com lista
   vazia: "Total no periodo: 0", "Tickets resolvidos: 0", "Nenhum ativo
   encontrado". Um "nao consegui consultar" virava um zero que parece verdade.
   ``_resolve_entity_id`` fazia o mesmo com o escopo: falhou -> relatorio GLOBAL.

## O que continua erro de PROTOCOLO (de proposito)

Tool inexistente, ``name`` ausente e ``arguments`` que nao e objeto: a chamada nem
chegou a ser uma execucao de tool. E o que a especificacao do MCP manda.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.handlers import mcp_handler
from src.models.exceptions import AuthenticationError, GLPIError, NotFoundError, RateLimitError


def _call(name: str, arguments, rid: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "method": "tools/call",
            "params": {"name": name, "arguments": arguments}}


def _falha_da_tool(response: dict) -> str:
    """A falha tem de vir DENTRO do resultado, com texto legivel."""
    assert "error" not in response, f"veio erro de protocolo: {response.get('error')}"
    result = response["result"]
    assert result.get("isError") is True, f"sem isError: {result}"
    texto = result["content"][0]["text"]
    assert result["content"][0]["type"] == "text" and texto
    return texto


# ---------------------------------------------------------------- tools/call


class TestFalhaDaToolVaiNoResultado:
    async def test_argumento_que_a_tool_nao_aceita(self):
        resp = await mcp_handler.handle_request(_call(
            "glpi_search_admin_resources", {"resource": "entities", "campo_inexistente": "x"}))
        texto = _falha_da_tool(resp)
        assert "campo_inexistente" in texto
        # o agente precisa saber o que PODE mandar para corrigir a chamada
        assert "resource" in texto

    async def test_tipo_errado(self):
        resp = await mcp_handler.handle_request(_call(
            "glpi_search_admin_resources", {"resource": "entities", "limit": "tres"}))
        assert "limit" in _falha_da_tool(resp)

    async def test_valor_fora_do_enum(self):
        resp = await mcp_handler.handle_request(_call(
            "glpi_search_admin_resources", {"resource": "nao-existe"}))
        assert "nao-existe" in _falha_da_tool(resp)

    async def test_chamado_inexistente(self):
        with patch("src.services.ticket_service.ticket_service.get_ticket_detail",
                   new_callable=AsyncMock, side_effect=NotFoundError("Ticket", 999999999)):
            resp = await mcp_handler.handle_request(_call(
                "glpi_manage_ticket_operations", {"action": "get", "ticket_id": 999999999}))
        assert "999999999" in _falha_da_tool(resp)

    async def test_erro_da_api_do_glpi(self):
        with patch("src.services.ticket_service.ticket_service.get_ticket_detail",
                   new_callable=AsyncMock, side_effect=GLPIError(503, "GLPI em manutencao")):
            resp = await mcp_handler.handle_request(_call(
                "glpi_manage_ticket_operations", {"action": "get", "ticket_id": 1}))
        assert "GLPI em manutencao" in _falha_da_tool(resp)

    async def test_limite_de_taxa_dentro_da_tool(self):
        with patch("src.services.ticket_service.ticket_service.get_ticket_detail",
                   new_callable=AsyncMock,
                   side_effect=RateLimitError("Limite de 500 chamadas por minuto ao GLPI atingido")):
            resp = await mcp_handler.handle_request(_call(
                "glpi_manage_ticket_operations", {"action": "get", "ticket_id": 1}))
        assert "500 chamadas" in _falha_da_tool(resp)

    async def test_erro_inesperado_nao_vaza_stack(self):
        with patch("src.services.ticket_service.ticket_service.get_ticket_detail",
                   new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            resp = await mcp_handler.handle_request(_call(
                "glpi_manage_ticket_operations", {"action": "get", "ticket_id": 1}))
        texto = _falha_da_tool(resp)
        assert "boom" in texto and "Traceback" not in texto

    async def test_sucesso_nao_ganha_isError(self):
        with patch("src.services.ticket_service.ticket_service.get_ticket_detail",
                   new_callable=AsyncMock, return_value={"id": 1, "name": "x"}):
            resp = await mcp_handler.handle_request(_call(
                "glpi_manage_ticket_operations", {"action": "get", "ticket_id": 1}))
        assert "error" not in resp and not resp["result"].get("isError")


class TestContinuaErroDeProtocolo:
    async def test_tool_inexistente(self):
        resp = await mcp_handler.handle_request(_call("glpi_nao_existe", {}))
        assert resp["error"]["code"] == -32601

    async def test_nome_ausente(self):
        resp = await mcp_handler.handle_request(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"arguments": {}}})
        assert resp["error"]["code"] == -32602

    async def test_arguments_que_nao_e_objeto(self):
        resp = await mcp_handler.handle_request(_call("glpi_search_helpdesk_tickets", "texto"))
        assert resp["error"]["code"] == -32602


# ---------------------------------------------------------------- HTTP: limite de taxa


class TestLimiteDeTaxaNaEntradaHTTP:
    """Antes: RateLimitError escapava e o cliente recebia 500 sem texto."""

    def _post(self, method: str, params: dict | None = None):
        from fastapi.testclient import TestClient
        from src.main import app

        body = {"jsonrpc": "2.0", "id": 9, "method": method}
        if params is not None:
            body["params"] = params
        with patch("src.main.session_manager._check_rate_limit",
                   side_effect=RateLimitError("Limite de 500 chamadas por minuto ao GLPI atingido")):
            return TestClient(app, raise_server_exceptions=False).post(
                "/mcp", json=body, headers={"x-glpi-user-token": "t"})

    def test_tools_call_recebe_isError_com_texto(self):
        r = self._post("tools/call", {"name": "glpi_search_helpdesk_tickets", "arguments": {}})
        assert r.status_code == 200, r.text
        corpo = r.json()
        assert corpo["result"]["isError"] is True
        assert "500 chamadas" in corpo["result"]["content"][0]["text"]

    def test_outro_metodo_recebe_429_com_texto(self):
        r = self._post("tools/list", {})
        assert r.status_code == 429, r.text
        assert "500 chamadas" in r.json()["error"]["message"]


def test_mensagem_do_limite_diz_quando_tentar_de_novo():
    from src.auth.session_manager import session_manager

    chave = "teste-limite-mensagem"
    limite = session_manager._rate_limit_per_minute
    try:
        with pytest.raises(RateLimitError) as exc:
            for _ in range(limite + 2):  # a 1a chamada so abre a janela
                session_manager._check_rate_limit(chave)
    finally:
        session_manager._rate_limits.pop(chave, None)
    msg = exc.value.message
    assert str(limite) in msg and "por minuto" in msg and " s" in msg


# ---------------------------------------------------------------- prompts: zero falso


class TestPromptNaoTransformaFalhaEmZero:
    """Consulta principal falhou -> erro com motivo. Nunca 'Total: 0'."""

    FALHA = GLPIError(503, "GLPI fora do ar")

    async def _prompt(self, name: str, args: dict):
        from src.prompts_handlers.prompts import handle_get_prompt
        return await handle_get_prompt(name, args)

    @pytest.mark.parametrize("nome", [
        "glpi_ticket_trends", "glpi_recurring_problems", "glpi_technician_productivity",
    ])
    async def test_agregacao_de_chamados(self, nome):
        from src.services.glpi_client import glpi_client
        with patch.object(glpi_client, "get", AsyncMock(side_effect=self.FALHA)):
            with pytest.raises(GLPIError) as exc:
                await self._prompt(nome, {})
        assert "GLPI fora do ar" in exc.value.message

    async def test_historico_do_usuario(self):
        from src.services.glpi_client import glpi_client
        from src.prompts_handlers.prompts import prompt_handler
        # O usuario RESOLVE; quem falha e a busca de chamados dele (a que era engolida).
        with patch.object(prompt_handler.service, "search_users",
                          AsyncMock(return_value=[{"id": 7, "name": "joao"}])), \
             patch.object(glpi_client, "get", AsyncMock(side_effect=self.FALHA)):
            with pytest.raises(GLPIError) as exc:
                await self._prompt("glpi_user_ticket_history", {"username": "joao"})
        assert "GLPI fora do ar" in exc.value.message

    async def test_busca_de_ativo(self):
        with patch("src.services.asset_service.asset_service.search_assets",
                   AsyncMock(side_effect=self.FALHA)):
            with pytest.raises(GLPIError) as exc:
                await self._prompt("glpi_asset_lookup", {"search_term": "notebook"})
        assert "GLPI fora do ar" in exc.value.message

    async def test_satisfacao(self):
        from src.services.glpi_client import glpi_client
        with patch.object(glpi_client, "get", AsyncMock(side_effect=self.FALHA)):
            with pytest.raises(GLPIError):
                await self._prompt("glpi_client_satisfaction", {})

    @pytest.mark.parametrize("nome", ["glpi_asset_roi", "glpi_cost_per_ticket"])
    async def test_entidade_que_nao_resolve_nao_vira_global(self, nome):
        from src.prompts_handlers.prompts import prompt_handler
        with patch.object(prompt_handler.service, "list_entities", AsyncMock(side_effect=self.FALHA)):
            with pytest.raises(GLPIError) as exc:
                await self._prompt(nome, {"entity_name": "CLIENTE-X"})
        assert "entidade" in exc.value.message and "GLPI fora do ar" in exc.value.message

    async def test_credencial_ausente_mantem_o_tipo(self):
        """Quem chama precisa distinguir 'sem credencial' de 'GLPI falhou'."""
        from src.services.glpi_client import glpi_client
        with patch.object(glpi_client, "get",
                          AsyncMock(side_effect=AuthenticationError("Credencial do GLPI ausente"))):
            with pytest.raises(AuthenticationError):
                await self._prompt("glpi_ticket_trends", {})


# ---------------------------------------------------------------- tool-ponte de prompts


class TestPonteDePrompts:
    """glpi_get_prompt_template e o caminho de quem nao tem prompts nativos (mcphub, gateways).

    Antes: falha do prompt voltava como ``{"error": ...}`` num resultado de SUCESSO, e o
    exemplo da descricao ('sla_dashboard') nao existia no catalogo.
    """

    async def test_falha_do_prompt_vira_isError(self):
        from src.services.glpi_client import glpi_client
        with patch.object(glpi_client, "get", AsyncMock(side_effect=GLPIError(503, "GLPI fora do ar"))):
            resp = await mcp_handler.handle_request(_call(
                "glpi_get_prompt_template", {"name": "glpi_ticket_trends", "arguments": {}}))
        assert "GLPI fora do ar" in _falha_da_tool(resp)

    async def test_prompt_inexistente_vira_isError_com_a_lista(self):
        resp = await mcp_handler.handle_request(_call(
            "glpi_get_prompt_template", {"name": "nao_existe"}))
        assert "glpi_sla_performance" in _falha_da_tool(resp)

    async def test_aceita_o_nome_sem_o_prefixo(self):
        with patch("src.prompts_handlers.prompts.prompt_handler.get_prompt",
                   AsyncMock(return_value={"prompt_name": "glpi_ticket_trends", "compact": "ok"})) as get:
            resp = await mcp_handler.handle_request(_call(
                "glpi_get_prompt_template", {"name": "ticket_trends", "arguments": {}}))
        assert not resp["result"].get("isError")
        assert get.await_args.args[0] == "glpi_ticket_trends"

    def test_exemplos_da_descricao_existem_no_catalogo(self):
        import re as _re
        from src.prompts_handlers.prompts import PROMPTS_CATALOG
        nomes = {p["name"] for p in PROMPTS_CATALOG}
        tool = mcp_handler.tools["glpi_get_prompt_template"]
        texto = tool["input_schema"]["properties"]["name"]["description"]
        citados = set(_re.findall(r"'([a-z_]+)'", texto))
        assert citados and citados <= nomes, citados - nomes
