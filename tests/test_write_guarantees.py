"""
Tests for the write guarantees: idempotency store and write policy.

Both backends are exercised through the same parametrized suite so the SQLite
implementation cannot silently drift from the in-memory one.
"""

import asyncio

import pytest

from src.security.idempotency import (
    DEFAULT_BACKEND,
    DEFAULT_NAMESPACE,
    DEFAULT_TTL_SECONDS,
    ENV_BACKEND,
    ENV_DB_PATH,
    ENV_ENABLED,
    ENV_NAMESPACE,
    ENV_TTL_SECONDS,
    OUTCOME_EXECUTE,
    OUTCOME_IN_PROGRESS,
    OUTCOME_REPLAY,
    REPLAY_FLAG,
    IdempotencyBackendError,
    IdempotencyConflict,
    IdempotencyInProgress,
    IdempotencyKey,
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
    ENV_READ_ONLY,
    PROFILE_ADMINISTRATOR,
    PROFILE_READ_ONLY,
    PROFILE_TICKET_OPERATOR,
    REASON_DISABLED,
    REASON_READ_ONLY,
    WRITE_ENV_VARS,
    WRITE_OPERATIONS,
    WRITE_PROFILES,
    WriteNotAllowedError,
    WriteOperation,
    WritePolicy,
    get_write_policy,
    operation_env_var,
    require_write_allowed,
    reset_write_policy,
    resolve_operation,
    set_write_policy,
)


# ===========================================================================
# Helpers
# ===========================================================================


