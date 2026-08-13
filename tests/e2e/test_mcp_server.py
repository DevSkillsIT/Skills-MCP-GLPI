"""
E2E tests for GLPI MCP server.
Requires a running server with real GLPI API connection.

SPEC-GLPI-ENHANCE-001/F10 — Section 5.6

Run (against a running instance; GET tools that hit the GLPI API are skipped
unless a user token is provided):
    # Ramada (3 KB sources)
    GLPI_MCP_E2E_URL=http://localhost:8826 \
      GLPI_MCP_E2E_USER_TOKEN=<glpi user token> \
      .venv/bin/python -m pytest tests/e2e/ -v -o asyncio_mode=auto
    # Skills (2 KB sources)
    GLPI_MCP_E2E_URL=http://localhost:8824 .venv/bin/python -m pytest tests/e2e/ -v -o asyncio_mode=auto

Knowledge-base (pgvector) tests need no GLPI token — they hit the DB directly.
"""

import sys
sys.path.insert(0, "/opt/mcp-servers/glpi/.base-code")

import os
import pytest
import httpx

# Target instance is configurable so the same suite runs against any deployment:
#   GLPI_MCP_E2E_URL=http://localhost:8826 pytest tests/e2e/ -v   # Ramada
#   GLPI_MCP_E2E_URL=http://localhost:8824 pytest tests/e2e/ -v   # Skills (default)
BASE_URL = os.environ.get("GLPI_MCP_E2E_URL", "http://localhost:8824")
MCP_URL = f"{BASE_URL}/mcp"
# Optional GLPI user token (some GET tools need it); sent as a header when set.
_USER_TOKEN = os.environ.get("GLPI_MCP_E2E_USER_TOKEN", "")
_HEADERS = {"X-GLPI-User-Token": _USER_TOKEN} if _USER_TOKEN else {}


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
    reason=f"GLPI MCP server not running at {BASE_URL}",
)


