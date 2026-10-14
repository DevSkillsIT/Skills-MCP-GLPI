"""One version, defined once (src.__version__), reported everywhere.

initialize said 2.0.0, FastAPI and /health said 1.0.0, the docs said 2.2.0.
"""
import re
from pathlib import Path

from fastapi.testclient import TestClient

import src
from src.handlers import mcp_handler
from src.main import app

ROOT = Path(__file__).resolve().parent.parent


def _latest_released_version() -> str:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    return re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.MULTILINE).group(1)


async def _initialize_version() -> str:
    response = await mcp_handler.handle_request(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    return response["result"]["serverInfo"]["version"]


async def test_initialize_reports_the_package_version():
    assert await _initialize_version() == src.__version__


def test_health_and_openapi_report_the_package_version():
    client = TestClient(app)
    assert client.get("/health").json()["version"] == src.__version__
    assert app.version == src.__version__


async def test_initialize_and_health_agree():
    assert await _initialize_version() == TestClient(app).get("/health").json()["version"]


def test_package_version_is_the_latest_changelog_release():
    assert src.__version__ == _latest_released_version()


def test_tools_package_does_not_carry_its_own_version():
    from src import tools
    assert tools.__version__ == src.__version__
