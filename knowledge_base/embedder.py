"""Embedding clients for the knowledge_base pipeline.

Mirrors the reference ``embeddings.ts`` design: three mutually-exclusive
providers selected by ``EMBEDDING_PROVIDER`` via :func:`build_embedding_client`.

- ``VllmEmbeddingClient``  — production client (OpenAI-compatible /v1/embeddings).
- ``OpenAIEmbeddingClient`` — OpenAI embeddings (sends explicit ``dimensions``);
  requires ``OPENAI_API_KEY``. Cross-model vectors are NOT comparable to vLLM's
  by cosine similarity, so providers never fall back to one another — the DB is
  indexed with one model and queried with the same one.
- ``NullEmbeddingClient`` — for ``EMBEDDING_PROVIDER=none``: embeddings disabled.
  During ingestion this means rows are stored text-only (FTS still works); at
  search time (Phase 2) hybrid degrades to keyword.

Both HTTP providers speak the OpenAI ``/v1/embeddings`` shape, so they share one
async base with retries (full-jitter backoff), dimension validation and
char-budget truncation.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Sequence

import httpx
import structlog

from .settings import Settings, get_settings

log = structlog.get_logger(__name__)

_HTTP_TOO_MANY = 429
_HTTP_CLIENT_ERROR_MIN = 400
_HTTP_SERVER_ERROR_MIN = 500

# Embedding-model context ceilings are a few thousand tokens; in PT-BR technical
# text the tokens/char ratio reaches ~0.34, so 8000 chars stays under budget with
# margin. Truncation happens ONLY at the embedding boundary — the full text stays
# in PostgreSQL for FTS and for re-embedding under a larger model later.
_MAX_EMBED_CHARS = 8000


class EmbeddingError(RuntimeError):
    """Raised when the embedding endpoint fails permanently."""


class EmbeddingTooLongError(EmbeddingError):
    """Input exceeds model context even after truncation; caller may skip it."""


class _HttpEmbeddingClient:
    """Shared async client for OpenAI-compatible /v1/embeddings endpoints."""

    _MAX_ATTEMPTS = 3
    _BACKOFF_BASE = 1.5

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int,
        timeout: float,
        send_dimensions: bool,
    ) -> None:
        self._model = model
        self._dimensions = dimensions
        self._send_dimensions = send_dimensions
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout, headers=headers
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):  # noqa: ANN204 - returns self subtype
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        payload: dict[str, object] = {
            "model": self._model,
            "input": [self._truncate(t) for t in texts],
        }
        if self._send_dimensions:
            payload["dimensions"] = self._dimensions

        last_error: Exception | None = None
        for attempt in range(1, self._MAX_ATTEMPTS + 1):
            try:
                resp = await self._client.post("/embeddings", json=payload)
            except httpx.RequestError as exc:
                last_error = exc
                if not self._should_retry(attempt, str(exc)):
                    break
                await self._sleep_backoff(attempt)
                continue

            status = resp.status_code
            if status >= _HTTP_SERVER_ERROR_MIN or status == _HTTP_TOO_MANY:
                last_error = httpx.HTTPStatusError(
                    f"embedding endpoint returned {status}",
                    request=resp.request,
                    response=resp,
                )
                if not self._should_retry(attempt, f"HTTP {status}"):
                    break
                await self._sleep_backoff(attempt)
                continue

            if status >= _HTTP_CLIENT_ERROR_MIN:
                snippet = resp.text[:200]
                if "maximum context length" in resp.text:
                    raise EmbeddingTooLongError(f"context-length exceeded: {snippet}")
                raise EmbeddingError(f"client error {status}: {snippet}")

            try:
                data = resp.json()
                vectors = [item["embedding"] for item in data["data"]]
            except (KeyError, ValueError) as exc:
                raise EmbeddingError(f"malformed embedding response: {exc}") from exc

            self._validate_dims(vectors)
            log.debug("embeddings.ok", count=len(vectors), model=self._model)
            return vectors

        raise EmbeddingError(
            f"embedding failed after {self._MAX_ATTEMPTS} attempts: {last_error}"
        ) from last_error

    def _should_retry(self, attempt: int, reason: str) -> bool:
        if attempt >= self._MAX_ATTEMPTS:
            return False
        log.warning("embeddings.retry", attempt=attempt, error=reason)
        return True

    async def _sleep_backoff(self, attempt: int) -> None:
        base_delay = self._BACKOFF_BASE**attempt
        jitter = secrets.SystemRandom().uniform(0.0, base_delay / 2)
        await asyncio.sleep(base_delay + jitter)

    def _truncate(self, text: str) -> str:
        if len(text) <= _MAX_EMBED_CHARS:
            return text
        log.debug("embeddings.truncated", original=len(text), kept=_MAX_EMBED_CHARS)
        return text[:_MAX_EMBED_CHARS]

    def _validate_dims(self, vectors: list[list[float]]) -> None:
        for v in vectors:
            if len(v) != self._dimensions:
                raise EmbeddingError(
                    f"unexpected embedding dimension: got {len(v)}, expected {self._dimensions}"
                )


class VllmEmbeddingClient(_HttpEmbeddingClient):
    """vLLM embedding endpoint (OpenAI-compatible). Dimension is fixed by the
    served model, so the ``dimensions`` param is not sent."""

    def __init__(self, settings: Settings) -> None:
        cfg = settings.vllm
        if not cfg.base_url:
            raise EmbeddingError("VLLM_BASE_URL not set (EMBEDDING_PROVIDER=vllm)")
        super().__init__(
            base_url=cfg.base_url,
            api_key=cfg.api_key.get_secret_value(),
            model=cfg.model,
            dimensions=cfg.dimensions,
            timeout=cfg.timeout,
            send_dimensions=False,
        )


class OpenAIEmbeddingClient(_HttpEmbeddingClient):
    """OpenAI embeddings (text-embedding-3-* honor an explicit output dimension).
    Requires OPENAI_API_KEY."""

    def __init__(self, settings: Settings) -> None:
        cfg = settings.openai
        if not cfg.api_key.get_secret_value():
            raise EmbeddingError(
                "OPENAI_API_KEY not set (EMBEDDING_PROVIDER=openai). "
                "Set it in .env or choose EMBEDDING_PROVIDER=vllm."
            )
        super().__init__(
            base_url=cfg.base_url,
            api_key=cfg.api_key.get_secret_value(),
            model=cfg.model,
            dimensions=cfg.dimensions,
            timeout=cfg.timeout,
            send_dimensions=True,
        )


class NullEmbeddingClient:
    """EMBEDDING_PROVIDER=none: embeddings disabled. Rows are stored text-only
    (FTS still works); the orchestrator skips the embed step for this client."""

    enabled = False

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> NullEmbeddingClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def embed(self, text: str) -> list[float]:  # noqa: ARG002 - interface parity
        raise EmbeddingError("embeddings disabled (EMBEDDING_PROVIDER=none)")


# Anything with an async ``embed`` + ``close`` + context-manager protocol.
EmbeddingClient = _HttpEmbeddingClient | NullEmbeddingClient


def build_embedding_client(settings: Settings | None = None) -> EmbeddingClient:
    """Factory: build the client for the configured EMBEDDING_PROVIDER.

    Providers are mutually exclusive — the DB must be indexed and queried with
    the same model (cross-model cosine similarity is invalid)."""
    cfg = settings if settings is not None else get_settings()
    if cfg.provider == "vllm":
        return VllmEmbeddingClient(cfg)
    if cfg.provider == "openai":
        return OpenAIEmbeddingClient(cfg)
    return NullEmbeddingClient()
