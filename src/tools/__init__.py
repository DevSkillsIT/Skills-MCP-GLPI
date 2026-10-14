"""
MCP Tools Package - Conforme SPEC.md seção 4.2
Pacote das implementações de tools; o catálogo exposto vem de src/handlers.py
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

# Versão do pacote: a mesma do servidor (fonte única em src/__init__.py)
from src import __version__
