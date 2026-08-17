from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from loushang.harness.authorization import (
    EffectiveExecutionProfile,
    ExecutionAuthorizationError,
)
from loushang.harness.policy import PolicyDecision
from loushang.harness.tools.process_hosting import (
    ProcessExecutionScope,
    ScopeBoundProcessLauncher,
    _process_launch_fingerprint,
)
from loushang.harness.tools.workspace.policy import PolicyEnforcementError
from loushang.harness.workspace.process import (
    ProcessExit,
    ProcessLaunchRequest,
    ProcessStderrTail,
)
from loushang.harness.workspace.process.host import ProcessHostClosedError
from loushang.harness.workspace.process.local import ProcessContainmentPlan


class _Handle:
    async def read_stdout(self, max_bytes: int = 64 * 1024) -> bytes:
        del max_bytes
        return b""

    async def write_stdin(self, data: bytes) -> None:
        del data

    async def close_stdin(self) -> None:
        return None

    async def wait(self) -> ProcessExit:
        return ProcessExit(0)

    async def terminate(self) -> ProcessExit:
        return ProcessExit(0)

    async def close(self) -> None:
        return None

    def stderr_tail(self) -> ProcessStderrTail:
        return ProcessStderrTail()


class _Host:
    def __init__(self) -> None:
        self.requests: list[ProcessLaunchRequest] = []
        self.closed = False

    async def start(self, request, *, containment_planner=None):
        if self.closed:
            raise ProcessHostClosedError("host is closed")
        assert containment_planner is not None
        plan = await containment_planner(request)
        self.requests.append(plan.request)
        return _Handle()


class _Containment:
    def __init__(self) -> None:
        self.profiles: list[EffectiveExecutionProfile | None] = []

    async def plan(self, request, *, execution_profile=None):
        self.profiles.append(execution_profile)
        return ProcessContainmentPlan(request)