class FakeClock:
    """Controllable wall clock so TTL/lease tests never sleep."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Recorder:
    """Executor double that counts how often the business call ran."""

    def __init__(self, result=None, error: Exception = None, delay: float = 0.0):
        self.result = result if result is not None else {"id": 42}
        self.error = error
        self.delay = delay
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.result


class BrokenBackend(MemoryIdempotencyBackend):
    """Backend whose storage is unavailable, to prove graceful degradation."""

    def __init__(self, fail_on=("begin", "complete", "discard", "get")):
        super().__init__()
        self.fail_on = set(fail_on)

    async def begin(self, *args, **kwargs):
        if "begin" in self.fail_on:
            raise IdempotencyBackendError("disco indisponivel")
        return await super().begin(*args, **kwargs)

    async def complete(self, *args, **kwargs):
        if "complete" in self.fail_on:
            raise IdempotencyBackendError("disco indisponivel")
        return await super().complete(*args, **kwargs)

    async def discard(self, *args, **kwargs):
        if "discard" in self.fail_on:
            raise IdempotencyBackendError("disco indisponivel")
        return await super().discard(*args, **kwargs)

    async def get(self, *args, **kwargs):
        if "get" in self.fail_on:
            raise IdempotencyBackendError("disco indisponivel")
        return await super().get(*args, **kwargs)


@pytest.fixture(params=["memory", "sqlite"])
def backend_factory(request, tmp_path):
    """Build either backend on demand, sharing one clock and one DB file."""

    created = []

    def factory(clock=None):
        clock = clock or FakeClock()
        if request.param == "memory":
            backend = MemoryIdempotencyBackend(time_func=clock)
        else:
            backend = SQLiteIdempotencyBackend(
                db_path=tmp_path / "idem.sqlite3", time_func=clock
            )
        created.append(backend)
        return backend, clock

    yield factory

    for backend in created:
        if isinstance(backend, SQLiteIdempotencyBackend):
            backend.close_sync()


@pytest.fixture
def key():
    return IdempotencyKey(namespace="t1", operation="ticket.create", key="k-1")


def make_store(backend, **kwargs):
    """Store wired to a backend, with test-friendly timings.

    The store keeps the real monotonic clock (it only drives wait deadlines);
    TTL and lease expiry live on the backend's injectable clock, so those tests
    advance time instead of sleeping.
    """
    params = {
        "namespace": "t1",
        "ttl_seconds": 100.0,
        "lease_seconds": 10.0,
        "wait_timeout": 2.0,
        "poll_interval": 0.01,
        "purge_interval": 1e9,  # never auto-purge unless asked
    }
    params.update(kwargs)
    return IdempotencyStore(backend, **params)


@pytest.fixture(autouse=True)
def _clean_singletons():
    """Keep module singletons from leaking between tests."""
    reset_idempotency_store()
    reset_write_policy()
    yield
    reset_idempotency_store()
    reset_write_policy()


# ===========================================================================
# Fingerprinting
# ===========================================================================


class TestPayloadFingerprint:
    def test_same_payload_same_fingerprint(self):
        a = {"name": "chamado", "urgency": 3, "tags": ["a", "b"]}
        b = {"name": "chamado", "urgency": 3, "tags": ["a", "b"]}
        assert payload_fingerprint(a) == payload_fingerprint(b)

    def test_key_order_does_not_matter(self):
        a = {"name": "x", "urgency": 3}
        b = {"urgency": 3, "name": "x"}
        assert payload_fingerprint(a) == payload_fingerprint(b)

    def test_different_payload_different_fingerprint(self):
        a = {"name": "chamado", "urgency": 3}
        b = {"name": "chamado", "urgency": 4}
        assert payload_fingerprint(a) != payload_fingerprint(b)

    def test_list_order_matters(self):
        assert payload_fingerprint([1, 2]) != payload_fingerprint([2, 1])

    def test_tuple_and_list_are_equivalent(self):
        assert payload_fingerprint((1, 2)) == payload_fingerprint([1, 2])

    def test_set_order_is_stable(self):
        assert payload_fingerprint({"a", "b"}) == payload_fingerprint({"b", "a"})

    def test_exclude_ignores_volatile_fields(self):
        a = {"name": "x", "timestamp": 1}
        b = {"name": "x", "timestamp": 2}
        assert payload_fingerprint(a) != payload_fingerprint(b)
        assert payload_fingerprint(a, exclude=["timestamp"]) == payload_fingerprint(
            b, exclude=["timestamp"]
        )

    def test_non_serializable_payload_does_not_raise(self):
        class Weird:
            def __repr__(self):
                return "<weird>"

        assert isinstance(payload_fingerprint({"o": Weird()}), str)

    def test_nested_structures_are_canonicalized(self):
        a = {"outer": {"b": 1, "a": [1, {"y": 2, "x": 1}]}}
        b = {"outer": {"a": [1, {"x": 1, "y": 2}], "b": 1}}
        assert payload_fingerprint(a) == payload_fingerprint(b)

    def test_none_and_empty_dict_differ(self):
        assert payload_fingerprint(None) != payload_fingerprint({})


# ===========================================================================
# Backend behaviour (both implementations)
# ===========================================================================


class TestBackendContract:
    async def test_first_begin_grants_execution(self, backend_factory, key):
        backend, _ = backend_factory()
        outcome = await backend.begin(
            key, "fp1", ttl_seconds=100, lease_seconds=10, owner="w1"
        )
        assert outcome.status == OUTCOME_EXECUTE
        assert outcome.reclaimed is False

    async def test_second_begin_while_leased_reports_in_progress(
        self, backend_factory, key
    ):
        backend, _ = backend_factory()
        await backend.begin(key, "fp1", ttl_seconds=100, lease_seconds=10, owner="w1")
        outcome = await backend.begin(
            key, "fp1", ttl_seconds=100, lease_seconds=10, owner="w2"
        )
        assert outcome.status == OUTCOME_IN_PROGRESS

    async def test_completed_entry_is_replayed(self, backend_factory, key):
        backend, _ = backend_factory()
        await backend.begin(key, "fp1", ttl_seconds=100, lease_seconds=10, owner="w1")
        await backend.complete(key, {"id": 7}, ttl_seconds=100)
        outcome = await backend.begin(
            key, "fp1", ttl_seconds=100, lease_seconds=10, owner="w2"
        )
        assert outcome.status == OUTCOME_REPLAY
        assert outcome.record.result == {"id": 7}

    async def test_different_fingerprint_raises_conflict(self, backend_factory, key):
        backend, _ = backend_factory()
        await backend.begin(key, "fp1", ttl_seconds=100, lease_seconds=10, owner="w1")
        await backend.complete(key, {"id": 7}, ttl_seconds=100)
        with pytest.raises(IdempotencyConflict) as exc:
            await backend.begin(
                key, "fp2", ttl_seconds=100, lease_seconds=10, owner="w2"
            )
        assert exc.value.code == 409
        assert "conteudo diferente" in exc.value.message

    async def test_expired_entry_allows_new_payload(self, backend_factory, key):
        """After the TTL, key reuse with new data is legitimate, not a conflict."""
        backend, clock = backend_factory()
        await backend.begin(key, "fp1", ttl_seconds=100, lease_seconds=10, owner="w1")
        await backend.complete(key, {"id": 7}, ttl_seconds=100)
        clock.advance(101)
        outcome = await backend.begin(
            key, "fp2", ttl_seconds=100, lease_seconds=10, owner="w2"
        )
        assert outcome.status == OUTCOME_EXECUTE

    async def test_expired_entry_is_not_replayed(self, backend_factory, key):
        backend, clock = backend_factory()
        await backend.begin(key, "fp1", ttl_seconds=100, lease_seconds=10, owner="w1")
        await backend.complete(key, {"id": 7}, ttl_seconds=100)
        clock.advance(101)
        assert await backend.get(key) is None

    async def test_expired_lease_is_reclaimed(self, backend_factory, key):
        """A worker that died mid-flight must not poison the key forever."""
        backend, clock = backend_factory()
        await backend.begin(key, "fp1", ttl_seconds=100, lease_seconds=10, owner="w1")
        clock.advance(11)  # lease dead, TTL still alive
        outcome = await backend.begin(
            key, "fp1", ttl_seconds=100, lease_seconds=10, owner="w2"
        )
        assert outcome.status == OUTCOME_EXECUTE
        assert outcome.reclaimed is True
        assert outcome.record.owner == "w2"

    async def test_reclaim_preserves_created_at(self, backend_factory, key):
        backend, clock = backend_factory()
        first = await backend.begin(
            key, "fp1", ttl_seconds=100, lease_seconds=10, owner="w1"
        )
        clock.advance(11)
        second = await backend.begin(
            key, "fp1", ttl_seconds=100, lease_seconds=10, owner="w2"
        )
        assert second.record.created_at == first.record.created_at

    async def test_discard_allows_fresh_execution(self, backend_factory, key):
        backend, _ = backend_factory()
        await backend.begin(key, "fp1", ttl_seconds=100, lease_seconds=10, owner="w1")
        await backend.discard(key)
        outcome = await backend.begin(
            key, "fp2", ttl_seconds=100, lease_seconds=10, owner="w2"
        )
        assert outcome.status == OUTCOME_EXECUTE

    async def test_get_returns_stored_record(self, backend_factory, key):
        backend, _ = backend_factory()
        await backend.begin(key, "fp1", ttl_seconds=100, lease_seconds=10, owner="w1")
        await backend.complete(key, {"id": 3}, ttl_seconds=100)
        record = await backend.get(key)
        assert record is not None
        assert record.is_completed
        assert record.result == {"id": 3}

    async def test_get_missing_returns_none(self, backend_factory, key):
        backend, _ = backend_factory()
        assert await backend.get(key) is None

    async def test_namespaces_are_isolated(self, backend_factory):
        """Two tenants sharing a database must not collide on the same key."""
        backend, _ = backend_factory()
        a = IdempotencyKey("tenant-a", "ticket.create", "same-key")
        b = IdempotencyKey("tenant-b", "ticket.create", "same-key")
        await backend.begin(a, "fp1", ttl_seconds=100, lease_seconds=10, owner="w1")
        await backend.complete(a, {"id": 1}, ttl_seconds=100)
        outcome = await backend.begin(
            b, "fp2", ttl_seconds=100, lease_seconds=10, owner="w1"
        )
        assert outcome.status == OUTCOME_EXECUTE

    async def test_operations_are_isolated(self, backend_factory):
        backend, _ = backend_factory()
        a = IdempotencyKey("t1", "ticket.create", "same-key")
        b = IdempotencyKey("t1", "asset.create", "same-key")
        await backend.begin(a, "fp1", ttl_seconds=100, lease_seconds=10, owner="w1")
        await backend.complete(a, {"id": 1}, ttl_seconds=100)
        outcome = await backend.begin(
            b, "fp2", ttl_seconds=100, lease_seconds=10, owner="w1"
        )
        assert outcome.status == OUTCOME_EXECUTE

    async def test_purge_expired_removes_only_dead_entries(self, backend_factory):
        backend, clock = backend_factory()
        old = IdempotencyKey("t1", "ticket.create", "old")
        new = IdempotencyKey("t1", "ticket.create", "new")
        await backend.begin(old, "fp", ttl_seconds=10, lease_seconds=5, owner="w1")
        await backend.complete(old, {"id": 1}, ttl_seconds=10)
        clock.advance(11)
        await backend.begin(new, "fp", ttl_seconds=100, lease_seconds=5, owner="w1")
        assert await backend.purge_expired() == 1
        assert await backend.get(new) is not None

    async def test_complete_on_missing_entry_is_harmless(self, backend_factory, key):
        backend, _ = backend_factory()
        await backend.complete(key, {"id": 1}, ttl_seconds=100)
        assert await backend.get(key) is None


class TestSQLitePersistence:
    async def test_state_survives_a_restart(self, tmp_path):
        """The whole point of the SQLite backend: PM2 restarts keep the state."""
        db = tmp_path / "idem.sqlite3"
        key = IdempotencyKey("t1", "ticket.create", "k-1")

        first = SQLiteIdempotencyBackend(db_path=db)
        await first.begin(key, "fp1", ttl_seconds=100, lease_seconds=10, owner="w1")
        await first.complete(key, {"id": 99}, ttl_seconds=100)
        await first.close()

        second = SQLiteIdempotencyBackend(db_path=db)
        try:
            outcome = await second.begin(
                key, "fp1", ttl_seconds=100, lease_seconds=10, owner="w2"
            )
            assert outcome.status == OUTCOME_REPLAY
            assert outcome.record.result == {"id": 99}
        finally:
            await second.close()

    async def test_two_connections_coordinate_like_two_processes(self, tmp_path):
        """Separate connections stand in for the two PM2 workers."""
        db = tmp_path / "idem.sqlite3"
        key = IdempotencyKey("t1", "ticket.create", "k-1")
        worker_a = SQLiteIdempotencyBackend(db_path=db)
        worker_b = SQLiteIdempotencyBackend(db_path=db)
        try:
            first = await worker_a.begin(
                key, "fp1", ttl_seconds=100, lease_seconds=10, owner="a"
            )
            second = await worker_b.begin(
                key, "fp1", ttl_seconds=100, lease_seconds=10, owner="b"
            )
            assert first.status == OUTCOME_EXECUTE
            assert second.status == OUTCOME_IN_PROGRESS

            await worker_a.complete(key, {"id": 1}, ttl_seconds=100)
            third = await worker_b.begin(
                key, "fp1", ttl_seconds=100, lease_seconds=10, owner="b"
            )
            assert third.status == OUTCOME_REPLAY
        finally:
            await worker_a.close()
            await worker_b.close()

    async def test_creates_parent_directory(self, tmp_path):
        db = tmp_path / "nested" / "deeper" / "idem.sqlite3"
        backend = SQLiteIdempotencyBackend(db_path=db)
        try:
            await backend.begin(
                IdempotencyKey("t1", "op", "k"),
                "fp",
                ttl_seconds=10,
                lease_seconds=5,
                owner="w",
            )
            assert db.exists()
        finally:
            await backend.close()

    async def test_unwritable_path_raises_backend_error(self, tmp_path):
        """A blocked path must surface as a backend error, not a raw OSError."""
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        backend = SQLiteIdempotencyBackend(db_path=blocker / "sub" / "idem.sqlite3")
        with pytest.raises(IdempotencyBackendError):
            await backend.begin(
                IdempotencyKey("t1", "op", "k"),
                "fp",
                ttl_seconds=10,
                lease_seconds=5,
                owner="w",
            )

    async def test_corrupt_database_raises_backend_error(self, tmp_path):
        """Raw sqlite3 errors must be wrapped so the store can degrade them."""
        db = tmp_path / "corrupt.sqlite3"
        db.write_bytes(b"this is definitely not a sqlite file" * 10)
        backend = SQLiteIdempotencyBackend(db_path=db)
        with pytest.raises(IdempotencyBackendError):
            await backend.begin(
                IdempotencyKey("t1", "op", "k"),
                "fp",
                ttl_seconds=10,
                lease_seconds=5,
                owner="w",
            )

    def test_default_db_path_is_inside_the_project(self):
        path = default_db_path()
        assert path.name == "store.sqlite3"
        # `var/` is already covered by .gitignore, so state stays untracked.
        assert path.parent.parent.name == "var"


# ===========================================================================
# Store orchestration
# ===========================================================================


class TestStoreReplay:
    async def test_executes_once_and_returns_result(self, backend_factory):
        backend, _ = backend_factory()
        store = make_store(backend)
        run = Recorder({"id": 1})
        result = await store.run("ticket.create", "k1", {"name": "x"}, run)
        assert result == {"id": 1}
        assert run.calls == 1

    async def test_same_payload_replays_without_executing(self, backend_factory):
        backend, _ = backend_factory()
        store = make_store(backend)
        run = Recorder({"id": 1})
        await store.run("ticket.create", "k1", {"name": "x"}, run)
        replayed = await store.run("ticket.create", "k1", {"name": "x"}, run)
        assert run.calls == 1
        assert replayed[REPLAY_FLAG] is True
        assert replayed["id"] == 1

    async def test_replay_carries_key_metadata(self, backend_factory):
        backend, _ = backend_factory()
        store = make_store(backend)
        run = Recorder({"id": 1})
        await store.run("ticket.create", "k1", {"name": "x"}, run)
        replayed = await store.run("ticket.create", "k1", {"name": "x"}, run)
        assert replayed["idempotency_key"] == "k1"
        assert replayed["idempotency_operation"] == "ticket.create"

    async def test_first_response_is_not_flagged_as_replayed(self, backend_factory):
        backend, _ = backend_factory()
        store = make_store(backend)
        result = await store.run("ticket.create", "k1", {"name": "x"}, Recorder())
        assert REPLAY_FLAG not in result

    async def test_different_key_executes_again(self, backend_factory):
        backend, _ = backend_factory()
        store = make_store(backend)
        run = Recorder({"id": 1})
        await store.run("ticket.create", "k1", {"name": "x"}, run)
        await store.run("ticket.create", "k2", {"name": "x"}, run)
        assert run.calls == 2

    async def test_missing_key_disables_the_guard(self, backend_factory):
        backend, _ = backend_factory()
        store = make_store(backend)
        run = Recorder()
        await store.run("ticket.create", None, {"name": "x"}, run)
        await store.run("ticket.create", "", {"name": "x"}, run)
        assert run.calls == 2

    async def test_conflicting_payload_raises(self, backend_factory):
        backend, _ = backend_factory()
        store = make_store(backend)
        run = Recorder()
        await store.run("ticket.create", "k1", {"name": "x"}, run)
        with pytest.raises(IdempotencyConflict):
            await store.run("ticket.create", "k1", {"name": "OUTRO"}, run)
        assert run.calls == 1

    async def test_conflict_is_not_swallowed_as_degradation(self, backend_factory):
        """A conflict is a caller error; it must never be degraded away."""
        backend, _ = backend_factory()
        store = make_store(backend)
        await store.run("ticket.create", "k1", {"name": "x"}, Recorder())
        with pytest.raises(IdempotencyConflict):
            await store.run("ticket.create", "k1", {"name": "y"}, Recorder())
        assert store.is_degraded is False

    async def test_ttl_expiry_allows_re_execution(self, backend_factory):
        backend, clock = backend_factory()
        store = make_store(backend, ttl_seconds=50.0)
        run = Recorder()
        await store.run("ticket.create", "k1", {"name": "x"}, run)
        clock.advance(51)
        await store.run("ticket.create", "k1", {"name": "x"}, run)
        assert run.calls == 2

    async def test_non_dict_result_is_wrapped_on_replay(self, backend_factory):
        backend, _ = backend_factory()
        store = make_store(backend)
        run = Recorder(result=[1, 2, 3])
        first = await store.run("ticket.create", "k1", {"n": 1}, run)
        second = await store.run("ticket.create", "k1", {"n": 1}, run)
        assert first == [1, 2, 3]
        assert second[REPLAY_FLAG] is True
        assert second["result"] == [1, 2, 3]

    async def test_fingerprint_exclude_ignores_volatile_fields(self, backend_factory):
        backend, _ = backend_factory()
        store = make_store(backend)
        run = Recorder()
        await store.run(
            "ticket.create", "k1", {"n": 1, "ts": 1}, run, fingerprint_exclude=["ts"]
        )
        result = await store.run(
            "ticket.create", "k1", {"n": 1, "ts": 999}, run, fingerprint_exclude=["ts"]
        )
        assert run.calls == 1
        assert result[REPLAY_FLAG] is True

    async def test_namespace_override_isolates_tenants(self, backend_factory):
        backend, _ = backend_factory()
        store = make_store(backend)
        run = Recorder()
        await store.run("ticket.create", "k1", {"n": 1}, run, namespace="a")
        await store.run("ticket.create", "k1", {"n": 1}, run, namespace="b")
        assert run.calls == 2


class TestStoreFailures:
    async def test_executor_error_propagates(self, backend_factory):
        backend, _ = backend_factory()
        store = make_store(backend)
        run = Recorder(error=ValueError("GLPI fora do ar"))
        with pytest.raises(ValueError):
            await store.run("ticket.create", "k1", {"n": 1}, run)

    async def test_failures_are_never_cached(self, backend_factory):
        """A transient GLPI error must not become a permanently replayed error."""
        backend, _ = backend_factory()
        store = make_store(backend)
        failing = Recorder(error=ValueError("timeout"))
        with pytest.raises(ValueError):
            await store.run("ticket.create", "k1", {"n": 1}, failing)

        succeeding = Recorder({"id": 5})
        result = await store.run("ticket.create", "k1", {"n": 1}, succeeding)
        assert result == {"id": 5}
        assert succeeding.calls == 1

    async def test_failed_call_releases_the_lease(self, backend_factory, key):
        backend, _ = backend_factory()
        store = make_store(backend)
        with pytest.raises(ValueError):
            await store.run(
                "ticket.create", "k-1", {"n": 1}, Recorder(error=ValueError("x"))
            )
        assert await backend.get(key) is None


class TestGracefulDegradation:
    async def test_begin_failure_still_executes(self):
        store = make_store(BrokenBackend(fail_on=("begin",)))
        run = Recorder({"id": 1})
        result = await store.run("ticket.create", "k1", {"n": 1}, run)
        assert result == {"id": 1}
        assert run.calls == 1
        assert store.is_degraded is True

    async def test_begin_failure_loses_deduplication_but_not_the_write(self):
        """Explicit trade-off: duplicates are possible while storage is down."""
        store = make_store(BrokenBackend(fail_on=("begin",)))
        run = Recorder()
        await store.run("ticket.create", "k1", {"n": 1}, run)
        await store.run("ticket.create", "k1", {"n": 1}, run)
        assert run.calls == 2

    async def test_complete_failure_still_returns_the_real_result(self):
        store = make_store(BrokenBackend(fail_on=("complete", "discard")))
        run = Recorder({"id": 7})
        result = await store.run("ticket.create", "k1", {"n": 1}, run)
        assert result == {"id": 7}
        assert store.is_degraded is True

    async def test_discard_failure_does_not_mask_the_business_error(self):
        store = make_store(BrokenBackend(fail_on=("discard",)))
        with pytest.raises(ValueError):
            await store.run(
                "ticket.create", "k1", {"n": 1}, Recorder(error=ValueError("boom"))
            )

    async def test_unexpected_backend_exception_is_degraded(self):
        class Exploding(MemoryIdempotencyBackend):
            async def begin(self, *args, **kwargs):
                raise RuntimeError("erro inesperado")

        store = make_store(Exploding())
        run = Recorder({"id": 2})
        assert await store.run("ticket.create", "k1", {"n": 1}, run) == {"id": 2}
        assert run.calls == 1

    async def test_unwritable_sqlite_degrades_instead_of_blocking(self, tmp_path):
        """Real backend, real failure: the ticket still gets created."""
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        backend = SQLiteIdempotencyBackend(db_path=blocker / "sub" / "idem.sqlite3")
        store = make_store(backend)
        run = Recorder({"id": 1})
        assert await store.run("ticket.create", "k1", {"n": 1}, run) == {"id": 1}
        assert run.calls == 1
        assert store.is_degraded is True

    async def test_purge_failure_never_breaks_a_write(self):
        class BadPurge(MemoryIdempotencyBackend):
            async def purge_expired(self):
                raise IdempotencyBackendError("falha ao limpar")

        store = make_store(BadPurge(), purge_interval=0.0)
        run = Recorder({"id": 1})
        assert await store.run("ticket.create", "k1", {"n": 1}, run) == {"id": 1}

    async def test_disabled_store_executes_directly(self):
        store = IdempotencyStore(MemoryIdempotencyBackend(), enabled=False)
        run = Recorder()
        await store.run("ticket.create", "k1", {"n": 1}, run)
        await store.run("ticket.create", "k1", {"n": 1}, run)
        assert run.calls == 2

    async def test_store_without_backend_executes_directly(self):
        store = IdempotencyStore(None)
        run = Recorder()
        await store.run("ticket.create", "k1", {"n": 1}, run)
        await store.run("ticket.create", "k1", {"n": 1}, run)
        assert run.calls == 2


class TestConcurrency:
    async def test_two_coroutines_same_key_execute_once(self, backend_factory):
        """The client retried while the first call was still in flight."""
        backend, _ = backend_factory()
        store = make_store(backend)
        run = Recorder({"id": 1}, delay=0.05)

        first, second = await asyncio.gather(
            store.run("ticket.create", "k1", {"n": 1}, run),
            store.run("ticket.create", "k1", {"n": 1}, run),
        )
        assert run.calls == 1
        flags = sorted(bool(r.get(REPLAY_FLAG)) for r in (first, second))
        assert flags == [False, True]

    async def test_many_coroutines_same_key_execute_once(self, backend_factory):
        backend, _ = backend_factory()
        store = make_store(backend)
        run = Recorder({"id": 1}, delay=0.05)
        results = await asyncio.gather(
            *[store.run("ticket.create", "k1", {"n": 1}, run) for _ in range(8)]
        )
        assert run.calls == 1
        assert sum(1 for r in results if r.get(REPLAY_FLAG)) == 7

    async def test_different_keys_run_in_parallel(self, backend_factory):
        backend, _ = backend_factory()
        store = make_store(backend)
        run = Recorder({"id": 1}, delay=0.02)
        await asyncio.gather(
            *[store.run("ticket.create", f"k{i}", {"n": i}, run) for i in range(5)]
        )
        assert run.calls == 5

    async def test_waiter_times_out_when_lease_outlives_the_wait(
        self, backend_factory, key
    ):
        backend, _ = backend_factory()
        store = make_store(backend, wait_timeout=0.05)
        await backend.begin(
            key, payload_fingerprint({"n": 1}), ttl_seconds=100,
            lease_seconds=1000, owner="other-worker",
        )
        run = Recorder()
        with pytest.raises(IdempotencyInProgress):
            await store.run("ticket.create", "k-1", {"n": 1}, run)
        assert run.calls == 0

    async def test_waiter_reclaims_a_dead_lease(self, backend_factory, key):
        """A crashed worker's key must not stay locked until its TTL."""
        backend, clock = backend_factory()
        store = make_store(backend, wait_timeout=5.0)
        await backend.begin(
            key, payload_fingerprint({"n": 1}), ttl_seconds=100,
            lease_seconds=10, owner="dead-worker",
        )
        clock.advance(11)
        run = Recorder({"id": 3})
        assert await store.run("ticket.create", "k-1", {"n": 1}, run) == {"id": 3}
        assert run.calls == 1

    async def test_second_caller_gets_the_first_result(self, backend_factory):
        backend, _ = backend_factory()
        store = make_store(backend)
        run = Recorder({"id": 123, "name": "chamado"}, delay=0.05)
        first, second = await asyncio.gather(
            store.run("ticket.create", "k1", {"n": 1}, run),
            store.run("ticket.create", "k1", {"n": 1}, run),
        )
        replayed = second if second.get(REPLAY_FLAG) else first
        assert replayed["id"] == 123
        assert replayed["name"] == "chamado"


