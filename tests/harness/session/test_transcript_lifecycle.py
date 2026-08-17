from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.session import (
    AgentTranscriptSessionRuntime,
    ProductTranscriptSessionBinding,
    ProductTranscriptSessionLifecyclePorts,
    ProductTranscriptSessionLifecycleStore,
    SessionDiagnosticScope,
    SessionDiagnosticsRuntime,
    SessionLifecycleHooks,
    SessionLifecycleRuntime,
    SessionLifecycleTransition,
    resolve_fork_target,
)
from loushang.harness.transcript import ProductTranscriptSession


@dataclass(frozen=True)
class _Session:
    ref: str
    cwd: str
    leaf_id: str = "leaf"


class _Store:
    def __init__(self) -> None:
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
        cwd = cwd_override or "/restored"
        self.actions.append(("restore", current, transition.reason, str(session_ref)))
        return _Session(str(session_ref), cwd)

    async def fork(
        self,
        session: _Session,
        transition: SessionLifecycleTransition,
        target_entry_id: str | None,
    ) -> _Session:
        self.actions.append(
            ("fork", session.ref, transition.fork_position, target_entry_id)
        )
        return _Session("fork", session.cwd)

    def get_cwd(self, session: _Session) -> str:
        return session.cwd

    def get_session_ref(self, session: _Session) -> str:
        return session.ref

    def get_leaf_entry_id(self, session: _Session) -> str:
        return session.leaf_id


@dataclass
class _TranscriptSession:
    ref: str
    cwd: str
    leaf_id: str = "leaf"


class _ProductPorts:
    def __init__(self) -> None:
        self.actions: list[tuple[object, ...]] = []
        self.disposed: list[str] = []

    async def create(
        self,
        cwd: str,
        parent_session_ref: str | None,
    ) -> _TranscriptSession:
        self.actions.append(("create", cwd, parent_session_ref))
        return _TranscriptSession("new.jsonl", cwd)

    async def restore(
        self,
        session_ref: str | Path,
        cwd_override: str | None,
    ) -> _TranscriptSession:
        self.actions.append(("restore", str(session_ref), cwd_override))
        return _TranscriptSession(str(session_ref), cwd_override or "/restored")

    async def fork(
        self,
        transcript: _TranscriptSession,
        target_entry_id: str | None,
    ) -> _TranscriptSession:
        self.actions.append(("fork", transcript.ref, target_entry_id))
        return _TranscriptSession("fork.jsonl", transcript.cwd)

    async def dispose(self, transcript: _TranscriptSession) -> None:
        self.disposed.append(transcript.ref)

    @staticmethod
    def transcript_for_session(session: _Session) -> _TranscriptSession:
        return _TranscriptSession(session.ref, session.cwd, session.leaf_id)

    @staticmethod
    def cwd(transcript: _TranscriptSession) -> str:
        return transcript.cwd

    @staticmethod
    def session_ref(transcript: _TranscriptSession) -> str:
        return transcript.ref

    @staticmethod
    def leaf_entry_id(transcript: _TranscriptSession) -> str:
        return transcript.leaf_id

    def lifecycle_ports(
        self,
    ) -> ProductTranscriptSessionLifecyclePorts[_TranscriptSession, _Session]:
        return ProductTranscriptSessionLifecyclePorts(
            create_transcript=self.create,
            restore_transcript=self.restore,
            fork_transcript=self.fork,
            dispose_transcript=self.dispose,
            transcript_for_session=self.transcript_for_session,
            transcript_cwd=self.cwd,
            transcript_session_ref=self.session_ref,
            transcript_leaf_entry_id=self.leaf_entry_id,
        )


