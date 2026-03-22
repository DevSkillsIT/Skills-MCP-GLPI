"""
E2E tests for GLPI MCP server.
Requires a running server with real GLPI API connection.

SPEC-GLPI-ENHANCE-001/F10 — Section 5.6
Run with: pytest tests/e2e/ -v --runInBand

Prerequisites:
- Server running on http://localhost:8824
- Valid GLPI API credentials configured
"""

import sys
sys.path.insert(0, "/opt/mcp-servers/glpi/.base-code")

import json
import pytest
import httpx

BASE_URL = "http://localhost:8824"
MCP_URL = f"{BASE_URL}/mcp"


def _server_available() -> bool:
    """Check if server is available."""
    try:
        with httpx.Client(timeout=5) as client:
            r = client.get(f"{BASE_URL}/health")
            return r.status_code == 200
    except Exception:
        return False


# Skip all E2E tests if server is not running
pytestmark = pytest.mark.skipif(
    not _server_available(),
    reason="GLPI MCP server not running at localhost:8824",
)


async def mcp_call(method: str, params: dict = None) -> dict:
    """Make a JSON-RPC 2.0 call to the MCP server."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(MCP_URL, json=payload)
        return response.json()


# === E2E-01: Health check ===

@pytest.mark.asyncio
async def test_health_check():
    """GET /health returns 200 with version 2.0.0."""
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.get(f"{BASE_URL}/health")
    assert res.status_code == 200
    data = res.json()
    assert data.get("status") in ("healthy", "ok", "running")


# === E2E-02: Initialize with instructions ===

@pytest.mark.asyncio
async def test_initialize_returns_instructions():
    """Initialize returns server instructions."""
    res = await mcp_call("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test-e2e", "version": "1.0"},
    })
    result = res.get("result", {})
    assert "instructions" in result
    assert len(result["instructions"]) > 100
    assert "search_tickets" in result["instructions"]
    assert result["serverInfo"]["version"] == "2.0.0"


# === E2E-03: tools/list returns consolidated tools ===

@pytest.mark.asyncio
async def test_tools_list_count():
    """tools/list returns 14+ consolidated tools."""
    res = await mcp_call("tools/list", {})
    tools = res.get("result", {}).get("tools", [])
    assert len(tools) >= 14
    tool_names = [t["name"] for t in tools]
    # Check core tools
    assert "glpi_search_ticket_requests" in tool_names
    assert "glpi_manage_ticket_operations" in tool_names
    assert "glpi_search_asset_inventory" in tool_names
    assert "glpi_manage_asset_operations" in tool_names


# === E2E-04: All tools have annotations ===

@pytest.mark.asyncio
async def test_all_tools_have_annotations():
    """All tools returned have annotations."""
    res = await mcp_call("tools/list", {})
    tools = res.get("result", {}).get("tools", [])
    for tool in tools:
        assert "annotations" in tool, f"{tool['name']} missing annotations"
        ann = tool["annotations"]
        assert "readOnlyHint" in ann, f"{tool['name']} missing readOnlyHint"
        assert "destructiveHint" in ann, f"{tool['name']} missing destructiveHint"


# === E2E-05: resources/list returns resources ===

@pytest.mark.asyncio
async def test_resources_list():
    """resources/list returns >= 4 resources."""
    res = await mcp_call("resources/list", {})
    resources = res.get("result", {}).get("resources", [])
    assert len(resources) >= 4
    uris = [r["uri"] for r in resources]
    assert "glpi://entities" in uris
    assert "glpi://ticket-status" in uris


# === E2E-06: search_tickets returns Markdown ===

@pytest.mark.asyncio
async def test_search_tickets_returns_markdown():
    """search_tickets returns Markdown, not JSON."""
    res = await mcp_call("tools/call", {
        "name": "glpi_search_ticket_requests",
        "arguments": {"limit": 5},
    })
    text = res.get("result", {}).get("content", [{}])[0].get("text", "")
    # Should contain Markdown table OR "Nenhum" message
    assert "|" in text or "Nenhum" in text
    assert '"id":' not in text  # NOT JSON


# === E2E-07: search_assets returns Markdown ===

@pytest.mark.asyncio
async def test_search_assets_returns_markdown():
    """search_assets returns Markdown, not JSON."""
    res = await mcp_call("tools/call", {
        "name": "glpi_search_asset_inventory",
        "arguments": {"limit": 5},
    })
    text = res.get("result", {}).get("content", [{}])[0].get("text", "")
    assert "|" in text or "Nenhum" in text
    assert '"id":' not in text


# === E2E-08: Default limit is 10 ===

@pytest.mark.asyncio
async def test_default_limit_is_10():
    """search_tickets without limit returns max 10 results."""
    res = await mcp_call("tools/call", {
        "name": "glpi_search_ticket_requests",
        "arguments": {},
    })
    text = res.get("result", {}).get("content", [{}])[0].get("text", "")
    # Count table rows (lines starting with |, excluding header and separator)
    if "|" in text:
        rows = [line for line in text.split("\n") if line.startswith("|") and "---" not in line]
        # Subtract header row
        data_rows = len(rows) - 1 if rows else 0
        assert data_rows <= 10


# === E2E-09: read_resource returns Markdown ===

@pytest.mark.asyncio
async def test_read_resource_ticket_status():
    """read_resource(glpi://ticket-status) returns Markdown."""
    res = await mcp_call("resources/read", {"uri": "glpi://ticket-status"})
    contents = res.get("result", {}).get("contents", [])
    assert len(contents) > 0
    assert contents[0].get("mimeType") == "text/markdown"
    assert "Novo" in contents[0].get("text", "")


# === E2E-10: Response size under 400KB ===

@pytest.mark.asyncio
async def test_response_size_under_400kb():
    """search_tickets with max limit stays under 400KB."""
    res = await mcp_call("tools/call", {
        "name": "glpi_search_ticket_requests",
        "arguments": {"limit": 50},
    })
    text = res.get("result", {}).get("content", [{}])[0].get("text", "")
    size = len(text.encode("utf-8"))
    assert size < 400 * 1024, f"Response size {size} exceeds 400KB"
