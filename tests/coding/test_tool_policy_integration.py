from __future__ import annotations

import asyncio
import json

import pytest


def _tool_context_provider(*, cwd: str):
    from loushang.harness.tools.workspace import ToolContext

    def _provider(*, tool_call_id: str) -> ToolContext:
        return ToolContext(tool_call_id=tool_call_id, cwd=cwd)

    return _provider


def _tool_context_provider_with_events(*, cwd: str, events: list[dict[str, object]]):
    from loushang.harness.tools.workspace import ToolContext

    async def emit_event(event: dict[str, object]) -> None:
        events.append(event)

    def _provider(*, tool_call_id: str) -> ToolContext:
        return ToolContext(tool_call_id=tool_call_id, cwd=cwd, event_sink=emit_event)

    return _provider


def test_global_policy_engine_blocks_write_tool_before_mutation(tmp_path) -> None:
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    registry = ToolRegistry()
    register_builtin_tools(
        registry, policy_engine=PolicyEngine(blocked_tools=["write"])
    )
    runtime_tool = registry.materialize_tool(
        "write", context_provider=_tool_context_provider(cwd=str(tmp_path))
    )

    with pytest.raises(PermissionError) as exc:
        asyncio.run(
            runtime_tool.execute(
                "call-write-policy", {"path": "blocked.txt", "content": "blocked"}
            )
        )

    assert "write" in str(exc.value)
    assert getattr(exc.value, "tool_result_details", None) == {
        "tool_name": "write",
        "cwd": str(tmp_path),
        "policy_disposition": "deny",
        "policy_code": "tool_blocked",
        "policy_reason": "Tool write is blocked by policy",
        "approval_required": False,
        "argument_keys": ["content", "path"],
        "path": str(tmp_path / "blocked.txt"),
    }
    assert not (tmp_path / "blocked.txt").exists()


def test_global_policy_engine_blocks_bash_by_tool_name(tmp_path) -> None:
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    registry = ToolRegistry()
    register_builtin_tools(registry, policy_engine=PolicyEngine(blocked_tools=["bash"]))
    runtime_tool = registry.materialize_tool("bash")

    with pytest.raises(PermissionError) as exc:
        asyncio.run(
            runtime_tool.execute(
                "call-bash-policy", {"command": "pwd", "cwd": str(tmp_path)}
            )
        )

    assert "bash" in str(exc.value)


def test_default_tool_registration_does_not_enable_policy_by_default(tmp_path) -> None:
    import asyncio

    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )
    from loushang.harness.workspace.exec import ExecResult

    class RecordingExecService:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def execute(self, request) -> ExecResult:
            self.requests.append(request)
            return ExecResult(exit_code=0, stdout="ok", stderr="")

    registry = ToolRegistry()
    exec_service = RecordingExecService()
    register_builtin_tools(registry, exec_service=exec_service)
    runtime_tool = registry.materialize_tool("bash")
    result = asyncio.run(
        runtime_tool.execute(
            "call-bash-no-policy", {"command": "printf ok", "cwd": str(tmp_path)}
        )
    )

    assert result.content[0].text == "ok"
    assert len(exec_service.requests) == 1
    assert exec_service.requests[0].command == ("/bin/bash", "-lc", "printf ok")


def test_default_approval_resolver_denies_ask_policy_before_write(tmp_path) -> None:
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    registry = ToolRegistry()
    register_builtin_tools(registry, policy_engine=PolicyEngine(ask_tools=["write"]))
    runtime_tool = registry.materialize_tool(
        "write", context_provider=_tool_context_provider(cwd=str(tmp_path))
    )

    with pytest.raises(PermissionError) as exc:
        asyncio.run(
            runtime_tool.execute(
                "call-write-approval-default",
                {"path": "needs-approval.txt", "content": "x"},
            )
        )

    assert "write" in str(exc.value)
    details = getattr(exc.value, "tool_result_details", None)
    assert details is not None
    assert "approval_action_id" in details
    assert details.pop("approval_action_id") is not None
    assert details == {
        "tool_name": "write",
        "cwd": str(tmp_path),
        "policy_disposition": "ask",
        "policy_code": "tool_requires_approval",
        "policy_reason": "Tool write requires approval",
        "approval_required": True,
        "approval_decision": "deny",
        "approval_reason": "Tool write requires approval",
        "argument_keys": ["content", "path"],
        "path": str(tmp_path / "needs-approval.txt"),
    }
    assert not (tmp_path / "needs-approval.txt").exists()


