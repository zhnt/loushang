from __future__ import annotations

import os

import pytest

from loushang.harness.policy import (
    build_tool_policy_subject,
    executable_search_path_from_env,
    normalize_command_subject,
    shell_command_policy_subject,
)
from loushang.harness.policy_engine import PolicyEngine
from loushang.harness.workspace.exec import ExecRequest, materialize_exec_request


def _evaluate_action(
    engine: PolicyEngine, *, tool_name: str, exec_request: ExecRequest
):
    request = materialize_exec_request(exec_request)
    environment = request.effective_environment
    assert environment is not None
    return engine.evaluate(
        build_tool_policy_subject(
            tool_name=tool_name,
            arguments={"command": request.command, "cwd": request.cwd},
            cwd=request.cwd,
            command=normalize_command_subject(
                request.command,
                cwd=request.cwd,
                executable_search_path=executable_search_path_from_env(
                    environment,
                    default=os.defpath,
                ),
                environment_overrides=environment,
                environment_is_complete=True,
            ),
        )
    )


def _evaluate_tool_call(
    engine: PolicyEngine,
    *,
    tool_name: str,
    arguments: dict[str, object],
    cwd: str | None = None,
):
    return engine.evaluate(
        build_tool_policy_subject(
            tool_name=tool_name,
            arguments=arguments,
            cwd=cwd,
        )
    )


def test_policy_engine_is_product_neutral_and_namespaces_rules() -> None:
    engine = PolicyEngine(
        rule_id_prefix="design",
        blocked_substrings=("rm -rf",),
    )

    decision = _evaluate_action(
        engine,
        tool_name="bash",
        exec_request=ExecRequest(
            command=("/bin/sh", "-lc", "rm -rf /tmp/demo"), cwd="/tmp"
        ),
    )

    assert decision.disposition == "deny"
    assert engine._evaluator.rules[0].id == "design.command.block.0"


def test_policy_engine_accepts_product_specific_tool_and_path_values() -> None:
    engine = PolicyEngine(
        rule_id_prefix="ppt",
        blocked_tools=("write",),
        ask_path_substrings=("/secrets",),
    )

    tool_decision = _evaluate_tool_call(
        engine, tool_name="write", arguments={"path": "/tmp/file"}, cwd="/tmp"
    )
    path_decision = _evaluate_tool_call(
        engine, tool_name="read", arguments={"path": "/tmp/secrets/key"}, cwd="/tmp"
    )

    assert tool_decision.disposition == "deny"
    assert path_decision.disposition == "ask"


@pytest.mark.parametrize("tool_name", ["bash", "shell"])
def test_policy_engine_blocks_stable_capability_across_tool_names(
    tool_name: str,
) -> None:
    decision = PolicyEngine(blocked_capabilities=("workspace.command",)).evaluate(
        build_tool_policy_subject(
            tool_name=tool_name,
            capability_id="workspace.command",
            arguments={"command": "Get-Location"},
        )
    )

    assert decision.disposition == "deny"
    assert decision.code == "capability_blocked"


def test_policy_engine_can_ask_for_stable_capability() -> None:
    decision = PolicyEngine(ask_capabilities=("workspace.command",)).evaluate(
        build_tool_policy_subject(
            tool_name="shell",
            capability_id="workspace.command",
            arguments={"command": "Get-Location"},
        )
    )

    assert decision.disposition == "ask"
    assert decision.code == "capability_requires_approval"


def test_capability_ask_does_not_weaken_existing_exact_tool_block() -> None:
    decision = PolicyEngine(
        blocked_tools=("shell",),
        ask_capabilities=("workspace.command",),
    ).evaluate(
        build_tool_policy_subject(
            tool_name="shell",
            capability_id="workspace.command",
            arguments={"command": "Get-Location"},
        )
    )

    assert decision.disposition == "deny"
    assert decision.code == "tool_blocked"