class TestStoreHelpers:
    def test_mark_replayed_on_dict(self):
        from src.security.idempotency import IdempotencyRecord

        record = IdempotencyRecord(
            namespace="t1",
            operation="ticket.create",
            key="k1",
            fingerprint="fp",
            state="completed",
            created_at=10.0,
        )
        marked = mark_replayed({"id": 1}, record)
        assert marked == {
            "id": 1,
            REPLAY_FLAG: True,
            "idempotency_key": "k1",
            "idempotency_operation": "ticket.create",
            "first_executed_at": 10.0,
        }

    def test_mark_replayed_does_not_mutate_the_original(self):
        from src.security.idempotency import IdempotencyRecord

        record = IdempotencyRecord("t1", "op", "k", "fp", "completed")
        original = {"id": 1}
        mark_replayed(original, record)
        assert original == {"id": 1}

    async def test_status_reports_configuration(self, backend_factory):
        backend, _ = backend_factory()
        store = make_store(backend)
        status = store.status()
        assert status["enabled"] is True
        assert status["namespace"] == "t1"
        assert status["degraded"] is False
        assert status["backend"] == type(backend).__name__


class TestStoreFactories:
    def test_build_backend_by_name(self):
        assert isinstance(build_backend("memory"), MemoryIdempotencyBackend)
        assert isinstance(build_backend("sqlite"), SQLiteIdempotencyBackend)
        assert build_backend("none") is None
        assert build_backend("") is None

    def test_unknown_backend_degrades_to_none(self):
        assert build_backend("redis") is None

    def test_build_store_from_env_defaults(self):
        store = build_store_from_env({})
        assert store.enabled is True
        assert store.namespace == DEFAULT_NAMESPACE
        assert store.ttl_seconds == DEFAULT_TTL_SECONDS
        assert isinstance(store.backend, SQLiteIdempotencyBackend)
        assert DEFAULT_BACKEND == "sqlite"

    def test_build_store_from_env_overrides(self, tmp_path):
        store = build_store_from_env(
            {
                ENV_BACKEND: "sqlite",
                ENV_DB_PATH: str(tmp_path / "custom.sqlite3"),
                ENV_NAMESPACE: "cliente-x",
                ENV_TTL_SECONDS: "60",
            }
        )
        assert store.namespace == "cliente-x"
        assert store.ttl_seconds == 60.0
        assert store.backend.db_path == tmp_path / "custom.sqlite3"

    def test_build_store_from_env_disabled(self):
        store = build_store_from_env({ENV_ENABLED: "false"})
        assert store.enabled is False
        assert store.backend is None

    def test_invalid_numbers_fall_back_to_defaults(self):
        store = build_store_from_env({ENV_TTL_SECONDS: "nao-e-numero"})
        assert store.ttl_seconds == DEFAULT_TTL_SECONDS

    def test_negative_ttl_falls_back_to_default(self):
        store = build_store_from_env({ENV_TTL_SECONDS: "-5"})
        assert store.ttl_seconds == DEFAULT_TTL_SECONDS

    def test_singleton_is_reused_and_replaceable(self):
        first = get_idempotency_store()
        assert get_idempotency_store() is first
        replacement = IdempotencyStore(None)
        set_idempotency_store(replacement)
        assert get_idempotency_store() is replacement
        reset_idempotency_store()
        assert get_idempotency_store() is not replacement


