from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.coding.sandbox import (
    CodingSandboxScopePolicy,
    bind_coding_sandbox_runtime,
)
from loushang.harness.authorization import EffectiveExecutionProfile
from loushang.harness.diagnostics import DiagnosticsService
from loushang.harness.environment import LocalHostEnvironmentProbe
from loushang.harness.sandbox import (
    SandboxBackendRegistry,
    SandboxSettings,
    SandboxStatus,
)
from loushang.harness.workspace.exec import ExecRequest, ExecService


def _materialized_request(cwd: Path) -> ExecRequest:
    return ExecRequest(
        command=("python3", "-c", "print(1)"),
        cwd=str(cwd),
        effective_environment=(),
    )


def test_coding_scope_policy_makes_root_sessions_writable(tmp_path: Path) -> None:
    child = tmp_path / "package"
    child.mkdir()
    policy = CodingSandboxScopePolicy(
        workspace_root=tmp_path,
        writable_workspace=True,
    )

    scope = policy(_materialized_request(child))

    assert scope.cwd == child
    assert scope.readable_roots == (tmp_path,)
    assert scope.writable_roots == (tmp_path,)
    assert scope.network == "allowed"


def test_coding_scope_policy_keeps_read_only_children_non_writable(
    tmp_path: Path,
) -> None:
    policy = CodingSandboxScopePolicy(
        workspace_root=tmp_path,
        writable_workspace=False,
    )

    scope = policy(_materialized_request(tmp_path))

    assert scope.readable_roots == (tmp_path,)
    assert scope.writable_roots == ()


def test_coding_scope_policy_consumes_a_narrower_authorized_profile(
    tmp_path: Path,
) -> None:
    policy = CodingSandboxScopePolicy(
        workspace_root=tmp_path,
        writable_workspace=True,
        execution_profile=EffectiveExecutionProfile(
            readable_roots=(tmp_path,),
            network="denied",
        ),
    )

    scope = policy(_materialized_request(tmp_path))

    assert scope.readable_roots == (tmp_path,)
    assert scope.writable_roots == ()
    assert scope.network == "denied"


def test_coding_scope_policy_constrains_a_per_execution_profile(
    tmp_path: Path,
) -> None:
    policy = CodingSandboxScopePolicy(
        workspace_root=tmp_path,
        writable_workspace=True,
    )
    request = replace(
        _materialized_request(tmp_path),
        execution_profile=EffectiveExecutionProfile(
            readable_roots=(tmp_path,),
            network="restricted",
        ),
    )

    scope = policy(request)

    assert scope.writable_roots == ()
    assert scope.network == "restricted"


def test_coding_scope_policy_exposes_linked_worktree_git_metadata(
    tmp_path: Path,
) -> None:
    common_git_dir = tmp_path / "repository.git"
    worktree_git_dir = common_git_dir / "worktrees" / "task"
    worktree_git_dir.mkdir(parents=True)
    (worktree_git_dir / "HEAD").write_text(
        "ref: refs/heads/task\n",
        encoding="utf-8",
    )
    (worktree_git_dir / "commondir").write_text("../..\n", encoding="utf-8")
    workspace = tmp_path / "worktree"
    workspace.mkdir()
    (workspace / ".git").write_text(
        f"gitdir: {worktree_git_dir}\n",
        encoding="utf-8",
    )

    writable_scope = CodingSandboxScopePolicy(
        workspace_root=workspace,
        writable_workspace=True,
    )(_materialized_request(workspace))
    read_only_scope = CodingSandboxScopePolicy(
        workspace_root=workspace,
        writable_workspace=False,
    )(_materialized_request(workspace))

    assert writable_scope.readable_roots == (workspace, common_git_dir)
    assert writable_scope.writable_roots == (workspace, common_git_dir)
    assert read_only_scope.readable_roots == (workspace, common_git_dir)
    assert read_only_scope.writable_roots == ()


def test_coding_scope_policy_rejects_a_cwd_outside_the_session_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    policy = CodingSandboxScopePolicy(workspace_root=workspace)

    with pytest.raises(PermissionError, match="outside"):
        policy(_materialized_request(outside))


