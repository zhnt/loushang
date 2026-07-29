from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

from loushang.harness.policy import PolicyDecision


def _context_provider(cwd: Path):
    from loushang.harness.tools.workspace import ToolContext

    def provide(*, tool_call_id: str) -> ToolContext:
        return ToolContext(tool_call_id=tool_call_id, cwd=str(cwd))

    return provide


def test_workspace_read_tool_executes_without_product_adapter(tmp_path: Path) -> None:
    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    target = tmp_path / "notes.txt"
    target.write_text("alpha\nbeta\n", encoding="utf-8")
    tool = wrap_tool_definition(
        create_read_tool_definition(),
        context_provider=_context_provider(tmp_path),
    )

    result = asyncio.run(tool.execute("read-1", {"path": "notes.txt"}))

    assert result.content[0].text == "alpha\nbeta\n"
    assert result.details["path"] == str(target.resolve())


def test_bash_tool_uses_the_live_session_execution_service(
    tmp_path: Path,
) -> None:
    from loushang.harness.authorization import EffectiveExecutionProfile
    from loushang.harness.tools.workspace import (
        ToolContext,
        create_bash_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
    from loushang.harness.workspace.exec import ExecResult, ExecService

    calls: list[object] = []

    async def unexpected_backend(request, **kwargs):
        del request, kwargs
        raise AssertionError("the registry-time execution service must not run")

    async def session_backend(request, **kwargs):
        del kwargs
        calls.append(request)
        return ExecResult(exit_code=0, stdout="session service\n")

    execution_profile = EffectiveExecutionProfile(
        readable_roots=(tmp_path,),
        writable_roots=(tmp_path,),
        network="restricted",
    )
    session_service = ExecService(
        backend=session_backend,
        execution_profile=execution_profile,
    )
    definition = create_bash_tool_definition(
        exec_service=ExecService(backend=unexpected_backend)
    )
    tool = wrap_tool_definition(
        definition,
        context_provider=lambda *, tool_call_id: ToolContext(
            tool_call_id=tool_call_id,
            cwd=str(tmp_path),
            exec_service=session_service,
        ),
    )

    result = asyncio.run(
        tool.execute("bash-session-1", {"command": ["example", "--version"]})
    )

    assert result.content[0].text == "session service\n"
    assert len(calls) == 1
    assert calls[0].cwd == str(tmp_path)
    assert calls[0].execution_profile == execution_profile


@dataclass(frozen=True)
class _DenyReads:
    def evaluate(self, subject) -> PolicyDecision:
        return PolicyDecision.deny(
            f"{subject.tool_name} disabled",
            code="disabled",
        )


def test_workspace_policy_accepts_product_neutral_evaluator(tmp_path: Path) -> None:
    from loushang.harness.tools.workspace import (
        PolicyEnforcementError,
        create_read_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / "notes.txt").write_text("content", encoding="utf-8")
    tool = wrap_tool_definition(
        create_read_tool_definition(policy_engine=_DenyReads()),
        context_provider=_context_provider(tmp_path),
    )

    with pytest.raises(PolicyEnforcementError, match="read disabled") as exc_info:
        asyncio.run(tool.execute("read-2", {"path": "notes.txt"}))

    assert exc_info.value.tool_result_details["policy_code"] == "disabled"


def test_file_tools_enforce_the_live_session_execution_profile(
    tmp_path: Path,
) -> None:
    from loushang.harness.authorization import (
        EffectiveExecutionProfile,
        ExecutionAuthorizationError,
    )
    from loushang.harness.tools.workspace import (
        ToolContext,
        create_edit_tool_definition,
        create_read_tool_definition,
        create_write_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
    from loushang.harness.workspace.exec import ExecService

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("old", encoding="utf-8")
    service = ExecService(
        execution_profile=EffectiveExecutionProfile(
            readable_roots=(workspace,),
            writable_roots=(workspace,),
        )
    )

    def context(*, tool_call_id: str) -> ToolContext:
        return ToolContext(
            tool_call_id=tool_call_id,
            cwd=str(workspace),
            exec_service=service,
        )

    calls = (
        (create_read_tool_definition(), {"path": str(outside)}),
        (
            create_write_tool_definition(),
            {"path": str(outside), "content": "new"},
        ),
        (
            create_edit_tool_definition(),
            {
                "path": str(outside),
                "edits": [{"oldText": "old", "newText": "new"}],
            },
        ),
    )
    for definition, arguments in calls:
        tool = wrap_tool_definition(definition, context_provider=context)
        with pytest.raises(ExecutionAuthorizationError, match="outside"):
            asyncio.run(tool.execute("outside-root", arguments))

    assert outside.read_text(encoding="utf-8") == "old"


def test_workspace_factory_uses_product_neutral_metadata() -> None:
    from loushang.harness.tools.workspace import (
        ALL_TOOL_NAMES,
        create_all_tool_definitions,
    )

    definitions = create_all_tool_definitions()

    assert tuple(definitions) == ALL_TOOL_NAMES
    assert all(
        "coding" not in definition.description.lower()
        for definition in definitions.values()
    )
    assert all(
        definition.prompt_snippet is None
        or "coding" not in definition.prompt_snippet.lower()
        for definition in definitions.values()
    )


def test_workspace_tool_settings_accept_product_policy_factory() -> None:
    from types import SimpleNamespace

    from loushang.harness.tools.workspace import workspace_tool_runtime_settings

    captured: dict[str, object] = {}

    def policy_factory(**kwargs: object) -> object:
        captured.update(kwargs)
        return "policy"

    manager = SimpleNamespace(
        get_tool_settings=lambda: SimpleNamespace(
            blocked_tools=("bash",),
            ask_tools=(),
            blocked_substrings=(),
            ask_substrings=("sudo",),
            blocked_path_substrings=(),
            ask_path_substrings=(),
            approval_mode="deny",
            approval_reason="headless",
        )
    )

    result = workspace_tool_runtime_settings(
        manager,
        policy_factory=policy_factory,
    )

    assert result.policy_engine == "policy"
    assert result.approval_resolver is not None
    assert result.approval_resolver.mode == "deny"
    assert captured["blocked_tools"] == ("bash",)
    assert captured["ask_substrings"] == ("sudo",)


def test_workspace_tool_settings_install_default_policy_without_configuration() -> None:
    from loushang.harness.tools.workspace import workspace_tool_runtime_settings

    created: list[dict[str, object]] = []
    policy = object()

    def policy_factory(**kwargs: object) -> object:
        created.append(dict(kwargs))
        return policy

    result = workspace_tool_runtime_settings(
        None,
        policy_factory=policy_factory,
    )

    assert result.policy_engine is policy
    assert result.approval_resolver is None
    assert created == [{}]


def test_workspace_policy_observes_live_permission_profile_changes(
    tmp_path: Path,
) -> None:
    from loushang.harness.config.agent import SettingsManager, ToolSettings
    from loushang.harness.policy import ToolPolicySubject, evaluate_policy
    from loushang.harness.tools.workspace import workspace_tool_runtime_settings

    manager = SettingsManager(global_settings_path=tmp_path / "settings.json")
    manager.update_settings(
        scope="session",
        tools=ToolSettings(ask_tools=("bash",)),
    )
    runtime = workspace_tool_runtime_settings(manager)
    subject = ToolPolicySubject(tool_name="bash", arguments={"command": ["echo"]})

    standard = asyncio.run(evaluate_policy(runtime.policy_engine, subject))
    assert standard is not None
    assert standard.disposition == "ask"

    manager.set_permission_profile("full_access", scope="session")
    full_access = asyncio.run(evaluate_policy(runtime.policy_engine, subject))
    assert full_access is not None
    assert full_access.disposition == "allow"

    manager.set_permission_profile("cautious", scope="session")
    cautious_write = asyncio.run(
        evaluate_policy(
            runtime.policy_engine,
            ToolPolicySubject(tool_name="write", arguments={"path": "notes.txt"}),
        )
    )
    assert cautious_write is not None
    assert cautious_write.disposition == "ask"
    assert cautious_write.code == "cautious_workspace_mutation"
