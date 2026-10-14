"""The resource and knowledge bridge tools report failures as isError.

Same contract as the prompt bridge (commits b87d2fe / 97550d9): a failure
returned as ``{"error": ...}`` inside a successful result is read by the agent
as an answer. For the knowledge search it is worse -- a failed query looked like
"no articles found".
"""
from unittest.mock import AsyncMock, patch

from src.handlers import mcp_handler
import pytest

from src.models.exceptions import GLPIError, NotFoundError, ValidationError
from src.tools.bridge_tools import bridge_tools
from src.services.glpi_client import glpi_client


def _call(name: str, arguments: dict) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": arguments}}


def _failure_text(response: dict) -> str:
    assert "error" not in response, f"protocol error: {response.get('error')}"
    result = response["result"]
    assert result.get("isError") is True, f"not isError: {result}"
    return result["content"][0]["text"]


class TestReadResourceBridge:
    async def test_empty_uri_is_a_tool_failure_listing_the_uris(self):
        resp = await mcp_handler.handle_request(_call("glpi_read_resource_by_uri", {"uri": ""}))
        assert "glpi://entities" in _failure_text(resp)

    async def test_unknown_uri_is_a_tool_failure(self):
        resp = await mcp_handler.handle_request(
            _call("glpi_read_resource_by_uri", {"uri": "glpi://nao-existe"}))
        assert "nao-existe" in _failure_text(resp)

    async def test_glpi_failure_is_a_tool_failure(self):
        with patch.object(glpi_client, "get",
                          AsyncMock(side_effect=GLPIError(503, "GLPI fora do ar"))):
            resp = await mcp_handler.handle_request(
                _call("glpi_read_resource_by_uri", {"uri": "glpi://entities"}))
        assert "GLPI fora do ar" in _failure_text(resp)

    async def test_known_static_uri_still_succeeds(self):
        resp = await mcp_handler.handle_request(
            _call("glpi_read_resource_by_uri", {"uri": "glpi://priorities"}))
        assert not resp["result"].get("isError")


class TestBridgeMethodsRaiseInsteadOfReturningErrorDicts:
    """The schema enum hides the defect on the MCP path; the method itself must still raise."""

    async def test_read_resource_with_empty_uri_raises_and_lists_uris(self):
        with pytest.raises(ValidationError) as caught:
            await bridge_tools.read_resource_tool(uri="")
        assert "glpi://entities" in caught.value.message

    async def test_read_resource_with_unknown_uri_raises(self):
        with pytest.raises(NotFoundError) as caught:
            await bridge_tools.read_resource_tool(uri="glpi://nao-existe")
        assert "nao-existe" in str(caught.value.details) + caught.value.message

    async def test_search_knowledge_without_query_raises(self):
        with pytest.raises(ValidationError):
            await bridge_tools.search_knowledge(query="")


class TestKnowledgeSearchBridge:
    async def test_missing_query_is_a_tool_failure(self):
        resp = await mcp_handler.handle_request(
            _call("glpi_search_knowledge_articles", {"query": ""}))
        assert "query" in _failure_text(resp)

    async def test_failed_search_is_not_reported_as_no_articles(self):
        with patch.object(glpi_client, "search",
                          AsyncMock(side_effect=GLPIError(503, "GLPI fora do ar"))):
            resp = await mcp_handler.handle_request(
                _call("glpi_search_knowledge_articles", {"query": "impressora"}))
        assert "GLPI fora do ar" in _failure_text(resp)