class _Policy:
    def __init__(
        self,
        decision: PolicyDecision,
        *,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.decision = decision
        self.gate = gate
        self.entered = asyncio.Event()
        self.subjects: list[object] = []

    async def evaluate(self, subject):
        self.subjects.append(subject)
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        return self.decision


class _UnusedActorApprovalResolver:
    actor_id = "coding-lsp"

    def resolve(self, request):
        del request
        raise AssertionError("allow policy must not invoke approval")


class _Signal:
    aborted = False


def _request(
    tmp_path: Path,
    *,
    command: tuple[str, ...] = ("server", "--stdio"),
    environment: tuple[tuple[str, str], ...] = (("TOKEN", "secret-one"),),
) -> ProcessLaunchRequest:
    return ProcessLaunchRequest(
        command=command,
        cwd=str(tmp_path),
        effective_environment=environment,
    )


def test_scope_bound_launcher_silently_allows_and_audits_each_start(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        events: list[dict[str, object]] = []
        policy = _Policy(PolicyDecision.allow())
        host = _Host()
        containment = _Containment()
        ceiling = EffectiveExecutionProfile(
            readable_roots=(tmp_path,),
            writable_roots=(tmp_path,),
            network="restricted",
        )
        launcher = ScopeBoundProcessLauncher(
            scope=ProcessExecutionScope(
                policy_evaluator=policy,
                approval_resolver=_UnusedActorApprovalResolver(),
                audit_sink=events.append,
                execution_profile_ceiling=ceiling,
            ),
            host=host,  # type: ignore[arg-type]
            containment=containment,
        )

        await launcher.start(_request(tmp_path), correlation_id="inspect-1")
        await launcher.start(
            _request(tmp_path, environment=(("TOKEN", "secret-two"),)),
            correlation_id="inspect-2",
        )

        assert launcher.scope_actor_id == "coding-lsp"
        assert len(policy.subjects) == 2
        assert len(host.requests) == 2
        assert containment.profiles == [ceiling, ceiling]
        assert not any(event["type"] == "tool_approval_requested" for event in events)
        frozen = [event for event in events if event["type"] == "tool_action_frozen"]
        assert len(frozen) == 2
        assert frozen[0]["action_fingerprint"] != frozen[1]["action_fingerprint"]
        assert {event.get("tool_call_id") for event in frozen} == {
            "inspect-1",
            "inspect-2",
        }
        assert {event.get("actor_id") for event in frozen} == {"coding-lsp"}
        serialized = json.dumps(events, sort_keys=True)
        assert "secret-one" not in serialized
        assert "secret-two" not in serialized

    asyncio.run(scenario())


def test_launcher_deny_and_late_allow_never_reach_spawn(tmp_path: Path) -> None:
    async def scenario() -> None:
        denied_host = _Host()
        denied = ScopeBoundProcessLauncher(
            scope=ProcessExecutionScope(
                policy_evaluator=_Policy(PolicyDecision.deny("blocked")),
            ),
            host=denied_host,  # type: ignore[arg-type]
            containment=_Containment(),
        )
        with pytest.raises(PolicyEnforcementError, match="blocked"):
            await denied.start(_request(tmp_path), correlation_id="denied")
        assert denied_host.requests == []

        gate = asyncio.Event()
        policy = _Policy(PolicyDecision.allow(), gate=gate)
        late_host = _Host()
        launcher = ScopeBoundProcessLauncher(
            scope=ProcessExecutionScope(policy_evaluator=policy),
            host=late_host,  # type: ignore[arg-type]
            containment=_Containment(),
        )
        launch_task = asyncio.create_task(
            launcher.start(_request(tmp_path), correlation_id="late")
        )
        await policy.entered.wait()
        late_host.closed = True
        gate.set()

        with pytest.raises(ProcessHostClosedError):
            await launch_task
        assert late_host.requests == []

    asyncio.run(scenario())


def test_launcher_rechecks_abort_before_policy_and_immediately_before_spawn(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        already_aborted = _Signal()
        already_aborted.aborted = True
        untouched_policy = _Policy(PolicyDecision.allow())
        untouched_host = _Host()
        launcher = ScopeBoundProcessLauncher(
            scope=ProcessExecutionScope(policy_evaluator=untouched_policy),
            host=untouched_host,  # type: ignore[arg-type]
            containment=_Containment(),
        )
        with pytest.raises(RuntimeError, match="Operation aborted"):
            await launcher.start(
                _request(tmp_path),
                correlation_id="already-aborted",
                signal=already_aborted,
            )
        assert untouched_policy.subjects == []
        assert untouched_host.requests == []

        gate = asyncio.Event()
        policy = _Policy(PolicyDecision.allow(), gate=gate)
        late_signal = _Signal()
        late_host = _Host()
        launcher = ScopeBoundProcessLauncher(
            scope=ProcessExecutionScope(policy_evaluator=policy),
            host=late_host,  # type: ignore[arg-type]
            containment=_Containment(),
        )
        start_task = asyncio.create_task(
            launcher.start(
                _request(tmp_path),
                correlation_id="late-abort",
                signal=late_signal,
            )
        )
        await policy.entered.wait()
        late_signal.aborted = True
        gate.set()

        with pytest.raises(RuntimeError, match="Operation aborted"):
            await start_task
        assert late_host.requests == []

    asyncio.run(scenario())


def test_launcher_rejects_cwd_outside_execution_profile_before_spawn(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        admitted_root = tmp_path / "admitted"
        admitted_root.mkdir()
        outside_root = tmp_path / "outside"
        outside_root.mkdir()
        host = _Host()
        containment = _Containment()
        launcher = ScopeBoundProcessLauncher(
            scope=ProcessExecutionScope(
                execution_profile_ceiling=EffectiveExecutionProfile(
                    readable_roots=(admitted_root,),
                ),
            ),
            host=host,  # type: ignore[arg-type]
            containment=containment,
        )

        with pytest.raises(
            ExecutionAuthorizationError,
            match="outside the authorized readable roots",
        ):
            await launcher.start(
                _request(outside_root),
                correlation_id="outside-root",
            )

        assert host.requests == []
        assert containment.profiles == []

    asyncio.run(scenario())


def test_private_launch_fingerprint_covers_argv_cwd_and_complete_environment(
    tmp_path: Path,
) -> None:
    base = _request(tmp_path)
    other_root = tmp_path / "other"
    other_root.mkdir()
    variants = (
        _request(tmp_path, command=("server", "--pipe")),
        ProcessLaunchRequest(
            command=base.command,
            cwd=str(other_root),
            effective_environment=base.effective_environment,
        ),
        _request(tmp_path, environment=(("TOKEN", "different"),)),
    )

    assert (
        len(
            {
                _process_launch_fingerprint(base),
                *map(_process_launch_fingerprint, variants),
            }
        )
        == 4
    )
