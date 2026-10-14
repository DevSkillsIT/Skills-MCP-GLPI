"""Behaviour behind the newly declared parameters (tickets, assets, users).

Declaring a parameter is a promise: the value must reach GLPI under the right column, be
validated against what the code accepts, and -- for passwords -- never come back out.
"""
import logging
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.auth.session_manager import SessionManager
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

PASSWORD = "Sup3r-Segredo-Do-Teste"  # fictitious leak sentinel  gitleaks:allow
ADMIN = "glpi_manage_admin_resources"
TICKETS = "glpi_manage_ticket_operations"


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


class TestTicketParameters:
    async def test_create_reaches_the_service_with_every_declared_field(self, handler):
        create = AsyncMock(return_value={"id": 1})
        with patch("src.tools.consolidated_tickets.ticket_service.create_ticket", create):
            await handler.handle_call_tool(TICKETS, {
                "action": "create", "title": "Titulo", "description": "Descricao longa",
                "urgency": 4, "type": "request", "category_id": 12,
                "requester_id": 7, "assignee_id": 8, "location_id": 3,
            })
        kwargs = create.await_args.kwargs
        assert (kwargs["urgency"], kwargs["type"], kwargs["category_id"]) == (4, 2, 12)
        assert (kwargs["requester_id"], kwargs["assignee_id"], kwargs["location_id"]) == (7, 8, 3)

    @pytest.mark.parametrize("bad", [{"urgency": 9}, {"urgency": 0}, {"type": "outro"}])
    async def test_values_outside_the_declared_domain_are_refused(self, handler, bad):
        create = AsyncMock(return_value={"id": 1})
        with patch("src.tools.consolidated_tickets.ticket_service.create_ticket", create):
            with pytest.raises(ValidationError):
                await handler.handle_call_tool(TICKETS, {
                    "action": "create", "title": "Titulo", "description": "Descricao longa", **bad})
        create.assert_not_awaited()

    async def test_close_accepts_solution_type_and_legacy_resolution(self, handler):
        close = AsyncMock(return_value={"id": 5})
        with patch("src.tools.consolidated_tickets.ticket_service.close_ticket", close):
            await handler.handle_call_tool(TICKETS, {
                "action": "close", "ticket_id": 5, "resolution": "Resolvido pelo texto legado",
                "solution_type": 3})
        assert close.await_args.kwargs["solution_type"] == 3


def _glpi(post=None, get=None, put=None):
    """Replace only the GLPI HTTP client; the real services run."""
    return (
        patch("src.services.glpi_client.glpi_client.post", post or AsyncMock(return_value={"id": 5})),
        patch("src.services.glpi_client.glpi_client.get", get or AsyncMock(return_value={"id": 5, "name": "jdoe"})),
        patch("src.services.glpi_client.glpi_client.put", put or AsyncMock(return_value={"success": True})),
    )


class TestUserUpdateColumns:
    async def test_foreign_keys_are_sent_under_glpi_column_names(self, handler):
        put = AsyncMock(return_value={"success": True})
        post_p, get_p, put_p = _glpi(put=put)
        with post_p, get_p, put_p:
            await handler.handle_call_tool(ADMIN, {
                "resource": "users", "action": "update", "resource_id": 5,
                "location_id": 3, "profile_id": 4, "usertitle_id": 6,
                "usercategory_id": 7, "entity_id": 2, "firstname": "Maria"})
        sent = put.await_args.args[1]
        assert sent == {"locations_id": 3, "profiles_id": 4, "usertitles_id": 6,
                        "usercategories_id": 7, "entities_id": 2, "firstname": "Maria"}


class TestPasswordNeverComesBack:
    """password / password2 go to GLPI on create and are never returned or logged."""

    CREATE = {"resource": "users", "action": "create", "name": "jdoe",
              "password": PASSWORD, "password2": PASSWORD}

    async def _create(self, handler, glpi_user):
        post_p, get_p, put_p = _glpi(get=AsyncMock(return_value=glpi_user))
        with post_p as post, get_p, put_p:
            result = await handler.handle_call_tool(ADMIN, dict(self.CREATE))
        return result, post

    async def test_password_reaches_glpi(self, handler):
        _, post = await self._create(handler, {"id": 5, "name": "jdoe"})
        sent = post.await_args_list[0].args[1]
        assert sent["password"] == PASSWORD and sent["password2"] == PASSWORD

    async def test_response_text_omits_the_password_even_if_glpi_echoes_it(self, handler):
        echoing = {"id": 5, "name": "jdoe", "password": PASSWORD, "password2": PASSWORD}
        result, _ = await self._create(handler, echoing)
        assert PASSWORD not in str(result)

    async def test_update_response_omits_the_password_even_if_glpi_echoes_it(self, handler):
        echoing = {"id": 5, "name": "jdoe", "password": PASSWORD}
        post_p, get_p, put_p = _glpi(get=AsyncMock(return_value=echoing))
        with post_p, get_p, put_p:
            result = await handler.handle_call_tool(ADMIN, {
                "resource": "users", "action": "update", "resource_id": 5, "firstname": "Maria"})
        assert PASSWORD not in str(result)

    async def test_logs_omit_the_password(self, handler, caplog):
        echoing = {"id": 5, "name": "jdoe", "password": PASSWORD}
        with caplog.at_level(logging.DEBUG):
            await self._create(handler, echoing)
        assert PASSWORD not in caplog.text

    async def test_formatter_never_prints_password_fields(self):
        from src.formatters.response_formatter import format_tool_response
        user = {"id": 5, "name": "jdoe", "password": PASSWORD, "password2": PASSWORD}
        text = await format_tool_response(ADMIN, user, {"resource": "users", "action": "get"})
        assert PASSWORD not in (text or "")


class TestFailingCreateDoesNotCarryTheRequest:
    """A failing create must not put the request body (password, secret) in the error or logs."""

    @pytest.mark.parametrize("failure", ["connect", "http400"])
    async def test_error_text_and_logs(self, handler, caplog, failure):
        manager = SessionManager()
        client = AsyncMock()
        if failure == "connect":
            client.request.side_effect = httpx.ConnectError("boom")
        else:
            resp = AsyncMock()
            resp.status_code = 400
            resp.text = '["ERROR_GLPI_ADD","Campo invalido"]'
            resp.headers = {}
            client.request.return_value = resp
        manager.set_current_user_token("test-token")
        manager._get_session_for_user = AsyncMock(return_value=client)
        with patch("src.services.glpi_client.glpi_client.session", manager), \
             patch("src.auth.session_manager.asyncio.sleep", new=AsyncMock()), \
             caplog.at_level(logging.DEBUG):
            with pytest.raises(GLPIError) as caught:
                await handler.handle_call_tool(ADMIN, {
                    "resource": "users", "action": "create", "name": "jdoe",
                    "password": PASSWORD, "password2": PASSWORD})
        assert PASSWORD not in caught.value.message
        assert PASSWORD not in caplog.text
