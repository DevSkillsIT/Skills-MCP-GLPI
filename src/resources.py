"""
MCP Resources for semi-static GLPI data.
Exposes entities, ticket status, categories and priorities as MCP resources.

SPEC-GLPI-ENHANCE-001/F06 — Section 4.6
"""

from src.formatters.glpi_formatters import format_entities_list
from src.formatters.markdown_helpers import (
    TICKET_PRIORITY,
    TICKET_STATUS,
    esc,
)


GLPI_RESOURCES = [
    {
        "uri": "glpi://entities",
        "name": "Entidades GLPI",
        "description": "Lista de entidades (clientes/unidades) cadastradas no GLPI",
        "mimeType": "text/markdown",
        "annotations": {"audience": ["assistant"], "priority": 0.7},
    },
    {
        "uri": "glpi://ticket-status",
        "name": "Status de Ticket",
        "description": "Mapa de codigos de status de ticket GLPI (1=Novo, 2=Atribuido, etc.)",
        "mimeType": "text/markdown",
        "annotations": {"audience": ["assistant"], "priority": 0.8},
    },
    {
        "uri": "glpi://ticket-categories",
        "name": "Categorias de Ticket",
        "description": "Arvore de categorias de ticket configuradas no GLPI",
        "mimeType": "text/markdown",
        "annotations": {"audience": ["assistant"], "priority": 0.5},
    },
    {
        "uri": "glpi://priorities",
        "name": "Prioridades GLPI",
        "description": "Mapa de niveis de prioridade GLPI (1=Muito baixa a 6=Maior)",
        "mimeType": "text/markdown",
        "annotations": {"audience": ["assistant"], "priority": 0.6},
    },
]


def list_resources() -> list:
    """Return list of available MCP resources."""
    return GLPI_RESOURCES


async def read_resource(uri: str, session) -> dict:
    """
    Read a specific MCP resource.
    Uses session for multi-tenant authentication.
    """
    if uri == "glpi://entities":
        entities = await session.get_items("Entity", limit=100)
        text = format_entities_list({"items": entities}, {"limit": 100})
        return {"uri": uri, "mimeType": "text/markdown", "text": text}

    elif uri == "glpi://ticket-status":
        rows = [f"| {code} | {esc(name)} |" for code, name in TICKET_STATUS.items()]
        text = "# Status de Ticket GLPI\n\n| Codigo | Status |\n|---|---|\n" + "\n".join(rows)
        return {"uri": uri, "mimeType": "text/markdown", "text": text}

    elif uri == "glpi://ticket-categories":
        categories = await session.get_items("ITILCategory", limit=100)
        rows = [
            f"| {esc(c.get('id'))} | {esc(c.get('name', 'N/A'))} |"
            for c in (categories or [])
        ]
        text = (
            f"**{len(categories or [])} categorias**\n\n"
            f"| ID | Nome |\n|---|---|\n" + "\n".join(rows)
        )
        return {"uri": uri, "mimeType": "text/markdown", "text": text}

    elif uri == "glpi://priorities":
        rows = [f"| {code} | {esc(name)} |" for code, name in TICKET_PRIORITY.items()]
        text = "# Prioridades GLPI\n\n| Codigo | Prioridade |\n|---|---|\n" + "\n".join(rows)
        return {"uri": uri, "mimeType": "text/markdown", "text": text}

    else:
        raise ValueError(
            f'Resource desconhecido: "{uri}". '
            f"URIs disponiveis: {', '.join(r['uri'] for r in GLPI_RESOURCES)}"
        )
