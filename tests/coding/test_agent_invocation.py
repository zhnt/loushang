from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.agent import AbortController
from loushang.ai.types import ToolCall
from loushang.coding.agent_invocation import CodingCliAgentInvocationAdapter
from loushang.coding.cli.args import parse_args
from loushang.harness.tools.agent_delegate import (
    AgentDelegateToolPack,
    AgentInvocationRequest,
)
from loushang.harness.tools.execution import ToolCallContext
from loushang.harness.tools.workspace.authorization import (
    create_workspace_tool_execution_host,
)
from loushang.harness.workspace.exec import ExecResult, ExecService


def _executable(tmp_path: Path) -> Path:
    executable = tmp_path / "loushang"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    return executable


def test_coding_cli_invocation_compiles_a_hardened_non_widening_command(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    nested = workspace / "src"
    nested.mkdir(parents=True)
    executable = _executable(tmp_path)
    adapter = CodingCliAgentInvocationAdapter(
        workspace_root=workspace,
        parent_allowed_tools=(
            "delegate_agent",
            "spawn_agent",
            "bash",
            "read",
            "grep",
        ),
        executable=executable,
        environment={"PATH": "/usr/bin", "PROVIDER_TOKEN": "secret"},
        timeout_seconds=45,
    )
    task = "inspect the parser without changing files"

    prepared = adapter.prepare(
        AgentInvocationRequest(
            agent_type="explorer",
            task=task,
            cwd="src",
        ),
        default_cwd=str(workspace),
        model=SimpleNamespace(
            provider_id="openai", endpoint_id="responses", id="gpt-test"
        ),
    )

    request = prepared.exec_request
    assert request.cwd == str(nested)
    assert request.stdin == task
    assert task not in request.command
    assert request.timeout_seconds == 45
    assert request.capture_full_output is False
    assert request.retain_output_artifacts is False
    assert request.effective_environment == (
        ("PATH", "/usr/bin"),
        ("PROVIDER_TOKEN", "secret"),
    )
    assert prepared.allowed_tools == ("read", "grep")
    assert prepared.model_ref == "openai:responses:gpt-test"
    assert request.command[0] == str(executable.resolve())
    assert _flag_value(request.command, "--mode") == "print"
    assert _flag_value(request.command, "--tools") == "read,grep"
    assert _flag_value(request.command, "--cwd") == str(nested)
    assert _flag_value(request.command, "--model") == "openai:responses:gpt-test"
    assert _flag_value(request.command, "--system-prompt")
    assert {
        "--no-session",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
    }.issubset(request.command)
    assert "delegate_agent" not in _flag_value(request.command, "--tools")
    assert "spawn_agent" not in _flag_value(request.command, "--tools")
    assert "bash" not in _flag_value(request.command, "--tools")
    child_args = parse_args(list(request.command[1:]))
    assert child_args.mode == "print"
    assert child_args.no_session is True
    assert child_args.no_extensions is True
    assert child_args.no_skills is True
    assert child_args.no_prompt_templates is True
    assert child_args.tools == ("read", "grep")


def test_coding_cli_invocation_uses_the_live_session_cwd_as_dynamic_root(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    adapter = CodingCliAgentInvocationAdapter(
        parent_allowed_tools=("read",),
        executable=_executable(tmp_path),
    )

    prepared = adapter.prepare(
        AgentInvocationRequest(agent_type="reviewer", task="review"),
        default_cwd=str(second),
        model=None,
    )

    assert prepared.exec_request.cwd == str(second)


def test_coding_cli_invocation_rejects_cwd_escape_and_non_read_only_roles(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    adapter = CodingCliAgentInvocationAdapter(
        workspace_root=workspace,
        parent_allowed_tools=("read",),
        executable=_executable(tmp_path),
    )

    with pytest.raises(PermissionError, match="outside"):
        adapter.prepare(
            AgentInvocationRequest(
                agent_type="reviewer",
                task="review",
                cwd=str(outside),
            ),
            default_cwd=str(workspace),
            model=None,
        )
    with pytest.raises(ValueError, match="non-read-only"):
        adapter.prepare(
            AgentInvocationRequest(
                agent_type="implementation_worker",
                task="edit",
            ),
            default_cwd=str(workspace),
            model=None,
        )


def test_coding_cli_invocation_rejects_when_parent_grants_no_role_tools(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    adapter = CodingCliAgentInvocationAdapter(
        workspace_root=workspace,
        parent_allowed_tools=("delegate_agent", "spawn_agent"),
        executable=_executable(tmp_path),
    )

    with pytest.raises(PermissionError, match="grants no admitted tools"):
        adapter.prepare(
            AgentInvocationRequest(agent_type="reviewer", task="review"),
            default_cwd=str(workspace),
            model=None,
        )


def test_coding_cli_invocation_projects_bounded_stdout_and_errors(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    adapter = CodingCliAgentInvocationAdapter(
        workspace_root=workspace,
        parent_allowed_tools=("read",),
        executable=_executable(tmp_path),
        preview_max_bytes=16,
        preview_max_lines=2,
        rolling_max_bytes=32,
    )
    prepared = adapter.prepare(
        AgentInvocationRequest(agent_type="reviewer", task="review"),
        default_cwd=str(workspace),
        model=None,
    )

    success = adapter.project(
        prepared,
        ExecResult(exit_code=0, stdout="one\ntwo\nthree\n"),
    )
    failure = adapter.project(
        prepared,
        ExecResult(exit_code=2, stdout="ignored", stderr="safe failure"),
    )

    assert success.output_text == "two\nthree\n"
    assert success.truncated is True
    assert failure.output_text == "safe failure"
    assert failure.exit_code == 2


def test_coding_delegate_runs_through_the_real_exec_service(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = tmp_path / "loushang"
    executable.write_text(
        "#!/bin/sh\ntask=$(cat)\nprintf 'child:%s\\n' \"$task\"\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    adapter = CodingCliAgentInvocationAdapter(
        workspace_root=workspace,
        parent_allowed_tools=("read",),
        executable=executable,
        environment={"PATH": "/usr/bin:/bin"},
    )
    definition = AgentDelegateToolPack(adapter=adapter).definition()

    task = "检查 parser\nreport ✓"
    result = asyncio.run(
        create_workspace_tool_execution_host(policy_evaluator=None).dispatch(
            definition,
            ToolCall(
                type="toolCall",
                id="delegate-1",
                name="delegate_agent",
                arguments={"agent_type": "reviewer", "task": task},
            ),
            ToolCallContext(
                tool_call_id="delegate-1",
                cwd=str(workspace),
                exec_service=ExecService(),
            ),
        )
    )

    assert result.content[0].text == f"child:{task}\n"
    assert result.details["exit_code"] == 0


def test_coding_delegate_cancels_the_real_subprocess(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = tmp_path / "loushang"
    executable.write_text("#!/bin/sh\nsleep 30\nprintf never\n", encoding="utf-8")
    executable.chmod(0o755)
    adapter = CodingCliAgentInvocationAdapter(
        workspace_root=workspace,
        parent_allowed_tools=("read",),
        executable=executable,
        environment={"PATH": "/usr/bin:/bin"},
        timeout_seconds=5,
    )
    definition = AgentDelegateToolPack(adapter=adapter).definition()
    controller = AbortController()

    async def scenario() -> None:
        async def abort_soon() -> None:
            await asyncio.sleep(0.05)
            controller.abort()

        abort_task = asyncio.create_task(abort_soon())
        with pytest.raises(RuntimeError, match="Delegated agent aborted"):
            await create_workspace_tool_execution_host(policy_evaluator=None).dispatch(
                definition,
                ToolCall(
                    type="toolCall",
                    id="delegate-cancel",
                    name="delegate_agent",
                    arguments={"agent_type": "reviewer", "task": "wait"},
                ),
                ToolCallContext(
                    tool_call_id="delegate-cancel",
                    cwd=str(workspace),
                    signal=controller.signal,
                    exec_service=ExecService(),
                ),
            )
        await abort_task

    asyncio.run(scenario())


def test_coding_invocation_bounds_large_output_without_leaking_artifacts(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    artifact_dir = tmp_path / "artifacts"
    workspace.mkdir()
    artifact_dir.mkdir()
    executable = tmp_path / "loushang"
    executable.write_text(
        "#!/bin/sh\ni=0\nwhile [ $i -lt 400 ]; do "
        "printf 'line-%04d\\n' \"$i\"; i=$((i + 1)); done\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    adapter = CodingCliAgentInvocationAdapter(
        workspace_root=workspace,
        parent_allowed_tools=("read",),
        executable=executable,
        environment={"PATH": "/usr/bin:/bin"},
        preview_max_bytes=1024,
        preview_max_lines=2,
        rolling_max_bytes=1024,
    )
    prepared = adapter.prepare(
        AgentInvocationRequest(agent_type="reviewer", task="inspect"),
        default_cwd=str(workspace),
        model=None,
    )

    exec_result = asyncio.run(
        ExecService().execute(
            replace(prepared.exec_request, artifact_dir=str(artifact_dir))
        )
    )
    projected = adapter.project(prepared, exec_result)

    assert projected.output_text == "line-0398\nline-0399\n"
    assert projected.truncated is True
    assert exec_result.stdout_artifact_path is None
    assert list(artifact_dir.iterdir()) == []


def _flag_value(command: tuple[str, ...], flag: str) -> str:
    index = command.index(flag)
    return command[index + 1]
