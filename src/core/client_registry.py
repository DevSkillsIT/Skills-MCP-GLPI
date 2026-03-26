"""
Registry central de clientes GLPI configurados.
Permite descoberta e validação cross-instância.
Espelha o padrão do AD MCP (ClientRegistry).
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mcp-glpi.registry")

DEFAULT_REGISTRY_PATH = "/opt/mcp-servers/_shared/configs/glpi-clients-registry.json"


class ClientRegistry:
    """Gerencia registry central de clientes com GLPI configurado."""

    def __init__(self, registry_path: Optional[str] = None) -> None:
        self.registry_path = registry_path or DEFAULT_REGISTRY_PATH
        self._registry_data: Optional[Dict] = None
        self._load_registry()

    def _load_registry(self) -> None:
        """Carrega registry do arquivo JSON."""
        try:
            if os.path.exists(self.registry_path):
                with open(self.registry_path, "r", encoding="utf-8") as f:
                    self._registry_data = json.load(f)
                clients = self.get_all_clients()
                logger.info(f"Client registry carregado: {len(clients)} clientes")
            else:
                logger.warning(f"Client registry não encontrado: {self.registry_path}")
                self._registry_data = {"clients": {}, "aliases": {}}
        except Exception as e:
            logger.error(f"Erro ao carregar client registry: {e}")
            self._registry_data = {"clients": {}, "aliases": {}}

    def get_all_clients(self) -> Dict[str, Dict[str, Any]]:
        """Retorna todos os clientes configurados."""
        return self._registry_data.get("clients", {})

    def get_active_clients(self) -> Dict[str, Dict[str, Any]]:
        """Retorna apenas clientes ativos."""
        return {
            slug: data
            for slug, data in self.get_all_clients().items()
            if data.get("active", True)
        }

    def get_client(self, slug_or_name: str) -> Optional[Dict[str, Any]]:
        """Busca cliente por slug ou nome/alias."""
        normalized = slug_or_name.lower().strip()
        clients = self.get_all_clients()

        # Busca direta por slug
        if normalized in clients:
            return {**clients[normalized], "slug": normalized}

        # Busca por alias
        aliases = self._registry_data.get("aliases", {})
        if normalized in aliases:
            resolved_slug = aliases[normalized]
            if resolved_slug in clients:
                return {**clients[resolved_slug], "slug": resolved_slug}

        # Busca parcial por nome
        for slug, data in clients.items():
            client_name = data.get("name", "").lower()
            if normalized in client_name or client_name in normalized:
                return {**data, "slug": slug}

        return None

    def client_exists(self, slug_or_name: str) -> bool:
        """Verifica se um cliente tem GLPI configurado."""
        return self.get_client(slug_or_name) is not None

    def resolve_client_slug(self, slug_or_name: str) -> Optional[str]:
        """Resolve nome/alias para slug correto."""
        client = self.get_client(slug_or_name)
        return client.get("slug") if client else None

    def list_client_names(self) -> List[str]:
        """Retorna lista de nomes de clientes para exibição."""
        return [
            f"{data.get('name')} ({slug})"
            for slug, data in self.get_active_clients().items()
        ]


# Singleton do registry
_registry_instance: Optional[ClientRegistry] = None


def get_client_registry() -> ClientRegistry:
    """Retorna instância singleton do ClientRegistry."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = ClientRegistry()
    return _registry_instance
