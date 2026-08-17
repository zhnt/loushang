from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from loushang.harness.session import (
    AgentProductSessionRuntime,
    SessionLifecycleTransition,
    build_agent_product_session_runtime_ports,
    build_agent_session_lifecycle_hooks,
    prepare_current_agent_session,
)
from loushang.harness.session.agent_adapter import (
    AgentProductSessionRuntime as CompatibilityAgentProductSessionRuntime,
)
from loushang.harness.session.agent_product_runtime import (
    AgentProductSessionRuntime as OwnedAgentProductSessionRuntime,
)


class _Manager:
    def __init__(self, cwd: str, session_file: str) -> None:
        self._cwd = cwd
        self.session_file = session_file

    def get_cwd(self) -> str:
        return self._cwd


def test_agent_adapter_keeps_product_runtime_import_compatibility() -> None:
    assert CompatibilityAgentProductSessionRuntime is OwnedAgentProductSessionRuntime


class _Runner:
    def __init__(self, actions: list[tuple[object, ...]]) -> None:
        self.actions = actions

    async def before_session_fork(self, event: object) -> object:
        self.actions.append(("before-fork", event.entry_id, event.position))
        return SimpleNamespace(cancel=False)

    async def before_session_switch(self, event: object) -> object:
        self.actions.append(("before-switch", event.reason))
        return SimpleNamespace(cancel=False)

    async def emit_session_shutdown(self, event: object) -> None:
        self.actions.append(("shutdown", event.reason, event.target_session_file))


class _Session:
    def __init__(self, actions: list[tuple[object, ...]], name: str) -> None:
        self.actions = actions
        self.session_manager = _Manager(f"/{name}", f"/{name}.jsonl")
        self.extension_runner = _Runner(actions)
        self.diagnostics_service = None
        self.disposed = False

    def _stage_session_approvals(self) -> None:
        self.actions.append(("stage-approvals",))

    def _open_session_approvals(self) -> None:
        self.actions.append(("open-approvals",))

    def set_extension_runtime_host(self, host: object) -> None:
        self.actions.append(("bind-host", host))

    async def prepare_model_call_runtime(self) -> None:
        self.actions.append(("bind-model-call-graph",))

    async def start_extension_runtime(self, *, reason: str) -> None:
        self.actions.append(("start-extensions", reason))

    def _sync_extension_diagnostics(self, *, phase: str) -> None:
        self.actions.append(("sync-diagnostics", phase))

    async def dispose(self) -> None:
        self.disposed = True


def test_agent_session_lifecycle_hooks_bind_existing_session_capabilities() -> None:
    async def scenario() -> None:
        actions: list[tuple[object, ...]] = []
        runtime_host = object()
        session = _Session(actions, "current")
        target = _Session(actions, "target")
        failures: list[Exception] = []
        hooks = build_agent_session_lifecycle_hooks(
            runtime_host=runtime_host,
            record_shutdown_failure=lambda _session, _event, exc: failures.append(exc),
        )
        transition = SessionLifecycleTransition(
            reason="fork",
            fork_entry_id="entry-1",
            fork_position="before",
        )

        assert hooks.before_transition is not None
        decision = await hooks.before_transition(session, transition)
        assert decision is not None and decision.cancelled is False
        assert hooks.prepare_session is not None
        await hooks.prepare_session(session, None, transition)
        assert hooks.activate_session is not None
        await hooks.activate_session(session, None, transition)
        assert hooks.before_release is not None
        await hooks.before_release(session, target, transition)
        assert hooks.dispose_session is not None
        await hooks.dispose_session(session)

        assert failures == []
        assert session.disposed is True
        assert actions == [
            ("before-fork", "entry-1", "before"),
            ("sync-diagnostics", "runtime"),
            ("stage-approvals",),
            ("bind-host", runtime_host),
            ("bind-model-call-graph",),
            ("open-approvals",),
            ("start-extensions", "fork"),
            ("shutdown", "fork", "/target.jsonl"),
            ("sync-diagnostics", "runtime"),
        ]

    asyncio.run(scenario())


def test_prepare_current_agent_session_reopens_and_binds_runtime_host() -> None:
    actions: list[tuple[object, ...]] = []
    session = _Session(actions, "current")
    runtime_host = object()

    prepare_current_agent_session(session, runtime_host)

    assert actions == [("open-approvals",), ("bind-host", runtime_host)]


def test_agent_product_runtime_ports_bind_standard_session_conventions(
    tmp_path: Path,
) -> None:
    events: list[object] = []

    class Transcript:
        def get_cwd(self) -> str:
            return str(tmp_path)

        def get_session_file(self) -> Path:
            return tmp_path / "research.jsonl"

        def get_leaf_id(self) -> str:
            return "leaf-1"

    class Session:
        def __init__(self, manager: Transcript) -> None:
            self.session_manager = manager

    def session_factory(
        manager: Transcript,
        *,
        session_start_event: object,
    ) -> Session:
        events.append(session_start_event)
        return Session(manager)

    ports = build_agent_product_session_runtime_ports(
        runtime_host=object(),
        transcript_session_type=Transcript,
        session_dir=tmp_path,
        session_factory=session_factory,
        persist=True,
        diagnostics_runtime=None,
        record_shutdown_failure=lambda _session, _event, _error: None,
        copy_file=lambda _source, _destination: None,
    )
    transcript = Transcript()
    session = ports.build_session(
        transcript,
        None,
        SessionLifecycleTransition(reason="new"),
    )

    assert session.session_manager is transcript
    assert events[0].reason == "startup"
    assert ports.transcript_for_session(session) is transcript
    assert ports.transcript_cwd(transcript) == str(tmp_path)
    assert ports.transcript_session_ref(transcript).endswith("research.jsonl")
    assert ports.transcript_leaf_entry_id(transcript) == "leaf-1"
    assert ports.fork_profile.default_position == "before"
    assert ports.fork_profile.supported_positions == frozenset({"at", "before"})


def test_agent_product_session_runtime_binds_current_session_without_product_code(
    tmp_path: Path,
) -> None:
    actions: list[tuple[object, ...]] = []
    current = _Session(actions, "research")

    runtime = AgentProductSessionRuntime[
        _Session,
        _Manager,
    ](
        transcript_session_type=_Manager,
        session_dir=tmp_path,
        session_factory=lambda manager: _Session(actions, manager.get_cwd()),
        current_session=current,
    )

    assert runtime.current_session is current
    assert actions == [
        ("open-approvals",),
        ("bind-host", runtime),
    ]
