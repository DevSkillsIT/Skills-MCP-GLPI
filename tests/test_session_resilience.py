"""
Tests for the unified request path: retries, backoff, re-auth and error mapping.

The rule that matters most here is the asymmetry between reads and writes.
A read can always be repeated. A write can only be repeated when the request
provably never reached GLPI — otherwise a retry risks creating a second ticket
or a duplicate followup, which is worse than surfacing the error.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.auth.session_manager import SessionManager
from src.models.exceptions import (
    AuthenticationError,
    GLPIError,
    RateLimitError,
    TimeoutError as GLPITimeoutError,
)


def _response(status: int = 200, body: str = '{"ok": true}', headers: dict | None = None):
    resp = MagicMock()
    resp.status_code = status
    resp.text = body
    resp.headers = headers or {}
    resp.json.return_value = {"ok": True}
    return resp


def _manager(dispatch) -> tuple:
    """Build a manager whose HTTP client is driven by `dispatch`."""
    manager = SessionManager()
    client = AsyncMock()
    client.request.side_effect = dispatch
    manager.set_current_user_token("test-token")
    manager._get_session_for_user = AsyncMock(return_value=client)
    return manager, client


@pytest.fixture(autouse=True)
def _no_sleep():
    """Backoff waits are real seconds — skip them so tests stay fast."""
    with patch("src.auth.session_manager.asyncio.sleep", new=AsyncMock()) as sleep:
        yield sleep


class TestReadRetries:
    async def test_server_error_is_retried_then_succeeds(self):
        attempts = []

        async def dispatch(method, *args, **kwargs):
            attempts.append(method)
            return _response(500) if len(attempts) == 1 else _response(200)

        manager, client = _manager(dispatch)
        result = await manager.get("/api/x", use_cache=False)

        assert result == {"ok": True}
        assert client.request.call_count == 2

    async def test_server_error_gives_up_after_max_retries(self):
        async def dispatch(method, *args, **kwargs):
            return _response(503, body="unavailable")

        manager, client = _manager(dispatch)
        with pytest.raises(GLPIError) as exc:
            await manager.get("/api/x", use_cache=False)

        assert exc.value.code == 503
        # 1 initial attempt + max_retries
        assert client.request.call_count == 3

    async def test_read_timeout_is_retried(self):
        calls = []

        async def dispatch(method, *args, **kwargs):
            calls.append(method)
            if len(calls) == 1:
                raise httpx.ReadTimeout("too slow")
            return _response(200)

        manager, client = _manager(dispatch)
        assert await manager.get("/api/x", use_cache=False) == {"ok": True}
        assert client.request.call_count == 2

    async def test_persistent_timeout_raises_timeout_error(self):
        async def dispatch(method, *args, **kwargs):
            raise httpx.ReadTimeout("too slow")

        manager, _ = _manager(dispatch)
        with pytest.raises(GLPITimeoutError):
            await manager.get("/api/x", use_cache=False)


class TestWriteSafety:
    async def test_write_is_not_retried_after_server_error(self):
        """GLPI may have applied the write before failing — never replay it."""
        async def dispatch(method, *args, **kwargs):
            return _response(500, body="boom")

        manager, client = _manager(dispatch)
        with pytest.raises(GLPIError):
            await manager.post("/Ticket", data={"name": "x"})

        assert client.request.call_count == 1

    async def test_write_is_not_retried_after_read_timeout(self):
        """A timeout after sending means the server may have processed it."""
        async def dispatch(method, *args, **kwargs):
            raise httpx.ReadTimeout("too slow")

        manager, client = _manager(dispatch)
        with pytest.raises(GLPITimeoutError):
            await manager.post("/Ticket", data={"name": "x"})

        assert client.request.call_count == 1

    async def test_write_is_retried_when_connection_never_opened(self):
        """Connection refused proves GLPI never saw the request."""
        calls = []

        async def dispatch(method, *args, **kwargs):
            calls.append(method)
            if len(calls) == 1:
                raise httpx.ConnectError("refused")
            return _response(201, body='{"id": 1}')

        manager, client = _manager(dispatch)
        await manager.post("/Ticket", data={"name": "x"})

        assert client.request.call_count == 2

    async def test_write_is_retried_on_rate_limit(self):
        """429 means the server rejected without doing the work."""
        calls = []

        async def dispatch(method, *args, **kwargs):
            calls.append(method)
            if len(calls) == 1:
                return _response(429, headers={"retry-after": "1"})
            return _response(201, body='{"id": 1}')

        manager, client = _manager(dispatch)
        await manager.post("/Ticket", data={"name": "x"})

        assert client.request.call_count == 2


class TestRateLimitHandling:
    async def test_retry_after_header_drives_the_wait(self, _no_sleep):
        calls = []

        async def dispatch(method, *args, **kwargs):
            calls.append(method)
            if len(calls) == 1:
                return _response(429, headers={"retry-after": "7"})
            return _response(200)

        manager, _ = _manager(dispatch)
        await manager.get("/api/x", use_cache=False)

        _no_sleep.assert_awaited_once_with(7.0)

    async def test_malformed_retry_after_falls_back_to_backoff(self, _no_sleep):
        calls = []

        async def dispatch(method, *args, **kwargs):
            calls.append(method)
            if len(calls) == 1:
                # HTTP-date form: valid per spec, but not a plain delay.
                return _response(429, headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})
            return _response(200)

        manager, _ = _manager(dispatch)
        await manager.get("/api/x", use_cache=False)

        _no_sleep.assert_awaited_once()
        assert _no_sleep.await_args.args[0] != 0

    async def test_exhausted_rate_limit_raises_rate_limit_error(self):
        async def dispatch(method, *args, **kwargs):
            return _response(429, headers={"retry-after": "1"})

        manager, _ = _manager(dispatch)
        with pytest.raises(RateLimitError):
            await manager.get("/api/x", use_cache=False)


class TestReauthentication:
    async def test_401_triggers_single_reauth_then_succeeds(self):
        calls = []

        async def dispatch(method, *args, **kwargs):
            calls.append(method)
            return _response(401) if len(calls) == 1 else _response(200)

        manager, client = _manager(dispatch)
        assert await manager.get("/api/x", use_cache=False) == {"ok": True}
        assert client.request.call_count == 2

    async def test_repeated_401_is_not_retried_forever(self):
        async def dispatch(method, *args, **kwargs):
            return _response(401)

        manager, client = _manager(dispatch)
        with pytest.raises(AuthenticationError):
            await manager.get("/api/x", use_cache=False)

        # One reauth attempt only, then surface the failure.
        assert client.request.call_count == 2

    async def test_reauth_applies_to_writes_too(self):
        calls = []

        async def dispatch(method, *args, **kwargs):
            calls.append(method)
            return _response(401) if len(calls) == 1 else _response(201, body='{"id": 1}')

        manager, client = _manager(dispatch)
        await manager.post("/Ticket", data={"name": "x"})
        assert client.request.call_count == 2


class TestCacheStillAuthenticates:
    """A cache hit must not bypass session validation.

    Resolving the session is what validates the caller's token, and the cache
    key is global — it does not include the token. Serving a cached read
    without validating would hand one tenant's data to another caller.
    """

    async def test_cache_hit_still_resolves_the_session(self):
        async def dispatch(method, *args, **kwargs):
            return _response(200)

        manager, client = _manager(dispatch)

        await manager.get("/api/x", params={"a": 1}, use_cache=True)
        await manager.get("/api/x", params={"a": 1}, use_cache=True)

        # Second call served from cache: no extra HTTP request...
        assert client.request.call_count == 1
        # ...but the session was resolved on both calls.
        assert manager._get_session_for_user.await_count == 2

    async def test_cache_hit_is_blocked_when_session_is_invalid(self):
        async def dispatch(method, *args, **kwargs):
            return _response(200)

        manager, _ = _manager(dispatch)
        await manager.get("/api/x", params={"a": 1}, use_cache=True)

        # Credentials stop being valid between the two reads.
        manager._get_session_for_user = AsyncMock(return_value=None)

        with pytest.raises(GLPIError):
            await manager.get("/api/x", params={"a": 1}, use_cache=True)


class TestErrorMapping:
    async def test_404_mentions_the_resource(self):
        async def dispatch(method, *args, **kwargs):
            return _response(404, body="not found")

        manager, _ = _manager(dispatch)
        with pytest.raises(GLPIError) as exc:
            await manager.get("/apirest.php/Ticket/999", use_cache=False)

        assert exc.value.code == 404
        assert "Ticket/999" in exc.value.message

    async def test_connection_failure_maps_to_service_unavailable(self):
        async def dispatch(method, *args, **kwargs):
            raise httpx.ConnectError("refused")

        manager, _ = _manager(dispatch)
        with pytest.raises(GLPIError) as exc:
            await manager.get("/api/x", use_cache=False)

        assert exc.value.code == 503

    async def test_client_error_preserves_status(self):
        async def dispatch(method, *args, **kwargs):
            return _response(400, body="bad input")

        manager, _ = _manager(dispatch)
        with pytest.raises(GLPIError) as exc:
            await manager.get("/api/x", use_cache=False)

        assert exc.value.code == 400
