"""Refuse arguments an operation would silently ignore.

A declared parameter that the chosen action does not apply used to be dropped and the call
answered plain success, so "mudar o grupo do usuario" looked done when nothing happened.
"""

from typing import Any, Iterable, Mapping

from src.models.exceptions import ValidationError


def refuse_inapplicable(
    context: str,
    provided: Mapping[str, Any],
    allowed: Iterable[str] = (),
    create_only: Iterable[str] = (),
) -> None:
    """Raise ValidationError naming every provided field the operation would ignore.

    Args:
        context: What is being done, e.g. "update de users".
        provided: Candidate arguments; a value of None means "not provided".
        allowed: Fields the operation applies.
        create_only: Fields that are valid only on create (they get a tailored message).
    """
    allowed_set = set(allowed)
    create_only_set = set(create_only)
    refused = [
        name for name, value in provided.items()
        if value is not None and name not in allowed_set
    ]
    if not refused:
        return
    parts = []
    for name in refused:
        if name in create_only_set:
            parts.append(f"'{name}' so vale em action=create")
        else:
            parts.append(f"'{name}' nao se aplica a {context}")
    raise ValidationError(
        f"Argumento(s) que {context} ignoraria: " + "; ".join(parts)
        + ". Remova-os da chamada: ignorados em silencio, ela pareceria bem-sucedida.",
        refused[0],
    )
