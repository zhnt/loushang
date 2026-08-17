from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from loushang.harness.approval import (
    ActorBoundApprovalResolver,
    ApprovalDecision,
    HeadlessApprovalResolver,
    InteractiveApprovalResolver,
    JsonApprovalPolicyRuleStore,
)
from loushang.harness.authorization import (
    EffectiveExecutionProfile,
    ExecutionAuthorizationError,
)
from loushang.harness.policy import (
    PolicyDecision,
    build_tool_policy_subject,
    normalize_command_subject,
)
from loushang.harness.policy_engine import PolicyEngine
from loushang.harness.tools.workspace.authorization import (
    _execute_authorized_tool_action as execute_workspace_tool_action,
)


def test_workspace_authorization_gateway_freezes_and_fingerprints_actions() -> None:
    arguments = {"path": "/workspace/file", "edits": [{"old": "a", "new": "b"}]}

    first = asyncio.run(
        execute_workspace_tool_action(
            None,
            tool_name="edit",
            arguments=arguments,
            cwd="/workspace",
            executor=lambda action: action,
        )
    )
    second = asyncio.run(
        execute_workspace_tool_action(
            None,
            tool_name="edit",
            arguments=arguments,
            cwd="/workspace",
            executor=lambda action: action,
        )
    )

    assert first.fingerprint == second.fingerprint
    assert first.authorization_arguments["edits"] == (
        {"old": "a", "new": "b"},
    )
    with pytest.raises(TypeError):
        first.authorization_arguments["path"] = "/other"  # type: ignore[index]


@pytest.mark.parametrize("tool_name", ("read", "grep", "find", "ls"))
def test_workspace_gateway_enforces_read_roots_from_execution_profile(
    tool_name: str,
) -> None:
    profile = EffectiveExecutionProfile(
        readable_roots=(Path("/workspace"),),
    )
    events: list[dict[str, object]] = []

    with pytest.raises(ExecutionAuthorizationError, match="outside"):
        asyncio.run(
            execute_workspace_tool_action(
                None,
                tool_name=tool_name,
                arguments={"path": "/outside/secret"},
                cwd="/workspace",
                execution_profile_ceiling=profile,
                audit_sink=events.append,
                executor=lambda _action: pytest.fail("executor must not run"),
            )
        )

    assert [event["type"] for event in events] == [
        "tool_action_frozen",
        "tool_policy_evaluated",
        "tool_execution_failed",
    ]
    assert events[-1]["phase"] == "pre_execution"
    assert events[-1]["outcome"] == "denied"


def test_workspace_gateway_binds_policy_and_approval_to_execution_profile(
    tmp_path: Path,
) -> None:
    class AskPolicy:
        def evaluate(self, subject):
            del subject
            return PolicyDecision.ask("confirm", code="external_effect")

    action = asyncio.run(
        execute_workspace_tool_action(
            AskPolicy(),
            tool_name="bash",
            arguments={"command": ("gh", "pr", "create")},
            cwd=str(tmp_path),
            approval_resolver=HeadlessApprovalResolver(mode="allow"),
            execution_profile_ceiling=EffectiveExecutionProfile(
                readable_roots=(tmp_path,),
                writable_roots=(tmp_path,),
            ),
            executor=lambda action: action,
        )
    )

    assert action.execution_profile is not None
    assert action.execution_profile.policy_code == "external_effect"
    assert action.execution_profile.approval_action_id is not None


def test_workspace_gateway_owns_policy_approval_and_execution_order(
    tmp_path: Path,
) -> None:
    events: list[str] = []

    class AskPolicy:
        def evaluate(self, subject):
            del subject
            events.append("policy")
            return PolicyDecision.ask("confirm")

    class Resolver:
        def resolve(self, request):
            del request
            events.append("approval")
            return ApprovalDecision.allow()

    def execute(action):
        events.append("execute")
        return action.fingerprint

    result = asyncio.run(
        execute_workspace_tool_action(
            AskPolicy(),
            tool_name="bash",
            arguments={"command": ("git", "status")},
            cwd=str(tmp_path),
            approval_resolver=Resolver(),
            executor=execute,
        )
    )

    assert events == ["policy", "approval", "execute"]
    assert len(result) == 64


