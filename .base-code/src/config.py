"""
Configuração centralizada do MCP GLPI.
Re-exporta settings do módulo config/ para compatibilidade.
"""

from src.config.settings import settings

__all__ = ["settings"]
