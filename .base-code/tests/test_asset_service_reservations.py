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
async def test_update_reservation_calls_put_and_get_item():
    service = AssetService()
    mock_client = AsyncMock()
    mock_client.put.return_value = {}
    mock_client.get_item.return_value = {"id": 10, "updated": True}
    service.client = mock_client

    updated = await service.update_reservation(10, comment="Test")
    assert updated["id"] == 10
    assert updated["updated"] is True
    mock_client.put.assert_awaited_once()
    mock_client.get_item.assert_awaited_once()