def test_transcript_session_runtime_delegates_lifecycle_operations(tmp_path) -> None:
    async def scenario() -> None:
        store = _Store()
        disposed: list[str] = []
        lifecycle = SessionLifecycleRuntime[_Session, object](
            store=store,
            hooks=SessionLifecycleHooks(
                dispose_session=lambda session: disposed.append(session.ref)
            ),
        )
        runtime = AgentTranscriptSessionRuntime(
            session_dir=tmp_path,
            lifecycle=lifecycle,
        )

        created = await runtime.new_session_operation(
            cwd="/project",
            parent_session_ref="parent.jsonl",
            metadata={"operation": "new"},
        )
        assert created.current == _Session("new", "/project")
        assert runtime.session is created.current
        assert runtime.cwd == "/project"

        forked = await runtime.fork_session_operation("leaf", position="at")
        assert forked.current == _Session("fork", "/project")
        assert runtime.get_current_session() is forked.current

        await runtime.dispose_session_runtime(metadata={"operation": "dispose"})
        assert disposed == ["new", "fork"]
        assert store.actions == [
            ("create", None, "new", "/project", "parent.jsonl"),
            ("fork", "new", "at", "leaf"),
        ]

    asyncio.run(scenario())


def test_transcript_session_runtime_resolves_conversation_jsonl_session_id(
    tmp_path,
) -> None:
    session_file = tmp_path / "2026-07-20_demo-session.jsonl"
    session_file.write_text("{}\n", encoding="utf-8")
    lifecycle = SessionLifecycleRuntime[_Session, object](
        store=_Store(),
        hooks=SessionLifecycleHooks(dispose_session=lambda _session: None),
    )
    runtime = AgentTranscriptSessionRuntime(session_dir=tmp_path, lifecycle=lifecycle)

    assert runtime.resolve_session_file("demo-session") == session_file


def test_transcript_session_runtime_exposes_optional_diagnostics_binding(
    tmp_path,
) -> None:
    service = DiagnosticsService()
    diagnostics = SessionDiagnosticsRuntime(
        diagnostics_service=service,
        get_scope=lambda: SessionDiagnosticScope(session_id="session-1"),
        get_extension_diagnostics=lambda: None,
    )
    service.capture_failure(
        code="session_test_failure",
        error="test",
        phase="runtime",
        source="session",
        session_id="session-1",
    )
    lifecycle = SessionLifecycleRuntime[_Session, object](
        store=_Store(),
        hooks=SessionLifecycleHooks(dispose_session=lambda _session: None),
    )
    runtime = AgentTranscriptSessionRuntime(
        session_dir=tmp_path,
        lifecycle=lifecycle,
        diagnostics_runtime=lambda _session: diagnostics,
    )

    assert [record.code for record in runtime.get_last_diagnostics()] == [
        "session_test_failure"
    ]
    assert runtime.get_diagnostics_summary().total_count == 1


def test_product_transcript_store_creates_and_forks_runtime_sessions() -> None:
    async def scenario() -> None:
        ports = _ProductPorts()
        store = ProductTranscriptSessionLifecycleStore(
            ports=ports.lifecycle_ports(),
            build_session=lambda transcript, _current, _transition: _Session(
                transcript.ref,
                transcript.cwd,
                transcript.leaf_id,
            ),
        )
        lifecycle = SessionLifecycleRuntime[_Session, object](
            store=store,
            hooks=SessionLifecycleHooks(dispose_session=lambda _session: None),
        )

        created = await lifecycle.new(cwd="/project", parent_session_ref="parent")
        forked = await lifecycle.fork("leaf")

        assert created.current == _Session("new.jsonl", "/project")
        assert forked.current == _Session("fork.jsonl", "/project")
        assert ports.actions == [
            ("create", "/project", "parent"),
            ("fork", "new.jsonl", "leaf"),
        ]

    asyncio.run(scenario())


def test_product_transcript_store_disposes_restore_when_runtime_build_fails() -> None:
    async def scenario() -> None:
        ports = _ProductPorts()
        store = ProductTranscriptSessionLifecycleStore(
            ports=ports.lifecycle_ports(),
            build_session=lambda _transcript, _current, _transition: _raise_build(),
        )
        lifecycle = SessionLifecycleRuntime[_Session, object](
            store=store,
            hooks=SessionLifecycleHooks(dispose_session=lambda _session: None),
        )

        with pytest.raises(RuntimeError, match="build failed"):
            await lifecycle.restore("saved.jsonl")

        assert ports.disposed == ["saved.jsonl"]

    asyncio.run(scenario())


