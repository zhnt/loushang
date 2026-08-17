from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

from loushang.harness.runtime import SessionOperationPhase
from loushang.harness.session.lifecycle import (
    DEFAULT_FORK_PROFILE,
    ForkProfile,
    ForkSelection,
    MissingSessionCwdError,
    PreparedSessionOperationStateError,
    SessionCwdIssue,
    SessionLifecycleDecision,
    SessionLifecycleHooks,
    SessionLifecyclePreparationCancelledError,
    SessionLifecycleRuntime,
    SessionLifecycleTransition,
)
from loushang.harness.session.lifecycle import (
    __all__ as lifecycle_exports,
)


@dataclass(frozen=True)
class _Session:
    ref: str
    cwd: str
    leaf_id: str = "leaf"


class _Store:
    def __init__(self, *, restored_cwd: str | None = None) -> None:
        self.restored_cwd = restored_cwd
        self.actions: list[tuple[object, ...]] = []

    async def create(
        self,
        current: _Session | None,
        transition: SessionLifecycleTransition,
        *,
        cwd: str,
        parent_session_ref: str | None,
    ) -> _Session:
        self.actions.append(
            ("create", current, transition.reason, cwd, parent_session_ref)
        )
        return _Session("new", cwd)

    async def restore(
        self,
        current: _Session | None,
        transition: SessionLifecycleTransition,
        session_ref: str | Path,
        *,
        cwd_override: str | None = None,
    ) -> _Session:
        cwd = cwd_override or self.restored_cwd or "/missing"
        self.actions.append(
            ("restore", current, transition.reason, str(session_ref), cwd_override)
        )
        return _Session(str(session_ref), cwd)

    async def fork(
        self,
        session: _Session,
        transition: SessionLifecycleTransition,
        target_entry_id: str | None,
    ) -> _Session:
        self.actions.append(
            ("fork", session, transition.fork_position, target_entry_id)
        )
        return _Session("fork", session.cwd)

    def get_cwd(self, session: _Session) -> str:
        return session.cwd

    def get_session_ref(self, session: _Session) -> str:
        return session.ref

    def get_leaf_entry_id(self, session: _Session) -> str:
        return session.leaf_id


def test_lifecycle_default_profile_forks_at_selected_entry(
    tmp_path: Path,
) -> None:
    store = _Store()
    disposed: list[str] = []
    lifecycle = SessionLifecycleRuntime[_Session, str](
        store=store,
        current_session=_Session("current", str(tmp_path)),
        hooks=SessionLifecycleHooks(
            dispose_session=lambda session: disposed.append(session.ref)
        ),
    )

    result = asyncio.run(lifecycle.fork("selected"))

    assert result.current == _Session("fork", str(tmp_path))
    assert result.payload is None
    assert store.actions == [
        ("fork", _Session("current", str(tmp_path)), "at", "selected"),
    ]
    assert disposed == ["current"]
    assert lifecycle.fork_profile is DEFAULT_FORK_PROFILE


def test_lifecycle_accepts_product_fork_profile_and_resolver(
    tmp_path: Path,
) -> None:
    store = _Store()
    lifecycle = SessionLifecycleRuntime[_Session, str](
        store=store,
        current_session=_Session("current", str(tmp_path)),
        hooks=SessionLifecycleHooks(dispose_session=lambda _session: None),
        fork_profile=ForkProfile(
            default_position="before",
            supported_positions=frozenset({"at", "before"}),
        ),
        fork_target_resolver=lambda _session, entry_id, position: ForkSelection(
            target_entry_id=None if position == "before" else entry_id,
            payload=f"{position}:{entry_id}",
        ),
    )

    result = asyncio.run(lifecycle.fork("selected"))

    assert result.payload == "before:selected"
    assert store.actions[-1] == (
        "fork",
        _Session("current", str(tmp_path)),
        "before",
        None,
    )


def test_fork_profile_rejects_invalid_default() -> None:
    with pytest.raises(ValueError, match="must be one of"):
        ForkProfile(default_position="before", supported_positions=frozenset({"at"}))


def test_lifecycle_cancellation_prevents_store_and_replacement(
    tmp_path: Path,
) -> None:
    store = _Store()
    disposed: list[str] = []
    lifecycle = SessionLifecycleRuntime[_Session, object](
        store=store,
        current_session=_Session("current", str(tmp_path)),
        hooks=SessionLifecycleHooks(
            before_transition=lambda _session, transition: SessionLifecycleDecision(
                cancelled=transition.reason == "new"
            ),
            dispose_session=lambda session: disposed.append(session.ref),
        ),
    )

    result = asyncio.run(lifecycle.new(cwd=str(tmp_path)))

    assert result.cancelled is True
    assert result.current == _Session("current", str(tmp_path))
    assert store.actions == []
    assert disposed == []


