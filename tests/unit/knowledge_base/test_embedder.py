"""Unit tests for embedding-provider selection (no network)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from knowledge_base.embedder import (
    EmbeddingError,
    NullEmbeddingClient,
    OpenAIEmbeddingClient,
    VllmEmbeddingClient,
    build_embedding_client,
)


def _settings(provider: str, *, vllm_url: str = "", openai_key: str = ""):
    return SimpleNamespace(
        provider=provider,
        vllm=SimpleNamespace(
            base_url=vllm_url, api_key=SecretStr(""), model="/model",
            dimensions=2560, timeout=60.0,
        ),
        openai=SimpleNamespace(
            base_url="https://api.openai.com/v1", api_key=SecretStr(openai_key),
            model="text-embedding-3-large", dimensions=2560, timeout=60.0,
        ),
    )


def test_none_provider_returns_null_client() -> None:
    client = build_embedding_client(_settings("none"))
    assert isinstance(client, NullEmbeddingClient)


def test_vllm_provider_builds_client() -> None:
    client = build_embedding_client(_settings("vllm", vllm_url="http://vllm:8090/v1"))
    assert isinstance(client, VllmEmbeddingClient)


def test_vllm_without_base_url_raises() -> None:
    with pytest.raises(EmbeddingError, match="VLLM_BASE_URL"):
        build_embedding_client(_settings("vllm", vllm_url=""))


def test_openai_provider_builds_client_with_key() -> None:
    client = build_embedding_client(_settings("openai", openai_key="sk-test"))
    assert isinstance(client, OpenAIEmbeddingClient)


def test_openai_without_key_raises() -> None:
    with pytest.raises(EmbeddingError, match="OPENAI_API_KEY"):
        build_embedding_client(_settings("openai", openai_key=""))


@pytest.mark.asyncio
async def test_null_client_embed_raises() -> None:
    client = NullEmbeddingClient()
    with pytest.raises(EmbeddingError):
        await client.embed("anything")
