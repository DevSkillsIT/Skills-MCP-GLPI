"""Minimal async embedding client for query embedding (vLLM | OpenAI | none).

Mirrors the reference embedding contract: OpenAI-compatible /v1/embeddings,
3-attempt full-jitter retry. Only the query is embedded here (search side), so
this is intentionally small. provider=none raises EmbeddingError so the caller
degrades to keyword.
"""

from __future__ import annotations

import asyncio
import secrets
from typing import Literal

import httpx

Provider = Literal["vllm", "openai", "none"]

_HTTP_TOO_MANY = 429
_SERVER_MIN = 500
_CLIENT_MIN = 400
_MAX_ATTEMPTS = 3
_BACKOFF_BASE = 1.5
_MAX_CHARS = 8000


class EmbeddingError(RuntimeError):
    """Embedding endpoint unavailable or failed permanently."""


class QueryEmbedder:
    """Embeds a single query string against the configured provider."""

    def __init__(
        self,
        *,
        provider: Provider,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int,
        timeout: float = 60.0,
    ) -> None:
        self.provider = provider
        self.model = model
        self.dimensions = dimensions
        self._send_dims = provider == "openai"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._headers = headers

    async def embed(self, text: str) -> list[float]:
        if self.provider == "none":
            raise EmbeddingError("embeddings disabled (provider=none)")
        if not self._base_url:
            raise EmbeddingError(f"no base_url for provider '{self.provider}'")
        payload: dict[str, object] = {"model": self.model, "input": [text[:_MAX_CHARS]]}
        if self._send_dims:
            payload["dimensions"] = self.dimensions

        last: Exception | None = None
        async with httpx.AsyncClient(
            base_url=self._base_url, timeout=self._timeout, headers=self._headers
        ) as client:
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    resp = await client.post("/embeddings", json=payload)
                except httpx.RequestError as exc:
                    last = exc
                    if attempt == _MAX_ATTEMPTS:
                        break
                    await self._backoff(attempt)
                    continue
                if resp.status_code >= _SERVER_MIN or resp.status_code == _HTTP_TOO_MANY:
                    last = httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}", request=resp.request, response=resp
                    )
                    if attempt == _MAX_ATTEMPTS:
                        break
                    await self._backoff(attempt)
                    continue
                if resp.status_code >= _CLIENT_MIN:
                    raise EmbeddingError(f"client error {resp.status_code}: {resp.text[:200]}")
                try:
                    vec = resp.json()["data"][0]["embedding"]
                except (KeyError, ValueError, IndexError) as exc:
                    raise EmbeddingError(f"malformed embedding response: {exc}") from exc
                if len(vec) != self.dimensions:
                    raise EmbeddingError(
                        f"unexpected dimension: got {len(vec)}, expected {self.dimensions}"
                    )
                return vec
        raise EmbeddingError(f"embedding failed after {_MAX_ATTEMPTS} attempts: {last}") from last

    async def _backoff(self, attempt: int) -> None:
        base = _BACKOFF_BASE**attempt
        await asyncio.sleep(base + secrets.SystemRandom().uniform(0.0, base / 2))
