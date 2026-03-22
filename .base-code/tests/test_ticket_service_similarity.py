"""
Testes para TicketService.find_similar_tickets cobrindo integração com SimilarityService.
"""

import pytest
from unittest.mock import AsyncMock, patch

from src.services.ticket_service import ticket_service


@pytest.mark.asyncio
async def test_find_similar_tickets_uses_similarity_service(monkeypatch):
    # Mock ticket e lista de candidatos
    monkeypatch.setattr(ticket_service, "get_ticket", AsyncMock(return_value={
        "id": 1,
        "name": "Printer issue",
        "content": "Printer not working"
    }))
    monkeypatch.setattr(ticket_service, "list_tickets", AsyncMock(return_value=[
        {"id": 2, "name": "Printer offline", "content": "Network printer down"},
        {"id": 3, "name": "Email issue", "content": "Cannot send email"},
    ]))

    mocked_similarity = AsyncMock(return_value=[{"id": 2, "combined": 0.8}])
    with patch("src.services.ticket_service.similarity_service.find_similar_tickets", mocked_similarity):
        result = await ticket_service.find_similar_tickets(1, max_results=5, threshold=0.2)

    # Deve retornar o resultado mockado do similarity_service
    assert result == [{"id": 2, "combined": 0.8}]
    mocked_similarity.assert_awaited_once()
