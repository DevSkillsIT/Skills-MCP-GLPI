"""An update never reports plain success for an argument it did not apply.

Found while declaring parameters:
- update_reservation sent an EMPTY PUT (date_start/date_end/comment are explicit
  parameters, so **kwargs was empty) and answered success.
- create-only fields (users: group_id, entity_name, password...; tickets: type,
  requester_id, location_id) were silently ignored on update.
- group update reset the flags to their create defaults (non-None signature defaults).
- asset update sent the tool's names (serial_number, status, ...) instead of GLPI columns.
"""
from unittest.mock import AsyncMock, patch

import pytest

from src.handlers import MCPHandler
from src.models.exceptions import GLPIError, ValidationError
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
ADMIN = "glpi_manage_admin_resources"
TICKETS = "glpi_manage_ticket_operations"
CLIENT = "src.services.glpi_client.glpi_client"


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


BEFORE = {"id": 7, "begin": "2030-01-01 08:00:00", "end": "2030-01-01 09:00:00",
          "comment": "antigo", "users_id": 2}


def _reservation_client(after):
    """get_item answers BEFORE first, then `after` (the read-back)."""
    return (
        patch(f"{CLIENT}.get_item", AsyncMock(side_effect=[dict(BEFORE), dict(after)])),
        patch(f"{CLIENT}.put", AsyncMock(return_value={"success": True})),
    )


class TestUpdateReservation:
    async def test_put_carries_glpi_columns_in_glpi_format(self, handler):
        after = {**BEFORE, "begin": "2030-01-02 10:00:00", "end": "2030-01-02 11:30:00",
                 "comment": "novo"}
        get_p, put_p = _reservation_client(after)
        with get_p, put_p as put:
            result = await handler.handle_call_tool(ASSETS, {
                "action": "update_reservation", "reservation_id": 7,
                "date_start": "2030-01-02 10:00:00", "date_end": "2030-01-02 11:30:00",
                "comment": "novo"})
        endpoint, payload = put.await_args.args
        assert endpoint == "/apirest.php/Reservation/7"
        assert payload == {"begin": "2030-01-02 10:00:00", "end": "2030-01-02 11:30:00",
                           "comment": "novo"}
        assert "2030-01-02 10:00:00" in result["content"][0]["text"]

    async def test_user_id_maps_to_users_id(self, handler):
        get_p, put_p = _reservation_client({**BEFORE, "users_id": 9})
        with get_p, put_p as put:
            await handler.handle_call_tool(ASSETS, {
                "action": "update_reservation", "reservation_id": 7, "user_id": 9})
        assert put.await_args.args[1] == {"users_id": 9}

    async def test_only_the_changed_field_is_sent(self, handler):
        get_p, put_p = _reservation_client({**BEFORE, "comment": "so isso"})
        with get_p, put_p as put:
            await handler.handle_call_tool(ASSETS, {
                "action": "update_reservation", "reservation_id": 7, "comment": "so isso"})
        assert put.await_args.args[1] == {"comment": "so isso"}

    async def test_nothing_to_change_is_an_error_and_no_put(self, handler):
        put = AsyncMock()
        with patch(f"{CLIENT}.put", put), patch(f"{CLIENT}.get_item", AsyncMock(return_value=BEFORE)):
            response = await handler.handle_request({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": ASSETS, "arguments": {
                    "action": "update_reservation", "reservation_id": 7}}})
        assert response["result"]["isError"] is True
        assert "date_start" in response["result"]["content"][0]["text"]
        put.assert_not_awaited()

    @pytest.mark.parametrize("bad", [
        {"date_start": "02/01/2030 10:00"},
        {"date_start": "2030-01-01 10:00:00", "date_end": "2030-01-01 09:00:00"},
        {"date_end": "2030-01-01 07:00:00"},  # before the stored begin (08:00)
    ])
    async def test_invalid_dates_are_refused(self, handler, bad):
        put = AsyncMock()
        with patch(f"{CLIENT}.put", put), patch(f"{CLIENT}.get_item", AsyncMock(return_value=dict(BEFORE))):
            with pytest.raises(ValidationError):
                await handler.handle_call_tool(ASSETS, {
                    "action": "update_reservation", "reservation_id": 7, **bad})
        put.assert_not_awaited()

    async def test_glpi_not_applying_the_change_is_not_success(self, handler):
        get_p, put_p = _reservation_client(dict(BEFORE))  # read-back unchanged
        with get_p, put_p:
            with pytest.raises(GLPIError) as caught:
                await handler.handle_call_tool(ASSETS, {
                    "action": "update_reservation", "reservation_id": 7, "comment": "novo"})
        assert "comment" in caught.value.message


class TestTicketUpdateRefusesCreateOnlyFields:
    @pytest.mark.parametrize("field,value", [
        ("type", "request"), ("requester_id", 4), ("location_id", 3), ("entity_id", 2)])
    async def test_refused_and_named(self, handler, field, value):
        update = AsyncMock()
        with patch("src.tools.consolidated_tickets.ticket_service.update_ticket", update):
            with pytest.raises(ValidationError) as caught:
                await handler.handle_call_tool(TICKETS, {
                    "action": "update", "ticket_id": 5, "priority": 2, field: value})
        assert field in caught.value.message and "create" in caught.value.message
        update.assert_not_awaited()

    async def test_applicable_fields_still_update(self, handler):
        update = AsyncMock(return_value={"id": 5})
        with patch("src.tools.consolidated_tickets.ticket_service.update_ticket", update):
            await handler.handle_call_tool(TICKETS, {
                "action": "update", "ticket_id": 5, "urgency": 2, "category_id": 3, "assignee_id": 4})
        update.assert_awaited_once()


