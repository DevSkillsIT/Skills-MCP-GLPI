"""Configuration for the knowledge_base ingestion pipeline.

Loaded from environment variables (pydantic-settings, ``SecretStr`` for secrets,
an aggregated ``Settings`` exposed once via ``get_settings``), following the
reference ETL conventions.

Embedding provider selection mirrors the reference design: ``EMBEDDING_PROVIDER``
is one of ``vllm`` | ``openai`` | ``none`` and they are MUTUALLY EXCLUSIVE — there
is no automatic cross-provider fallback, because vectors from different models are
not comparable by cosine similarity. The DB must be indexed with the same model
used at query time; ``embedding_model`` is stored per row so Phase 2 can guard it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["vllm", "openai", "none"]
EmbedStrategy = Literal["full", "form_description"]

# Resolve .env next to this package so config loads regardless of the CWD the
# pipeline is invoked from (e.g. `python -m knowledge_base.ingest_tickets`).
_ENV_FILE = str(Path(__file__).with_name(".env"))

# Both supported models emit 2560-dim vectors (a local vLLM embedding model, or
# OpenAI text-embedding-3-large with dimensions=2560). Keeping the default
# aligned lets a deployment mix sources in the same vector space.
_DEFAULT_DIM = 2560


class PgSettings(BaseSettings):
    """PostgreSQL + pgvector target for the tickets KB."""

    model_config = SettingsConfigDict(env_prefix="PG_", env_file=_ENV_FILE, extra="ignore")

    host: str = "localhost"
    port: int = 5432
    db: str = "glpi_kb"
    user: str = "glpi_kb"
    password: SecretStr = SecretStr("")

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.user}:{self.password.get_secret_value()}"
            f"@{self.host}:{self.port}/{self.db}"
        )


class VllmSettings(BaseSettings):
    """vLLM endpoint (OpenAI-compatible). No hardcoded URL — set in .env."""

    model_config = SettingsConfigDict(env_prefix="VLLM_", env_file=_ENV_FILE, extra="ignore")

    base_url: str = ""
    api_key: SecretStr = SecretStr("")
    model: str = "/model"
    dimensions: int = _DEFAULT_DIM
    timeout: float = 60.0


class OpenAISettings(BaseSettings):
    """OpenAI embeddings endpoint (also OpenAI-compatible)."""

    model_config = SettingsConfigDict(env_prefix="OPENAI_", env_file=_ENV_FILE, extra="ignore")

    base_url: str = "https://api.openai.com/v1"
    api_key: SecretStr = SecretStr("")
    model: str = "text-embedding-3-large"
    dimensions: int = _DEFAULT_DIM
    timeout: float = 60.0


class EmbeddingSettings(BaseSettings):
    """Selects the embedding provider (mutually exclusive: vllm|openai|none)."""

    model_config = SettingsConfigDict(env_prefix="EMBEDDING_", env_file=_ENV_FILE, extra="ignore")

    provider: Provider = "vllm"


class KbSettings(BaseSettings):
    """Knowledge-base shaping knobs: recency, status filter, embed strategy."""

    model_config = SettingsConfigDict(env_prefix="KB_", env_file=_ENV_FILE, extra="ignore")

    # Recency: IT solutions age out. Default 18 months, configurable. Applied at
    # extraction and as a purge of rows that have aged past the window.
    max_age_months: int = 18

    # Only tickets that carry a useful resolution. GLPI status codes:
    # 5 = Solucionado (solved), 6 = Fechado (closed).
    ticket_statuses: str = Field(default="5,6")

    # What text is embedded:
    #   full              -> title + category + description (default; right when
    #                        the ticket title is real signal — most GLPI setups)
    #   form_description  -> only the form's "Descrição" field (for form-driven
    #                        instances where titles are repetitive boilerplate)
    embed_strategy: EmbedStrategy = "full"

    # Identifies the source GLPI instance in the `source` column / metadata.
    source_label: str = "glpi"

    # SSH alias (from ~/.ssh/config) for the GLPI host used during extraction.
    # No default — set per deployment in .env.
    ssh_host: str = ""

    # Path to GLPI's DB config on the remote host; credentials are read there so
    # the DB password never leaves the GLPI server.
    remote_db_config: str = "/etc/glpi/config_db.php"

    @property
    def status_list(self) -> list[int]:
        return [int(s) for s in self.ticket_statuses.split(",") if s.strip()]


class Settings:
    """Aggregated settings; instantiate once per process via ``get_settings``."""

    def __init__(self) -> None:
        self.pg = PgSettings()
        self.kb = KbSettings()
        self.vllm = VllmSettings()
        self.openai = OpenAISettings()
        self.provider: Provider = EmbeddingSettings().provider


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