def test_coding_disabled_sandbox_preserves_service_and_emits_no_diagnostic(
    tmp_path: Path,
) -> None:
    service = ExecService()
    diagnostics = DiagnosticsService()
    runtime = bind_coding_sandbox_runtime(
        workspace_root=tmp_path,
        writable_workspace=True,
        settings=SandboxSettings(),
        base_exec_service=service,
        diagnostics_service=diagnostics,
        session_id="session-1",
    )

    assert runtime.exec_service is service
    assert runtime.status().state == "disabled"
    assert diagnostics.get_diagnostics(code="sandbox_unavailable") == []
    asyncio.run(runtime.close())


def test_coding_best_effort_unavailable_backend_records_scoped_diagnostic(
    tmp_path: Path,
) -> None:
    diagnostics = DiagnosticsService()
    runtime = bind_coding_sandbox_runtime(
        workspace_root=tmp_path,
        writable_workspace=True,
        settings=SandboxSettings(enabled=True),
        base_exec_service=ExecService(),
        diagnostics_service=diagnostics,
        session_id="session-1",
        registry=SandboxBackendRegistry(),
        environment_probe=LocalHostEnvironmentProbe(
            platform_name="linux",
            architecture="x86_64",
            environ={},
        ),
    )

    records = diagnostics.get_diagnostics(code="sandbox_unavailable")
    assert runtime.status().state == "degraded"
    assert len(records) == 1
    assert records[0].phase == "runtime"
    assert records[0].source == "exec"
    assert records[0].session_id == "session-1"
    asyncio.run(runtime.close())


def test_coding_session_owns_and_closes_its_sandbox_runtime(
    tmp_path: Path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager

    class Runtime:
        def __init__(self) -> None:
            self.close_count = 0

        def status(self) -> SandboxStatus:
            return SandboxStatus(
                state="enabled",
                backend_id="fake",
                enforced_capabilities=frozenset({"filesystem_roots"}),
            )

        async def close(self) -> None:
            self.close_count += 1

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=tmp_path,
            persist=False,
        )
        runtime = Runtime()
        session = AgentSession(
            agent=Agent(),
            session_manager=manager,
            sandbox_runtime=runtime,  # type: ignore[arg-type]
        )

        assert session.get_sandbox_status().backend_id == "fake"
        await session.dispose()
        assert runtime.close_count == 1

    asyncio.run(scenario())


def test_enabled_coding_session_routes_registered_bash_through_bound_service(
    tmp_path: Path,
) -> None:
    from loushang.agent import Agent
    from loushang.coding.session import AgentSession
    from loushang.coding.session_manager import SessionManager
    from loushang.coding.tool_pack import register_coding_builtin_tools
    from loushang.harness.tools.workspace.registry import WorkspaceToolRegistry
    from loushang.harness.workspace.exec import ExecResult

    class UnexpectedExecService:
        async def execute(self, request, **kwargs):
            del request, kwargs
            raise AssertionError("registry-time execution service must not run")

    class BoundExecService:
        def __init__(self) -> None:
            self.requests: list[ExecRequest] = []

        async def execute(self, request, **kwargs):
            del kwargs
            self.requests.append(request)
            return ExecResult(exit_code=0, stdout="sandbox-bound\n")

    class Runtime:
        def status(self) -> SandboxStatus:
            return SandboxStatus(state="enabled", backend_id="fake")

        async def close(self) -> None:
            return None

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=tmp_path,
            persist=False,
        )
        registry = WorkspaceToolRegistry()
        register_coding_builtin_tools(
            registry,
            exec_service=UnexpectedExecService(),  # type: ignore[arg-type]
        )
        bound_service = BoundExecService()
        session = AgentSession(
            agent=Agent(),
            session_manager=manager,
            tool_registry=registry,
            active_tool_names=["bash"],
            exec_service=bound_service,  # type: ignore[arg-type]
            sandbox_runtime=Runtime(),  # type: ignore[arg-type]
        )

        result = await session.execute_bash("printf ignored")

        assert result["output"] == "sandbox-bound\n"
        assert len(bound_service.requests) == 1
        await session.dispose()

    asyncio.run(scenario())
