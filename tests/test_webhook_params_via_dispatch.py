"""Webhook parameters the code handles must be declared in the schema, and a secret never leaks.

``manage_webhooks`` handled secret / is_active / headers / data / webhook_ids but the
input schema did not declare them, so the dispatcher rejected them: a caller could not
set a webhook secret or create an inactive webhook. These tests go through
``handle_call_tool`` (validation + alias + write policy + idempotency), not the method.
"""
import logging
from unittest.mock import AsyncMock, patch

import pytest

from src.handlers import MCPHandler
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

TOOL = "glpi_manage_webhook_integrations"
SECRET = "segredo-hmac-0123456789"
HEADERS = {"X-Origem": "glpi"}


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


def test_schema_declares_every_parameter_the_handler_reads(handler):
    props = handler.tools[TOOL]["input_schema"]["properties"]
    for name in ("secret", "is_active", "headers", "data", "webhook_ids"):
        assert name in props, f"{name} is handled by manage_webhooks but not declared"
    assert props["is_active"]["type"] == "boolean"
    assert props["headers"]["type"] == "object"
    assert props["data"]["type"] == "object"
    assert props["webhook_ids"]["type"] == "array"
    assert "sensivel" in props["secret"]["description"].lower()


async def test_create_passes_secret_active_and_headers_to_the_service(handler):
    create = AsyncMock(return_value={"id": 7, "name": "n", "secret": "***"})
    with patch("src.tools.consolidated_webhooks.webhook_tools.create_webhook", create):
        await handler.handle_call_tool(TOOL, {
            "action": "create", "name": "Teste", "url": "https://example.com/hook",
            "event_type": "ticket.created", "secret": SECRET,
            "is_active": False, "headers": HEADERS,
        })
    create.assert_awaited_once_with(
        name="Teste", url="https://example.com/hook", event_type="ticket.created",
        secret=SECRET, is_active=False, headers=HEADERS,
    )


async def test_update_passes_secret_active_and_headers_to_the_service(handler):
    update = AsyncMock(return_value={"id": 7, "name": "n", "secret": "***"})
    with patch("src.tools.consolidated_webhooks.webhook_tools.update_webhook", update):
        await handler.handle_call_tool(TOOL, {
            "action": "update", "webhook_id": "7", "secret": SECRET,
            "is_active": False, "headers": HEADERS,
        })
    update.assert_awaited_once_with(
        webhook_id="7", name=None, url=None, event_type=None,
        secret=SECRET, is_active=False, headers=HEADERS,
    )


async def test_trigger_passes_data_and_webhook_ids(handler):
    trigger = AsyncMock(return_value={"supported": False, "message": "x"})
    with patch("src.tools.consolidated_webhooks.webhook_tools.trigger_webhook", trigger):
        await handler.handle_call_tool(TOOL, {
            "action": "trigger", "event_type": "ticket.created",
            "data": {"id": 1}, "webhook_ids": ["7"],
        })
    trigger.assert_awaited_once_with(
        event_type="ticket.created", data={"id": 1}, webhook_ids=["7"])


class TestSecretIsNeverEchoed:
    async def _create_through_the_real_service(self, handler, post_response):
        """Create with the real service; only the GLPI HTTP client is replaced."""
        stored = {"id": 7, "name": "Teste", "url": "https://example.com/hook",
                  "itemtype": "Ticket", "event": "new", "secret": SECRET}
        # The destination check (allowlist + DNS) has its own tests in
        # test_webhook_outbound_guard.py; here only the secret handling matters.
        with patch("src.tools.webhooks.glpi_client.post", AsyncMock(return_value=post_response)), \
             patch("src.tools.webhooks.glpi_client.get", AsyncMock(return_value=stored)), \
             patch("src.tools.webhooks._validate_url", AsyncMock()):
            return await handler.handle_call_tool(TOOL, {
                "action": "create", "name": "Teste", "url": "https://example.com/hook",
                "event_type": "ticket.created", "secret": SECRET,
            })

    async def test_response_does_not_contain_the_secret(self, handler):
        result = await self._create_through_the_real_service(handler, {"id": 7})
        assert SECRET not in str(result)

    async def test_logs_do_not_contain_the_secret(self, handler, caplog):
        # A GLPI answer that echoes the input must not reach the log either.
        with caplog.at_level(logging.DEBUG):
            await self._create_through_the_real_service(
                handler, {"id": 7, "secret": SECRET})
        assert SECRET not in caplog.text

    async def test_idempotency_store_does_not_keep_the_secret(self, handler):
        seen = []

        class Spy:
            async def run(self, operation, key, payload, executor, **kw):
                seen.append((operation, key))
                return await executor()

        set_idempotency_store(Spy())
        await self._create_through_the_real_service(handler, {"id": 7})
        assert seen, "create did not go through the idempotency store"
        assert all(SECRET not in key for _, key in seen)
