"""
MCP GLPI - Model Context Protocol server for GLPI ITSM integration.
"""

# Single source of truth for the server version: serverInfo (initialize), /health
# and the FastAPI app all read it. Bump it together with the CHANGELOG release.
__version__ = "2.2.0"
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
