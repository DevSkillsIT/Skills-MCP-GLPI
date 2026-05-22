"""
Testes para TicketService.find_similar_tickets cobrindo integração com SimilarityService.
"""

import pytest
from unittest.mock import AsyncMock, patch

from src.services.ticket_service import ticket_service


@pytest.mark.asyncio
async def test_find_similar_tickets_enriches_with_ticket_fields(monkeypatch):
    """find_similar deve mapear o score de volta para campos de ticket
    (id/name/status/date/score) que o formatter consegue renderizar."""
    monkeypatch.setattr(ticket_service, "get_ticket", AsyncMock(return_value={
        "id": 1,
        "name": "Printer issue",
        "content": "Printer not working",
    }))
    monkeypatch.setattr(ticket_service, "list_tickets", AsyncMock(return_value=[
        {"id": 2, "name": "Printer offline", "content": "Network printer down", "status": 2, "date": "2026-05-01"},
        {"id": 3, "name": "Email issue", "content": "Cannot send email", "status": 6, "date": "2026-04-01"},
    ]))

    # similarity_service retorna o formato cru {id1, id2, combined}
    mocked_similarity = AsyncMock(return_value=[{"id1": 1, "id2": 2, "combined": 0.8}])
    with patch("src.services.ticket_service.similarity_service.find_similar_tickets", mocked_similarity):
        result = await ticket_service.find_similar_tickets(1, max_results=5, threshold=0.2)

    assert result == [
        {"id": 2, "name": "Printer offline", "status": 2, "date": "2026-05-01", "score": 0.8}
    ]
    mocked_similarity.assert_awaited_once()
