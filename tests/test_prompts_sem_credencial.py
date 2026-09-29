"""prompts/get SEM credencial no modo multiempresa: roteiro honesto, nunca zero nem falha muda.

## O defeito, medido em 28/09/2026 atras do ContextForge v1.0.11

O ContextForge chama ``prompts/get`` sozinho, SEM os headers ``x-glpi-*`` do cliente
(limitacao dele). Dos 15 prompts, 11 consultam o GLPI: 6 falhavam ("Failed to fetch
prompt") e 4 devolviam ZERO FALSO ("Total no periodo: 0", "Nenhum ativo encontrado"),
porque a falha de credencial era engolida. Medido tambem: os 3 checklists (onboarding,
mudanca, pedido de hardware) nao tocam o GLPI.

## O comportamento travado aqui

- prompt de dados sem credencial: NAO consulta nada e devolve um roteiro que diz o motivo
  e a chamada exata de ``glpi_get_prompt_template`` (uma tool: leva a credencial do
  cliente e devolve o mesmo relatorio com dados reais);
- checklist sem credencial: o modelo de sempre;
- com credencial, ou fora do modo multiempresa: o prompt de sempre.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.auth.session_manager import session_manager
from src.config import settings
from src.handlers import mcp_handler
from src.prompts_handlers.prompts import PROMPTS_CATALOG, TEMPLATE_ONLY_PROMPTS

CHECKLISTS = {"glpi_onboarding_checklist", "glpi_change_management", "glpi_hardware_request"}
DADOS = sorted({p["name"] for p in PROMPTS_CATALOG} - CHECKLISTS)


def _args(nome: str) -> dict:
    p = next(p for p in PROMPTS_CATALOG if p["name"] == nome)
    return {a["name"]: ("42" if "id" in a["name"] else "teste") for a in p.get("arguments", [])
            if a.get("required")}


@pytest.fixture
def multiempresa(monkeypatch):
    monkeypatch.setitem(settings.__dict__, "credencial_por_requisicao", True)
    session_manager.set_current_tenant("", "")
    session_manager.set_current_user_token("")
    acessos = AsyncMock(side_effect=AssertionError("tocou o GLPI sem credencial"))
    monkeypatch.setattr(session_manager, "_get_session_for_user", acessos)
    kb = AsyncMock(side_effect=AssertionError("consultou a base de conhecimento sem credencial"))
    monkeypatch.setattr("src.services.kb_search.handler.search_knowledge_unified", kb)
    return acessos


async def _get(nome: str, args: dict) -> str:
    resp = await mcp_handler.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "prompts/get", "params": {"name": nome, "arguments": args}})
    assert "error" not in resp, resp.get("error")
    return resp["result"]["messages"][0]["content"]["text"]


def test_classificacao_medida():
    assert TEMPLATE_ONLY_PROMPTS == CHECKLISTS
    assert len(DADOS) == 12


@pytest.mark.parametrize("nome", DADOS)
async def test_prompt_de_dados_sem_credencial_devolve_roteiro(multiempresa, nome):
    args = _args(nome)
    texto = await _get(nome, args)
    assert "glpi_get_prompt_template" in texto and nome in texto
    assert "credencial" in texto.lower()
    for valor in args.values():  # o agente reaproveita os argumentos que mandou
        assert valor in texto
    # nenhum numero inventado: o roteiro nao traz "Total", "0 chamados" etc.
    assert "Total no per" not in texto and "Nenhum ativo" not in texto
    multiempresa.assert_not_called()


@pytest.mark.parametrize("nome", sorted(CHECKLISTS))
async def test_checklist_sem_credencial_devolve_o_modelo(multiempresa, nome):
    texto = await _get(nome, _args(nome))
    assert "glpi_get_prompt_template(" not in texto
    assert len(texto) > 500
    multiempresa.assert_not_called()


async def test_com_credencial_roda_o_prompt(monkeypatch):
    monkeypatch.setitem(settings.__dict__, "credencial_por_requisicao", True)
    session_manager.set_current_tenant("https://suporte.meucomputador.com.br", "APP")
    session_manager.set_current_user_token("USER")
    real = AsyncMock(return_value={"prompt_name": "glpi_ticket_trends", "compact": "dados reais"})
    with patch("src.prompts_handlers.prompts.prompt_handler.get_prompt", real):
        texto = await _get("glpi_ticket_trends", {})
    assert "dados reais" in texto
    real.assert_awaited_once()


async def test_fora_do_modo_multiempresa_roda_o_prompt(monkeypatch):
    monkeypatch.setitem(settings.__dict__, "credencial_por_requisicao", False)
    session_manager.set_current_tenant("", "")
    session_manager.set_current_user_token("")
    real = AsyncMock(return_value={"prompt_name": "glpi_ticket_trends", "compact": "dados reais"})
    with patch("src.prompts_handlers.prompts.prompt_handler.get_prompt", real):
        texto = await _get("glpi_ticket_trends", {})
    assert "dados reais" in texto


async def test_roteiro_e_json_como_os_outros_prompts(multiempresa):
    """Mesmo envelope dos prompts (JSON com compact/detailed): cliente nao precisa de caso especial."""
    corpo = json.loads(await _get("glpi_sla_performance", {}))
    assert corpo["prompt_name"] == "glpi_sla_performance"
    assert "glpi_get_prompt_template" in corpo["compact"]
