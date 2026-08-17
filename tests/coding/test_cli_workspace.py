from __future__ import annotations

import asyncio
import json
from io import StringIO
from pathlib import Path

from loushang.coding.cli.__main__ import run_cli
from loushang.coding.cli.workspace import (
    extract_workspace_argv,
    run_coding_workspace_command,
)
from loushang.coding.worktree import create_coding_git_workspace_manager
from loushang.harness.workspace.exec import ExecRequest, ExecService


async def _git(service: ExecService, cwd: Path, *args: str) -> None:
    result = await service.execute(
        ExecRequest(command=("git", *args), cwd=str(cwd))
    )
    assert result.exit_code == 0, result.stderr


async def _manager(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    service = ExecService()
    await _git(service, repo, "init")
    await _git(service, repo, "config", "user.email", "workspace@example.invalid")
    await _git(service, repo, "config", "user.name", "Workspace CLI")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    await _git(service, repo, "add", "README.md")
    await _git(service, repo, "commit", "-m", "initial")
    manager = create_coding_git_workspace_manager(
        cwd=repo,
        exec_service=service,
        state_root=tmp_path / "state",
        managed_root=tmp_path / "checkouts",
        uuid_factory=lambda: "cli",
    )
    record = await manager.acquire(owner_ref="/root/worker#1", name_hint="worker")
    (Path(record.path) / "README.md").write_text("from worker\n", encoding="utf-8")
    await manager.capture(record.workspace_ref)
    await manager.release(record.workspace_ref)
    return repo, manager, record.workspace_ref


def test_extracts_workspace_command_before_standard_cli_parsing() -> None:
    assert extract_workspace_argv(("workspace", "list")) == ("list",)
    assert extract_workspace_argv(("--cwd", "/repo", "workspace", "list")) == (
        "--cwd",
        "/repo",
        "list",
    )
    assert extract_workspace_argv(("hello",)) is None


def test_run_cli_routes_workspace_command_before_session_bootstrap() -> None:
    observed: list[tuple[str, ...]] = []

    async def runner(argv, **_kwargs):
        observed.append(tuple(argv))
        return 23

    result = asyncio.run(
        run_cli(
            ("workspace", "list"),
            workspace_runner=runner,
        )
    )

    assert result == 23
    assert observed == [("list",)]


def test_workspace_cli_lists_diffs_applies_and_discards(tmp_path: Path) -> None:
    async def scenario() -> None:
        repo, manager, workspace_ref = await _manager(tmp_path)

        def factory(**_kwargs):
            return manager

        stdout = StringIO()
        stderr = StringIO()
        result = await run_coding_workspace_command(
            ("list", "--format", "json"),
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
            cwd=repo,
            manager_factory=factory,
        )
        assert result == 0
        assert json.loads(stdout.getvalue())[0]["workspace_ref"] == workspace_ref

        stdout = StringIO()
        result = await run_coding_workspace_command(
            ("diff", workspace_ref),
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
            cwd=repo,
            manager_factory=factory,
        )
        assert result == 0
        assert "+from worker" in stdout.getvalue()

        nested = repo / "nested"
        nested.mkdir()
        stdout = StringIO()
        result = await run_coding_workspace_command(
            ("apply", workspace_ref, "--yes"),
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
            cwd=nested,
            manager_factory=factory,
        )
        assert result == 0
        assert (repo / "README.md").read_text(encoding="utf-8") == "from worker\n"
        assert f"to {repo}" in stdout.getvalue()

        stdout = StringIO()
        result = await run_coding_workspace_command(
            ("discard", workspace_ref, "--yes"),
            stdin=StringIO(),
            stdout=stdout,
            stderr=stderr,
            cwd=repo,
            manager_factory=factory,
        )
        assert result == 0
        assert manager.get(workspace_ref).status == "discarded"

    asyncio.run(scenario())


def test_workspace_cli_requires_explicit_noninteractive_confirmation(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repo, manager, workspace_ref = await _manager(tmp_path)
        stderr = StringIO()
        result = await run_coding_workspace_command(
            ("apply", workspace_ref),
            stdin=StringIO("yes\n"),
            stdout=StringIO(),
            stderr=stderr,
            cwd=repo,
            manager_factory=lambda **_kwargs: manager,
        )

        assert result == 2
        assert "pass --yes" in stderr.getvalue()
        assert (repo / "README.md").read_text(encoding="utf-8") == "base\n"

    asyncio.run(scenario())
