"""
Idempotency store for GLPI MCP write operations.

Why this exists
---------------
This MCP is driven by AI agents. When the client times out, reconnects, or the
model simply repeats a tool call, a "create" runs twice and a second ticket (or
a duplicated follow-up) shows up in GLPI. The server also runs as two PM2
instances, so a purely in-process guard cannot see a retry that lands on the
other worker.

The store therefore answers three questions for every guarded call:

1. Was this exact call already executed?      -> replay the stored result.
2. Is this key already running somewhere?     -> wait instead of running twice.
3. Is this key being reused with a different  -> raise a conflict instead of
   payload?                                      silently returning stale data.

Backends
--------
`MemoryIdempotencyBackend` keeps everything in the process (single worker,
tests). `SQLiteIdempotencyBackend` persists to a file so state survives a
restart and coordinates between the PM2 workers through SQLite's own locking
(``BEGIN IMMEDIATE`` + WAL).

Graceful degradation
--------------------
Idempotency is a safety net, never a dependency. If the backend is unreachable
(read-only filesystem, corrupt database, locked file) the store logs a warning
and runs the business operation anyway. Losing de-duplication is bad; refusing
to open a ticket because a bookkeeping database is down is worse. The only
error that is allowed to escape is `IdempotencyConflict`, which is a caller
mistake and not a backend failure.

Relationship with other guards
------------------------------
This module answers "did this already happen?". It does not decide whether the
caller may write at all -- that is `src/security/write_policy.py` -- and it does
not ask a human for confirmation -- that is `src/utils/safety_guard.py`.

Configuration (environment only, never reads .env or credentials):
    GLPI_IDEMPOTENCY_ENABLED        default "true"
    GLPI_IDEMPOTENCY_BACKEND        default "sqlite" ("sqlite" | "memory" | "none")
    GLPI_IDEMPOTENCY_DB_PATH        default "<root>/var/idempotency/store.sqlite3"
    GLPI_IDEMPOTENCY_NAMESPACE      default "default"
    GLPI_IDEMPOTENCY_TTL_SECONDS    default 86400 (24h)
    GLPI_IDEMPOTENCY_LEASE_SECONDS  default 60
    GLPI_IDEMPOTENCY_WAIT_TIMEOUT   default 30
    GLPI_IDEMPOTENCY_POLL_INTERVAL  default 0.25
    GLPI_IDEMPOTENCY_PURGE_INTERVAL default 300
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Mapping, Optional

from src.models.exceptions import GLPIError

logger = logging.getLogger("mcp-glpi.security.idempotency")


# ---------------------------------------------------------------------------
# Environment variable contract
# ---------------------------------------------------------------------------

ENV_ENABLED = "GLPI_IDEMPOTENCY_ENABLED"
ENV_BACKEND = "GLPI_IDEMPOTENCY_BACKEND"
ENV_DB_PATH = "GLPI_IDEMPOTENCY_DB_PATH"
ENV_NAMESPACE = "GLPI_IDEMPOTENCY_NAMESPACE"
ENV_TTL_SECONDS = "GLPI_IDEMPOTENCY_TTL_SECONDS"
ENV_LEASE_SECONDS = "GLPI_IDEMPOTENCY_LEASE_SECONDS"
ENV_WAIT_TIMEOUT = "GLPI_IDEMPOTENCY_WAIT_TIMEOUT"
ENV_POLL_INTERVAL = "GLPI_IDEMPOTENCY_POLL_INTERVAL"
ENV_PURGE_INTERVAL = "GLPI_IDEMPOTENCY_PURGE_INTERVAL"

DEFAULT_ENABLED = True
DEFAULT_BACKEND = "sqlite"
DEFAULT_NAMESPACE = "default"
DEFAULT_TTL_SECONDS = 86400.0
DEFAULT_LEASE_SECONDS = 60.0
DEFAULT_WAIT_TIMEOUT = 30.0
DEFAULT_POLL_INTERVAL = 0.25
DEFAULT_PURGE_INTERVAL = 300.0

#: Key added to replayed dict results so the caller (and the model) can tell a
#: cached answer from a freshly executed one.
REPLAY_FLAG = "replayed"

_TRUTHY = frozenset({"1", "true", "t", "yes", "y", "on", "sim"})
_FALSY = frozenset({"0", "false", "f", "no", "n", "off", "nao"})

# Entry lifecycle states.
STATE_IN_PROGRESS = "in_progress"
STATE_COMPLETED = "completed"

# `begin()` outcomes.
OUTCOME_EXECUTE = "execute"
OUTCOME_REPLAY = "replay"
OUTCOME_IN_PROGRESS = "in_progress"


def _project_root() -> Path:
    """Return the repository root (two levels above src/security/)."""
    return Path(__file__).resolve().parent.parent.parent


def default_db_path() -> Path:
    """Default SQLite location.

    ``var/`` is already covered by the repository .gitignore, so the state file
    never shows up as an untracked artifact.
    """
    return _project_root() / "var" / "idempotency" / "store.sqlite3"


def _env_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    logger.warning(
        "Invalid boolean for %s=%r; falling back to default %r", name, raw, default
    )
    return default


def _env_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw.strip())
    except (TypeError, ValueError):
        logger.warning(
            "Invalid number for %s=%r; falling back to default %r", name, raw, default
        )
        return default
    if value <= 0:
        logger.warning(
            "Non-positive value for %s=%r; falling back to default %r",
            name,
            raw,
            default,
        )
        return default
    return value


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class IdempotencyError(GLPIError):
    """Base class for idempotency failures."""


class IdempotencyConflict(IdempotencyError):
    """Same idempotency key replayed with a different payload.

    This is never swallowed: returning the previous result for a different
    payload would silently drop the caller's new data.
    """

    def __init__(self, operation: str, key: str) -> None:
        super().__init__(
            409,
            (
                f"Chave de idempotencia '{key}' ja foi usada na operacao "
                f"'{operation}' com um conteudo diferente. Use uma chave nova "
                f"para uma requisicao nova, ou reenvie exatamente o mesmo "
                f"conteudo para receber o resultado anterior."
            ),
            {"operation": operation, "key": key, "reason": "payload_mismatch"},
        )


class IdempotencyInProgress(IdempotencyError):
    """Another worker holds the lease and did not finish before the timeout."""

    def __init__(self, operation: str, key: str, waited_seconds: float) -> None:
        super().__init__(
            409,
            (
                f"A operacao '{operation}' com a chave '{key}' ja esta em "
                f"execucao em outro processo e nao terminou em "
                f"{waited_seconds:.0f}s. Aguarde e consulte o resultado antes "
                f"de tentar de novo."
            ),
            {
                "operation": operation,
                "key": key,
                "reason": "lease_held",
                "waited_seconds": waited_seconds,
            },
        )


class IdempotencyBackendError(IdempotencyError):
    """Storage-level failure. Always degraded into a normal execution."""

    def __init__(self, message: str) -> None:
        super().__init__(503, message, {"reason": "backend_unavailable"})


# ---------------------------------------------------------------------------
# Payload fingerprinting
# ---------------------------------------------------------------------------


def _canonicalize(value: Any) -> Any:
    """Reduce a payload to a deterministic, JSON-encodable shape.

    Dict ordering, tuples vs lists and set ordering must not change the
    fingerprint; anything exotic degrades to its string form so the function
    never raises on unexpected input.
    """
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {
            str(k): _canonicalize(v)
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, (set, frozenset)):
        return sorted((_canonicalize(v) for v in value), key=repr)
    if isinstance(value, (list, tuple)):
        return [_canonicalize(v) for v in value]
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return str(value)


def payload_fingerprint(
    payload: Any, *, exclude: Optional[Iterable[str]] = None
) -> str:
    """Stable SHA-256 of a payload.

    Args:
        payload: Any value. Dicts are the common case (tool kwargs).
        exclude: Top-level dict keys to ignore, for volatile fields such as
            timestamps or the idempotency key itself.

    Returns:
        Hex digest. Equal payloads always produce equal digests.
    """
    data = payload
    if exclude and isinstance(payload, Mapping):
        skip = set(exclude)
        data = {k: v for k, v in payload.items() if k not in skip}
    canonical = _canonicalize(data)
    encoded = json.dumps(
        canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IdempotencyKey:
    """Composite identity of a guarded call.

    `namespace` isolates tenants that share one database file, `operation`
    isolates two tools that happen to receive the same caller key.
    """

    namespace: str
    operation: str
    key: str

    def as_tuple(self) -> tuple[str, str, str]:
        return (self.namespace, self.operation, self.key)


@dataclass(frozen=True)
class IdempotencyRecord:
    """A single stored entry."""

    namespace: str
    operation: str
    key: str
    fingerprint: str
    state: str
    result: Any = None
    created_at: float = 0.0
    updated_at: float = 0.0
    expires_at: float = 0.0
    lease_expires_at: Optional[float] = None
    owner: Optional[str] = None

    @property
    def is_completed(self) -> bool:
        return self.state == STATE_COMPLETED


@dataclass(frozen=True)
class BeginOutcome:
    """What the caller should do after reserving a key.

    status is one of OUTCOME_EXECUTE (the lease is ours), OUTCOME_REPLAY (a
    result is already stored) or OUTCOME_IN_PROGRESS (someone else holds a
    valid lease).
    """

    status: str
    record: Optional[IdempotencyRecord] = None
    reclaimed: bool = False


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------


class IdempotencyBackend(ABC):
    """Storage contract shared by the in-memory and SQLite implementations."""

    @abstractmethod
    async def begin(
        self,
        ik: IdempotencyKey,
        fingerprint: str,
        *,
        ttl_seconds: float,
        lease_seconds: float,
        owner: str,
    ) -> BeginOutcome:
        """Atomically reserve `ik` or report what is already stored.

        Raises:
            IdempotencyConflict: stored fingerprint differs from `fingerprint`.
            IdempotencyBackendError: storage is unavailable.
        """

    @abstractmethod
    async def complete(
        self, ik: IdempotencyKey, result: Any, *, ttl_seconds: float
    ) -> None:
        """Store the successful result and release the lease."""

    @abstractmethod
    async def discard(self, ik: IdempotencyKey) -> None:
        """Drop the entry so a later retry executes again.

        Used when the business call failed: errors must not be replayed.
        """

    @abstractmethod
    async def get(self, ik: IdempotencyKey) -> Optional[IdempotencyRecord]:
        """Return the live (non-expired) entry, or None."""

    @abstractmethod
    async def purge_expired(self) -> int:
        """Delete expired entries. Returns how many were removed."""

    async def close(self) -> None:
        """Release resources. No-op by default."""
        return None


def _decide(
    record: Optional[IdempotencyRecord],
    ik: IdempotencyKey,
    fingerprint: str,
    now: float,
) -> str:
    """Shared decision table for both backends.

    Returns one of: "fresh" (no usable entry), "replay", "reclaim" (dead lease)
    or "in_progress". Raises IdempotencyConflict on a fingerprint mismatch.

    Order matters: TTL expiry is checked before the fingerprint, because an
    expired entry is equivalent to no entry -- reusing the key with a new
    payload after the TTL is legitimate, not a conflict.
    """
    if record is None or record.expires_at <= now:
        return "fresh"
    if record.fingerprint != fingerprint:
        raise IdempotencyConflict(ik.operation, ik.key)
    if record.state == STATE_COMPLETED:
        return "replay"
    if record.lease_expires_at is None or record.lease_expires_at <= now:
        # The worker that held this lease died mid-flight. Without reclaiming,
        # the key would stay poisoned until its TTL expired.
        return "reclaim"
    return "in_progress"


# ---------------------------------------------------------------------------
# In-memory backend
# ---------------------------------------------------------------------------


class MemoryIdempotencyBackend(IdempotencyBackend):
    """Process-local backend.

    Correct for a single worker and for tests; it cannot coordinate the two PM2
    instances and it forgets everything on restart.
    """

    def __init__(self, *, time_func: Callable[[], float] = time.time) -> None:
        self._entries: dict[tuple[str, str, str], IdempotencyRecord] = {}
        self._lock = asyncio.Lock()
        self._time = time_func

    async def begin(
        self,
        ik: IdempotencyKey,
        fingerprint: str,
        *,
        ttl_seconds: float,
        lease_seconds: float,
        owner: str,
    ) -> BeginOutcome:
        async with self._lock:
            now = self._time()
            record = self._entries.get(ik.as_tuple())
            decision = _decide(record, ik, fingerprint, now)

            if decision == "replay":
                return BeginOutcome(OUTCOME_REPLAY, record)
            if decision == "in_progress":
                return BeginOutcome(OUTCOME_IN_PROGRESS, record)

            reclaimed = decision == "reclaim"
            created_at = record.created_at if reclaimed and record else now
            entry = IdempotencyRecord(
                namespace=ik.namespace,
                operation=ik.operation,
                key=ik.key,
                fingerprint=fingerprint,
                state=STATE_IN_PROGRESS,
                result=None,
                created_at=created_at,
                updated_at=now,
                expires_at=now + ttl_seconds,
                lease_expires_at=now + lease_seconds,
                owner=owner,
            )
            self._entries[ik.as_tuple()] = entry
            return BeginOutcome(OUTCOME_EXECUTE, entry, reclaimed=reclaimed)

    async def complete(
        self, ik: IdempotencyKey, result: Any, *, ttl_seconds: float
    ) -> None:
        async with self._lock:
            now = self._time()
            record = self._entries.get(ik.as_tuple())
            if record is None:
                return
            self._entries[ik.as_tuple()] = replace(
                record,
                state=STATE_COMPLETED,
                result=result,
                updated_at=now,
                expires_at=now + ttl_seconds,
                lease_expires_at=None,
            )

    async def discard(self, ik: IdempotencyKey) -> None:
        async with self._lock:
            self._entries.pop(ik.as_tuple(), None)

    async def get(self, ik: IdempotencyKey) -> Optional[IdempotencyRecord]:
        async with self._lock:
            record = self._entries.get(ik.as_tuple())
            if record is None or record.expires_at <= self._time():
                return None
            return record

    async def purge_expired(self) -> int:
        async with self._lock:
            now = self._time()
            dead = [k for k, v in self._entries.items() if v.expires_at <= now]
            for k in dead:
                del self._entries[k]
            return len(dead)


# ---------------------------------------------------------------------------
# SQLite backend
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS idempotency_entries (
    namespace        TEXT NOT NULL,
    operation        TEXT NOT NULL,
    key              TEXT NOT NULL,
    fingerprint      TEXT NOT NULL,
    state            TEXT NOT NULL,
    result           TEXT,
    created_at       REAL NOT NULL,
    updated_at       REAL NOT NULL,
    expires_at       REAL NOT NULL,
    lease_expires_at REAL,
    owner            TEXT,
    PRIMARY KEY (namespace, operation, key)
);
CREATE INDEX IF NOT EXISTS idx_idempotency_expires
    ON idempotency_entries (expires_at);
"""

