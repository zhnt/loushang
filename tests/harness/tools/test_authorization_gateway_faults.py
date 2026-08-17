from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import pytest

from loushang.harness.approval import (
    HeadlessApprovalResolver,
    InteractiveApprovalResolver,
)
from loushang.harness.policy import PolicyDecision
from loushang.harness.sandbox import SandboxUnavailableError
from loushang.harness.tools import (
    PublicationActionAdapter,
    ToolContext,
    ToolRegistry,
    authorized_tool,
    tool,
)
from loushang.harness.tools.workspace.authorization import (
    create_workspace_tool_execution_host,
)


@dataclass
class _Policy:
    decision: PolicyDecision | None = None
    error: Exception | None = None

    def evaluate(self, _subject: object) -> PolicyDecision:
        if self.error is not None:
            raise self.error
        assert self.decision is not None
        return self.decision


class _AuditSink:
    def __init__(self, *, fail_on: str | None = None) -> None:
        self.fail_on = fail_on
        self.events: list[dict[str, object]] = []

    def __call__(self, event: dict[str, object]) -> None:
        self.events.append(dict(event))
        if event["type"] == self.fail_on:
            raise RuntimeError(f"audit transport failed at {self.fail_on}")


def _materialize_effect_tool(
    *,
    policy: _Policy,
    handler: Callable[[str], str | Awaitable[str]],
    audit_sink: _AuditSink,
    approval_resolver: object | None = None,
):
    @tool(name="publish_artifact")
    async def publish_artifact(target: str, context: ToolContext) -> str:
        del context
        result = handler(target)
        return await result if isinstance(result, Awaitable) else result

    definition = authorized_tool(
        publish_artifact,
        action=PublicationActionAdapter(),
    )
    registry = ToolRegistry(
        execution_host=create_workspace_tool_execution_host(
            policy_evaluator=policy,
            approval_resolver=approval_resolver,  # type: ignore[arg-type]
        )
    )
    registry.register_tool(definition)
    return registry.materialize_definitions(
        [definition],
        context_provider=lambda *, tool_call_id: ToolContext(
            tool_call_id=tool_call_id,
            event_sink=audit_sink,
        ),
    )[0]


@pytest.mark.parametrize(
    ("failure", "expected_types"),
    (
        (
            "action_audit",
            ("tool_action_frozen",),
        ),
        (
            "policy",
            ("tool_action_frozen",),
        ),
        (
            "policy_audit",
            ("tool_action_frozen", "tool_policy_evaluated"),
        ),
        (
            "approval_resolved_audit",
            (
                "tool_action_frozen",
                "tool_policy_evaluated",
                "tool_approval_requested",
                "tool_approval_resolved",
            ),
        ),
        (
            "execution_started_audit",
            (
                "tool_action_frozen",
                "tool_policy_evaluated",
                "tool_execution_started",
            ),
        ),
    ),
)
def test_gateway_fails_closed_when_a_pre_effect_stage_fails(
    failure: str,
    expected_types: tuple[str, ...],
) -> None:
    handler_calls = 0

    def handler(_target: str) -> str:
        nonlocal handler_calls
        handler_calls += 1
        return "published"

    policy = _Policy(
        error=RuntimeError("policy unavailable") if failure == "policy" else None,
        decision=(
            None
            if failure == "policy"
            else (
                PolicyDecision.ask(
                    "Confirm publication",
                    code="publication",
                )
                if failure == "approval_resolved_audit"
                else PolicyDecision.allow()
            )
        ),
    )
    sink = _AuditSink(
        fail_on={
            "action_audit": "tool_action_frozen",
            "policy_audit": "tool_policy_evaluated",
            "approval_resolved_audit": "tool_approval_resolved",
            "execution_started_audit": "tool_execution_started",
        }.get(failure)
    )
    runtime_tool = _materialize_effect_tool(
        policy=policy,
        handler=handler,
        audit_sink=sink,
        approval_resolver=(
            HeadlessApprovalResolver(mode="allow")
            if failure == "approval_resolved_audit"
            else None
        ),
    )

    with pytest.raises(RuntimeError):
        asyncio.run(
            runtime_tool.execute(
                f"call-{failure}",
                {"target": "registry.example.invalid/release"},
            )
        )

    assert handler_calls == 0
    assert tuple(event["type"] for event in sink.events) == expected_types


