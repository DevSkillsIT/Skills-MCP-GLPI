"""
The safety guard has to work END TO END when it is switched on.

Before this suite the guard worked in the tool bodies but not through the
server: the input schemas of the asset, admin and webhook manage tools never
declared ``confirmation_token`` / ``reason``, and the dispatcher rejects any
argument the schema does not declare. With ``MCP_SAFETY_GUARD=true`` those
deletes could be refused but never confirmed.

The suite is driven by the tool definitions: it finds every destructive
action (``delete`` in a manage tool's ``action`` enum, per ``resource`` /
``record_type`` where the tool has one) and requires a row in ``CASES`` for it,
so a tool added later cannot silently miss the guard.
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
from src.utils.safety_guard import safety_guard

TOKEN = "token-de-teste"
REASON = "limpeza autorizada pelo responsavel"

# Row key: (tool, discriminator value or None).
# Row value: (call arguments, dotted path of the call that performs the delete,
# or None when the tool does not offer the delete for that resource at all).
CASES = {
    ("glpi_manage_ticket_operations", None): (
        {"action": "delete", "ticket_id": 5},
        "src.tools.consolidated_tickets.ticket_service.delete_ticket",
    ),
    ("glpi_manage_asset_operations", None): (
        {"action": "delete", "asset_type": "Computer", "asset_id": 7},
        "src.tools.assets.asset_service.delete_asset",
    ),
    ("glpi_manage_admin_resources", "users"): (
        {"action": "delete", "resource": "users", "resource_id": 3},
        "src.tools.admin.admin_service.delete_user",
    ),
    ("glpi_manage_admin_resources", "groups"): (
        {"action": "delete", "resource": "groups", "resource_id": 3},
        "src.services.admin_service.admin_service.delete_group",
    ),
    ("glpi_manage_admin_resources", "locations"): (
        {"action": "delete", "resource": "locations", "resource_id": 3},
        "src.services.admin_service.admin_service.delete_location",
    ),
    ("glpi_manage_admin_resources", "entities"): (
        {"action": "delete", "resource": "entities", "resource_id": 3},
        None,  # entities cannot be deleted through this server
    ),
    ("glpi_manage_webhook_integrations", None): (
        {"action": "delete", "webhook_id": "4"},
        "src.tools.webhooks.glpi_client.delete",
    ),
}
for _record_type in ("problems", "changes", "projects", "contracts", "suppliers"):
    CASES[("glpi_manage_itil_records", _record_type)] = (
        {"action": "delete", "record_type": _record_type, "record_id": 9},
        "src.tools.consolidated_itil.itil_service.delete_record",
    )

_DISCRIMINATORS = ("resource", "record_type")


def _destructive_actions(handler):
    """Every (tool, discriminator) the definitions say can delete something."""
    found = set()
    for name, info in handler.tools.items():
        props = (info["input_schema"].get("properties") or {})
        action = props.get("action") or {}
        if "delete" not in (action.get("enum") or []):
            continue
        discriminator = next((d for d in _DISCRIMINATORS if d in props), None)
        if discriminator is None:
            found.add((name, None))
        else:
            for value in props[discriminator].get("enum") or []:
                found.add((name, value))
    return found


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


@pytest.fixture
def guard_on():
    with patch.object(safety_guard, "_guard_enabled", True), patch.object(
        safety_guard, "_safety_token", TOKEN
    ):
        yield


@pytest.fixture
def guard_off():
    with patch.object(safety_guard, "_guard_enabled", False):
        yield


def _live_cases():
    return [(key, row) for key, row in CASES.items() if row[1] is not None]


def _ids(items):
    return [f"{tool}:{disc}" if disc else tool for (tool, disc), _ in items]


def _effect_mock(path):
    """Mock of the call that performs the delete (the thing the guard protects)."""
    return patch(path, AsyncMock(return_value={"id": 1}))


def _patches_for(path):
    # The webhook delete first confirms the webhook exists.
    if path == "src.tools.webhooks.glpi_client.delete":
        return [patch("src.tools.webhooks.webhook_tools.get_webhook", AsyncMock(return_value={}))]
    return []


class TestEveryDestructiveActionIsCovered:
    def test_cases_enumerate_every_delete_in_the_tool_definitions(self, handler):
        """A new delete action without a row here fails the suite."""
        assert _destructive_actions(handler) == set(CASES)


class TestSchemaDeclaresWhatTheGuardRequires:
    @pytest.mark.parametrize("key,row", _live_cases(), ids=_ids(_live_cases()))
    def test_confirmation_token_and_reason_are_declared(self, handler, key, row):
        props = handler.tools[key[0]]["input_schema"]["properties"]
        assert "confirmation_token" in props, f"{key[0]} does not declare confirmation_token"
        assert "reason" in props, f"{key[0]} does not declare reason"


class TestGuardOn:
    @pytest.mark.parametrize("key,row", _live_cases(), ids=_ids(_live_cases()))
    async def test_refused_without_token_and_names_declared_parameters(
        self, handler, guard_on, key, row
    ):
        args, path = row
        props = handler.tools[key[0]]["input_schema"]["properties"]
        with _effect_mock(path) as effect:
            for extra in _patches_for(path):
                extra.start()
            try:
                with pytest.raises(ValidationError) as caught:
                    await handler.handle_call_tool(key[0], dict(args))
            finally:
                patch.stopall()
        assert "SAFETY GUARD" in caught.value.message
        # The refusal must ask for parameters the caller is allowed to send.
        for asked in ("confirmation_token", "reason"):
            assert asked in caught.value.message
            assert asked in props
        effect.assert_not_awaited()

    @pytest.mark.parametrize("key,row", _live_cases(), ids=_ids(_live_cases()))
    async def test_refused_with_wrong_token(self, handler, guard_on, key, row):
        args, path = row
        with _effect_mock(path) as effect:
            for extra in _patches_for(path):
                extra.start()
            try:
                with pytest.raises(ValidationError):
                    await handler.handle_call_tool(
                        key[0], {**args, "confirmation_token": "errado-errado", "reason": REASON}
                    )
            finally:
                patch.stopall()
        effect.assert_not_awaited()

    @pytest.mark.parametrize("key,row", _live_cases(), ids=_ids(_live_cases()))
    async def test_accepted_with_valid_token_and_reason(self, handler, guard_on, key, row):
        args, path = row
        with _effect_mock(path) as effect:
            for extra in _patches_for(path):
                extra.start()
            try:
                response = await handler.handle_call_tool(
                    key[0], {**args, "confirmation_token": TOKEN, "reason": REASON}
                )
            finally:
                patch.stopall()
        assert response["content"]
        effect.assert_awaited_once()

    @pytest.mark.parametrize("key,row", _live_cases(), ids=_ids(_live_cases()))
    async def test_camel_case_spelling_is_still_accepted(self, handler, guard_on, key, row):
        """Callers written against the old handler signature keep working."""
        args, path = row
        with _effect_mock(path) as effect:
            for extra in _patches_for(path):
                extra.start()
            try:
                await handler.handle_call_tool(
                    key[0], {**args, "confirmationToken": TOKEN, "reason": REASON}
                )
            finally:
                patch.stopall()
        effect.assert_awaited_once()


class TestGuardOff:
    @pytest.mark.parametrize("key,row", _live_cases(), ids=_ids(_live_cases()))
    async def test_delete_needs_no_token(self, handler, guard_off, key, row):
        args, path = row
        with _effect_mock(path) as effect:
            for extra in _patches_for(path):
                extra.start()
            try:
                await handler.handle_call_tool(key[0], dict(args))
            finally:
                patch.stopall()
        effect.assert_awaited_once()