_SELECT_COLUMNS = (
    "namespace, operation, key, fingerprint, state, result, "
    "created_at, updated_at, expires_at, lease_expires_at, owner"
)


class SQLiteIdempotencyBackend(IdempotencyBackend):
    """Persistent backend shared by every worker on the host.

    Cross-process safety comes from SQLite itself: each `begin` runs inside a
    ``BEGIN IMMEDIATE`` transaction, so the read-then-write that hands out a
    lease cannot interleave with another worker's. WAL mode keeps readers from
    blocking the writer, and `busy_timeout` absorbs short contention instead of
    raising "database is locked".

    sqlite3 is blocking, so every call is dispatched to a worker thread and
    guarded by a threading lock (one connection, `check_same_thread=False`).
    """

    def __init__(
        self,
        db_path: Optional[os.PathLike[str] | str] = None,
        *,
        busy_timeout_ms: int = 5000,
        time_func: Callable[[], float] = time.time,
    ) -> None:
        self.db_path = Path(db_path) if db_path is not None else default_db_path()
        self._busy_timeout_ms = busy_timeout_ms
        self._time = time_func
        self._conn: Optional[sqlite3.Connection] = None
        self._conn_lock = threading.Lock()

    # -- connection management ------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open (once) and configure the connection.

        Lazily invoked so a broken path degrades at first use instead of
        exploding at import time.
        """
        if self._conn is not None:
            return self._conn
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                str(self.db_path),
                timeout=self._busy_timeout_ms / 1000.0,
                check_same_thread=False,
                isolation_level=None,  # explicit transaction control
            )
            conn.row_factory = sqlite3.Row
            conn.execute(f"PRAGMA busy_timeout = {int(self._busy_timeout_ms)}")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.executescript(_SCHEMA)
        except (sqlite3.Error, OSError) as exc:
            raise IdempotencyBackendError(
                f"Nao foi possivel abrir o banco de idempotencia em "
                f"'{self.db_path}': {exc}"
            ) from exc
        self._conn = conn
        return conn

    def close_sync(self) -> None:
        with self._conn_lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:  # pragma: no cover - best effort
                    pass
                self._conn = None

    async def close(self) -> None:
        await asyncio.to_thread(self.close_sync)

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> IdempotencyRecord:
        raw = row["result"]
        result: Any = None
        if raw is not None:
            try:
                result = json.loads(raw)
            except (TypeError, ValueError):  # pragma: no cover - defensive
                logger.warning("Corrupt idempotency result payload; ignoring cache")
                result = None
        return IdempotencyRecord(
            namespace=row["namespace"],
            operation=row["operation"],
            key=row["key"],
            fingerprint=row["fingerprint"],
            state=row["state"],
            result=result,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expires_at=row["expires_at"],
            lease_expires_at=row["lease_expires_at"],
            owner=row["owner"],
        )

    def _fetch(
        self, conn: sqlite3.Connection, ik: IdempotencyKey
    ) -> Optional[IdempotencyRecord]:
        cur = conn.execute(
            f"SELECT {_SELECT_COLUMNS} FROM idempotency_entries "
            "WHERE namespace = ? AND operation = ? AND key = ?",
            ik.as_tuple(),
        )
        row = cur.fetchone()
        return self._row_to_record(row) if row is not None else None

    # -- interface ------------------------------------------------------------

    def _begin_sync(
        self,
        ik: IdempotencyKey,
        fingerprint: str,
        ttl_seconds: float,
        lease_seconds: float,
        owner: str,
    ) -> BeginOutcome:
        with self._conn_lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
            except sqlite3.Error as exc:
                raise IdempotencyBackendError(
                    f"Banco de idempotencia indisponivel: {exc}"
                ) from exc
            try:
                now = self._time()
                record = self._fetch(conn, ik)
                decision = _decide(record, ik, fingerprint, now)

                if decision == "replay":
                    conn.execute("COMMIT")
                    return BeginOutcome(OUTCOME_REPLAY, record)
                if decision == "in_progress":
                    conn.execute("COMMIT")
                    return BeginOutcome(OUTCOME_IN_PROGRESS, record)

                reclaimed = decision == "reclaim"
                created_at = record.created_at if reclaimed and record else now
                conn.execute(
                    "INSERT OR REPLACE INTO idempotency_entries "
                    "(namespace, operation, key, fingerprint, state, result, "
                    " created_at, updated_at, expires_at, lease_expires_at, owner) "
                    "VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)",
                    (
                        ik.namespace,
                        ik.operation,
                        ik.key,
                        fingerprint,
                        STATE_IN_PROGRESS,
                        created_at,
                        now,
                        now + ttl_seconds,
                        now + lease_seconds,
                        owner,
                    ),
                )
                conn.execute("COMMIT")
                entry = IdempotencyRecord(
                    namespace=ik.namespace,
                    operation=ik.operation,
                    key=ik.key,
                    fingerprint=fingerprint,
                    state=STATE_IN_PROGRESS,
                    created_at=created_at,
                    updated_at=now,
                    expires_at=now + ttl_seconds,
                    lease_expires_at=now + lease_seconds,
                    owner=owner,
                )
                return BeginOutcome(OUTCOME_EXECUTE, entry, reclaimed=reclaimed)
            except IdempotencyConflict:
                self._rollback(conn)
                raise
            except sqlite3.Error as exc:
                self._rollback(conn)
                raise IdempotencyBackendError(
                    f"Falha ao reservar chave de idempotencia: {exc}"
                ) from exc

    @staticmethod
    def _rollback(conn: sqlite3.Connection) -> None:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:  # pragma: no cover - best effort
            pass

    async def begin(
        self,
        ik: IdempotencyKey,
        fingerprint: str,
        *,
        ttl_seconds: float,
        lease_seconds: float,
        owner: str,
    ) -> BeginOutcome:
        return await asyncio.to_thread(
            self._begin_sync, ik, fingerprint, ttl_seconds, lease_seconds, owner
        )

    def _complete_sync(
        self, ik: IdempotencyKey, result: Any, ttl_seconds: float
    ) -> None:
        try:
            encoded = json.dumps(_canonicalize(result), ensure_ascii=False)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise IdempotencyBackendError(
                f"Resultado nao serializavel para idempotencia: {exc}"
            ) from exc
        with self._conn_lock:
            conn = self._connect()
            now = self._time()
            try:
                conn.execute(
                    "UPDATE idempotency_entries "
                    "SET state = ?, result = ?, updated_at = ?, expires_at = ?, "
                    "    lease_expires_at = NULL "
                    "WHERE namespace = ? AND operation = ? AND key = ?",
                    (
                        STATE_COMPLETED,
                        encoded,
                        now,
                        now + ttl_seconds,
                        ik.namespace,
                        ik.operation,
                        ik.key,
                    ),
                )
            except sqlite3.Error as exc:
                raise IdempotencyBackendError(
                    f"Falha ao gravar resultado de idempotencia: {exc}"
                ) from exc

    async def complete(
        self, ik: IdempotencyKey, result: Any, *, ttl_seconds: float
    ) -> None:
        await asyncio.to_thread(self._complete_sync, ik, result, ttl_seconds)

    def _discard_sync(self, ik: IdempotencyKey) -> None:
        with self._conn_lock:
            conn = self._connect()
            try:
                conn.execute(
                    "DELETE FROM idempotency_entries "
                    "WHERE namespace = ? AND operation = ? AND key = ?",
                    ik.as_tuple(),
                )
            except sqlite3.Error as exc:
                raise IdempotencyBackendError(
                    f"Falha ao remover chave de idempotencia: {exc}"
                ) from exc

    async def discard(self, ik: IdempotencyKey) -> None:
        await asyncio.to_thread(self._discard_sync, ik)

    def _get_sync(self, ik: IdempotencyKey) -> Optional[IdempotencyRecord]:
        with self._conn_lock:
            conn = self._connect()
            try:
                record = self._fetch(conn, ik)
            except sqlite3.Error as exc:
                raise IdempotencyBackendError(
                    f"Falha ao ler chave de idempotencia: {exc}"
                ) from exc
        if record is None or record.expires_at <= self._time():
            return None
        return record

    async def get(self, ik: IdempotencyKey) -> Optional[IdempotencyRecord]:
        return await asyncio.to_thread(self._get_sync, ik)

    def _purge_sync(self) -> int:
        with self._conn_lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "DELETE FROM idempotency_entries WHERE expires_at <= ?",
                    (self._time(),),
                )
                return cur.rowcount or 0
            except sqlite3.Error as exc:
                raise IdempotencyBackendError(
                    f"Falha ao limpar chaves expiradas: {exc}"
                ) from exc

    async def purge_expired(self) -> int:
        return await asyncio.to_thread(self._purge_sync)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def mark_replayed(result: Any, record: IdempotencyRecord) -> Any:
    """Tag a cached result so the caller can see it was not re-executed.

    Dict results (every MCP tool returns one) get `replayed: True` plus the key
    that produced them. Anything else is wrapped, because a bare value has
    nowhere to carry the flag.
    """
    meta = {
        REPLAY_FLAG: True,
        "idempotency_key": record.key,
        "idempotency_operation": record.operation,
        "first_executed_at": record.created_at,
    }
    if isinstance(result, Mapping):
        merged = dict(result)
        merged.update(meta)
        return merged
    return {"result": result, **meta}


class IdempotencyStore:
    """Front door for guarded write operations.

    Typical use from a tool handler::

        store = get_idempotency_store()
        return await store.run(
            "ticket.create",
            idempotency_key,
            payload={"name": name, "content": content},
            executor=lambda: ticket_service.create_ticket(...),
        )
    """

    def __init__(
        self,
        backend: Optional[IdempotencyBackend] = None,
        *,
        enabled: bool = True,
        namespace: str = DEFAULT_NAMESPACE,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        wait_timeout: float = DEFAULT_WAIT_TIMEOUT,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        purge_interval: float = DEFAULT_PURGE_INTERVAL,
        time_func: Callable[[], float] = time.monotonic,
    ) -> None:
        self.backend = backend
        self.enabled = enabled and backend is not None
        self.namespace = namespace
        self.ttl_seconds = ttl_seconds
        self.lease_seconds = lease_seconds
        self.wait_timeout = wait_timeout
        self.poll_interval = poll_interval
        self.purge_interval = purge_interval
        self.owner = f"{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._clock = time_func
        self._last_purge = 0.0
        self._degraded = False

    # -- diagnostics ----------------------------------------------------------

    @property
    def is_degraded(self) -> bool:
        """True once a backend failure has been swallowed."""
        return self._degraded

    def status(self) -> dict[str, Any]:
        """Snapshot for health endpoints and troubleshooting."""
        backend_name = type(self.backend).__name__ if self.backend else None
        return {
            "enabled": self.enabled,
            "backend": backend_name,
            "namespace": self.namespace,
            "ttl_seconds": self.ttl_seconds,
            "lease_seconds": self.lease_seconds,
            "wait_timeout": self.wait_timeout,
            "owner": self.owner,
            "degraded": self._degraded,
        }

    # -- internals ------------------------------------------------------------

    def _degrade(self, action: str, ik: IdempotencyKey, exc: BaseException) -> None:
        """Record a swallowed backend failure.

        Deliberately never re-raises: idempotency is best-effort and must not
        take a ticket-creation down with it.
        """
        self._degraded = True
        logger.warning(
            "Idempotency backend unavailable during %s for %s/%s (%s); "
            "proceeding without de-duplication",
            action,
            ik.operation,
            ik.key,
            exc,
        )

    async def _maybe_purge(self) -> None:
        """Housekeeping on a timer so the table cannot grow without bound."""
        if self.backend is None:
            return
        now = self._clock()
        if now - self._last_purge < self.purge_interval:
            return
        self._last_purge = now
        try:
            removed = await self.backend.purge_expired()
            if removed:
                logger.debug("Purged %d expired idempotency entries", removed)
        except Exception as exc:  # noqa: BLE001 - housekeeping must never raise
            logger.warning("Failed to purge idempotency entries: %s", exc)

    async def run(
        self,
        operation: str,
        key: Optional[str],
        payload: Any,
        executor: Callable[[], Awaitable[Any]],
        *,
        namespace: Optional[str] = None,
        ttl_seconds: Optional[float] = None,
        lease_seconds: Optional[float] = None,
        wait_timeout: Optional[float] = None,
        fingerprint_exclude: Optional[Iterable[str]] = None,
    ) -> Any:
        """Execute `executor` at most once for (`operation`, `key`).

        Args:
            operation: Stable operation id, e.g. "ticket.create".
            key: Caller-supplied idempotency key. None/empty disables the guard
                for this call and the executor simply runs.
            payload: Value fingerprinted to detect key reuse with new data.
            executor: Zero-argument coroutine factory doing the real work.
            namespace: Tenant scope override.
            ttl_seconds: Entry lifetime override.
            lease_seconds: Lease lifetime override.
            wait_timeout: How long to wait for another worker's lease.
            fingerprint_exclude: Top-level payload keys to ignore.

        Returns:
            The executor result, or the previous result tagged via
            `mark_replayed` when the same key+payload was already processed.

        Raises:
            IdempotencyConflict: same key, different payload.
            IdempotencyInProgress: another worker held the lease past the wait
                timeout.
            Whatever `executor` raises (failures are never cached).
        """
        if not self.enabled or self.backend is None or not key:
            return await executor()

        ik = IdempotencyKey(
            namespace=namespace or self.namespace,
            operation=operation,
            key=str(key),
        )
        ttl = ttl_seconds if ttl_seconds is not None else self.ttl_seconds
        lease = lease_seconds if lease_seconds is not None else self.lease_seconds
        timeout = wait_timeout if wait_timeout is not None else self.wait_timeout
        fingerprint = payload_fingerprint(payload, exclude=fingerprint_exclude)

        await self._maybe_purge()

        deadline = self._clock() + timeout
        while True:
            try:
                outcome = await self.backend.begin(
                    ik, fingerprint, ttl_seconds=ttl, lease_seconds=lease,
                    owner=self.owner,
                )
            except IdempotencyConflict:
                # Caller error, not a backend problem: must surface.
                raise
            except Exception as exc:  # noqa: BLE001 - degrade, never block writes
                self._degrade("begin", ik, exc)
                return await executor()

            if outcome.status == OUTCOME_REPLAY and outcome.record is not None:
                logger.info(
                    "Idempotent replay for %s/%s; executor skipped",
                    ik.operation,
                    ik.key,
                )
                return mark_replayed(outcome.record.result, outcome.record)

            if outcome.status == OUTCOME_EXECUTE:
                if outcome.reclaimed:
                    logger.warning(
                        "Reclaimed expired idempotency lease for %s/%s",
                        ik.operation,
                        ik.key,
                    )
                return await self._execute_and_store(ik, executor, ttl)

            # OUTCOME_IN_PROGRESS: another worker owns a live lease.
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise IdempotencyInProgress(ik.operation, ik.key, timeout)
            await asyncio.sleep(min(self.poll_interval, remaining))

    async def _execute_and_store(
        self,
        ik: IdempotencyKey,
        executor: Callable[[], Awaitable[Any]],
        ttl: float,
    ) -> Any:
        """Run the business call, then persist or release the reservation."""
        try:
            result = await executor()
        except BaseException:
            # Never cache a failure: a transient GLPI error must not turn into
            # a permanently replayed error response.
            try:
                await self.backend.discard(ik)  # type: ignore[union-attr]
            except Exception as exc:  # noqa: BLE001 - cleanup is best effort
                self._degrade("discard", ik, exc)
            raise

        try:
            await self.backend.complete(ik, result, ttl_seconds=ttl)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001 - degrade, never block writes
            self._degrade("complete", ik, exc)
            # The reservation would otherwise stay "in_progress" and block
            # honest retries until its lease expired.
            try:
                await self.backend.discard(ik)  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001 - best effort
                pass
        return result

    async def close(self) -> None:
        if self.backend is not None:
            await self.backend.close()


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def build_backend(
    name: str,
    *,
    db_path: Optional[str] = None,
    time_func: Callable[[], float] = time.time,
) -> Optional[IdempotencyBackend]:
    """Instantiate a backend by name. Unknown names degrade to no backend."""
    normalized = (name or "").strip().lower()
    if normalized in ("none", "off", "disabled", ""):
        return None
    if normalized == "memory":
        return MemoryIdempotencyBackend(time_func=time_func)
    if normalized == "sqlite":
        return SQLiteIdempotencyBackend(db_path=db_path, time_func=time_func)
    logger.warning(
        "Unknown %s=%r; idempotency disabled for this process", ENV_BACKEND, name
    )
    return None


def build_store_from_env(
    env: Optional[Mapping[str, str]] = None,
) -> IdempotencyStore:
    """Build a store from environment variables only.

    Reads plain environment variables; it never parses .env files and never
    touches credentials.
    """
    source: Mapping[str, str] = env if env is not None else os.environ
    enabled = _env_bool(source, ENV_ENABLED, DEFAULT_ENABLED)
    backend_name = source.get(ENV_BACKEND, DEFAULT_BACKEND)
    db_path = source.get(ENV_DB_PATH) or None

    backend = build_backend(backend_name, db_path=db_path) if enabled else None
    return IdempotencyStore(
        backend,
        enabled=enabled,
        namespace=source.get(ENV_NAMESPACE) or DEFAULT_NAMESPACE,
        ttl_seconds=_env_float(source, ENV_TTL_SECONDS, DEFAULT_TTL_SECONDS),
        lease_seconds=_env_float(source, ENV_LEASE_SECONDS, DEFAULT_LEASE_SECONDS),
        wait_timeout=_env_float(source, ENV_WAIT_TIMEOUT, DEFAULT_WAIT_TIMEOUT),
        poll_interval=_env_float(source, ENV_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        purge_interval=_env_float(source, ENV_PURGE_INTERVAL, DEFAULT_PURGE_INTERVAL),
    )


_store: Optional[IdempotencyStore] = None
_store_lock = threading.Lock()


def get_idempotency_store() -> IdempotencyStore:
    """Return the process-wide store, building it on first use."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = build_store_from_env()
                logger.info("Idempotency store initialized: %s", _store.status())
    return _store


def set_idempotency_store(store: Optional[IdempotencyStore]) -> None:
    """Replace the singleton. Intended for tests and for explicit wiring."""
    global _store
    with _store_lock:
        _store = store


def reset_idempotency_store() -> None:
    """Drop the singleton so the next call rebuilds it from the environment."""
    set_idempotency_store(None)
