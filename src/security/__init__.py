"""
Security - Write guarantees for the MCP GLPI.

Two complementary modules, both usable independently:

- `idempotency`: at-most-once execution for guarded write calls, backed by an
  in-memory store or by SQLite (survives restarts, coordinates PM2 workers).
- `write_policy`: per-operation authorization plus a global read-only switch.

Both degrade or fail loudly on purpose: idempotency never blocks a write when
its backend is down, while write_policy always blocks when configuration says
so. Neither replaces `src/utils/safety_guard.py`, which asks a human to confirm
destructive calls; see the module docstring in `write_policy` for how the three
layers compose.
"""

from src.security.idempotency import (
    BeginOutcome,
    IdempotencyBackend,
    IdempotencyBackendError,
    IdempotencyConflict,
    IdempotencyError,
    IdempotencyInProgress,
    IdempotencyKey,
    IdempotencyRecord,
    IdempotencyStore,
    MemoryIdempotencyBackend,
    SQLiteIdempotencyBackend,
    build_backend,
    build_store_from_env,
    default_db_path,
    get_idempotency_store,
    mark_replayed,
    payload_fingerprint,
    reset_idempotency_store,
    set_idempotency_store,
)
from src.security.write_policy import (
    DESTRUCTIVE_OPERATIONS,
    PROFILE_ADMINISTRATOR,
    PROFILE_READ_ONLY,
    PROFILE_TICKET_OPERATOR,
    WRITE_ENV_VARS,
    WRITE_OPERATIONS,
    WRITE_PROFILES,
    WriteNotAllowedError,
    WriteOperation,
    WriteOperationSpec,
    WritePolicy,
    WriteProfile,
    get_write_policy,
    operation_env_var,
    require_write_allowed,
    reset_write_policy,
    resolve_operation,
    set_write_policy,
)

__all__ = [
    # idempotency
    "BeginOutcome",
    "IdempotencyBackend",
    "IdempotencyBackendError",
    "IdempotencyConflict",
    "IdempotencyError",
    "IdempotencyInProgress",
    "IdempotencyKey",
    "IdempotencyRecord",
    "IdempotencyStore",
    "MemoryIdempotencyBackend",
    "SQLiteIdempotencyBackend",
    "build_backend",
    "build_store_from_env",
    "default_db_path",
    "get_idempotency_store",
    "mark_replayed",
    "payload_fingerprint",
    "reset_idempotency_store",
    "set_idempotency_store",
    # write policy
    "DESTRUCTIVE_OPERATIONS",
    "PROFILE_ADMINISTRATOR",
    "PROFILE_READ_ONLY",
    "PROFILE_TICKET_OPERATOR",
    "WRITE_ENV_VARS",
    "WRITE_OPERATIONS",
    "WRITE_PROFILES",
    "WriteNotAllowedError",
    "WriteOperation",
    "WriteOperationSpec",
    "WritePolicy",
    "WriteProfile",
    "get_write_policy",
    "operation_env_var",
    "require_write_allowed",
    "reset_write_policy",
    "resolve_operation",
    "set_write_policy",
]