# ===========================================================================
# Write policy
# ===========================================================================


class TestOperationRegistry:
    def test_every_operation_has_a_spec(self):
        assert set(WRITE_OPERATIONS) == set(WriteOperation)

    def test_env_var_naming_is_systematic(self):
        for operation, spec in WRITE_OPERATIONS.items():
            assert spec.env_var.startswith("GLPI_ALLOW_")
            assert spec.env_var == operation_env_var(operation)

    def test_env_var_names_are_unique(self):
        names = [spec.env_var for spec in WRITE_OPERATIONS.values()]
        assert len(names) == len(set(names))
        assert len(WRITE_ENV_VARS) == len(names)

    def test_specific_env_var_names(self):
        assert operation_env_var(WriteOperation.TICKET_CREATE) == (
            "GLPI_ALLOW_TICKET_CREATE"
        )
        assert operation_env_var(WriteOperation.ASSET_RESERVATION_CREATE) == (
            "GLPI_ALLOW_ASSET_RESERVATION_CREATE"
        )

    def test_descriptions_have_no_accents(self):
        """User-facing text must stay ASCII per project convention."""
        for spec in WRITE_OPERATIONS.values():
            assert spec.description.isascii(), spec.description

    def test_destructive_operations_default_to_disabled(self):
        for operation in DESTRUCTIVE_OPERATIONS:
            assert WRITE_OPERATIONS[operation].default_enabled is False

    def test_non_destructive_operations_default_to_enabled(self):
        for spec in WRITE_OPERATIONS.values():
            if not spec.destructive:
                assert spec.default_enabled is True

    def test_delete_operations_are_marked_destructive(self):
        deletes = {op for op in WriteOperation if op.value.endswith(".delete")}
        assert deletes == DESTRUCTIVE_OPERATIONS

    def test_safety_guard_links_match_the_existing_guard(self):
        """The policy must reference the guard's real operation names."""
        from src.utils.safety_guard import SafetyGuard

        linked = {
            spec.safety_guard_operation
            for spec in WRITE_OPERATIONS.values()
            if spec.safety_guard_operation
        }
        assert linked <= set(SafetyGuard.PROTECTED_OPERATIONS)

    def test_every_destructive_operation_has_a_safety_guard(self):
        """No destructive operation may rely on the policy alone.

        This test used to assert the opposite for locations: the guard covered
        ticket, asset, user and webhook, and deleting a location went through
        with no confirmation at all. That asymmetry was an accident of how the
        guard grew, so both location and group deletion were added to it. The
        assertion is now the invariant, not the exception.
        """
        unguarded = sorted(
            spec.operation.value
            for spec in WRITE_OPERATIONS.values()
            if spec.destructive and not spec.safety_guard_operation
        )
        assert unguarded == [], f"operacoes destrutivas sem guard: {unguarded}"

    def test_location_delete_is_guarded(self):
        spec = WRITE_OPERATIONS[WriteOperation.LOCATION_DELETE]
        assert spec.destructive is True
        assert spec.safety_guard_operation == "delete_location"

    def test_registry_is_immutable(self):
        with pytest.raises(TypeError):
            WRITE_OPERATIONS[WriteOperation.TICKET_CREATE] = None


