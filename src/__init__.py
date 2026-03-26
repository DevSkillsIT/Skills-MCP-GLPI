"""
MCP GLPI - Model Context Protocol server for GLPI ITSM integration.
"""

__version__ = "1.0.0"
__author__ = "Skills IT"
__description__ = "MCP server for GLPI ITSM platform integration"

# Imports condicionais para permitir funcionamento independente do MCP
try:
    from src.main import app
    _has_web_framework = True
except ImportError:
    app = None
    _has_web_framework = False

from src.config import settings
from src.handlers import mcp_handler

# Exportar apenas o que está disponível
__all__ = ["settings", "mcp_handler"]
if _has_web_framework:
    __all__.append("app")
