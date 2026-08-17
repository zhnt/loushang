from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from loushang.harness.approval import HeadlessApprovalResolver
from loushang.harness.policy import PolicyDecision
from loushang.harness.tools import (
    FilesystemActionAdapter,
    ToolContext,
    ToolRegistry,
    authorized_tool,
    direct_tool,
    tool,
)
from loushang.harness.tools.workspace.authorization import (
    create_workspace_tool_execution_host,
)


@tool()
async def _add(left: int, right: int) -> int:
    """Add two integers without consuming a protected resource."""

    return left + right


@tool()
async def _write_note(
    path: str,
    content: str,
    context: ToolContext,
) -> str:
    """Write one note after the filesystem action has been authorized."""

    target = Path(context.cwd or ".") / path
    target.write_text(content, encoding="utf-8")
    return str(target.resolve())


@dataclass
class _Policy:
    decision: PolicyDecision
    subjects: list[object] = field(default_factory=list)

    def evaluate(self, subject: object) -> PolicyDecision:
        self.subjects.append(subject)
        return self.decision


def _materialize_note_tool(
    tmp_path: Path,
    *,
    policy: _Policy,
    approval_resolver: object | None = None,
    events: list[dict[str, object]] | None = None,
):
    registry = ToolRegistry(
        execution_host=create_workspace_tool_execution_host(
            policy_evaluator=policy,
            approval_resolver=approval_resolver,  # type: ignore[arg-type]
        )
    )
    definition = authorized_tool(
        _write_note,
        action=FilesystemActionAdapter(
            "write",
            authorization_fields=("content",),
        ),
    )
    registry.register_tool(definition)
    return registry.materialize_definitions(
        [definition],
        context_provider=lambda *, tool_call_id: ToolContext(
            tool_call_id=tool_call_id,
            cwd=str(tmp_path),
            event_sink=events.append if events is not None else None,
        ),
    )[0]


def test_harness_only_product_registers_and_runs_explicit_tool_bindings(
    tmp_path: Path,
) -> None:
    policy = _Policy(PolicyDecision.allow())
    events: list[dict[str, object]] = []
    registry = ToolRegistry(
        execution_host=create_workspace_tool_execution_host(
            policy_evaluator=policy,
        )
    )
    direct = direct_tool(_add)
    authorized = authorized_tool(
        _write_note,
        action=FilesystemActionAdapter(
            "write",
            authorization_fields=("content",),
        ),
    )
    registry.register_tool(direct)
    registry.register_tool(authorized)

    with pytest.raises(TypeError, match="explicitly bound ToolDefinition"):
        registry.register_tool(_add)  # type: ignore[arg-type]

    materialized = {
        item.name: item
        for item in registry.materialize_definitions(
            registry.list_definitions(),
            context_provider=lambda *, tool_call_id: ToolContext(
                tool_call_id=tool_call_id,
                cwd=str(tmp_path),
                event_sink=events.append,
            ),
        )
    }
    direct_result = asyncio.run(
        materialized["_add"].execute(
            "direct-call",
            {"left": 2, "right": 3},
        )
    )
    authorized_result = asyncio.run(
        materialized["_write_note"].execute(
            "authorized-call",
            {"path": "note.txt", "content": "hello"},
        )
    )

    assert direct_result.details == 5
    assert authorized_result.details == str((tmp_path / "note.txt").resolve())
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "hello"
    assert len(policy.subjects) == 1
    assert [event["type"] for event in events] == [
        "tool_action_frozen",
        "tool_policy_evaluated",
        "tool_execution_started",
        "tool_execution_completed",
    ]


@pytest.mark.parametrize(
    ("decision", "approval_mode", "expected_events", "executes"),
    (
        (
            PolicyDecision.allow(),
            None,
            (
                "tool_action_frozen",
                "tool_policy_evaluated",
                "tool_execution_started",
                "tool_execution_completed",
            ),
            True,
        ),
        (
            PolicyDecision.ask("confirm write", code="test_write"),
            "allow",
            (
                "tool_action_frozen",
                "tool_policy_evaluated",
                "tool_approval_requested",
                "tool_approval_resolved",
                "tool_execution_started",
                "tool_execution_completed",
            ),
            True,
        ),
        (
            PolicyDecision.ask("confirm write", code="test_write"),
            "deny",
            (
                "tool_action_frozen",
                "tool_policy_evaluated",
                "tool_approval_requested",
                "tool_approval_resolved",
            ),
            False,
        ),
        (
            PolicyDecision.deny("managed deny", code="managed_deny"),
            None,
            (
                "tool_action_frozen",
                "tool_policy_evaluated",
            ),
            False,
        ),
    ),
)
def test_public_authorized_tool_runs_the_complete_gateway_decision_matrix(
    tmp_path: Path,
    decision: PolicyDecision,
    approval_mode: str | None,
    expected_events: tuple[str, ...],
    executes: bool,
) -> None:
    events: list[dict[str, object]] = []
    resolver = (
        HeadlessApprovalResolver(mode=approval_mode)
        if approval_mode is not None
        else None
    )
    tool = _materialize_note_tool(
        tmp_path,
        policy=_Policy(decision),
        approval_resolver=resolver,
        events=events,
    )

    async def execute() -> object:
        return await tool.execute(
            "matrix-call",
            {"path": "matrix.txt", "content": "allowed"},
        )

    if executes:
        result = asyncio.run(execute())
        assert getattr(result, "details") == str((tmp_path / "matrix.txt").resolve())
    else:
        with pytest.raises(PermissionError):
            asyncio.run(execute())

    assert (tmp_path / "matrix.txt").exists() is executes
    assert tuple(event["type"] for event in events) == expected_events