class TestResolveOperation:
    @pytest.mark.parametrize(
        "domain,action,resource,expected",
        [
            ("tickets", "create", None, WriteOperation.TICKET_CREATE),
            ("tickets", "add_followup", None, WriteOperation.TICKET_ADD_FOLLOWUP),
            ("tickets", "resolve", None, WriteOperation.TICKET_RESOLVE),
            ("assets", "create_reservation", None,
             WriteOperation.ASSET_RESERVATION_CREATE),
            ("admin", "create", "users", WriteOperation.USER_CREATE),
            ("admin", "delete", "groups", WriteOperation.GROUP_DELETE),
            ("admin", "update", "locations", WriteOperation.LOCATION_UPDATE),
            ("webhooks", "retry", None, WriteOperation.WEBHOOK_RETRY),
            ("ai_analysis", "publish", None, WriteOperation.AI_ANALYSIS_PUBLISH),
        ],
    )
    def test_known_write_actions_resolve(self, domain, action, resource, expected):
        assert resolve_operation(domain, action, resource) is expected

    @pytest.mark.parametrize(
        "domain,action,resource",
        [
            ("tickets", "get", None),
            ("tickets", "get_history", None),
            ("tickets", "find_similar", None),
            ("assets", "get_details", None),
            ("admin", "get", "users"),
            ("admin", "create", "entities"),  # entities are read-only in this MCP
            ("webhooks", "get", None),
            ("ai_analysis", "get_result", None),
        ],
    )
    def test_read_actions_resolve_to_none(self, domain, action, resource):
        assert resolve_operation(domain, action, resource) is None

    def test_resolution_is_case_insensitive(self):
        assert resolve_operation("TICKETS", "CREATE") is WriteOperation.TICKET_CREATE
        assert resolve_operation("Admin", "Create", "Users") is (
            WriteOperation.USER_CREATE
        )

    def test_admin_without_resource_resolves_to_none(self):
        assert resolve_operation("admin", "create") is None

    def test_unknown_domain_resolves_to_none(self):
        assert resolve_operation("inexistente", "create") is None


