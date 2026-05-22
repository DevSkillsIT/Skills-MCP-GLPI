"""
Configurações centralizadas do MCP GLPI - Multi-tenant
Suporta carregamento via JSON (GLPI_MCP_CONFIG) ou .env (fallback)
"""

import logging

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


logger = logging.getLogger("mcp-glpi.config")


class Settings(BaseSettings):
    """Configurações da aplicação - suporta JSON multi-tenant e .env."""

    # ============= GLPI Server =============
    glpi_base_url: str = Field(
        default="https://your-glpi-server.example.com", alias="GLPI_BASE_URL"
    )
    glpi_app_token: str = Field(default="", alias="GLPI_APP_TOKEN")
    glpi_user_token: str = Field(default="", alias="GLPI_USER_TOKEN")

    # ============= Client Identity (Multi-tenant) =============
    client_name: str = Field(default="default", alias="CLIENT_NAME")
    client_slug: str = Field(default="default", alias="CLIENT_SLUG")
    client_type: str = Field(default="interno", alias="CLIENT_TYPE")
    client_automation_token: str = Field(default="", alias="CLIENT_AUTOMATION_TOKEN")
    client_require_confirmation: bool = Field(
        default=True, alias="CLIENT_REQUIRE_CONFIRMATION"
    )
    client_log_all_operations: bool = Field(
        default=True, alias="CLIENT_LOG_ALL_OPERATIONS"
    )

    # ============= MCP Server =============
    mcp_port: int = Field(default=8824, alias="MCP_PORT")
    mcp_host: str = Field(default="0.0.0.0", alias="MCP_HOST")

    # ============= Logging =============
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_file: str = Field(
        default="/opt/mcp-servers/_shared/logs/mcp-glpi.log", alias="LOG_FILE"
    )
    log_max_bytes: int = Field(default=10485760, alias="LOG_MAX_BYTES")  # 10MB
    log_backup_count: int = Field(default=5, alias="LOG_BACKUP_COUNT")

    # ============= HTTP Client =============
    connection_timeout: int = Field(default=30, alias="CONNECTION_TIMEOUT")
    request_timeout: int = Field(default=60, alias="REQUEST_TIMEOUT")
    max_connections: int = Field(default=20, alias="MAX_CONNECTIONS")
    max_keepalive_connections: int = Field(
        default=10, alias="MAX_KEEPALIVE_CONNECTIONS"
    )

    # ============= Cache (RNF01) =============
    cache_ttl_seconds: int = Field(default=300, alias="CACHE_TTL_SECONDS")  # 5 minutos
    cache_max_size: int = Field(default=1000, alias="CACHE_MAX_SIZE")
    enable_cache: bool = Field(default=True, alias="ENABLE_CACHE")

    # ============= Rate Limiting (RNF01) =============
    rate_limit_requests_per_minute: int = Field(
        default=60, alias="RATE_LIMIT_REQUESTS_PER_MINUTE"
    )
    rate_limit_burst_size: int = Field(default=10, alias="RATE_LIMIT_BURST_SIZE")
    enable_rate_limiting: bool = Field(default=True, alias="ENABLE_RATE_LIMITING")

    # ============= Response Truncation (RNF01) =============
    response_max_size_bytes: int = Field(
        default=51200, alias="RESPONSE_MAX_SIZE_BYTES"
    )  # 50KB
    enable_response_truncation: bool = Field(
        default=True, alias="ENABLE_RESPONSE_TRUNCATION"
    )

    # ============= Similarity Service (RNF03) =============
    similarity_algorithm: str = Field(
        default="tfidf_cosine", alias="SIMILARITY_ALGORITHM"
    )
    similarity_threshold: float = Field(default=0.3, alias="SIMILARITY_THRESHOLD")
    similarity_max_results: int = Field(default=10, alias="SIMILARITY_MAX_RESULTS")
    pool_workers: int = Field(default=2, alias="POOL_WORKERS")

    # ============= Security (RNF02) =============
    enable_input_sanitization: bool = Field(
        default=True, alias="ENABLE_INPUT_SANITIZATION"
    )
    max_query_length: int = Field(default=1000, alias="MAX_QUERY_LENGTH")
    allowed_html_tags: list = Field(
        default=["p", "br", "strong", "em", "ul", "ol", "li"], alias="ALLOWED_HTML_TAGS"
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
    webhook_secret: str = Field(
        default="default-webhook-secret", alias="WEBHOOK_SECRET"
    )

    # ============= Session Management (RF01) =============
    session_timeout: int = Field(default=3600, alias="SESSION_TIMEOUT")  # 1 hora
    session_cache_ttl: int = Field(default=3600, alias="SESSION_CACHE_TTL")  # 1 hora
    enable_session_management: bool = Field(
        default=True, alias="ENABLE_SESSION_MANAGEMENT"
    )

    # ============= Knowledge Base (unified vector search) =============
    # Centralized config for the glpi_search_knowledge_unified tool: embedding
    # provider + vectorized sources (each exposes the kb_search contract).
    # From the per-instance JSON `knowledge_base` section, or the KNOWLEDGE_BASE
    # env (JSON string) in the .env fallback. None = tool disabled.
    knowledge_base: dict | None = Field(default=None, alias="KNOWLEDGE_BASE")

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
            "pool_workers": self.pool_workers,
        }

    def get_cache_config(self) -> dict:
        """Configurações do cache."""
        return {
            "ttl_seconds": self.cache_ttl_seconds,
            "max_size": self.cache_max_size,
            "enabled": self.enable_cache,
        }

    def get_rate_limit_config(self) -> dict:
        """Configurações de rate limiting."""
        return {
            "requests_per_minute": self.rate_limit_requests_per_minute,
            "burst_size": self.rate_limit_burst_size,
            "enabled": self.enable_rate_limiting,
        }

    def get_truncation_config(self) -> dict:
        """Configurações de truncagem de resposta."""
        return {
            "max_size_bytes": self.response_max_size_bytes,
            "enabled": self.enable_response_truncation,
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

    @classmethod
    def from_json(cls, config_path: str) -> "Settings":
        """Carrega configurações de um arquivo JSON multi-tenant.

        Mapeia a estrutura JSON hierárquica para os campos flat do Settings.
        Mantém compatibilidade total com o carregamento via .env.
        """
        import json
        from pathlib import Path

        config_file = Path(config_path)
        if not config_file.exists():
            raise FileNotFoundError(
                f"Arquivo de configuração não encontrado: {config_path}"
            )

        logger.info(f"Carregando configuração de: {config_path}")

        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Mapear JSON hierárquico para campos flat do Settings
        flat = {}

        # Seção glpi
        glpi = data.get("glpi", {})
        if glpi.get("base_url"):
            flat["GLPI_BASE_URL"] = glpi["base_url"]
        if glpi.get("app_token"):
            flat["GLPI_APP_TOKEN"] = glpi["app_token"]
        if glpi.get("user_token"):
            flat["GLPI_USER_TOKEN"] = glpi["user_token"]

        # Seção http
        http = data.get("http", {})
        if http.get("host"):
            flat["MCP_HOST"] = http["host"]
        if http.get("port"):
            flat["MCP_PORT"] = http["port"]

        # Seção client
        client = data.get("client", {})
        if client.get("name"):
            flat["CLIENT_NAME"] = client["name"]
        if client.get("slug"):
            flat["CLIENT_SLUG"] = client["slug"]
        if client.get("type"):
            flat["CLIENT_TYPE"] = client["type"]
        if client.get("automation_token"):
            flat["CLIENT_AUTOMATION_TOKEN"] = client["automation_token"]
        security = client.get("security", {})
        if "require_confirmation_for_writes" in security:
            flat["CLIENT_REQUIRE_CONFIRMATION"] = security[
                "require_confirmation_for_writes"
            ]
        if "log_all_operations" in security:
            flat["CLIENT_LOG_ALL_OPERATIONS"] = security["log_all_operations"]

        # Seção logging
        log = data.get("logging", {})
        if log.get("level"):
            flat["LOG_LEVEL"] = log["level"]
        if log.get("file"):
            flat["LOG_FILE"] = log["file"]

        # Seção performance
        perf = data.get("performance", {})
        if perf.get("connection_timeout"):
            flat["CONNECTION_TIMEOUT"] = perf["connection_timeout"]
        if perf.get("request_timeout"):
            flat["REQUEST_TIMEOUT"] = perf["request_timeout"]
        if perf.get("pool_workers"):
            flat["POOL_WORKERS"] = perf["pool_workers"]
        if perf.get("rate_limit_rpm"):
            flat["RATE_LIMIT_REQUESTS_PER_MINUTE"] = perf["rate_limit_rpm"]

        # Seção safety
        safety = data.get("safety", {})
        if safety.get("webhook_secret"):
            flat["WEBHOOK_SECRET"] = safety["webhook_secret"]

        # Seção knowledge_base (busca unificada de KB) — passada inteira.
        if data.get("knowledge_base") is not None:
            flat["KNOWLEDGE_BASE"] = data["knowledge_base"]

        logger.info(
            f"Configuração carregada: client={flat.get('CLIENT_NAME', 'unknown')}, port={flat.get('MCP_PORT', '?')}"
        )
        return cls(**flat)


def load_settings() -> Settings:
    """Carrega settings de JSON (GLPI_MCP_CONFIG) ou .env (fallback).

    Prioridade:
    1. Variável de ambiente GLPI_MCP_CONFIG aponta para JSON do cliente
    2. Fallback para .env tradicional (compatibilidade)
    """
    import os

    config_path = os.getenv("GLPI_MCP_CONFIG")
    if config_path:
        return Settings.from_json(config_path)

    logger.info("GLPI_MCP_CONFIG não definido, usando .env (modo legado)")
    return Settings()


# Instância global - carregada automaticamente
settings = load_settings()
