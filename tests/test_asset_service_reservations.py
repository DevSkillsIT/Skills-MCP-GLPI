"""
Testes para AssetService reservas e métodos novos.
"""

import pytest
from unittest.mock import AsyncMock

from src.services.asset_service import AssetService


@pytest.mark.asyncio
async def test_list_reservations_returns_data():
    service = AssetService()
    mock_client = AsyncMock()
    mock_client.get.return_value = {"data": [{"id": 1}, {"id": 2}]}
    service.client = mock_client

    result = await service.list_reservations(limit=2, offset=0)
    assert isinstance(result, list)
    assert len(result) == 2
    mock_client.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_reservation_puts_then_reads_back_to_confirm():
    service = AssetService()
    mock_client = AsyncMock()
    mock_client.put.return_value = {}
    # First read: the reservation as stored. Second read: the read-back after the PUT.
    mock_client.get_item.side_effect = [
        {"id": 10, "comment": "antes"},
        {"id": 10, "comment": "Test", "updated": True},
    ]
    service.client = mock_client

    updated = await service.update_reservation(10, comment="Test")
    assert updated["id"] == 10
    assert updated["updated"] is True
    mock_client.put.assert_awaited_once_with("/apirest.php/Reservation/10", {"comment": "Test"})
    assert mock_client.get_item.await_count == 2
