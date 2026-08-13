"""
Contract tests for tool and prompt description quality.

These descriptions are not documentation — they are the retrieval surface.
Hubs that federate several MCP servers index them and pick a tool by semantic
similarity against the user's phrasing, so a thin description makes a working
tool unreachable: it simply never gets chosen.

The rules come from the project's naming guidelines (DIRETRIZES-OBRIGATORIAS-
MCP-TOOLS-NOMENCLATURA.md): Brazilian Portuguese, the key noun first, the MCP
identifier at least twice, and enough domain synonyms for real phrasing to
match.
"""

import sys

sys.path.insert(0, "/opt/mcp-servers/glpi/.base-code")

import pytest

from src.handlers import MCPHandler
from src.prompts_handlers.prompts import PROMPTS_CATALOG

# Minimum is the rule that actually protects retrieval: below it, a description
# cannot carry context plus synonyms. The guidelines recommend 400 as the upper
# bound; the ceiling here is a sanity limit, since a few tools legitimately
# spend extra characters on example phrasings ("chamados do grupo X"), which is
# precisely what makes them findable.
MIN_CHARS = 280
MAX_CHARS = 700

# Generic verbs that must not open a description: embedding models weight the
# first tokens, so the domain noun has to come first.
GENERIC_OPENERS = (
    "gera", "gerencia", "retorna", "busca", "lista", "obtem", "obtém",
    "consulta", "analisa", "permite", "executa", "realiza", "cria",
)


@pytest.fixture(scope="module")
def tools():
    return MCPHandler().tools


def _tool_cases(tools):
    return [(name, spec.get("description", "")) for name, spec in tools.items()]


class TestToolDescriptions:
    def test_every_tool_has_a_description(self, tools):
        missing = [name for name, spec in tools.items() if not spec.get("description")]
        assert missing == []

    def test_descriptions_are_long_enough_to_be_found(self, tools):
        thin = {
            name: len(desc)
            for name, desc in _tool_cases(tools)
            if len(desc) < MIN_CHARS
        }
        assert thin == {}, f"descricoes rasas prejudicam a busca semantica: {thin}"

    def test_descriptions_stay_within_a_sane_ceiling(self, tools):
        bloated = {
            name: len(desc)
            for name, desc in _tool_cases(tools)
            if len(desc) > MAX_CHARS
        }
        assert bloated == {}

    def test_mcp_identifier_appears_twice(self, tools):
        """The server identifier anchors the tool to its domain."""
        weak = {
            name: desc.lower().count("glpi")
            for name, desc in _tool_cases(tools)
            if desc.lower().count("glpi") < 2
        }
        assert weak == {}

    def test_description_opens_with_the_domain_noun(self, tools):
        offenders = {
            name: desc.split()[0]
            for name, desc in _tool_cases(tools)
            if desc.split() and desc.split()[0].lower().strip(",.") in GENERIC_OPENERS
        }
        assert offenders == {}, f"comecar por verbo generico derruba o match: {offenders}"

    def test_read_only_tools_declare_their_output_or_scope(self, tools):
        """A description has to say what comes back, or what it will not do."""
        signals = ("retorna", "consulta somente leitura", "somente leitura", "nao utilize")
        silent = [
            name
            for name, desc in _tool_cases(tools)
            if not any(s in desc.lower() for s in signals)
        ]
        assert silent == []


class TestPromptDescriptions:
    """Prompts are catalogued and searched exactly like tools."""

    def test_every_prompt_has_a_description(self):
        missing = [p["name"] for p in PROMPTS_CATALOG if not p.get("description")]
        assert missing == []

    def test_descriptions_are_long_enough_to_be_found(self):
        thin = {
            p["name"]: len(p.get("description", ""))
            for p in PROMPTS_CATALOG
            if len(p.get("description", "")) < MIN_CHARS
        }
        assert thin == {}, f"descricoes rasas prejudicam a busca semantica: {thin}"

    def test_descriptions_stay_within_a_sane_ceiling(self):
        bloated = {
            p["name"]: len(p.get("description", ""))
            for p in PROMPTS_CATALOG
            if len(p.get("description", "")) > MAX_CHARS
        }
        assert bloated == {}

    def test_mcp_identifier_appears_twice(self):
        weak = {
            p["name"]: p.get("description", "").lower().count("glpi")
            for p in PROMPTS_CATALOG
            if p.get("description", "").lower().count("glpi") < 2
        }
        assert weak == {}

    def test_description_states_when_to_use_it(self):
        """Without a usage condition the model cannot tell siblings apart."""
        silent = [
            p["name"]
            for p in PROMPTS_CATALOG
            if "use " not in p.get("description", "").lower()
        ]
        assert silent == []

    def test_description_opens_with_the_domain_noun(self):
        offenders = {
            p["name"]: p["description"].split()[0]
            for p in PROMPTS_CATALOG
            if p.get("description", "").split()
            and p["description"].split()[0].lower().strip(",.") in GENERIC_OPENERS
        }
        assert offenders == {}