def test_lifecycle_restore_uses_configured_fallback_cwd(tmp_path: Path) -> None:
    store = _Store(restored_cwd="/missing")
    disposed: list[str] = []
    lifecycle = SessionLifecycleRuntime[_Session, object](
        store=store,
        hooks=SessionLifecycleHooks(
            dispose_session=lambda session: disposed.append(session.ref)
        ),
    )

    result = asyncio.run(
        lifecycle.restore(
            "saved.jsonl",
            fallback_cwd=str(tmp_path),
            missing_cwd="fallback",
        )
    )

    assert result.current == _Session("saved.jsonl", str(tmp_path))
    assert store.actions == [
        ("restore", None, "resume", "saved.jsonl", None),
        ("restore", None, "resume", "saved.jsonl", str(tmp_path)),
    ]
    assert disposed == ["saved.jsonl"]


def test_lifecycle_prepared_restore_stages_before_atomic_publish(
    tmp_path: Path,
) -> None:
    store = _Store(restored_cwd=str(tmp_path))
    disposed: list[str] = []
    current = _Session("current", str(tmp_path))
    lifecycle = SessionLifecycleRuntime[_Session, object](
        store=store,
        current_session=current,
        hooks=SessionLifecycleHooks(
            dispose_session=lambda session: disposed.append(session.ref)
        ),
    )

    async def scenario() -> None:
        prepared = await lifecycle.prepare_restore("saved.jsonl")

        assert lifecycle.current_session is current
        assert prepared.consumed is False
        assert disposed == []

        result = await prepared.consume()

        assert result.previous is current
        assert result.current == _Session("saved.jsonl", str(tmp_path))
        assert prepared.consumed is True
        assert disposed == ["current"]

    asyncio.run(scenario())


def test_lifecycle_prepared_restore_abort_releases_unpublished_candidate(
    tmp_path: Path,
) -> None:
    store = _Store(restored_cwd=str(tmp_path))
    disposed: list[str] = []
    current = _Session("current", str(tmp_path))
    lifecycle = SessionLifecycleRuntime[_Session, object](
        store=store,
        current_session=current,
        hooks=SessionLifecycleHooks(
            dispose_session=lambda session: disposed.append(session.ref)
        ),
    )

    async def scenario() -> None:
        prepared = await lifecycle.prepare_restore("saved.jsonl")
        await prepared.abort()
        await prepared.abort()

        assert lifecycle.current_session is current
        assert prepared.consumed is False
        assert disposed == ["saved.jsonl"]

    asyncio.run(scenario())


def test_lifecycle_prepared_restore_uses_the_shared_cwd_fallback(
    tmp_path: Path,
) -> None:
    store = _Store(restored_cwd="/missing")
    disposed: list[str] = []
    lifecycle = SessionLifecycleRuntime[_Session, object](
        store=store,
        hooks=SessionLifecycleHooks(
            dispose_session=lambda session: disposed.append(session.ref)
        ),
    )

    async def scenario() -> None:
        prepared = await lifecycle.prepare_restore(
            "saved.jsonl",
            fallback_cwd=str(tmp_path),
            missing_cwd="fallback",
        )
        assert lifecycle.current_session is None
        assert disposed == ["saved.jsonl"]

        result = await prepared.consume()
        assert result.current == _Session("saved.jsonl", str(tmp_path))

    asyncio.run(scenario())
    assert store.actions == [
        ("restore", None, "resume", "saved.jsonl", None),
        ("restore", None, "resume", "saved.jsonl", str(tmp_path)),
    ]


def test_lifecycle_prepared_restore_cancellation_does_not_create_candidate(
    tmp_path: Path,
) -> None:
    store = _Store(restored_cwd=str(tmp_path))
    current = _Session("current", str(tmp_path))
    lifecycle = SessionLifecycleRuntime[_Session, object](
        store=store,
        current_session=current,
        hooks=SessionLifecycleHooks(
            before_transition=lambda _session, _transition: SessionLifecycleDecision(
                cancelled=True
            ),
            dispose_session=lambda _session: None,
        ),
    )

    with pytest.raises(SessionLifecyclePreparationCancelledError):
        asyncio.run(lifecycle.prepare_restore("saved.jsonl"))

    assert lifecycle.current_session is current
    assert store.actions == []


