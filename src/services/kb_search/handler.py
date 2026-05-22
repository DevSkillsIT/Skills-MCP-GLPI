"""Tool entrypoint for glpi_search_knowledge_unified.

Wires the kb_search service into the GLPI MCP tool dispatch: the handler is
called as ``await handler(**arguments)`` and returns ``{"message": markdown}``,
which the dispatch surfaces as the tool's text content.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .service import KbSearchService, format_markdown

logger = logging.getLogger(__name__)

# Load the kb_search .env (DSNs + embedding config) if present, without
# overriding anything already set in the process environment.
_ENV_FILE = Path(__file__).with_name(".env")
try:
    from dotenv import load_dotenv

    if _ENV_FILE.exists():
        load_dotenv(_ENV_FILE, override=False)
except ImportError:  # pragma: no cover - dotenv is a core dependency
    pass

_service: KbSearchService | None = None
_init_error: str | None = None


def _service_or_error() -> KbSearchService | None:
    global _service, _init_error  # noqa: PLW0603 - module-level lazy singleton
    if _service is None and _init_error is None:
        try:
            _service = KbSearchService.from_env()
        except Exception as exc:  # noqa: BLE001 - surface config errors to the caller
            _init_error = str(exc)
            logger.error("kb_search init failed: %s", exc)
    return _service


async def search_knowledge_unified(
    query: str = "", source: str = "all", limit: int = 15,
    tenant: str | None = None, **_kwargs: object
) -> dict[str, str]:
    """Run unified KB search; return {'message': <Markdown table>}."""
    svc = _service_or_error()
    if svc is None:
        return {"message": f"Busca de conhecimento indisponivel (config): {_init_error}"}
    try:
        hits = await svc.search(query=query, source=source, limit=limit, tenant=tenant)
        return {"message": format_markdown(hits)}
    except Exception as exc:  # noqa: BLE001 - never crash the dispatch on a query
        logger.error("kb_search query failed: %s", exc, exc_info=True)
        return {"message": f"Erro na busca de conhecimento do GLPI: {exc}"}