def test_sync_approval_resolver_can_allow_ask_policy_for_write(tmp_path) -> None:
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.approval import ApprovalDecision
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    class AllowingResolver:
        def __init__(self) -> None:
            self.requests = []

        def resolve(self, request):
            self.requests.append(request)
            return ApprovalDecision.allow()

    resolver = AllowingResolver()
    registry = ToolRegistry()
    register_builtin_tools(
        registry,
        policy_engine=PolicyEngine(ask_tools=["write"]),
        approval_resolver=resolver,
    )
    runtime_tool = registry.materialize_tool(
        "write", context_provider=_tool_context_provider(cwd=str(tmp_path))
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-write-approval-allow", {"path": "approved.txt", "content": "approved"}
        )
    )

    assert (tmp_path / "approved.txt").read_text(encoding="utf-8") == "approved"
    assert result.details["operation"] == "create"
    assert len(resolver.requests) == 1
    assert resolver.requests[0].tool_name == "write"
    assert resolver.requests[0].policy_code == "tool_requires_approval"
    assert "approved.txt" in str(resolver.requests[0].arguments["path"])


def test_live_child_context_overrides_the_root_definition_approval_actor(
    tmp_path,
) -> None:
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.approval import (
        ActorBoundApprovalResolver,
        ApprovalDecision,
        HeadlessApprovalResolver,
    )
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.tools.workspace import ToolContext
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    class AllowingResolver:
        def __init__(self) -> None:
            self.requests = []

        def resolve(self, request):
            self.requests.append(request)
            return ApprovalDecision.allow()

    child_exit = AllowingResolver()
    child_resolver = ActorBoundApprovalResolver(
        resolver=child_exit,
        actor_id="/root/worker@2",
    )
    registry = ToolRegistry()
    register_builtin_tools(
        registry,
        policy_engine=PolicyEngine(ask_tools=["write"]),
        approval_resolver=HeadlessApprovalResolver(mode="deny"),
    )
    runtime_tool = registry.materialize_tool(
        "write",
        context_provider=lambda *, tool_call_id: ToolContext(
            tool_call_id=tool_call_id,
            cwd=str(tmp_path),
            approval_resolver=child_resolver,
        ),
    )

    asyncio.run(
        runtime_tool.execute(
            "call-child-write",
            {"path": "child.txt", "content": "approved"},
        )
    )

    assert (tmp_path / "child.txt").read_text(encoding="utf-8") == "approved"
    assert [request.actor_id for request in child_exit.requests] == [
        "/root/worker@2"
    ]


def test_ask_policy_allow_emits_tool_approval_audit_events(tmp_path) -> None:
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.approval import ApprovalDecision
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    class AllowingResolver:
        def resolve(self, request):
            return ApprovalDecision.allow()

    events: list[dict[str, object]] = []
    registry = ToolRegistry()
    register_builtin_tools(
        registry,
        policy_engine=PolicyEngine(ask_tools=["write"]),
        approval_resolver=AllowingResolver(),
    )
    runtime_tool = registry.materialize_tool(
        "write",
        context_provider=_tool_context_provider_with_events(
            cwd=str(tmp_path), events=events
        ),
    )

    asyncio.run(
        runtime_tool.execute(
            "call-write-approval-audit",
            {"path": "approved-audit.txt", "content": "approved"},
        )
    )

    assert [event["type"] for event in events] == [
        "tool_action_frozen",
        "tool_policy_evaluated",
        "tool_approval_requested",
        "tool_approval_resolved",
        "tool_execution_started",
        "tool_execution_completed",
    ]
    assert {event["action_fingerprint"] for event in events} == {
        events[0]["action_fingerprint"]
    }
    assert all(event["capability"] == "filesystem.write" for event in events)
    assert events[1]["policy_disposition"] == "ask"
    assert events[1]["policy_code"] == "tool_requires_approval"
    assert events[1]["approval_required"] is True
    action_id = events[2].get("action_id")
    assert isinstance(action_id, str)
    assert events[3]["action_id"] == action_id
    assert events[3]["approval_decision"] == "allow"
    assert events[4]["approval_action_id"] == action_id
    assert events[5]["approval_action_id"] == action_id
    serialized = json.dumps(events)
    assert str(tmp_path) not in serialized
    assert "approved-audit.txt" not in serialized
    assert '"approved"' not in serialized


