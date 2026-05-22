"""Per-source index/provider embedding-model compatibility guardrail.

Faithful port of the reference ``index-compat.ts``. Each source stores its
``embedding_model``; comparing different models by cosine similarity is
mathematically invalid. This checks the model(s) present in a source against
the configured provider's model. An incompatible source degrades to keyword
ONLY for that source — compatible sources still run hybrid, and cross-source
RRF fuses the valid results (per-source, not a global flag).

Matching heuristic mirrors the reference: exact, substring, or OpenAI-family
("text-embedding*") vs local/custom (everything else).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

Provider = Literal["vllm", "openai", "none"]


def models_match(db_model: str, expected: str, provider: Provider) -> bool:
    if provider == "none":
        return True
    a = db_model.lower().strip()
    b = expected.lower().strip()
    if a == b:
        return True
    if a and b and (b in a or a in b):
        return True
    # Past exact/substring: cross-family (OpenAI text-embedding* vs local) and
    # same-family-different-name are both conservatively rejected.
    return False


@dataclass(slots=True)
class IndexCompatResult:
    compatible: bool
    provider: Provider
    db_models: list[str]
    expected_model: str
    reason: str | None


def check_index_compatibility(
    db_models: Sequence[str | None], provider: Provider, expected_model: str
) -> IndexCompatResult:
    """Decide whether the configured provider can run valid semantic queries
    against the model(s) already present in a source."""
    if provider == "none":
        return IndexCompatResult(True, provider, [], "(no embedding queries)", None)

    models = [m for m in db_models if m]
    if not models:
        # No embedded rows — semantic can't be wrong; treat as compatible.
        return IndexCompatResult(True, provider, [], expected_model, None)

    if any(models_match(m, expected_model, provider) for m in models):
        return IndexCompatResult(True, provider, models, expected_model, None)

    reason = (
        f"Source indexed with [{', '.join(models)}] but provider={provider} would "
        f'query with "{expected_model}". Cross-model cosine is invalid — this source '
        "degrades to keyword."
    )
    return IndexCompatResult(False, provider, models, expected_model, reason)