def test_workspace_gateway_revalidates_path_immediately_before_execution(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.txt"
    target.write_text("inside", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    executed = False
    events: list[dict[str, object]] = []

    def replace_target(_action):
        target.unlink()
        target.symlink_to(outside)

    def execute(_action):
        nonlocal executed
        executed = True

    with pytest.raises(ExecutionAuthorizationError, match="outside"):
        asyncio.run(
            execute_workspace_tool_action(
                None,
                tool_name="read",
                arguments={"path": str(target)},
                cwd=str(workspace),
                execution_profile_ceiling=EffectiveExecutionProfile(
                    readable_roots=(workspace,),
                ),
                audit_sink=events.append,
                on_authorized=replace_target,
                executor=execute,
            )
        )

    assert executed is False
    assert [event["type"] for event in events] == [
        "tool_action_frozen",
        "tool_policy_evaluated",
        "tool_execution_failed",
    ]
    assert events[-1]["phase"] == "pre_execution"


def test_workspace_gateway_rejects_a_changed_action_fingerprint(
    tmp_path: Path,
) -> None:
    executed = False

    def change_fingerprint(action):
        object.__setattr__(action, "fingerprint", "0" * 64)

    def execute(_action):
        nonlocal executed
        executed = True

    with pytest.raises(ExecutionAuthorizationError, match="changed"):
        asyncio.run(
            execute_workspace_tool_action(
                None,
                tool_name="bash",
                arguments={"command": ("git", "status")},
                cwd=str(tmp_path),
                on_authorized=change_fingerprint,
                executor=execute,
            )
        )

    assert executed is False


def test_workspace_gateway_emits_one_ordered_success_audit_sequence(
    tmp_path: Path,
) -> None:
    events: list[dict[str, object]] = []

    result = asyncio.run(
        execute_workspace_tool_action(
            None,
            tool_name="read",
            arguments={"path": str(tmp_path / "notes.txt")},
            cwd=str(tmp_path),
            tool_call_id="call-1",
            audit_sink=events.append,
            executor=lambda _action: "ok",
        )
    )

    assert result == "ok"
    assert [event["type"] for event in events] == [
        "tool_action_frozen",
        "tool_policy_evaluated",
        "tool_execution_started",
        "tool_execution_completed",
    ]
    assert {event["action_fingerprint"] for event in events} == {
        events[0]["action_fingerprint"]
    }
    assert all(event["capability"] == "filesystem.read" for event in events)
    assert events[1]["policy_disposition"] == "allow"
    assert events[2]["execution_profile"] == {"configured": False}
    assert events[3]["outcome"] == "completed"


def test_workspace_gateway_includes_approval_in_the_same_audit_sequence(
    tmp_path: Path,
) -> None:
    events: list[dict[str, object]] = []

    class AskPolicy:
        def evaluate(self, subject):
            del subject
            return PolicyDecision.ask("confirm", code="external_effect")

    asyncio.run(
        execute_workspace_tool_action(
            AskPolicy(),
            tool_name="write",
            arguments={
                "path": str(tmp_path / "notes.txt"),
                "content": "private-audit-content",
            },
            cwd=str(tmp_path),
            tool_call_id="call-2",
            approval_resolver=ActorBoundApprovalResolver(
                resolver=HeadlessApprovalResolver(mode="allow"),
                actor_id="/root/reviewer#2",
            ),
            audit_sink=events.append,
            executor=lambda _action: None,
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
    assert events[1]["policy_code"] == "external_effect"
    assert events[2]["action_id"] == events[3]["action_id"]
    assert events[3]["approval_decision"] == "allow"
    assert {event["actor_id"] for event in events} == {"/root/reviewer#2"}
    assert {event["tool_call_id"] for event in events} == {"call-2"}
    assert len({event["action_fingerprint"] for event in events}) == 1
    approval_id = events[2]["action_id"]
    assert {
        event["approval_action_id"]
        for event in events
        if event["type"]
        in {
            "tool_execution_started",
            "tool_execution_completed",
        }
    } == {approval_id}
    serialized = json.dumps(events)
    assert "private-audit-content" not in serialized
    assert str(tmp_path / "notes.txt") not in serialized


def test_workspace_gateway_reuses_policy_scoped_session_approval(
    tmp_path: Path,
) -> None:
    async def run() -> tuple[
        list[dict[str, object]],
        list[dict[str, object]],
        list[dict[str, object]],
    ]:
        payloads: list[dict[str, object]] = []
        presented = asyncio.Event()
        resolver = InteractiveApprovalResolver(
            fallback=HeadlessApprovalResolver(mode="deny")
        )

        def present(payload: dict[str, object]) -> None:
            payloads.append(payload)
            presented.set()

        resolver.set_request_presenter(present)
        first_events: list[dict[str, object]] = []
        first = asyncio.create_task(
            _execute_git_push(
                "git push origin main",
                cwd=tmp_path,
                resolver=resolver,
                events=first_events,
            )
        )
        await presented.wait()
        first_action_id = payloads[0]["action_id"]
        assert isinstance(first_action_id, str)
        assert await resolver.handle_result(
            first_action_id,
            approved=True,
            scope="session",
        )
        assert await first == "executed"

        second_events: list[dict[str, object]] = []
        assert (
            await _execute_git_push(
                "git push --porcelain origin main",
                cwd=tmp_path,
                resolver=resolver,
                events=second_events,
            )
            == "executed"
        )
        assert len(payloads) == 1

        changed_events: list[dict[str, object]] = []
        assert (
            await _execute_git_push(
                "git push origin release",
                cwd=tmp_path,
                resolver=resolver,
                events=changed_events,
            )
            == "executed"
        )
        assert len(payloads) == 1
        return first_events, second_events, changed_events

    first_events, second_events, changed_events = asyncio.run(run())

    assert [event["type"] for event in first_events] == [
        "tool_action_frozen",
        "tool_policy_evaluated",
        "tool_approval_requested",
        "tool_approval_resolved",
        "tool_execution_started",
        "tool_execution_completed",
    ]
    assert first_events[3]["approval_scope"] == "session"
    assert first_events[3]["approval_source"] == "reviewer"
    grant_id = first_events[3]["approval_grant_id"]
    assert isinstance(grant_id, str)
    assert [event["type"] for event in second_events] == [
        "tool_action_frozen",
        "tool_policy_evaluated",
        "tool_approval_resolved",
        "tool_execution_started",
        "tool_execution_completed",
    ]
    assert second_events[2]["approval_scope"] == "session"
    assert second_events[2]["approval_source"] == "session_grant"
    assert second_events[2]["approval_grant_id"] == grant_id
    assert [event["type"] for event in changed_events] == [
        "tool_action_frozen",
        "tool_policy_evaluated",
        "tool_approval_resolved",
        "tool_execution_started",
        "tool_execution_completed",
    ]
    assert changed_events[2]["approval_source"] == "session_grant"
    assert changed_events[2]["approval_grant_id"] == grant_id


def test_workspace_gateway_reuses_persistent_project_policy_after_restart(
    tmp_path: Path,
) -> None:
    policy_path = tmp_path / ".loushang" / "approval-policy.json"

    async def approve() -> list[dict[str, object]]:
        payloads: list[dict[str, object]] = []
        presented = asyncio.Event()
        resolver = InteractiveApprovalResolver(
            fallback=HeadlessApprovalResolver(mode="deny"),
            policy_stores={
                "project": JsonApprovalPolicyRuleStore("project", policy_path)
            },
        )
        resolver.set_request_presenter(
            lambda payload: (payloads.append(payload), presented.set())
        )
        events: list[dict[str, object]] = []
        pending = asyncio.create_task(
            _execute_git_push(
                "git push origin main",
                cwd=tmp_path,
                resolver=resolver,
                events=events,
            )
        )
        await presented.wait()
        options = payloads[0]["approval_options"]
        assert tuple(option["outcome"] for option in options) == (
            "allow_once",
            "allow_session",
            "allow_project",
            "deny",
        )
        action_id = payloads[0]["action_id"]
        assert isinstance(action_id, str)
        assert await resolver.handle_result(
            action_id,
            outcome="allow_project",
        )
        assert await pending == "executed"
        return events

    first_events = asyncio.run(approve())
    restarted = InteractiveApprovalResolver(
        fallback=HeadlessApprovalResolver(mode="deny"),
        policy_stores={
            "project": JsonApprovalPolicyRuleStore("project", policy_path)
        },
    )
    second_events: list[dict[str, object]] = []

    assert (
        asyncio.run(
            _execute_git_push(
                "git push origin release",
                cwd=tmp_path,
                resolver=restarted,
                events=second_events,
            )
        )
        == "executed"
    )
    assert first_events[3]["approval_policy_scope"] == "project"
    assert second_events[2]["approval_source"] == "policy_rule"
    assert second_events[2]["approval_policy_scope"] == "project"


def test_workspace_gateway_detaches_each_audit_event_for_observers(
    tmp_path: Path,
) -> None:
    events: list[dict[str, object]] = []

    def mutate_event(event: dict[str, object]) -> None:
        events.append(event)
        if event["type"] == "tool_action_frozen":
            summary = event["action_summary"]
            assert isinstance(summary, dict)
            summary["argument_count"] = 999

    asyncio.run(
        execute_workspace_tool_action(
            None,
            tool_name="read",
            arguments={"path": str(tmp_path / "notes.txt")},
            cwd=str(tmp_path),
            audit_sink=mutate_event,
            executor=lambda _action: None,
        )
    )

    assert events[0]["action_summary"]["argument_count"] == 999  # type: ignore[index]
    assert events[1]["action_summary"]["argument_count"] == 1  # type: ignore[index]
    assert events[2]["action_summary"]["argument_count"] == 1  # type: ignore[index]


def test_workspace_gateway_stops_audit_sequence_when_approval_denies(
    tmp_path: Path,
) -> None:
    events: list[dict[str, object]] = []

    class AskPolicy:
        def evaluate(self, subject):
            del subject
            return PolicyDecision.ask("confirm", code="external_effect")

    with pytest.raises(PermissionError):
        asyncio.run(
            execute_workspace_tool_action(
                AskPolicy(),
                tool_name="write",
                arguments={"path": str(tmp_path / "notes.txt"), "content": "hello"},
                cwd=str(tmp_path),
                approval_resolver=HeadlessApprovalResolver(mode="deny"),
                audit_sink=events.append,
                executor=lambda _action: pytest.fail("executor must not run"),
            )
        )

    assert [event["type"] for event in events] == [
        "tool_action_frozen",
        "tool_policy_evaluated",
        "tool_approval_requested",
        "tool_approval_resolved",
    ]
    assert events[-1]["approval_decision"] == "deny"


def test_workspace_gateway_emits_terminal_failure_without_masking_error(
    tmp_path: Path,
) -> None:
    events: list[dict[str, object]] = []

    def fail(_action):
        raise RuntimeError("private executor detail")

    with pytest.raises(RuntimeError, match="private executor detail"):
        asyncio.run(
            execute_workspace_tool_action(
                None,
                tool_name="read",
                arguments={"path": str(tmp_path / "notes.txt")},
                cwd=str(tmp_path),
                audit_sink=events.append,
                executor=fail,
            )
        )

    assert [event["type"] for event in events] == [
        "tool_action_frozen",
        "tool_policy_evaluated",
        "tool_execution_started",
        "tool_execution_failed",
    ]
    assert events[-1]["outcome"] == "error"
    assert events[-1]["phase"] == "execution"
    assert "private executor detail" not in json.dumps(events)


def test_workspace_gateway_records_executor_cancellation(
    tmp_path: Path,
) -> None:
    events: list[dict[str, object]] = []

    def cancel(_action):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            execute_workspace_tool_action(
                None,
                tool_name="read",
                arguments={"path": str(tmp_path / "notes.txt")},
                cwd=str(tmp_path),
                audit_sink=events.append,
                executor=cancel,
            )
        )

    assert events[-1]["type"] == "tool_execution_failed"
    assert events[-1]["outcome"] == "cancelled"


def test_workspace_gateway_audit_redacts_commands_paths_content_and_environment(
    tmp_path: Path,
) -> None:
    raw_command = (
        "curl -H 'Authorization: Bearer TOP_SECRET' "
        "https://user:password@example.com/private"
    )
    command_subject = normalize_command_subject(
        ("/bin/bash", "-lc", raw_command),
        cwd=str(tmp_path),
    )
    policy_subject = build_tool_policy_subject(
        tool_name="bash",
        arguments={
            "command": raw_command,
            "cwd": str(tmp_path),
            "env": (("API_TOKEN", "ENV_SECRET"),),
        },
        cwd=str(tmp_path),
        command=command_subject,
    )
    events: list[dict[str, object]] = []

    asyncio.run(
        execute_workspace_tool_action(
            None,
            tool_name="bash",
            arguments=policy_subject.arguments,
            cwd=str(tmp_path),
            policy_subject=policy_subject,
            audit_sink=events.append,
            executor=lambda _action: None,
        )
    )

    serialized = json.dumps(events, sort_keys=True)
    for secret in (
        raw_command,
        "TOP_SECRET",
        "ENV_SECRET",
        "Authorization",
        "user:password",
        str(tmp_path),
    ):
        assert secret not in serialized
    assert events[0]["capability"] == "network.request"
    assert events[0]["command_summary"] == {
        "form": "shell",
        "executable": "curl",
        "argument_count": 3,
        "flags": ["-H"],
        "normalization_complete": True,
        "command_count": 1,
        "executables": ["curl"],
    }


def test_workspace_gateway_redacts_file_name_and_content(
    tmp_path: Path,
) -> None:
    events: list[dict[str, object]] = []
    path = tmp_path / "private-customer-name.txt"

    asyncio.run(
        execute_workspace_tool_action(
            None,
            tool_name="write",
            arguments={"path": str(path), "content": "CUSTOMER_SECRET"},
            cwd=str(tmp_path),
            audit_sink=events.append,
            executor=lambda _action: None,
        )
    )

    serialized = json.dumps(events, sort_keys=True)
    assert "private-customer-name" not in serialized
    assert "CUSTOMER_SECRET" not in serialized
    assert events[0]["action_summary"] == {
        "argument_count": 2,
        "has_environment": False,
        "has_stdin": False,
        "resource": {"kind": "file", "scope": "workspace"},
    }


def test_workspace_gateway_redacts_unknown_executable_names(
    tmp_path: Path,
) -> None:
    raw_command = "./customer-acme-deploy --token COMMAND_SECRET"
    command_subject = normalize_command_subject(
        ("/bin/bash", "-lc", raw_command),
        cwd=str(tmp_path),
    )
    policy_subject = build_tool_policy_subject(
        tool_name="bash",
        arguments={"command": raw_command, "cwd": str(tmp_path)},
        cwd=str(tmp_path),
        command=command_subject,
    )
    events: list[dict[str, object]] = []

    asyncio.run(
        execute_workspace_tool_action(
            None,
            tool_name="bash",
            arguments=policy_subject.arguments,
            cwd=str(tmp_path),
            policy_subject=policy_subject,
            audit_sink=events.append,
            executor=lambda _action: None,
        )
    )

    serialized = json.dumps(events, sort_keys=True)
    assert "customer-acme-deploy" not in serialized
    assert "COMMAND_SECRET" not in serialized
    assert events[0]["command_summary"]["executable"] == "other"  # type: ignore[index]


async def _execute_git_push(
    command: str,
    *,
    cwd: Path,
    resolver: InteractiveApprovalResolver,
    events: list[dict[str, object]],
) -> str:
    command_subject = normalize_command_subject(
        ("/bin/sh", "-lc", command),
        cwd=str(cwd),
    )
    policy_subject = build_tool_policy_subject(
        tool_name="bash",
        arguments={"command": command},
        cwd=str(cwd),
        command=command_subject,
    )
    return await execute_workspace_tool_action(
        PolicyEngine(),
        tool_name="bash",
        arguments=policy_subject.arguments,
        cwd=str(cwd),
        policy_subject=policy_subject,
        approval_resolver=resolver,
        audit_sink=events.append,
        executor=lambda _action: "executed",
    )