def _evaluate_powershell(engine: PolicyEngine, script: str):
    command = (
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        "-NoProfile",
        "-EncodedCommand",
        "transport-blob",
    )
    return engine.evaluate(
        build_tool_policy_subject(
            tool_name="shell",
            arguments={"script": script},
            cwd=r"C:\workspace",
            command=shell_command_policy_subject(
                command,
                script=script,
                dialect="powershell",
                shell_flavor="windows-powershell",
                cwd=r"C:\workspace",
            ),
        )
    )


@pytest.mark.parametrize(
    "script",
    (
        "Get-Location",
        "Get-Process -Id 42",
        "Get-ChildItem -Force -Name",
        "Get-ChildItem src -Recurse -File",
        "dir src",
        "ls -Force",
        "Get-Content README.md -TotalCount 80",
        "Get-Content -Path:README.md",
        "cat README.md",
        "Select-String TODO README.md",
        "Test-Path pyproject.toml",
        "Resolve-Path .",
        "Get-Command git",
        "Write-Output 'hello'",
        "echo hello",
        "rg TODO src tests",
        "where.exe git",
        r".venv\Scripts\python.exe -m pytest tests -q",
        "uv run pytest tests -q",
        "uv run --extra dev pytest tests -q",
        "uv --cache-dir .uv-cache run --extra=dev ruff check src tests",
        "ruff check src tests",
        "mypy src/loushang/ai",
    ),
)
def test_powershell_policy_allows_routine_literal_commands(script: str) -> None:
    engine = PolicyEngine()

    assert _evaluate_powershell(engine, script).disposition == "allow"


@pytest.mark.parametrize(
    "script",
    (
        "Write-Output $env:API_TOKEN",
        "Get-Content *",
        "Get-ItemProperty HKCU:\\Software\\Example",
        "Set-Content output.txt hello",
        "python -c \"open('output.txt', 'w').write('hello')\"",
        "uv tool install example-package",
        "uv run --with example-package pytest tests -q",
        "rg --pre 'python helper.py' TODO .",
        "where git",
        "rg TODO src > report.txt",
        "Get-ChildItem src | Select-Object -First 1",
    ),
)
def test_powershell_policy_asks_for_unclassified_script(script: str) -> None:
    decision = _evaluate_powershell(PolicyEngine(), script)

    assert decision.disposition == "ask"
    assert decision.code == "unclassified_powershell_command"


@pytest.mark.parametrize(
    ("script", "expected_code"),
    (
        ("Get-Content .env", "secret_access"),
        ("Get-Content -Path:.env", "secret_access"),
        ("cat .env", "secret_access"),
        ("Select-String TOKEN .env", "secret_access"),
        ("Get-Content Env:API_TOKEN", "secret_environment"),
        ("Get-Content -LiteralPath:Env:API_TOKEN", "secret_environment"),
    ),
)
def test_powershell_routine_reads_still_protect_secrets(
    script: str,
    expected_code: str,
) -> None:
    decision = _evaluate_powershell(PolicyEngine(), script)

    assert decision.disposition == "ask"
    assert decision.code == expected_code


@pytest.mark.parametrize(
    "script",
    (
        "git status --short --branch",
        "git diff --stat",
        "git log --oneline -3",
        "git show --stat HEAD",
        "git rev-parse --show-toplevel",
        "git branch --show-current",
        "git tag --list",
        "git remote -v",
        "git add README.md",
        "git commit -m 'windows policy'",
        'git commit -m "windows policy"',
        "git switch feature/windows-policy",
        "git merge topic",
        "git fetch origin",
        "git pull --ff-only",
        "git reset HEAD README.md",
        "git clean -ndx",
        "GIT.EXE status --short",
    ),
)
def test_powershell_policy_allows_classified_simple_git_commands(
    script: str,
) -> None:
    assert _evaluate_powershell(PolicyEngine(), script).disposition == "allow"