def test_deny_policy_emits_tool_policy_evaluated_audit_event(tmp_path) -> None:
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    events: list[dict[str, object]] = []
    registry = ToolRegistry()
    register_builtin_tools(
        registry, policy_engine=PolicyEngine(blocked_tools=["write"])
    )
    runtime_tool = registry.materialize_tool(
        "write",
        context_provider=_tool_context_provider_with_events(
            cwd=str(tmp_path), events=events
        ),
    )

    with pytest.raises(PermissionError):
        asyncio.run(
            runtime_tool.execute(
                "call-write-deny-audit",
                {"path": "blocked-audit.txt", "content": "blocked"},
            )
        )

    assert [event["type"] for event in events] == [
        "tool_action_frozen",
        "tool_policy_evaluated",
    ]
    assert events[1]["policy_disposition"] == "deny"
    assert events[1]["policy_code"] == "tool_blocked"
    assert events[1]["approval_required"] is False
    serialized = json.dumps(events)
    assert str(tmp_path) not in serialized
    assert "blocked-audit.txt" not in serialized
    assert '"blocked"' not in serialized


def test_async_approval_resolver_can_deny_ask_policy_for_write(tmp_path) -> None:
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.approval import ApprovalDecision
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    class DenyingResolver:
        async def resolve(self, request):
            return ApprovalDecision.deny(f"denied {request.tool_name}")

    registry = ToolRegistry()
    register_builtin_tools(
        registry,
        policy_engine=PolicyEngine(ask_tools=["write"]),
        approval_resolver=DenyingResolver(),
    )
    runtime_tool = registry.materialize_tool(
        "write", context_provider=_tool_context_provider(cwd=str(tmp_path))
    )

    with pytest.raises(PermissionError) as exc:
        asyncio.run(
            runtime_tool.execute(
                "call-write-approval-deny", {"path": "denied.txt", "content": "denied"}
            )
        )

    assert str(exc.value) == "denied write"
    details = getattr(exc.value, "tool_result_details", None)
    assert details is not None
    assert "approval_action_id" in details
    assert details.pop("approval_action_id") is not None
    assert details == {
        "tool_name": "write",
        "cwd": str(tmp_path),
        "policy_disposition": "ask",
        "policy_code": "tool_requires_approval",
        "policy_reason": "Tool write requires approval",
        "approval_required": True,
        "approval_decision": "deny",
        "approval_reason": "denied write",
        "argument_keys": ["content", "path"],
        "path": str(tmp_path / "denied.txt"),
    }
    assert not (tmp_path / "denied.txt").exists()


