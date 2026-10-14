"""model_id is written to the per-type GLPI column (computermodels_id, printermodels_id...).

glpi_computers has no `models_id`: the old payload key was ignored, so a model set on create
or update was silently dropped.
"""
from unittest.mock import AsyncMock, patch

import pytest

from src.handlers import MCPHandler
from src.models.exceptions import ValidationError
from src.security.idempotency import (
    IdempotencyStore,
    MemoryIdempotencyBackend,
    reset_idempotency_store,
    set_idempotency_store,
)
from src.security.write_policy import (
    PROFILE_ADMINISTRATOR,
    WritePolicy,
    reset_write_policy,
    set_write_policy,
)

ASSETS = "glpi_manage_asset_operations"
CLIENT = "src.services.glpi_client.glpi_client"

COLUMNS = [
    ("Computer", "computermodels_id"), ("Monitor", "monitormodels_id"),
    ("NetworkEquipment", "networkequipmentmodels_id"), ("Peripheral", "peripheralmodels_id"),
    ("Phone", "phonemodels_id"), ("Printer", "printermodels_id"),
]


@pytest.fixture(autouse=True)
def _isolated():
    reset_write_policy()
    set_write_policy(WritePolicy(env=PROFILE_ADMINISTRATOR.as_environment()))
    set_idempotency_store(IdempotencyStore(backend=MemoryIdempotencyBackend()))
    yield
    reset_write_policy()
    reset_idempotency_store()


@pytest.fixture
def handler():
    return MCPHandler()


@pytest.mark.parametrize("asset_type,column", COLUMNS)
async def test_create_sends_the_per_type_model_column(handler, asset_type, column):
    post = AsyncMock(return_value={"id": 3})
    with patch(f"{CLIENT}.post", post), patch(f"{CLIENT}.get", AsyncMock(return_value={"id": 3, "name": "n"})):
        await handler.handle_call_tool(ASSETS, {
            "action": "create", "asset_type": asset_type, "name": "Equip-01", "model_id": 12})
    payload = post.await_args.args[1]
    assert payload[column] == 12 and "models_id" not in payload


@pytest.mark.parametrize("asset_type,column", COLUMNS)
async def test_update_sends_the_per_type_model_column(handler, asset_type, column):
    put = AsyncMock(return_value={"success": True})
    with patch(f"{CLIENT}.put", put), patch(f"{CLIENT}.get", AsyncMock(return_value={"id": 3, "name": "n"})):
        await handler.handle_call_tool(ASSETS, {
            "action": "update", "asset_type": asset_type, "asset_id": 3, "model_id": 12})
    assert put.await_args.args[1] == {column: 12}


@pytest.mark.parametrize("action", ["create", "update"])
async def test_type_outside_the_enum_never_reaches_glpi(handler, action):
    """The schema enum already stops types without a model column."""
    args = {"action": action, "asset_type": "Software", "model_id": 12}
    args.update({"name": "Prog-01"} if action == "create" else {"asset_id": 3})
    sent = AsyncMock()
    with patch(f"{CLIENT}.post", sent), patch(f"{CLIENT}.put", sent), \
         patch(f"{CLIENT}.get", AsyncMock(return_value={"id": 3, "name": "n"})):
        with pytest.raises(ValidationError):
            await handler.handle_call_tool(ASSETS, args)
    sent.assert_not_awaited()


def test_model_column_refuses_a_type_without_one():
    from src.services.asset_service import model_column
    with pytest.raises(ValidationError) as caught:
        model_column("Software")
    assert "model_id" in caught.value.message and "Software" in caught.value.message


async def test_read_side_still_resolves_the_model_name():
    from src.services.asset_service import AssetService
    service = AssetService()
    service.client = AsyncMock()
    service.client.get_item.return_value = {"id": 3, "name": "PC", "computermodels_id": 12}
    with patch("src.services.dropdown_cache.dropdown_cache.get_name",
               AsyncMock(return_value="OptiPlex 5060")) as get_name:
        asset = await service.get_asset("Computer", 3)
    assert asset["computermodels_name"] == "OptiPlex 5060"
    assert get_name.await_args_list[-1].args[0] == "ComputerModel" or any(
        c.args[0] == "ComputerModel" for c in get_name.await_args_list)
