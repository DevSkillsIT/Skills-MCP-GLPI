"""
Configurações centralizadas do MCP GLPI - Conforme SPEC.md
Estende config.py existente com configurações para serviços modulares
"""

import os
from pathlib import Path

# Import condicional para permitir funcionamento independente
try:
    from pydantic_settings import BaseSettings
    from pydantic import Field
    _HAS_PYDANTIC = True
except ImportError:
    _HAS_PYDANTIC = False
    
    # Fallback simples quando pydantic não está disponível
    class BaseSettings:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)
    
    def Field(default=None, alias=None, **kwargs):
        return default


class Settings(BaseSettings):
    """Configurações da aplicação conforme SPEC.md."""

    # ============= GLPI Server =============
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

    # ============= MCP Server =============
    mcp_port: int = Field(default=8824, alias="MCP_PORT")
    mcp_host: str = Field(default="0.0.0.0", alias="MCP_HOST")

    # ============= Logging =============
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_file: str = Field(
        default="/opt/mcp-servers/_shared/logs/mcp-glpi.log",
        alias="LOG_FILE"
    )
    log_max_bytes: int = Field(default=10485760, alias="LOG_MAX_BYTES")  # 10MB
    log_backup_count: int = Field(default=5, alias="LOG_BACKUP_COUNT")

    # ============= HTTP Client =============
    connection_timeout: int = Field(default=30, alias="CONNECTION_TIMEOUT")
    request_timeout: int = Field(default=60, alias="REQUEST_TIMEOUT")
    max_connections: int = Field(default=20, alias="MAX_CONNECTIONS")
    max_keepalive_connections: int = Field(default=10, alias="MAX_KEEPALIVE_CONNECTIONS")

    # ============= Cache (RNF01) =============
    cache_ttl_seconds: int = Field(default=300, alias="CACHE_TTL_SECONDS")  # 5 minutos
    cache_max_size: int = Field(default=1000, alias="CACHE_MAX_SIZE")
    enable_cache: bool = Field(default=True, alias="ENABLE_CACHE")

    # ============= Rate Limiting (RNF01) =============
    rate_limit_requests_per_minute: int = Field(
        default=60, 
        alias="RATE_LIMIT_REQUESTS_PER_MINUTE"
    )
    rate_limit_burst_size: int = Field(default=10, alias="RATE_LIMIT_BURST_SIZE")
    enable_rate_limiting: bool = Field(default=True, alias="ENABLE_RATE_LIMITING")

    # ============= Response Truncation (RNF01) =============
    response_max_size_bytes: int = Field(
        default=51200, 
        alias="RESPONSE_MAX_SIZE_BYTES"
    )  # 50KB
    enable_response_truncation: bool = Field(
        default=True, 
        alias="ENABLE_RESPONSE_TRUNCATION"
    )

    # ============= Similarity Service (RNF03) =============
    similarity_algorithm: str = Field(
        default="tfidf_cosine",
        alias="SIMILARITY_ALGORITHM"
    )
    similarity_threshold: float = Field(
        default=0.3,
        alias="SIMILARITY_THRESHOLD"
    )
    similarity_max_results: int = Field(
        default=10,
        alias="SIMILARITY_MAX_RESULTS"
    )
    pool_workers: int = Field(default=2, alias="POOL_WORKERS")

    # ============= Security (RNF02) =============
    enable_input_sanitization: bool = Field(
        default=True,
        alias="ENABLE_INPUT_SANITIZATION"
    )
    max_query_length: int = Field(default=1000, alias="MAX_QUERY_LENGTH")
    allowed_html_tags: list = Field(
        default=["p", "br", "strong", "em", "ul", "ol", "li"],
        alias="ALLOWED_HTML_TAGS"
    )

    # ============= Pagination =============
    default_limit: int = Field(default=250, alias="DEFAULT_LIMIT")
    max_limit: int = Field(default=1000, alias="MAX_LIMIT")
    default_offset: int = Field(default=0, alias="DEFAULT_OFFSET")

    # ============= Webhooks =============
    webhook_timeout: int = Field(default=30, alias="WEBHOOK_TIMEOUT")
    webhook_retry_attempts: int = Field(default=3, alias="WEBHOOK_RETRY_ATTEMPTS")
    webhook_retry_delay: int = Field(default=5, alias="WEBHOOK_RETRY_DELAY")
    enable_webhooks: bool = Field(default=True, alias="ENABLE_WEBHOOKS")
    webhook_secret: str = Field(default="default-webhook-secret", alias="WEBHOOK_SECRET")

    # ============= Session Management (RF01) =============
    session_timeout: int = Field(default=3600, alias="SESSION_TIMEOUT")  # 1 hora
    session_cache_ttl: int = Field(default=3600, alias="SESSION_CACHE_TTL")  # 1 hora
    enable_session_management: bool = Field(
        default=True,
        alias="ENABLE_SESSION_MANAGEMENT"
    )

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
        if self.glpi_user_token:
            headers["Authorization"] = f"user_token {self.glpi_user_token}"
        return headers

    @property
    def glpi_api_url(self) -> str:
        """URL base da API GLPI."""
        return f"{self.glpi_base_url}/apirest.php"

    def get_similarity_config(self) -> dict:
        """Configurações do serviço de similaridade."""
        return {
            "algorithm": self.similarity_algorithm,
            "threshold": self.similarity_threshold,
            "max_results": self.similarity_max_results,
            "pool_workers": self.pool_workers
        }

    def get_cache_config(self) -> dict:
        """Configurações do cache."""
        return {
            "ttl_seconds": self.cache_ttl_seconds,
            "max_size": self.cache_max_size,
            "enabled": self.enable_cache
        }

    def get_rate_limit_config(self) -> dict:
        """Configurações de rate limiting."""
        return {
            "requests_per_minute": self.rate_limit_requests_per_minute,
            "burst_size": self.rate_limit_burst_size,
            "enabled": self.enable_rate_limiting
        }

    def get_truncation_config(self) -> dict:
        """Configurações de truncagem de resposta."""
        return {
            "max_size_bytes": self.response_max_size_bytes,
            "enabled": self.enable_response_truncation
        }

    # ============= Property Aliases for Backward Compatibility =============
    @property
    def default_page_size(self) -> int:
        """Alias para default_limit - compatibilidade com código existente."""
        return self.default_limit
    
    @property
    def max_response_size(self) -> int:
        """Alias para response_max_size_bytes - compatibilidade com código existente."""
        return self.response_max_size_bytes
    
    @property
    def similarity_max_workers(self) -> int:
        """Alias para pool_workers - compatibilidade com código existente."""
        return self.pool_workers
    
    @property
    def similarity_max_items(self) -> int:
        """Alias para similarity_max_results - compatibilidade com código existente."""
        return self.similarity_max_results


# Instância global
settings = Settings()
