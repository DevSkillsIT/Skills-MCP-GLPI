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

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["vllm", "openai", "none"]
EmbedStrategy = Literal["full", "form_description", "problem_solution"]

# Resolve .env next to this package so config loads regardless of the CWD the
# pipeline is invoked from (e.g. `python -m knowledge_base.ingest_tickets`).
# Community/standalone fallback reads the SINGLE root .env (.base-code/.env),
# shared with the MCP — never a per-module .env. Our multi-instance deploy uses
# the central per-instance JSON (GLPI_MCP_CONFIG) instead; see get_settings().
_ENV_FILE = str(Path(__file__).resolve().parents[1] / ".env")

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
    #   form_description  -> only the form's free-text problem field (for
    #                        form-driven instances where titles are boilerplate)
    #   problem_solution  -> problem + resolution (findable by symptom AND fix)
    embed_strategy: EmbedStrategy = "full"

    # Labels of the form field holding the free-text problem. Instance-specific:
    # Formcreator forms name it differently ("Descrição", "Por favor, descreva o
    # problema", ...). Empty = use the built-in defaults.
    description_labels: list[str] = Field(default_factory=list)

    # Fold technician follow-ups into the indexed resolution text. GLPI keeps the
    # fix in a follow-up rather than a formal solution on many tickets.
    include_followups: bool = True

    # Exact secret values to strip from indexed text. Patterns cannot catch a
    # shared password sitting on a line of its own with no label near it.
    redact_literals: list[str] = Field(default_factory=list)

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
    """Aggregated settings. Built from the central per-instance JSON
    (GLPI_MCP_CONFIG -> knowledge_base.{embedding,ingestion}) when present, else
    from environment variables (community / standalone fallback)."""

    def __init__(
        self,
        *,
        pg: PgSettings | None = None,
        vllm: VllmSettings | None = None,
        openai: OpenAISettings | None = None,
        kb: KbSettings | None = None,
        provider: Provider | None = None,
    ) -> None:
        self.pg = pg or PgSettings()
        self.kb = kb or KbSettings()
        self.vllm = vllm or VllmSettings()
        self.openai = openai or OpenAISettings()
        self.provider: Provider = provider or EmbeddingSettings().provider

    @classmethod
    def from_central(cls, data: dict) -> Settings:
        """Build from the MCP's central config: knowledge_base.embedding (shared
        with search) + knowledge_base.ingestion (ETL-specific)."""
        kb = data.get("knowledge_base", {}) or {}
        emb = kb.get("embedding", {}) or {}
        ing = kb.get("ingestion", {}) or {}
        provider: Provider = emb.get("provider", "vllm")
        vllm = VllmSettings(
            base_url=emb.get("base_url", ""),
            api_key=SecretStr(emb.get("api_key", "")),
            model=emb.get("model", "/model"),
            dimensions=int(emb.get("dimensions", 2560)),
        )
        openai = OpenAISettings(
            api_key=SecretStr(emb.get("api_key", "") if provider == "openai" else ""),
            model=emb.get("model", "text-embedding-3-large"),
            dimensions=int(emb.get("dimensions", 2560)),
        )
        pgd = ing.get("pg", {}) or {}
        pg = PgSettings(
            host=pgd.get("host", "localhost"),
            port=int(pgd.get("port", 5432)),
            db=pgd.get("db", "glpi_kb"),
            user=pgd.get("user", "glpi_kb"),
            password=SecretStr(pgd.get("password", "")),
        )
        kbset = KbSettings(
            max_age_months=int(ing.get("max_age_months", 18)),
            ticket_statuses=str(ing.get("ticket_statuses", "5,6")),
            embed_strategy=ing.get("embed_strategy", "full"),
            source_label=ing.get("source_label", "glpi"),
            ssh_host=ing.get("ssh_host", ""),
            remote_db_config=ing.get("remote_db_config", "/etc/glpi/config_db.php"),
            description_labels=list(ing.get("description_labels") or []),
            include_followups=bool(ing.get("include_followups", True)),
            redact_literals=list(ing.get("redact_literals") or []),
        )
        return cls(pg=pg, vllm=vllm, openai=openai, kb=kbset, provider=provider)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Central JSON (GLPI_MCP_CONFIG) with an `ingestion` section wins; otherwise
    the environment fallback (for community/standalone use)."""
    cfg_path = os.environ.get("GLPI_MCP_CONFIG")
    if cfg_path and Path(cfg_path).exists():
        data = json.loads(Path(cfg_path).read_text(encoding="utf-8"))
        if (data.get("knowledge_base") or {}).get("ingestion"):
            return Settings.from_central(data)
    return Settings()
