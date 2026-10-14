"""The handler carries no table of tool names that no longer exist.

``_get_tool_description`` / ``_get_tool_schema`` were leftovers from the 68-tool
surface (old names such as ``glpi_list_prompts``) with no call site. A reader
trusting them documents tools the server does not expose.
"""
import pytest

from src.handlers import MCPHandler


@pytest.mark.parametrize("name", ["_get_tool_description", "_get_tool_schema"])
def test_legacy_lookup_tables_are_gone(name):
    assert not hasattr(MCPHandler, name)


def test_register_tools_docstring_does_not_state_a_stale_count():
    doc = MCPHandler._register_tools.__doc__
    assert "14 consolidated" not in doc and "68 tools" not in doc
