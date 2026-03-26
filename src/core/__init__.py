"""
Core - Módulos multi-tenant do MCP GLPI.
"""

from src.core.client_security import ClientSecurityManager, init_security_manager
from src.core.client_registry import ClientRegistry, get_client_registry

__all__ = [
    "ClientSecurityManager",
    "init_security_manager",
    "ClientRegistry",
    "get_client_registry",
]
