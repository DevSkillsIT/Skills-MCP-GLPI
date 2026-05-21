"""
Bridge tools for MCPHub integration.
Exposes MCP resources and prompts as tools for MCPHub compatibility.

SPEC-GLPI-ENHANCE-001/F07 — Section 4.7
"""

from typing import Any, Dict, Optional

from src.resources import GLPI_RESOURCES, list_resources, read_resource
from src.formatters.glpi_formatters import format_resources_list, format_prompts_list
from src.prompts_handlers.prompts import PROMPTS_CATALOG, prompt_handler
from src.services.glpi_client import glpi_client
from src.utils.helpers import logger


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
        """Read a specific MCP resource by URI.

        Delegates to read_resource which uses glpi_client internally
        (handles auth via SessionManager context vars).
        """
        if not uri:
            return {
                "error": "Parametro 'uri' obrigatorio. "
                f"URIs disponiveis: {', '.join(r['uri'] for r in GLPI_RESOURCES)}"
            }
        try:
            result = await read_resource(uri)
            return result.get("text", str(result))
        except ValueError as e:
            return {"error": str(e)}

    async def list_prompts_tool(self, **kwargs) -> Any:
        """List available professional prompts as Markdown table."""
        return format_prompts_list(self.prompts_catalog)

    async def get_prompt_tool(self, name: str = "", arguments: Optional[Dict] = None, **kwargs) -> Any:
        """Execute a specific prompt by name with arguments.

        Uses prompt_handler to actually run the prompt logic; the catalog
        entries themselves do not carry handlers.
        """
        if not name:
            return {"error": "Parametro 'name' obrigatorio. Use glpi_list_prompts para ver prompts disponiveis."}

        prompt = next((p for p in self.prompts_catalog if p.get("name") == name), None)
        if not prompt:
            names = [p.get("name", "") for p in self.prompts_catalog]
            return {
                "error": (
                    f"Prompt '{name}' nao encontrado. "
                    f"Disponiveis ({len(names)}): {', '.join(names)}"
                )
            }

        try:
            return await prompt_handler.get_prompt(name, arguments or {})
        except Exception as e:
            logger.error(f"get_prompt_tool error for '{name}': {e}")
            return {"error": f"Falha ao executar prompt '{name}': {e}"}

    async def search_knowledge(self, query: str = "", limit: int = 10, **kwargs) -> Any:
        """Search GLPI knowledge base (KnowbaseItem).

        GLPI 11 KnowbaseItem field map (from listSearchOptions/KnowbaseItem):
          1 = Assunto/name, 2 = ID, 7 = Conteudo/answer, 9 = Visualizacoes,
          79 = Categoria, 19 = Ultima atualizacao.
        NOTE: GLPI 11 renumbered these vs GLPI 10 (was 4=answer, 8=category, 7=view).
        """
        if not query or len(query) < 2:
            return {"error": "Parametro 'query' obrigatorio (minimo 2 caracteres)."}
        limit = min(max(limit, 1), 50)

        try:
            result = await glpi_client.search(
                "KnowbaseItem",
                criteria=[
                    {"field": 1, "searchtype": "contains", "value": query, "link": "OR"},
                    {"field": 7, "searchtype": "contains", "value": query, "link": "OR"},
                ],
                forcedisplay=["2", "1", "79", "9", "19"],  # id, name, category, views, last_update
                range_limit=limit,
                range_offset=0,
            )
        except Exception as e:
            logger.error(f"search_knowledge GLPI error: {e}")
            return {"articles": [], "query": query, "error": str(e)}

        articles = []
        if isinstance(result, dict) and isinstance(result.get("data"), list):
            for item in result["data"]:
                articles.append(
                    {
                        "id": item.get("2") or item.get("id"),
                        "name": item.get("1") or item.get("name", ""),
                        "category": item.get("79") or item.get("knowbaseitemcategories_id", ""),
                        "views": item.get("9") or item.get("view", 0),
                        "last_update": item.get("19") or item.get("date_mod", ""),
                    }
                )

        total = result.get("totalcount", len(articles)) if isinstance(result, dict) else len(articles)
        return {
            "articles": articles,
            "query": query,
            "count": len(articles),
            "total": total,
        }


bridge_tools = BridgeTools(prompts_catalog=PROMPTS_CATALOG)
