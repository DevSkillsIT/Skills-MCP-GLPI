"""
MCP Tools Package - Conforme SPEC.md seção 4.2
Implementação das 48 tools MCP organizadas por categoria
"""

from .tickets import ticket_tools
from .assets import asset_tools
from .admin import admin_tools
from .webhooks import webhook_tools

__all__ = [
    "ticket_tools",
    "asset_tools", 
    "admin_tools",
    "webhook_tools"
]

# Versão do pacote
__version__ = "1.0.0"

# Informações sobre as tools
TOOLS_INFO = {
    "total_tools": 48,
    "categories": {
        "tickets": 12,
        "assets": 12,
        "admin": 12,
        "webhooks": 12
    },
    "protocol": "JSON-RPC 2.0",
    "spec_version": "SPEC-GLPI-001"
}

def get_tools_summary():
    """Retorna resumo das tools MCP implementadas."""
    return {
        "version": __version__,
        "tools_info": TOOLS_INFO,
        "exports": __all__
    }
