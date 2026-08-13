"""
Bridge tools for MCPHub integration.
Exposes MCP resources and prompts as tools for MCPHub compatibility.

SPEC-GLPI-ENHANCE-001/F07 — Section 4.7
"""

from typing import Any, Dict, Optional

from src.resources import GLPI_RESOURCES, list_resources, read_resource
from src.formatters.glpi_formatters import format_resources_list, format_prompts_list
from src.prompts_handlers.prompts import PROMPTS_CATALOG, prompt_handler
from src.formatters.markdown_helpers import strip_html
from src.services.glpi_client import glpi_client
from src.utils.helpers import logger
from src.utils.text_search import describe_stage, run_text_search

#: Longest answer excerpt carried in a search row.
#
# @MX:NOTE: an excerpt, not the article.
# @MX:REASON: enough to tell relevant from irrelevant without opening the
# article, while a full KB answer in every row of a 50-hit page is exactly the
# token explosion this server exists to avoid.
_KB_SNIPPET_MAX = 300


def _kb_snippet(answer: Any) -> str:
    """Reduce a KB answer to a plain-text excerpt.

    GLPI stores the answer as TinyMCE HTML; rendered raw it is mostly markup.
    """
    text = strip_html(str(answer or "")).strip()
    if len(text) <= _KB_SNIPPET_MAX:
        return text
    return text[:_KB_SNIPPET_MAX].rstrip() + "..."


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

        # @MX:NOTE: field 7 (answer) is fetched, not only filtered on.
        # @MX:REASON: the result carried title, category, views and date but no
        # trace of the answer, so deciding whether an article was relevant meant
        # opening every hit -- one round-trip each, to learn what the search was
        # asked to find.
        _KB_TEXT_FIELDS = [1, 7]  # assunto, conteudo

        async def _run(text_groups, fetch_limit):
            result = await glpi_client.search(
                "KnowbaseItem",
                criteria=list(text_groups or []),
                # id, name, category, views, last_update, answer
                forcedisplay=["2", "1", "79", "9", "19", "7"],
                range_limit=fetch_limit,
                range_offset=0,
            )
            data = result.get("data", []) if isinstance(result, dict) else (result or [])
            count = result.get("totalcount") if isinstance(result, dict) else None
            return data, count

        try:
            rows, total, stage, terms = await run_text_search(
                query, _KB_TEXT_FIELDS, _run, limit
            )
        except Exception as e:
            logger.error(f"search_knowledge GLPI error: {e}")
            return {"articles": [], "query": query, "error": str(e)}

        result = {"data": rows, "totalcount": total if total is not None else len(rows)}

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
                        "answer": _kb_snippet(item.get("7") or item.get("answer", "")),
                    }
                )

        total = result.get("totalcount", len(articles)) if isinstance(result, dict) else len(articles)
        return {
            "articles": articles,
            "query": query,
            "count": len(articles),
            "total": total,
            "search_notice": describe_stage(stage, terms, found=bool(articles)),
        }


bridge_tools = BridgeTools(prompts_catalog=PROMPTS_CATALOG)
