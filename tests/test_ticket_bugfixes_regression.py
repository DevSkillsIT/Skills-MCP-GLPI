"""
Regression tests for the GLPI ticket bug fixes (black-box validation 2026-05-22).

Cobre os 5 bugs corrigidos:
  P0-1: search/list ignorava filtros (usava getAllItems em vez da Search API)
  P0-2: update com status string causava erro SQL (faltava map string->int)
  P0-3: get_ticket retornava cache obsoleto
  P0-5: combined_similarity zerava quando conteudo vazio (ignorava titulo)
  + get_ticket_history usa o endpoint /Log
"""

import pytest
from unittest.mock import AsyncMock, patch

from src.services.ticket_service import ticket_service, STATUS_MAP, _normalize_search_ticket
from src.services.similarity_service import TextSimilarity


# --------------------------------------------------------------------------
# P0-1: filtros via Search API
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_tickets_with_status_uses_search_api_and_maps_status():
    """Com filtro de status, deve usar glpi_client.search e converter
    o status string ('pending') para o codigo int (4) no criteria."""
    search_mock = AsyncMock(return_value={"data": [
        {"2": "9192", "1": "Conta de E-mail", "12": 4, "3": 4, "14": 1, "15": "2026-05-22"}
    ]})
    with patch("src.services.ticket_service.glpi_client.search", search_mock):
        rows = await ticket_service.list_tickets(status="pending", entity_id=0, limit=10)

    search_mock.assert_awaited_once()
    criteria = search_mock.await_args.kwargs["criteria"]
    status_crit = next(c for c in criteria if c["field"] == 12)
    assert status_crit["value"] == 4  # 'pending' -> 4
    # resultado normalizado para chaves nomeadas
    assert rows[0]["id"] == "9192"
    assert rows[0]["name"] == "Conta de E-mail"
    assert rows[0]["status"] == 4


@pytest.mark.asyncio
async def test_list_tickets_no_filters_still_uses_search_api():
    """Sem filtros, continua na Search API — de proposito.

    O endpoint leve getAllItems devolve IDs crus para solicitante e categoria,
    o que produzia listagens "podadas". A Search API com expand_dropdowns
    resolve esses nomes na mesma chamada, entao ela e usada mesmo sem criteria.
    """
    search_mock = AsyncMock(return_value={"data": [
        {"2": "1", "1": "X", "12": 1}
    ]})
    with patch("src.services.ticket_service.glpi_client.search", search_mock):
        rows = await ticket_service.list_tickets(limit=5)

    search_mock.assert_awaited_once()
    assert search_mock.await_args.kwargs["criteria"] == []
    assert rows[0]["name"] == "X"


def test_normalize_search_ticket_maps_numeric_fields():
    row = {"2": 42, "1": "Titulo", "12": 2, "3": 5, "14": 1, "15": "2026-05-01"}
    out = _normalize_search_ticket(row)
    assert out["id"] == 42
    assert out["name"] == "Titulo"
    assert out["status"] == 2
    assert out["priority"] == 5
    assert out["type"] == 1


# --------------------------------------------------------------------------
# P0-2: update status string -> int
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_ticket_maps_status_string_to_int():
    put_mock = AsyncMock(return_value={"success": True})
    get_mock = AsyncMock(return_value={"id": 9193, "name": "T", "status": 4})
    with patch("src.services.ticket_service.glpi_client.put", put_mock), \
         patch("src.services.ticket_service.glpi_client.get", get_mock):
        await ticket_service.update_ticket(9193, status="pending")

    put_mock.assert_awaited_once()
    sent = put_mock.await_args.kwargs.get("data") or put_mock.await_args.args[1]
    assert sent["status"] == 4  # nao a string 'pending'


def test_status_map_complete():
    assert STATUS_MAP == {
        "new": 1, "assigned": 2, "planned": 3,
        "pending": 4, "solved": 5, "closed": 6,
    }


# --------------------------------------------------------------------------
# P0-3: get_ticket sem cache
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_ticket_bypasses_cache():
    get_mock = AsyncMock(return_value={"id": 1, "name": "T"})
    with patch("src.services.ticket_service.glpi_client.get", get_mock):
        await ticket_service.get_ticket(1)
    get_mock.assert_awaited_once()
    assert get_mock.await_args.kwargs.get("use_cache") is False


# --------------------------------------------------------------------------
# get_history usa endpoint /Log
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_ticket_history_hits_log_endpoint():
    get_mock = AsyncMock(return_value=[{"id": 1, "new_value": "Atribuido"}])
    with patch("src.services.ticket_service.glpi_client.get", get_mock):
        hist = await ticket_service.get_ticket_history(7)
    called_endpoint = get_mock.await_args.args[0]
    assert called_endpoint.endswith("/Ticket/7/Log")
    assert isinstance(hist, list) and hist[0]["new_value"] == "Atribuido"


# --------------------------------------------------------------------------
# P0-5: combined_similarity recai sobre titulo quando conteudo vazio
# --------------------------------------------------------------------------

def test_combined_similarity_uses_title_when_content_empty():
    # Conteudo vazio mas titulos identicos -> alta similaridade (antes: 0.0)
    score = TextSimilarity.combined_similarity("", "", "Conta de E-mail", "Conta de E-mail")
    assert score > 0.9


def test_combined_similarity_zero_when_no_signal():
    assert TextSimilarity.combined_similarity("", "", "", "") == 0.0


# --------------------------------------------------------------------------
# Codex suggestion: input normalization for less-strict external agents
# --------------------------------------------------------------------------

from src.tools.consolidated_tickets import _coerce_int, _normalize_status


def test_coerce_int_accepts_numeric_string():
    assert _coerce_int("6") == 6
    assert _coerce_int(6) == 6
    assert _coerce_int("-3") == -3


def test_coerce_int_leaves_non_numeric_and_bool():
    assert _coerce_int("abc") == "abc"
    assert _coerce_int(None) is None
    assert _coerce_int(True) is True  # bool must not become 1


def test_normalize_status_accepts_code_or_string():
    assert _normalize_status("pending") == "pending"
    assert _normalize_status(4) == "pending"      # int code
    assert _normalize_status("4") == "pending"     # numeric string
    assert _normalize_status(None) is None
    assert _normalize_status("bogus") == "bogus"   # passthrough -> validator catches