def test_gateway_cleans_pending_approval_when_presenter_fails() -> None:
    handler_calls = 0

    def handler(_target: str) -> str:
        nonlocal handler_calls
        handler_calls += 1
        return "published"

    resolver = InteractiveApprovalResolver(
        fallback=HeadlessApprovalResolver(mode="deny")
    )
    resolver.open_session()

    def fail_presenter(_payload: dict[str, object]) -> None:
        raise RuntimeError("approval presenter unavailable")

    resolver.set_request_presenter(fail_presenter)
    sink = _AuditSink()
    runtime_tool = _materialize_effect_tool(
        policy=_Policy(
            decision=PolicyDecision.ask(
                "Confirm publication",
                code="publication",
            )
        ),
        handler=handler,
        audit_sink=sink,
        approval_resolver=resolver,
    )

    with pytest.raises(RuntimeError, match="approval presenter unavailable"):
        asyncio.run(
            runtime_tool.execute(
                "call-presenter-failure",
                {"target": "registry.example.invalid/release"},
            )
        )

    assert handler_calls == 0
    assert resolver.permissions_snapshot().pending == ()
    assert [event["type"] for event in sink.events] == [
        "tool_action_frozen",
        "tool_policy_evaluated",
        "tool_approval_requested",
    ]


@pytest.mark.parametrize(
    ("error", "outcome"),
    (
        (RuntimeError("executor failed to start"), "error"),
        (TimeoutError("executor timed out"), "timeout"),
        (SandboxUnavailableError("sandbox unavailable"), "error"),
    ),
)
def test_gateway_records_one_terminal_failure_for_executor_faults(
    error: Exception,
    outcome: str,
) -> None:
    handler_calls = 0

    def handler(_target: str) -> str:
        nonlocal handler_calls
        handler_calls += 1
        raise error

    sink = _AuditSink()
    runtime_tool = _materialize_effect_tool(
        policy=_Policy(decision=PolicyDecision.allow()),
        handler=handler,
        audit_sink=sink,
    )

    with pytest.raises(type(error), match=str(error)):
        asyncio.run(
            runtime_tool.execute(
                "call-executor-fault",
                {"target": "registry.example.invalid/release"},
            )
        )

    assert handler_calls == 1
    assert [event["type"] for event in sink.events][-2:] == [
        "tool_execution_started",
        "tool_execution_failed",
    ]
    assert sink.events[-1]["outcome"] == outcome
    assert sum(
        event["type"] in {"tool_execution_completed", "tool_execution_failed"}
        for event in sink.events
    ) == 1


def test_gateway_records_cancellation_without_reinvoking_handler() -> None:
    async def scenario() -> tuple[int, list[dict[str, object]]]:
        handler_calls = 0
        entered = asyncio.Event()
        release = asyncio.Event()

        async def handler(_target: str) -> str:
            nonlocal handler_calls
            handler_calls += 1
            entered.set()
            await release.wait()
            return "published"

        sink = _AuditSink()
        runtime_tool = _materialize_effect_tool(
            policy=_Policy(decision=PolicyDecision.allow()),
            handler=handler,
            audit_sink=sink,
        )
        pending = asyncio.create_task(
            runtime_tool.execute(
                "call-cancelled",
                {"target": "registry.example.invalid/release"},
            )
        )
        await entered.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        return handler_calls, sink.events

    handler_calls, events = asyncio.run(scenario())

    assert handler_calls == 1
    assert [event["type"] for event in events][-2:] == [
        "tool_execution_started",
        "tool_execution_failed",
    ]
    assert events[-1]["outcome"] == "cancelled"


def test_terminal_audit_failure_after_success_does_not_invite_effect_retry(
    caplog: pytest.LogCaptureFixture,
) -> None:
    handler_calls = 0

    def handler(_target: str) -> str:
        nonlocal handler_calls
        handler_calls += 1
        return "published"

    sink = _AuditSink(fail_on="tool_execution_completed")
    runtime_tool = _materialize_effect_tool(
        policy=_Policy(decision=PolicyDecision.allow()),
        handler=handler,
        audit_sink=sink,
    )

    with caplog.at_level(logging.ERROR):
        result = asyncio.run(
            runtime_tool.execute(
                "call-terminal-audit-failure",
                {"target": "registry.example.invalid/release"},
            )
        )

    assert result.details == "published"
    assert handler_calls == 1
    assert sink.events[-1]["type"] == "tool_execution_completed"
    assert (
        "terminal tool audit emission failed after successful execution"
        in caplog.text
    )


def test_terminal_audit_failure_preserves_original_executor_error() -> None:
    def handler(_target: str) -> str:
        raise ValueError("publication failed")

    sink = _AuditSink(fail_on="tool_execution_failed")
    runtime_tool = _materialize_effect_tool(
        policy=_Policy(decision=PolicyDecision.allow()),
        handler=handler,
        audit_sink=sink,
    )

    with pytest.raises(ValueError, match="publication failed") as caught:
        asyncio.run(
            runtime_tool.execute(
                "call-double-fault",
                {"target": "registry.example.invalid/release"},
            )
        )

    assert any(
        "terminal audit emission failed" in note
        for note in (caught.value.__notes__ or ())
    )
