"""
Gerenciador de segurança multi-tenant para MCP GLPI.
Identifica cliente, valida tokens de automação e controla operações de escrita.
Espelha o padrão do AD MCP (ClientSecurityManager).
"""

import logging
import secrets
from typing import Any, Dict, Optional

logger = logging.getLogger("mcp-glpi.security")


class ClientSecurityManager:
    """Gerencia identificação e segurança do cliente para MCP GLPI multi-tenant."""

    def __init__(self, settings) -> None:
        """Inicializa a partir do objeto Settings."""
        self.client_name: str = settings.client_name
        self.client_slug: str = settings.client_slug
        self.client_type: str = settings.client_type
        self.glpi_base_url: str = settings.glpi_base_url
        self.automation_token: str = settings.client_automation_token
        self.require_confirmation_for_writes: bool = (
            settings.client_require_confirmation
        )
        self.log_all_operations: bool = settings.client_log_all_operations

        logger.info(
            f"Client security inicializado: {self.client_name} ({self.client_slug})"
        )

    def get_client_info(self) -> Dict[str, Any]:
        """Retorna informações do cliente/tenant desta instância."""
        return {
            "client": {
                "name": self.client_name,
                "slug": self.client_slug,
                "type": self.client_type,
            },
            "glpi": {
                "base_url": self.glpi_base_url,
            },
            "security": {
                "require_confirmation_for_writes": self.require_confirmation_for_writes,
                "has_automation_token": bool(self.automation_token),
            },
            "warning": (
                f"ATENCAO: Operacoes afetam o GLPI do cliente "
                f"{self.client_name.upper()} ({self.glpi_base_url})"
            ),
        }

    def validate_automation_token(self, token: Optional[str]) -> bool:
        """Valida token de automação usando comparação constant-time."""
        if not self.automation_token or not token:
            return False
        return secrets.compare_digest(token, self.automation_token)

    def check_write_permission(
        self,
        operation: str,
        target: str,
        automation_token: Optional[str] = None,
        client_confirmation: Optional[str] = None,
    ) -> dict:
        """Verifica se operação de escrita é permitida.

        Returns:
            dict com 'permitted' (bool) e 'message'.
        """
        # Token de automação válido -> permite
        if automation_token and self.validate_automation_token(automation_token):
            logger.info(
                f"Operação '{operation}' em '{target}' autorizada via automation token"
            )
            return {"permitted": True, "mode": "automation_token"}

        # Confirmação manual do cliente -> permite
        if (
            client_confirmation
            and client_confirmation.lower() == self.client_slug.lower()
        ):
            logger.info(
                f"Operação '{operation}' em '{target}' autorizada via confirmação"
            )
            return {"permitted": True, "mode": "confirmed"}

        # Confirmação necessária -> nega
        if self.require_confirmation_for_writes:
            return {
                "permitted": False,
                "mode": "requires_confirmation",
                "message": (
                    f"Operação de escrita requer confirmação ou automation token. "
                    f"Envie client_confirmation='{self.client_slug}' para confirmar."
                ),
                "client": self.client_slug,
            }

        # Sem confirmação necessária -> permite
        return {"permitted": True, "mode": "no_confirmation_required"}


def init_security_manager(settings) -> ClientSecurityManager:
    """Inicializa o ClientSecurityManager a partir do Settings."""
    return ClientSecurityManager(settings)