class TestWritePolicyDefaults:
    def test_non_destructive_write_allowed_by_default(self):
        policy = WritePolicy(env={})
        assert policy.is_enabled(WriteOperation.TICKET_CREATE) is True
        policy.check(WriteOperation.TICKET_CREATE)

    def test_destructive_write_blocked_by_default(self):
        policy = WritePolicy(env={})
        assert policy.is_enabled(WriteOperation.TICKET_DELETE) is False
        with pytest.raises(WriteNotAllowedError):
            policy.check(WriteOperation.TICKET_DELETE)

    def test_not_read_only_by_default(self):
        assert WritePolicy(env={}).is_read_only is False

    @pytest.mark.parametrize("operation", list(WriteOperation))
    def test_every_operation_can_be_enabled(self, operation):
        spec = WRITE_OPERATIONS[operation]
        policy = WritePolicy(env={spec.env_var: "true"})
        assert policy.is_enabled(operation) is True
        policy.check(operation)

    @pytest.mark.parametrize("operation", list(WriteOperation))
    def test_every_operation_can_be_blocked(self, operation):
        spec = WRITE_OPERATIONS[operation]
        policy = WritePolicy(env={spec.env_var: "false"})
        assert policy.is_enabled(operation) is False
        with pytest.raises(WriteNotAllowedError):
            policy.check(operation)

    @pytest.mark.parametrize(
        "value", ["true", "TRUE", "1", "yes", "on", "sim", " true "]
    )
    def test_truthy_values(self, value):
        policy = WritePolicy(env={"GLPI_ALLOW_TICKET_DELETE": value})
        assert policy.is_enabled(WriteOperation.TICKET_DELETE) is True

    @pytest.mark.parametrize("value", ["false", "FALSE", "0", "no", "off", "nao"])
    def test_falsy_values(self, value):
        policy = WritePolicy(env={"GLPI_ALLOW_TICKET_CREATE": value})
        assert policy.is_enabled(WriteOperation.TICKET_CREATE) is False

    def test_garbage_value_falls_back_to_the_default(self):
        policy = WritePolicy(env={"GLPI_ALLOW_TICKET_CREATE": "talvez"})
        assert policy.is_enabled(WriteOperation.TICKET_CREATE) is True

    def test_empty_value_falls_back_to_the_default(self):
        policy = WritePolicy(env={"GLPI_ALLOW_TICKET_DELETE": "   "})
        assert policy.is_enabled(WriteOperation.TICKET_DELETE) is False

    def test_enabling_one_operation_does_not_enable_its_neighbours(self):
        policy = WritePolicy(env={"GLPI_ALLOW_TICKET_DELETE": "true"})
        assert policy.is_enabled(WriteOperation.TICKET_DELETE) is True
        assert policy.is_enabled(WriteOperation.USER_DELETE) is False


