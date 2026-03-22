"""
Bridge tools for MCPHub integration.
Exposes MCP resources and prompts as tools for MCPHub compatibility.

SPEC-GLPI-ENHANCE-001/F07 — Section 4.7
"""

from typing import Any, Dict, Optional

from src.resources import GLPI_RESOURCES, list_resources, read_resource
from src.formatters.glpi_formatters import format_resources_list, format_prompts_list


class BridgeTools:
    """Bridge tools for MCPHub resource/prompt access."""

    def __init__(self, session_manager=None, prompts_catalog=None):
        """Initialize with session manager and prompts catalog."""
        self.session_manager = session_manager
        self.prompts_catalog = prompts_catalog or []

    async def list_resources_tool(self, **kwargs) -> Any:
        """List available MCP resources as Markdown table."""
        resources = list_resources()
        return format_resources_list(resources)

    async def read_resource_tool(self, uri: str = "", **kwargs) -> Any:
        """Read a specific MCP resource by URI."""
        if not uri:
            return {
                "error": "Parametro 'uri' obrigatorio. "
                f"URIs disponiveis: {', '.join(r['uri'] for r in GLPI_RESOURCES)}"
            }
        session = await self.session_manager.get_current_session() if self.session_manager else None
        try:
            result = await read_resource(uri, session)
            return result.get("text", str(result))
        except ValueError as e:
            return {"error": str(e)}

    async def list_prompts_tool(self, **kwargs) -> Any:
        """List available professional prompts as Markdown table."""
        return format_prompts_list(self.prompts_catalog)

    async def get_prompt_tool(self, name: str = "", arguments: Optional[Dict] = None, **kwargs) -> Any:
        """Execute a specific prompt by name with arguments."""
        if not name:
            return {"error": "Parametro 'name' obrigatorio. Use glpi_list_prompts para ver prompts disponiveis."}

        # Find prompt in catalog
        prompt = next((p for p in self.prompts_catalog if p.get("name") == name), None)
        if not prompt:
            available = ", ".join(p.get("name", "") for p in self.prompts_catalog[:5])
            return {
                "error": f"Prompt '{name}' nao encontrado. "
                f"Disponiveis: {available}... Use glpi_list_prompts para lista completa."
            }

        # Delegate to prompt handler if available
        handler = prompt.get("handler")
        if handler:
            return await handler(arguments or {})

        return {"message": f"Prompt '{name}' encontrado mas sem handler configurado."}

    async def search_knowledge(self, query: str = "", limit: int = 10, **kwargs) -> Any:
        """Search GLPI knowledge base."""
        if not query or len(query) < 2:
            return {"error": "Parametro 'query' obrigatorio (minimo 2 caracteres)."}
        limit = min(limit, 50)
        # Delegate to existing search functionality
        # This will be connected to the ticket search with knowledge base scope
        return {"message": f"Busca na base de conhecimento por: '{query}' (limit: {limit})", "data": []}


bridge_tools = BridgeTools()