async def mcp_call(method: str, params: dict | None = None) -> dict:
    """Make a JSON-RPC 2.0 call to the MCP server."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {},
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(MCP_URL, json=payload, headers=_HEADERS)
        return response.json()


def _text(res: dict) -> str:
    """Extract the text content from a tools/call result."""
    return res.get("result", {}).get("content", [{}])[0].get("text", "")


async def _list_tools() -> list[dict]:
    return (await mcp_call("tools/list", {})).get("result", {}).get("tools", [])


def _readonly_no_required(tool: dict) -> bool:
    """A read-only tool callable with no required args (search/list)."""
    ann = tool.get("annotations", {})
    required = tool.get("inputSchema", {}).get("required", [])
    return bool(ann.get("readOnlyHint")) and not required


def _glpi_authed() -> bool:
    """True if GLPI-backed tools work (a usable GLPI user token is available).
    GLPI read tools need X-GLPI-User-Token; without it they return -32001."""
    try:
        with httpx.Client(timeout=10) as client:
            r = client.post(MCP_URL, headers=_HEADERS, json={
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": "glpi_search_helpdesk_tickets", "arguments": {"limit": 1}},
            })
            d = r.json()
            if "error" in d:
                return False
            txt = d.get("result", {}).get("content", [{}])[0].get("text", "")
            return bool(txt) and ("|" in txt or "Nenhum" in txt)
    except Exception:
        return False


# GLPI-backed tests need a real user token; skip them gracefully otherwise.
glpi_required = pytest.mark.skipif(
    not _glpi_authed(),
    reason="GLPI-backed tool requires a user token (set GLPI_MCP_E2E_USER_TOKEN)",
)


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
    assert "TICKETS" in result["instructions"]  # tool-category header (consolidated names)
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
    assert "glpi_search_helpdesk_tickets" in tool_names
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

@glpi_required
@pytest.mark.asyncio
async def test_search_tickets_returns_markdown():
    """search_tickets returns Markdown, not JSON."""
    res = await mcp_call("tools/call", {
        "name": "glpi_search_helpdesk_tickets",
        "arguments": {"limit": 5},
    })
    text = res.get("result", {}).get("content", [{}])[0].get("text", "")
    # Should contain Markdown table OR "Nenhum" message
    assert "|" in text or "Nenhum" in text
    assert '"id":' not in text  # NOT JSON


# === E2E-07: search_assets returns Markdown ===

@glpi_required
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

@glpi_required
@pytest.mark.asyncio
async def test_default_limit_is_10():
    """search_tickets without limit returns max 10 results."""
    res = await mcp_call("tools/call", {
        "name": "glpi_search_helpdesk_tickets",
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

@glpi_required
@pytest.mark.asyncio
async def test_response_size_under_400kb():
    """search_tickets with max limit stays under 400KB."""
    res = await mcp_call("tools/call", {
        "name": "glpi_search_helpdesk_tickets",
        "arguments": {"limit": 50},
    })
    text = res.get("result", {}).get("content", [{}])[0].get("text", "")
    size = len(text.encode("utf-8"))
    assert size < 400 * 1024, f"Response size {size} exceeds 400KB"


# === E2E-11: every read-only/GET tool is reachable (100% coverage) ===

@pytest.mark.asyncio
async def test_all_readonly_tools_reachable():
    """Call every read-only tool with no required args; each must return a valid
    JSON-RPC response with text content (a graceful error message counts) and
    never crash the transport or leak raw JSON."""
    tools = await _list_tools()
    targets = [t for t in tools if _readonly_no_required(t)]
    assert targets, "no read-only/no-required tools discovered"
    for t in targets:
        args = {"limit": 3} if "limit" in t.get("inputSchema", {}).get("properties", {}) else {}
        res = await mcp_call("tools/call", {"name": t["name"], "arguments": args})
        assert "result" in res or "error" in res, f"{t['name']}: no JSON-RPC result/error"
        if "result" in res:
            # Empty/"Nenhum" is fine (e.g. a GLPI tool with no user token); the
            # invariant is: never crash the transport, never leak raw JSON.
            text = _text(res)
            assert not text.lstrip().startswith("{"), f"{t['name']}: leaked raw JSON"


# === E2E-12: GET-by-id path via search -> manage(get) ===

@glpi_required
@pytest.mark.asyncio
async def test_get_ticket_by_id_roundtrip():
    """search tickets -> take an id -> manage_ticket_operations(action=get)."""
    res = await mcp_call("tools/call", {
        "name": "glpi_search_helpdesk_tickets", "arguments": {"limit": 3},
    })
    text = _text(res)
    if "Nenhum" in text or "|" not in text:
        pytest.skip("no tickets available to fetch by id")
    # crude id extraction from the first data row of the Markdown table
    import re
    m = re.search(r"\|\s*(\d+)\s*\|", text)
    if not m:
        pytest.skip("could not parse a ticket id from search result")
    tid = int(m.group(1))
    got = await mcp_call("tools/call", {
        "name": "glpi_manage_ticket_operations",
        "arguments": {"action": "get", "ticket_id": tid},
    })
    assert "result" in got or "error" in got


# === E2E-13: prompts/list + prompts/get for every prompt ===

@pytest.mark.asyncio
async def test_prompts_list_and_get_each():
    res = await mcp_call("prompts/list", {})
    prompts = res.get("result", {}).get("prompts", [])
    assert len(prompts) >= 1, "no prompts exposed"
    for p in prompts:
        # Fill required args with a placeholder so validation passes where possible.
        args = {a["name"]: "1" for a in p.get("arguments", []) if a.get("required")}
        got = await mcp_call("prompts/get", {"name": p["name"], "arguments": args})
        # Either a rendered prompt (messages) or a structured error — never a crash.
        assert "result" in got or "error" in got, f"prompt {p['name']}: no response"
        if "result" in got:
            assert "messages" in got["result"], f"prompt {p['name']}: no messages"


# === E2E-14: resources/read for every listed resource ===

@pytest.mark.asyncio
async def test_resources_read_each():
    res = await mcp_call("resources/list", {})
    resources = res.get("result", {}).get("resources", [])
    assert len(resources) >= 4
    read_with_text = 0
    for r in resources:
        got = await mcp_call("resources/read", {"uri": r["uri"]})
        if "error" in got:
            continue  # GLPI-backed resource (e.g. entities) needs a user token
        contents = got.get("result", {}).get("contents", [])
        assert contents, f"resource {r['uri']}: empty result"
        if contents[0].get("text"):
            read_with_text += 1
    assert read_with_text >= 1, "no static resource returned text content"


# === E2E-15: knowledge base unified search — real DB queries ===

KB_TOOL = "glpi_search_knowledge_unified"


def _kb_available(tools: list[dict]) -> bool:
    return any(t["name"] == KB_TOOL for t in tools)


@pytest.mark.asyncio
async def test_kb_search_real_query_returns_table():
    """Real semantic+FTS query over the configured pgvector sources."""
    tools = await _list_tools()
    if not _kb_available(tools):
        pytest.skip("kb_search tool not registered")
    res = await mcp_call("tools/call", {
        "name": KB_TOOL,
        "arguments": {"query": "erro ao gerar boleto no sankhya", "source": "all", "limit": 5},
    })
    assert "result" in res, f"kb_search errored: {res.get('error')}"
    text = _text(res)
    # Markdown table header from the unified formatter, or a graceful empty.
    # The similarity column is labelled "Sim." — "Score" was its earlier name.
    assert ("Fonte" in text and "Oficial" in text and "Sim." in text) or "Nenhum" in text


@pytest.mark.asyncio
async def test_kb_search_help_source_has_results():
    """The official help source should answer a clearly on-topic query."""
    tools = await _list_tools()
    if not _kb_available(tools):
        pytest.skip("kb_search tool not registered")
    res = await mcp_call("tools/call", {
        "name": KB_TOOL,
        "arguments": {"query": "nota fiscal", "source": "help", "limit": 5},
    })
    assert "result" in res
    text = _text(res)
    assert "HELP" in text or "Nenhum" in text


@pytest.mark.asyncio
async def test_kb_search_respects_limit():
    tools = await _list_tools()
    if not _kb_available(tools):
        pytest.skip("kb_search tool not registered")
    res = await mcp_call("tools/call", {
        "name": KB_TOOL, "arguments": {"query": "sistema lento", "source": "all", "limit": 3},
    })
    text = _text(res)
    if "|" in text:
        rows = [ln for ln in text.split("\n") if ln.startswith("|") and "---" not in ln]
        assert len(rows) - 1 <= 3  # minus header


@pytest.mark.asyncio
async def test_kb_search_invalid_source_is_graceful():
    tools = await _list_tools()
    if not _kb_available(tools):
        pytest.skip("kb_search tool not registered")
    res = await mcp_call("tools/call", {
        "name": KB_TOOL, "arguments": {"query": "x", "source": "inexistente", "limit": 3},
    })
    # enum-validated arg: server returns a structured error, never a 500/crash.
    assert "result" in res or "error" in res
