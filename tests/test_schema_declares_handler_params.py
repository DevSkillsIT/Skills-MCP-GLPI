"""Every handler parameter is declared in the tool's input schema.

The dispatcher forwards any argument the handler accepts, so a parameter missing from the
schema works but is INVISIBLE to a client that builds calls from tools/list (no category,
requester or urgency on a ticket; no password on a user...). The only intended exception
is ``purge`` on the admin tool: the docs promise that a permanent purge is not exposed.
"""
import inspect
import re

import pytest

from src.handlers import MCPHandler

#: (tool, parameter) pairs that are handled in code but must NOT be declared.
INTENTIONALLY_UNDECLARED = {("glpi_manage_admin_resources", "purge")}

SENSITIVE = ("password", "password2", "secret")


@pytest.fixture(scope="module")
def tools():
    return MCPHandler().tools


def _undeclared(tools):
    gaps = []
    for name, info in tools.items():
        sig = inspect.signature(info["handler"])
        props = set(info["input_schema"].get("properties") or {})
        for p in sig.parameters.values():
            if p.kind in (p.VAR_KEYWORD, p.VAR_POSITIONAL) or p.name in props:
                continue
            if (name, p.name) not in INTENTIONALLY_UNDECLARED:
                gaps.append(f"{name}.{p.name}")
    return gaps


def test_every_handler_parameter_is_declared(tools):
    assert _undeclared(tools) == []


def test_purge_is_not_exposed_on_the_admin_tool(tools):
    """Permanent purge of users/locations stays a GLPI-interface action."""
    schema = tools["glpi_manage_admin_resources"]["input_schema"]
    assert "purge" not in schema["properties"]


def test_allowlist_only_names_real_undeclared_parameters(tools):
    """A stale allowlist entry would hide a future gap."""
    for name, param in INTENTIONALLY_UNDECLARED:
        assert param in inspect.signature(tools[name]["handler"]).parameters


def test_sensitive_parameters_are_marked_and_typed(tools):
    for info in tools.values():
        for key, spec in (info["input_schema"].get("properties") or {}).items():
            if key in SENSITIVE:
                assert spec["type"] == "string"
                assert "sensivel" in spec["description"].lower(), key


def test_declared_enums_describe_their_values(tools):
    """FASE 4.4: the description of an enum lists the accepted values."""
    for tool, info in tools.items():
        for key, spec in (info["input_schema"].get("properties") or {}).items():
            if spec.get("enum") and len(spec["enum"]) <= 8:
                missing = [v for v in spec["enum"] if str(v) not in spec["description"]]
                assert not missing, f"{tool}.{key} description omits {missing}"