def test_product_transcript_binding_adapts_standard_session_api(tmp_path: Path) -> None:
    class BoundTranscript:
        actions: list[tuple[object, ...]] = []

        def __init__(self, cwd: str, session_file: Path | None) -> None:
            self.cwd = cwd
            self.session_file = session_file

        @classmethod
        async def new(
            cls,
            *,
            session_dir: Path,
            cwd: str,
            persist: bool,
            parent_session: str | None,
        ) -> BoundTranscript:
            cls.actions.append(
                ("new", session_dir, cwd, persist, parent_session)
            )
            return cls(cwd, session_dir / "new.jsonl")

        @classmethod
        async def open(
            cls,
            session_ref: str | Path,
            *,
            session_dir: Path,
            cwd_override: str | None,
            persist: bool,
        ) -> BoundTranscript:
            cls.actions.append(
                ("open", Path(session_ref), session_dir, cwd_override, persist)
            )
            return cls(cwd_override or "/restored", Path(session_ref))

        async def fork(self, leaf_id: str) -> BoundTranscript:
            self.actions.append(("fork", leaf_id))
            return type(self)(self.cwd, tmp_path / "fork.jsonl")

        async def dispose_runtime_profile(self) -> None:
            self.actions.append(("dispose", self.session_file))

        def get_cwd(self) -> str:
            return self.cwd

        def get_session_file(self) -> Path | None:
            return self.session_file

    async def scenario() -> None:
        BoundTranscript.actions.clear()
        binding = ProductTranscriptSessionBinding(
            session_type=cast(type[ProductTranscriptSession], BoundTranscript),
            session_dir=tmp_path,
            persist=True,
            resolve_cwd_override=lambda value: str(Path(value).resolve()),
        )

        created = await binding.create(str(tmp_path), "parent.jsonl")
        restored = await binding.restore(tmp_path / "saved.jsonl", str(tmp_path))
        forked = await binding.fork(created, "leaf")
        cloned = await binding.fork(created, None)
        await binding.dispose(restored)

        assert forked.get_session_file() == tmp_path / "fork.jsonl"
        assert cloned.get_session_file() == tmp_path / "new.jsonl"
        assert BoundTranscript.actions == [
            ("new", tmp_path, str(tmp_path), True, "parent.jsonl"),
            (
                "open",
                tmp_path / "saved.jsonl",
                tmp_path,
                str(tmp_path.resolve()),
                True,
            ),
            ("fork", "leaf"),
            (
                "new",
                tmp_path,
                str(tmp_path),
                True,
                str(tmp_path / "new.jsonl"),
            ),
            ("dispose", tmp_path / "saved.jsonl"),
        ]

    asyncio.run(scenario())


def test_resolve_fork_target_supports_product_boundary_predicates() -> None:
    @dataclass(frozen=True)
    class Entry:
        parent_id: str | None
        is_boundary: bool
        prompt: str

    entries = {
        "user": Entry("parent", True, "continue from here"),
        "tool": Entry("user", False, "tool output"),
    }

    before = resolve_fork_target(
        entries,
        "user",
        position="before",
        get_entry=lambda current, entry_id: current.get(entry_id),
        is_before_target=lambda entry: entry.is_boundary,
        get_parent_id=lambda entry: entry.parent_id,
        project_payload=lambda entry: entry.prompt,
    )
    assert before.target_entry_id == "parent"
    assert before.payload == "continue from here"

    at = resolve_fork_target(
        entries,
        "tool",
        position="at",
        get_entry=lambda current, entry_id: current.get(entry_id),
        is_before_target=lambda entry: entry.is_boundary,
        get_parent_id=lambda entry: entry.parent_id,
    )
    assert at.target_entry_id == "tool"


def _raise_build() -> _Session:
    raise RuntimeError("build failed")