def test_lifecycle_prepared_restore_rejects_stale_and_repeated_consumption(
    tmp_path: Path,
) -> None:
    store = _Store(restored_cwd=str(tmp_path))
    disposed: list[str] = []
    current = _Session("current", str(tmp_path))
    replacement = _Session("replacement", str(tmp_path))
    lifecycle = SessionLifecycleRuntime[_Session, object](
        store=store,
        current_session=current,
        hooks=SessionLifecycleHooks(
            dispose_session=lambda session: disposed.append(session.ref)
        ),
    )

    async def scenario() -> None:
        prepared = await lifecycle.prepare_restore("saved.jsonl")
        await lifecycle.replace(replacement)

        with pytest.raises(
            PreparedSessionOperationStateError,
            match="active session changed",
        ):
            await prepared.consume()
        with pytest.raises(
            PreparedSessionOperationStateError,
            match="closed",
        ):
            await prepared.consume()

    asyncio.run(scenario())
    assert lifecycle.current_session is replacement
    assert disposed == ["current", "saved.jsonl"]


def test_lifecycle_transition_preserves_transaction_hook_order(tmp_path: Path) -> None:
    events: list[str] = []

    class _OrderedStore(_Store):
        async def create(self, *args, **kwargs):
            events.append("create")
            return await super().create(*args, **kwargs)

    lifecycle = SessionLifecycleRuntime[_Session, object](
        store=_OrderedStore(),
        current_session=_Session("current", str(tmp_path)),
        hooks=SessionLifecycleHooks(
            before_transition=lambda _session, _transition: events.append("before"),
            prepare_session=lambda _session, _previous, _transition: events.append(
                "prepare"
            ),
            before_release=lambda _session, _target, _transition: events.append(
                "release"
            ),
            dispose_session=lambda _session: events.append("dispose"),
            activate_session=lambda _session, _previous, _transition: events.append(
                "activate"
            ),
            after_commit=lambda _result, _transition: events.append("commit"),
        ),
    )

    asyncio.run(lifecycle.new(cwd=str(tmp_path)))

    assert events == [
        "before",
        "create",
        "prepare",
        "release",
        "dispose",
        "activate",
        "commit",
    ]


def test_lifecycle_reports_missing_cwd_without_fallback() -> None:
    lifecycle = SessionLifecycleRuntime[_Session, object](
        store=_Store(restored_cwd="/missing"),
        hooks=SessionLifecycleHooks(dispose_session=lambda _session: None),
    )

    with pytest.raises(MissingSessionCwdError) as exc_info:
        asyncio.run(lifecycle.restore("saved.jsonl"))

    assert exc_info.value.issue.session_ref == "saved.jsonl"


def test_lifecycle_preserves_fallback_for_store_prevalidation() -> None:
    class _PrevalidatingStore(_Store):
        async def restore(
            self,
            current: _Session | None,
            transition: SessionLifecycleTransition,
            session_ref: str | Path,
            *,
            cwd_override: str | None = None,
        ) -> _Session:
            del current, transition, cwd_override
            raise MissingSessionCwdError(
                SessionCwdIssue(
                    session_cwd="/missing",
                    session_ref=str(session_ref),
                )
            )

    lifecycle = SessionLifecycleRuntime[_Session, object](
        store=_PrevalidatingStore(),
        hooks=SessionLifecycleHooks(dispose_session=lambda _session: None),
    )

    with pytest.raises(MissingSessionCwdError) as exc_info:
        asyncio.run(
            lifecycle.restore(
                "saved.jsonl",
                fallback_cwd="/fallback",
                missing_cwd="error",
            )
        )

    assert exc_info.value.issue.fallback_cwd == "/fallback"


def test_lifecycle_reports_import_preflight_failure(tmp_path: Path) -> None:
    failures = []
    lifecycle = SessionLifecycleRuntime[_Session, object](
        store=_Store(),
        hooks=SessionLifecycleHooks(
            dispose_session=lambda _session: None,
            on_failure=lambda failure, transition: failures.append(
                (failure, transition)
            ),
        ),
    )

    with pytest.raises(FileNotFoundError):
        asyncio.run(
            lifecycle.import_file(
                tmp_path / "missing.jsonl",
                destination_dir=tmp_path / "sessions",
            )
        )

    failure, transition = failures[0]
    assert failure.phase is SessionOperationPhase.PREPARE
    assert transition.target_session_ref == str(tmp_path / "missing.jsonl")


def test_lifecycle_module_exports_prepared_operation_contracts() -> None:
    assert {
        "PreparedSessionLifecycleOperation",
        "PreparedSessionOperationStateError",
        "SessionLifecyclePreparationCancelledError",
    } <= set(lifecycle_exports)