def _glpi_admin(put=None, post=None):
    return (
        patch(f"{CLIENT}.post", post or AsyncMock(return_value={"id": 5})),
        patch(f"{CLIENT}.get", AsyncMock(return_value={"id": 5, "name": "x"})),
        patch(f"{CLIENT}.put", put or AsyncMock(return_value={"success": True})),
    )


class TestAdminUpdateRefusesInapplicableFields:
    @pytest.mark.parametrize("resource,field,value", [
        ("users", "group_id", 4), ("users", "entity_name", "Filial"), ("users", "password", "abcdef"),
        ("users", "password2", "abcdef"), ("users", "authtype", 2), ("users", "name", "outro"),
        ("users", "building", "A"), ("groups", "entity_name", "Filial"), ("groups", "town", "X"),
        ("locations", "entity_name", "Filial"), ("locations", "is_notify", False),
    ])
    async def test_update_refuses_and_names_the_field(self, handler, resource, field, value):
        post_p, get_p, put_p = _glpi_admin()
        with post_p, get_p, put_p as put:
            with pytest.raises(ValidationError) as caught:
                await handler.handle_call_tool(ADMIN, {
                    "resource": resource, "action": "update", "resource_id": 5,
                    "comment": "ok", field: value})
        assert field in caught.value.message
        put.assert_not_awaited()

    async def test_create_refuses_a_field_of_another_resource(self, handler):
        post_p, get_p, put_p = _glpi_admin()
        with post_p as post, get_p, put_p:
            with pytest.raises(ValidationError) as caught:
                await handler.handle_call_tool(ADMIN, {
                    "resource": "users", "action": "create", "name": "jdoe", "building": "A"})
        assert "building" in caught.value.message
        post.assert_not_awaited()

    async def test_group_rename_does_not_reset_the_flags(self, handler):
        put = AsyncMock(return_value={"success": True})
        post_p, get_p, put_p = _glpi_admin(put=put)
        with post_p, get_p, put_p:
            await handler.handle_call_tool(ADMIN, {
                "resource": "groups", "action": "update", "resource_id": 5, "name": "Novo"})
        assert put.await_args.args[1] == {"name": "Novo"}

    async def test_group_create_keeps_its_defaults(self, handler):
        post = AsyncMock(return_value={"id": 5})
        post_p, get_p, put_p = _glpi_admin(post=post)
        with post_p, get_p, put_p:
            await handler.handle_call_tool(ADMIN, {
                "resource": "groups", "action": "create", "name": "Grupo N2"})
        sent = post.await_args.args[1]
        assert (sent["is_requester"], sent["is_assign"], sent["is_notify"]) == (1, 1, 1) or \
               (sent["is_requester"], sent["is_assign"], sent["is_notify"]) == (True, True, True)

    async def test_user_create_keeps_authtype_default(self, handler):
        post = AsyncMock(return_value={"id": 5})
        post_p, get_p, put_p = _glpi_admin(post=post)
        with post_p, get_p, put_p:
            await handler.handle_call_tool(ADMIN, {
                "resource": "users", "action": "create", "name": "jdoe", "password": "abcdef"})
        assert post.await_args_list[0].args[1]["authtype"] == 1


class TestAssetUpdateColumns:
    async def test_put_uses_glpi_column_names(self, handler):
        put = AsyncMock(return_value={"success": True})
        with patch(f"{CLIENT}.put", put), patch(f"{CLIENT}.get", AsyncMock(return_value={"id": 3, "name": "n"})):
            await handler.handle_call_tool(ASSETS, {
                "action": "update", "asset_type": "Computer", "asset_id": 3,
                "name": "PC", "serial_number": "S1", "other_serial": "O1", "status": 2,
                "entity_id": 1, "location_id": 4, "manufacturer_id": 5, "user_id": 6,
                "group_id": 7, "comment": "c"})
        sent = put.await_args.args[1]
        assert sent == {"name": "PC", "serial": "S1", "otherserial": "O1", "states_id": 2,
                        "entities_id": 1, "locations_id": 4, "manufacturers_id": 5,
                        "users_id": 6, "groups_id": 7, "comment": "c"}


class TestStatusDescriptionsStateTheType:
    def test_both_descriptions_state_type_and_example(self, handler):
        search = handler.tools["glpi_search_asset_inventory"]["input_schema"]["properties"]["status"]
        manage = handler.tools[ASSETS]["input_schema"]["properties"]["status"]
        assert "texto" in search["description"].lower() and "ex:" in search["description"].lower()
        assert "numero inteiro" in manage["description"].lower() and "ex:" in manage["description"].lower()


class TestAssetActionsRefuseFieldsTheyWouldIgnore:
    @pytest.mark.parametrize("action,extra,field", [
        ("update", {"asset_type": "Computer", "asset_id": 3, "name": "PC", "date_start": "2030-01-01 08:00:00"}, "date_start"),
        ("create", {"asset_type": "Computer", "name": "PC", "reservation_id": 4}, "reservation_id"),
        ("update_reservation", {"reservation_id": 7, "comment": "x", "serial_number": "S1"}, "serial_number"),
    ])
    async def test_refused_and_named(self, handler, action, extra, field):
        put = AsyncMock()
        with patch(f"{CLIENT}.put", put), patch(f"{CLIENT}.post", AsyncMock()):
            with pytest.raises(ValidationError) as caught:
                await handler.handle_call_tool(ASSETS, {"action": action, **extra})
        assert field in caught.value.message
        put.assert_not_awaited()