class TestReadOnlyMode:
    @pytest.mark.parametrize("operation", list(WriteOperation))
    def test_read_only_blocks_everything(self, operation):
        policy = WritePolicy(env={ENV_READ_ONLY: "true"})
        assert policy.is_enabled(operation) is False
        with pytest.raises(WriteNotAllowedError):
            policy.check(operation)

    def test_read_only_overrides_explicit_allow(self):
        policy = WritePolicy(
            env={ENV_READ_ONLY: "true", "GLPI_ALLOW_TICKET_CREATE": "true"}
        )
        with pytest.raises(WriteNotAllowedError) as exc:
            policy.check(WriteOperation.TICKET_CREATE)
        assert exc.value.reason == REASON_READ_ONLY

    def test_read_only_flag_is_exposed(self):
        assert WritePolicy(env={ENV_READ_ONLY: "true"}).is_read_only is True

    def test_read_only_message_names_the_variable(self):
        policy = WritePolicy(env={ENV_READ_ONLY: "true"})
        with pytest.raises(WriteNotAllowedError) as exc:
            policy.check(WriteOperation.TICKET_CREATE)
        assert ENV_READ_ONLY in exc.value.message
        assert "somente leitura" in exc.value.message


class TestErrorMessages:
    def test_disabled_message_names_the_enabling_variable(self):
        policy = WritePolicy(env={})
        with pytest.raises(WriteNotAllowedError) as exc:
            policy.check(WriteOperation.USER_DELETE)
        assert "GLPI_ALLOW_USER_DELETE=true" in exc.value.message
        assert exc.value.reason == REASON_DISABLED

    def test_messages_have_no_accents(self):
        policy = WritePolicy(env={ENV_READ_ONLY: "false"})
        for operation in DESTRUCTIVE_OPERATIONS:
            with pytest.raises(WriteNotAllowedError) as exc:
                policy.check(operation)
            assert exc.value.message.isascii(), exc.value.message

    def test_read_only_messages_have_no_accents(self):
        policy = WritePolicy(env={ENV_READ_ONLY: "true"})
        for operation in WriteOperation:
            with pytest.raises(WriteNotAllowedError) as exc:
                policy.check(operation)
            assert exc.value.message.isascii(), exc.value.message

    def test_error_uses_http_403_for_jsonrpc_mapping(self):
        from src.models.exceptions import HTTP_TO_JSONRPC

        policy = WritePolicy(env={})
        with pytest.raises(WriteNotAllowedError) as exc:
            policy.check(WriteOperation.TICKET_DELETE)
        assert exc.value.code == 403
        assert HTTP_TO_JSONRPC[403] == -32001

    def test_error_details_carry_machine_readable_context(self):
        policy = WritePolicy(env={})
        with pytest.raises(WriteNotAllowedError) as exc:
            policy.check(WriteOperation.ASSET_DELETE)
        assert exc.value.details["operation"] == "asset.delete"
        assert exc.value.details["env_var"] == "GLPI_ALLOW_ASSET_DELETE"
        assert exc.value.details["reason"] == REASON_DISABLED


