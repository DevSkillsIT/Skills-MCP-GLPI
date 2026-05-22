"""Tool entrypoint for glpi_search_knowledge_unified.

Reads its config from the MCP's CENTRAL Settings (the per-instance JSON
`knowledge_base` section, or the `KNOWLEDGE_BASE` env for the .env fallback) —
no per-module .env or sources file. The handler is called as
``await handler(**arguments)`` and returns ``{"message": markdown}``.
"""

from __future__ import annotations

import logging

from .service import KbSearchService, format_markdown

logger = logging.getLogger(__name__)

_service: KbSearchService | None = None
_init_error: str | None = None


def _kb_config() -> dict | None:
    """Pull the knowledge_base section from the central Settings."""
    from src.config.settings import load_settings

    settings = load_settings()
    return getattr(settings, "knowledge_base", None)


def _service_or_error() -> KbSearchService | None:
    global _service, _init_error  # noqa: PLW0603 - module-level lazy singleton
    if _service is None and _init_error is None:
        try:
            cfg = _kb_config()
            if not cfg or not cfg.get("sources"):
                _init_error = "knowledge_base nao configurado (secao ausente no config do MCP)"
            else:
                _service = KbSearchService.from_config(cfg)
        except Exception as exc:  # noqa: BLE001 - surface config errors to the caller
            _init_error = str(exc)
            logger.error("kb_search init failed: %s", exc)
    return _service


async def search_knowledge_unified(
    query: str = "", source: str = "all", limit: int = 15,
    tenant: str | None = None, **_kwargs: object
) -> str:
    """Run unified KB search; return the Markdown table directly.

    Returns a plain string so the central format_tool_response passes it through
    (Case 1) instead of JSON-wrapping a dict envelope.
    """
    svc = _service_or_error()
    if svc is None:
        return f"Busca de conhecimento indisponivel (config): {_init_error}"
    # Enforce the documented minimum query length (schema says "min 2 chars" but
    # nothing validated it — a 1-char query returned semantic noise).
    if not query or len(query.strip()) < 2:
        return "Consulta invalida: informe ao menos 2 caracteres para a busca de conhecimento."
    try:
        hits = await svc.search(query=query, source=source, limit=limit, tenant=tenant)
        return format_markdown(hits)
    except Exception as exc:  # noqa: BLE001 - never crash the dispatch on a query
        logger.error("kb_search query failed: %s", exc, exc_info=True)
        return f"Erro na busca de conhecimento do GLPI: {exc}"