@pytest.mark.parametrize(
    ("script", "expected_code"),
    (
        ("git push origin main", "external_publication"),
        ("git reset --hard HEAD", "repository_history_rewrite"),
        ("git clean -fdx", "repository_clean"),
        ("git custom-alias", "unclassified_powershell_command"),
        ("git STATUS --short", "unclassified_powershell_command"),
        (
            "git -c alias.inspect='!Write-Output compromised' inspect",
            "unclassified_powershell_command",
        ),
        ("git status; Write-Output 'extra'", "unclassified_powershell_command"),
        ("git $operation", "unclassified_powershell_command"),
        (
            "git switch --discard-changes topic",
            "unclassified_powershell_command",
        ),
        ("git checkout -- README.md", "unclassified_powershell_command"),
        ("git diff --ext-diff", "unclassified_powershell_command"),
        ("git branch --edit-description", "unclassified_powershell_command"),
        ("git tag --delete old", "repository_deletion"),
        (
            "git remote add upstream https://example.com/repo",
            "unclassified_powershell_command",
        ),
        ("git stash pop", "unclassified_powershell_command"),
        ("git worktree add ../review topic", "unclassified_powershell_command"),
        ("& git status", "unclassified_powershell_command"),
        ('"git" status', "unclassified_powershell_command"),
        ("g'it' status", "unclassified_powershell_command"),
        ("git sta$(Write-Output tus)", "unclassified_powershell_command"),
        ("git status | Write-Output", "unclassified_powershell_command"),
        ("git status > report.txt", "unclassified_powershell_command"),
        ("git status # inspect", "unclassified_powershell_command"),
    ),
)
def test_powershell_git_classification_fail_closes_unsafe_or_dynamic_forms(
    script: str,
    expected_code: str,
) -> None:
    decision = _evaluate_powershell(PolicyEngine(), script)

    assert decision.disposition == "ask"
    assert decision.code == expected_code


@pytest.mark.parametrize(
    ("script", "expected_code"),
    [
        ("Remove-Item target -Recurse -Force", "filesystem_deletion"),
        ("rm target -Recurse -Force", "filesystem_deletion"),
        ("ri target /Recurse /Force", "filesystem_deletion"),
        ("Remove-`Item target –Recurse —Force", "filesystem_deletion"),
        ("Invoke-Expression $downloadedText", "dynamic_code_execution"),
        ("i`ex $downloadedText", "dynamic_code_execution"),
        (
            "Start-Process powershell -V`erb RunAs",
            "privilege_escalation",
        ),
        ("Invoke-WebRequest $url | iex", "dynamic_code_execution"),
        ("pwsh -EncodedCommand $payload", "nested_shell_execution"),
    ],
)
def test_powershell_policy_fail_closes_dangerous_and_obfuscated_forms(
    script: str,
    expected_code: str,
) -> None:
    decision = _evaluate_powershell(PolicyEngine(), script)

    assert decision.disposition == "ask"
    assert decision.code == expected_code


def test_cmd_policy_is_unclassified_by_default() -> None:
    decision = PolicyEngine().evaluate(
        build_tool_policy_subject(
            tool_name="shell",
            arguments={"script": "dir"},
            command=shell_command_policy_subject(
                (r"C:\Windows\System32\cmd.exe", "/c", "dir"),
                script="dir",
                dialect="cmd",
            ),
        )
    )

    assert decision.disposition == "ask"
    assert decision.code == "unclassified_cmd_command"


def test_powershell_slash_parameter_compatibility_is_flavor_aware() -> None:
    command = (r"C:\Program Files\PowerShell\7\pwsh.exe", "-EncodedCommand", "blob")
    decision = PolicyEngine().evaluate(
        shell_command_policy_subject(
            command,
            script="Get-Process /Id 42",
            dialect="powershell",
            shell_flavor="pwsh",
        )
    )

    assert decision.disposition == "ask"
    assert decision.code == "unclassified_powershell_command"


def test_posix_normalization_keeps_existing_dialect_and_decision() -> None:
    command = normalize_command_subject(("/bin/sh", "-lc", "pwd"), cwd="/tmp")

    assert command.dialect == "posix"
    assert PolicyEngine().evaluate(command).disposition == "allow"