def test_interactive_approval_resolver_can_allow_ask_policy_for_write(tmp_path) -> None:
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.approval import (
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    presented: dict[str, object] = {}
    presented_event = asyncio.Event()

    def present_request(payload: dict[str, object]) -> None:
        presented.update(payload)
        presented_event.set()

    resolver = InteractiveApprovalResolver(
        fallback=HeadlessApprovalResolver(mode="deny")
    )
    resolver.set_request_presenter(present_request)

    registry = ToolRegistry()
    register_builtin_tools(
        registry,
        policy_engine=PolicyEngine(ask_tools=["write"]),
        approval_resolver=resolver,
    )
    runtime_tool = registry.materialize_tool(
        "write", context_provider=_tool_context_provider(cwd=str(tmp_path))
    )

    async def run() -> None:
        execute = asyncio.create_task(
            runtime_tool.execute(
                "call-write-approval-allow-interactive",
                {"path": "approved.txt", "content": "ok"},
            )
        )
        await presented_event.wait()
        action_id = presented.get("action_id")
        assert isinstance(action_id, str)
        await resolver.handle_result(action_id=action_id, approved=True)
        await execute

    asyncio.run(run())
    assert (tmp_path / "approved.txt").read_text(encoding="utf-8") == "ok"


def test_interactive_approval_resolver_can_deny_ask_policy_for_write(tmp_path) -> None:
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.approval import (
        HeadlessApprovalResolver,
        InteractiveApprovalResolver,
    )
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    presented: dict[str, object] = {}
    presented_event = asyncio.Event()

    def present_request(payload: dict[str, object]) -> None:
        presented.update(payload)
        presented_event.set()

    resolver = InteractiveApprovalResolver(
        fallback=HeadlessApprovalResolver(mode="deny")
    )
    resolver.set_request_presenter(present_request)

    registry = ToolRegistry()
    register_builtin_tools(
        registry,
        policy_engine=PolicyEngine(ask_tools=["write"]),
        approval_resolver=resolver,
    )
    runtime_tool = registry.materialize_tool(
        "write", context_provider=_tool_context_provider(cwd=str(tmp_path))
    )

    async def run() -> str:
        execute = asyncio.create_task(
            runtime_tool.execute(
                "call-write-approval-deny-interactive",
                {"path": "denied.txt", "content": "x"},
            )
        )
        await presented_event.wait()
        action_id = presented.get("action_id")
        assert isinstance(action_id, str)
        await resolver.handle_result(
            action_id=action_id, approved=False, reason="interactive reject"
        )
        try:
            await execute
        except PermissionError as exc:
            return getattr(exc, "tool_result_details", {}).get(
                "approval_action_id", "missing"
            )
        raise AssertionError("write tool execution should be rejected")

    approval_action_id = asyncio.run(run())
    assert approval_action_id == presented.get("action_id")
    assert approval_action_id != "missing"
    assert not (tmp_path / "denied.txt").exists()


def test_headless_approval_resolver_modes_are_stable(tmp_path) -> None:
    from loushang.coding.tool_pack import (
        register_coding_builtin_tools as register_builtin_tools,
    )
    from loushang.harness.approval import HeadlessApprovalResolver
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.tools.workspace.registry import (
        WorkspaceToolRegistry as ToolRegistry,
    )

    allow_registry = ToolRegistry()
    register_builtin_tools(
        allow_registry,
        policy_engine=PolicyEngine(ask_tools=["write"]),
        approval_resolver=HeadlessApprovalResolver(mode="allow"),
    )
    allow_tool = allow_registry.materialize_tool(
        "write", context_provider=_tool_context_provider(cwd=str(tmp_path))
    )

    asyncio.run(
        allow_tool.execute(
            "call-write-headless-allow", {"path": "allowed.txt", "content": "ok"}
        )
    )

    deny_registry = ToolRegistry()
    register_builtin_tools(
        deny_registry,
        policy_engine=PolicyEngine(ask_tools=["write"]),
        approval_resolver=HeadlessApprovalResolver(mode="deny", reason="headless deny"),
    )
    deny_tool = deny_registry.materialize_tool(
        "write", context_provider=_tool_context_provider(cwd=str(tmp_path))
    )

    with pytest.raises(PermissionError) as exc:
        asyncio.run(
            deny_tool.execute(
                "call-write-headless-deny",
                {"path": "denied-headless.txt", "content": "x"},
            )
        )

    assert (tmp_path / "allowed.txt").read_text(encoding="utf-8") == "ok"
    assert str(exc.value) == "headless deny"
    assert (
        getattr(exc.value, "tool_result_details", None)["approval_decision"] == "deny"
    )
    assert not (tmp_path / "denied-headless.txt").exists()


def test_persistent_permission_never_overrides_current_managed_deny(tmp_path) -> None:
    from loushang.harness.approval import (
        ApprovalGrantProposal,
        ApprovalRequest,
        HeadlessApprovalResolver,
        InMemoryApprovalPolicyRuleStore,
        InteractiveApprovalResolver,
        PolicyAmendmentProposal,
    )
    from loushang.harness.policy import (
        build_tool_policy_subject,
        normalize_command_subject,
    )
    from loushang.harness.policy_engine import PolicyEngine
    from loushang.harness.tools.workspace.policy import (
        PolicyEnforcementError,
        enforce_tool_policy,
    )

    proposal = ApprovalGrantProposal(
        capability="git.publish_refs",
        constraints=(
            ("repository", str(tmp_path)),
            ("remote", "origin"),
            ("force", "false"),
        ),
        summary="Publish non-force refs to origin from this repository",
    )
    amendment = PolicyAmendmentProposal(scope="project", grant=proposal)
    request = ApprovalRequest(
        tool_name="bash",
        arguments={"command": "git push origin main"},
        cwd=str(tmp_path),
        action_id="seed-policy-rule",
        session_grant=proposal,
        policy_amendments=(amendment,),
    )
    store = InMemoryApprovalPolicyRuleStore("project")
    store.issue(request, amendment)
    resolver = InteractiveApprovalResolver(
        fallback=HeadlessApprovalResolver(mode="deny")
    )
    resolver.set_policy_stores({"project": store})

    with pytest.raises(PolicyEnforcementError) as error:
        asyncio.run(
            enforce_tool_policy(
                PolicyEngine(blocked_substrings=("git push",)),
                tool_name="bash",
                arguments={"command": "git push origin main"},
                cwd=str(tmp_path),
                policy_subject=build_tool_policy_subject(
                    tool_name="bash",
                    arguments={"command": "git push origin main"},
                    cwd=str(tmp_path),
                    command=normalize_command_subject(
                        ("/bin/sh", "-lc", "git push origin main"),
                        cwd=str(tmp_path),
                    ),
                ),
                approval_resolver=resolver,
            )
        )

    assert error.value.tool_result_details["policy_disposition"] == "deny"
    assert resolver.permissions_snapshot().project_rules
