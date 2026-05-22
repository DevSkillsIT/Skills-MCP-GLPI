"""Unit tests: ETL central-config loader (Settings.from_central)."""

from __future__ import annotations

from knowledge_base.settings import Settings


def _central() -> dict:
    return {
        "knowledge_base": {
            "embedding": {
                "provider": "vllm", "base_url": "http://v:8090/v1",
                "api_key": "secret", "model": "/model", "dimensions": 2560,
            },
            "sources": [{"name": "x", "label": "X"}],  # search-side, ignored by ETL
            "ingestion": {
                "pg": {"host": "h", "port": 5433, "db": "glpi_ramada_kb",
                       "user": "u", "password": "p"},
                "source_label": "ramada",
                "ssh_host": "glpi-ramada",
                "remote_db_config": "/etc/glpi/config_db.php",
                "ticket_statuses": "5,6",
                "max_age_months": 12,
                "embed_strategy": "form_description",
            },
        }
    }


class TestFromCentral:
    def test_parses_embedding(self) -> None:
        s = Settings.from_central(_central())
        assert s.provider == "vllm"
        assert s.vllm.base_url == "http://v:8090/v1"
        assert s.vllm.api_key.get_secret_value() == "secret"
        assert s.vllm.dimensions == 2560

    def test_parses_ingestion_pg_and_knobs(self) -> None:
        s = Settings.from_central(_central())
        assert s.pg.host == "h" and s.pg.port == 5433 and s.pg.db == "glpi_ramada_kb"
        assert s.pg.password.get_secret_value() == "p"
        assert s.kb.source_label == "ramada" and s.kb.ssh_host == "glpi-ramada"
        assert s.kb.max_age_months == 12 and s.kb.embed_strategy == "form_description"
        assert s.kb.status_list == [5, 6]

    def test_openai_provider(self) -> None:
        cfg = _central()
        cfg["knowledge_base"]["embedding"]["provider"] = "openai"
        s = Settings.from_central(cfg)
        assert s.provider == "openai"
        assert s.openai.api_key.get_secret_value() == "secret"

    def test_empty_uses_defaults(self) -> None:
        s = Settings.from_central({})
        assert s.provider == "vllm" and s.kb.max_age_months == 18
