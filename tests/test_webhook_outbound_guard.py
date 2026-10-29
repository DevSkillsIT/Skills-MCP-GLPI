"""A webhook must not become an exfiltration or SSRF channel.

- the destination host has to be listed in WEBHOOK_ALLOWED_HOSTS;
- it must never resolve to loopback / link-local (cloud metadata);
- webhook_id never carries path characters into /apirest.php/Webhook/{id};
- test_webhook re-checks the stored URL and does not echo the response body.
"""
import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.exceptions import ValidationError
from src.tools.consolidated_webhooks import _validate_webhook_id
from src.tools.webhooks import _clean_webhook_id, _validate_url, webhook_tools


def _resolves_to(ip):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return AsyncMock(return_value=[(family, socket.SOCK_STREAM, 6, "", (ip, 0))])


@pytest.fixture
def allow(monkeypatch):
    def _set(value):
        monkeypatch.setattr("src.tools.webhooks.settings.webhook_allowed_hosts", value, raising=False)
    return _set


@pytest.fixture
def resolve(monkeypatch):
    def _set(ip):
        loop = MagicMock()
        loop.getaddrinfo = _resolves_to(ip)
        monkeypatch.setattr("src.tools.webhooks.asyncio.get_running_loop", lambda: loop)
    return _set


async def test_empty_allowlist_refuses_every_host(allow, resolve):
    allow("")
    resolve("93.184.216.34")
    with pytest.raises(ValidationError, match="WEBHOOK_ALLOWED_HOSTS"):
        await _validate_url("https://example.com/hook")


async def test_listed_host_is_accepted(allow, resolve):
    allow("example.com")
    resolve("93.184.216.34")
    await _validate_url("https://example.com/hook")


async def test_dot_entry_accepts_subdomains_only_of_that_domain(allow, resolve):
    allow(".empresa.pt")
    resolve("10.0.0.5")
    await _validate_url("https://n8n.empresa.pt/hook")
    await _validate_url("https://empresa.pt/hook")
    with pytest.raises(ValidationError):
        await _validate_url("https://empresa.pt.atacante.com/hook")


@pytest.mark.parametrize("ip", ["127.0.0.1", "169.254.169.254", "0.0.0.0", "::1", "::ffff:127.0.0.1", "224.0.0.1"])
async def test_listed_host_resolving_to_forbidden_address_is_refused(allow, resolve, ip):
    allow("hook.example.com")
    resolve(ip)
    with pytest.raises(ValidationError, match="nao permitido"):
        await _validate_url("https://hook.example.com/x")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/", "https://", "https://user:pw@example.com/"])
async def test_malformed_or_credentialed_urls_are_refused(allow, url):
    allow("example.com")
    with pytest.raises(ValidationError):
        await _validate_url(url)


@pytest.mark.parametrize("bad", ["../User/7", "7/../../User/7", "7?x=1", "7#a", "a b", "7%2F..", ""])
def test_webhook_id_rejects_path_characters(bad):
    with pytest.raises(ValidationError):
        _clean_webhook_id(bad)
    assert _validate_webhook_id(bad)["valid"] is False


@pytest.mark.parametrize("good", ["7", 7, "a1b2c3", "0f9e-4c_1"])
def test_webhook_id_accepts_numeric_and_hash_ids(good):
    assert _clean_webhook_id(good) == str(good)
    assert _validate_webhook_id(good)["valid"] is True


async def test_disable_with_traversal_id_never_reaches_glpi():
    put = AsyncMock()
    get = AsyncMock()
    with patch("src.tools.webhooks.glpi_client.put", put), \
         patch("src.tools.webhooks.glpi_client.get", get):
        with pytest.raises(ValidationError):
            await webhook_tools.disable_webhook("../User/7")
    put.assert_not_awaited()
    get.assert_not_awaited()


async def test_create_with_unlisted_host_never_reaches_glpi(allow):
    allow("")
    post = AsyncMock()
    with patch("src.tools.webhooks.glpi_client.post", post):
        with pytest.raises(ValidationError):
            await webhook_tools.create_webhook(
                name="x", url="https://atacante.example/coleta", event_type="ticket.created"
            )
    post.assert_not_awaited()


async def test_test_webhook_rechecks_stored_url_and_hides_body(allow, resolve):
    stored = {"id": 7, "name": "n", "url": "http://169.254.169.254/latest/meta-data"}
    with patch.object(webhook_tools, "get_webhook", AsyncMock(return_value=stored)):
        allow("169.254.169.254")
        resolve("169.254.169.254")
        with pytest.raises(ValidationError):
            await webhook_tools.test_webhook("7")

    stored = {"id": 7, "name": "n", "url": "https://hook.example.com/x"}
    response = MagicMock(is_success=True, status_code=200, text="segredo interno")
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    with patch.object(webhook_tools, "get_webhook", AsyncMock(return_value=stored)), \
         patch("src.tools.webhooks.httpx.AsyncClient", return_value=client) as ctor:
        allow("hook.example.com")
        resolve("93.184.216.34")
        result = await webhook_tools.test_webhook("7")
    assert ctor.call_args.kwargs["follow_redirects"] is False
    assert "response_body" not in result
    assert "segredo interno" not in str(result)