class TestProfiles:
    def test_read_only_profile_blocks_every_operation(self):
        policy = WritePolicy(env={})
        policy.apply_profile(PROFILE_READ_ONLY)
        assert policy.is_read_only is True
        for operation in WriteOperation:
            assert policy.is_enabled(operation) is False

    def test_ticket_operator_can_work_tickets(self):
        policy = WritePolicy(env={})
        policy.apply_profile(PROFILE_TICKET_OPERATOR)
        for operation in (
            WriteOperation.TICKET_CREATE,
            WriteOperation.TICKET_UPDATE,
            WriteOperation.TICKET_ASSIGN,
            WriteOperation.TICKET_CLOSE,
            WriteOperation.TICKET_RESOLVE,
            WriteOperation.TICKET_ADD_FOLLOWUP,
        ):
            policy.check(operation)

    def test_ticket_operator_cannot_delete_or_administer(self):
        policy = WritePolicy(env={})
        policy.apply_profile(PROFILE_TICKET_OPERATOR)
        for operation in (
            WriteOperation.TICKET_DELETE,
            WriteOperation.USER_CREATE,
            WriteOperation.USER_DELETE,
            WriteOperation.WEBHOOK_CREATE,
            WriteOperation.ASSET_CREATE,
        ):
            with pytest.raises(WriteNotAllowedError):
                policy.check(operation)

    def test_administrator_allows_everything(self):
        policy = WritePolicy(env={})
        policy.apply_profile(PROFILE_ADMINISTRATOR)
        for operation in WriteOperation:
            policy.check(operation)

    def test_profile_environment_is_explicit_for_every_operation(self):
        env = PROFILE_TICKET_OPERATOR.as_environment()
        assert env[ENV_READ_ONLY] == "false"
        for spec in WRITE_OPERATIONS.values():
            assert spec.env_var in env
            assert env[spec.env_var] in ("true", "false")

    def test_profile_environment_round_trips_through_the_policy(self):
        """Exporting a profile must reproduce it exactly, defaults aside."""
        for profile in WRITE_PROFILES.values():
            env = profile.as_environment()
            policy = WritePolicy(env=env)
            for operation in WriteOperation:
                expected = (not profile.read_only) and operation in profile.allowed
                assert policy.is_enabled(operation) is expected, (
                    f"{profile.name}/{operation.value}"
                )

    def test_read_only_profile_environment_sets_the_global_switch(self):
        env = PROFILE_READ_ONLY.as_environment()
        assert env[ENV_READ_ONLY] == "true"
        assert all(v == "false" for k, v in env.items() if k != ENV_READ_ONLY)

    def test_profile_descriptions_have_no_accents(self):
        for profile in WRITE_PROFILES.values():
            assert profile.description.isascii(), profile.description

    def test_registered_profile_names(self):
        assert set(WRITE_PROFILES) == {
            "read_only",
            "ticket_operator",
            "administrator",
        }


class TestPolicyIntegration:
    def test_check_tool_action_allows_a_read(self):
        policy = WritePolicy(env={ENV_READ_ONLY: "true"})
        assert policy.check_tool_action("tickets", "get") is None

    def test_check_tool_action_blocks_a_write(self):
        policy = WritePolicy(env={ENV_READ_ONLY: "true"})
        with pytest.raises(WriteNotAllowedError):
            policy.check_tool_action("tickets", "create")

    def test_check_tool_action_returns_the_resolved_operation(self):
        policy = WritePolicy(env={})
        resolved = policy.check_tool_action("admin", "create", "users")
        assert resolved is WriteOperation.USER_CREATE

    def test_reload_picks_up_environment_changes(self):
        env = {}
        policy = WritePolicy(env=env)
        assert policy.is_enabled(WriteOperation.TICKET_DELETE) is False
        env["GLPI_ALLOW_TICKET_DELETE"] = "true"
        assert policy.is_enabled(WriteOperation.TICKET_DELETE) is False  # cached
        policy.reload()
        assert policy.is_enabled(WriteOperation.TICKET_DELETE) is True

    def test_status_lists_enabled_and_blocked(self):
        policy = WritePolicy(env={})
        status = policy.status()
        assert "ticket.create" in status["enabled_operations"]
        assert "ticket.delete" in status["blocked_operations"]
        assert status["total_operations"] == len(WriteOperation)
        assert status["env_vars"]["ticket.create"] == "GLPI_ALLOW_TICKET_CREATE"

    def test_describe_returns_the_spec(self):
        policy = WritePolicy(env={})
        spec = policy.describe(WriteOperation.TICKET_DELETE)
        assert spec.env_var == "GLPI_ALLOW_TICKET_DELETE"
        assert spec.destructive is True

    def test_singleton_is_reused_and_replaceable(self):
        first = get_write_policy()
        assert get_write_policy() is first
        replacement = WritePolicy(env={ENV_READ_ONLY: "true"})
        set_write_policy(replacement)
        assert get_write_policy() is replacement

    def test_require_write_allowed_uses_the_singleton(self):
        set_write_policy(WritePolicy(env={ENV_READ_ONLY: "true"}))
        with pytest.raises(WriteNotAllowedError):
            require_write_allowed(WriteOperation.TICKET_CREATE)

    def test_require_write_allowed_passes_when_enabled(self):
        set_write_policy(WritePolicy(env={}))
        require_write_allowed(WriteOperation.TICKET_CREATE)


class TestGuardComposition:
    """The policy complements the safety guard; it does not replace it."""

    def test_policy_covers_creation_which_the_guard_ignores(self):
        from src.utils.safety_guard import SafetyGuard

        assert "create_ticket" not in SafetyGuard.PROTECTED_OPERATIONS
        assert WriteOperation.TICKET_CREATE in WRITE_OPERATIONS

    def test_policy_does_not_reimplement_confirmation_tokens(self):
        """No token comparison lives here: that stays in safety_guard."""
        import inspect

        from src.security import write_policy

        source = inspect.getsource(write_policy)
        assert "MCP_SAFETY_TOKEN" not in source
        assert "compare_digest" not in source

    def test_every_guarded_delete_is_also_in_the_policy(self):
        from src.utils.safety_guard import SafetyGuard

        linked = {
            spec.safety_guard_operation
            for spec in WRITE_OPERATIONS.values()
            if spec.safety_guard_operation
        }
        assert set(SafetyGuard.PROTECTED_OPERATIONS) == linked
