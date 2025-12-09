"""
Configuração centralizada do MCP GLPI.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
import os
from pathlib import Path


class Settings(BaseSettings):
    """Configurações da aplicação."""

    # GLPI Server
    glpi_base_url: str = Field(
        default="https://suporte.meucomputador.com.br",
        alias="GLPI_BASE_URL"
    )
    glpi_app_token: str = Field(
        default="",
        alias="GLPI_APP_TOKEN"
    )
    glpi_user_token: str = Field(
        default="",
        alias="GLPI_USER_TOKEN"
    )

    # Server
    mcp_port: int = Field(default=8824, alias="MCP_PORT")
    mcp_host: str = Field(default="0.0.0.0", alias="MCP_HOST")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_file: str = Field(
        default="/opt/mcp-servers/_shared/logs/mcp-glpi.log",
        alias="LOG_FILE"
    )

    # Performance
    connection_timeout: int = Field(default=30, alias="CONNECTION_TIMEOUT")
    request_timeout: int = Field(default=60, alias="REQUEST_TIMEOUT")
    pool_workers: int = Field(default=2, alias="POOL_WORKERS")

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"

    @property
    def glpi_headers(self) -> dict:
        """Headers obrigatórios para requisições GLPI conforme documentação oficial."""
        headers = {
            "Content-Type": "application/json",
        }
        # App-Token: identifica a aplicação (fixo no servidor)
        if self.glpi_app_token:
            headers["App-Token"] = self.glpi_app_token
        # Authorization: user_token para autenticação do usuário
        # Nota: Em produção, este token deve vir do cliente MCP (Claude, VSCode, etc.)
        # Por enquanto usa o token configurado no .env para testes
        if self.glpi_user_token:
            headers["Authorization"] = f"user_token {self.glpi_user_token}"
        return headers


# Instância global
settings = Settings()
