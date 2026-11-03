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
        "git name-rev HEAD",
        "git whatchanged -1",
        "git branch --edit-description",
        "git tag --delete old",
        "git remote add upstream https://example.com/repo",
        "git stash pop",
        "git stash drop",
        "git stash clear",
        "git worktree add ../review topic",
        "& git status",
        "& 'C:\\Program Files\\Git\\bin\\git.exe' -C 'C:\\my project' status",
        "git commit -m 'keep `literal` markup'",
        "git commit -m 'summary\n\nremove rm and curl examples'",
        "\n git status; git branch -d topic;\n",
        "GIT.EXE status --short",
    ),
)
def test_powershell_policy_allows_classified_simple_git_commands(
    script: str,
) -> None:
    assert _evaluate_powershell(PolicyEngine(), script).disposition == "allow"


def _git_decision(script: str, dialect: str, engine: PolicyEngine | None = None):
    import shlex

    from loushang.harness.policy import CommandPolicySubject

    command = (
        CommandPolicySubject(
            command=tuple(shlex.split(script)),
            direct_tokens=tuple(shlex.split(script)),
            cwd="/workspace/project",
        )
        if dialect == "direct"
        else shell_command_policy_subject(
            ("test-shell", "-c", script),
            script=script,
            dialect=dialect,
            cwd="/workspace/project",
        )
    )
    return (engine or PolicyEngine()).evaluate(command)


@pytest.mark.parametrize("dialect", ["direct", "posix", "powershell", "cmd"])
@pytest.mark.parametrize(
    "script",
    [
        "git -C /workspace/project status --short",
        "git -C/workspace/project -C src diff --check",
        "git --git-dir=/workspace/project/.git --work-tree=/workspace/project status",
        "git -c core.quotepath=false status",
        "git -ccore.quotepath=false diff",
        "git -c core.editor=true rebase --continue",
        "git check-ignore build",
        "git hash-object README.md",
        "git pack-refs --all",
        'git commit --amend -m "remove rm and curl examples"',
        "git branch -d merged",
        "git branch -D topic",
        "git branch -f topic HEAD~1",
        "git branch -M renamed",
        "git tag -f local HEAD~1",
        "git tag -d local",
        "git switch -c topic",
        "git checkout -b topic",
        "git merge topic",
        "git merge --abort",
        "git rebase main",
        "git rebase --abort",
        "git cherry-pick HEAD~1",
        "git revert HEAD",
        "git reset --soft HEAD~1",
        "git reset --mixed HEAD~1",
        "git restore --staged README.md",
        "git rm --cached -f README.md",
        "git checkout-index --all",
        "git read-tree --reset HEAD",
        "git reset -- --hard",
        "git restore --staged -- --worktree",
        "git mv -- old.txt -file.txt",
        "git stash push -m checkpoint",
        "git stash apply",
        "git stash pop",
        "git stash drop",
        "git stash clear",
        "git worktree add ../review topic",
        "git worktree remove ../review",
        "git remote add upstream https://example.com/repo",
        "git fetch origin",
        "git pull --ff-only",
        "git push --dry-run origin main",
        "git clean -ndx",
        "git reflog show",
        "git reflog expire --dry-run --expire=now --all",
        "git prune -n --expire=now",
    ],
)
def test_recoverable_git_operations_need_no_approval_in_any_dialect(script, dialect):
    decision = _git_decision(script, dialect)
    assert decision.disposition == "allow", (script, dialect, decision)


@pytest.mark.parametrize("dialect", ["posix", "powershell", "cmd"])
@pytest.mark.parametrize("separator", [" && ", " || ", "\n"])
def test_literal_git_chains_classify_every_command(dialect, separator):
    assert _git_decision(
        f"git -C /workspace/project status{separator}git branch -d merged", dialect,
    ).disposition == "allow"
    decision = _git_decision(
        f"git status{separator}git -C /workspace/project push origin main", dialect,
    )
    assert (decision.disposition, decision.code) == ("ask", "external_publication")


@pytest.mark.parametrize("dialect", ["posix", "powershell", "cmd"])
def test_git_only_pipeline_retains_each_commands_effects(dialect):
    assert _git_decision("git diff | git apply --check", dialect).disposition == "allow"
    assert _git_decision("git diff | git push origin main", dialect).code == "external_publication"


@pytest.mark.parametrize("dialect", ["direct", "posix", "powershell", "cmd"])
@pytest.mark.parametrize(
    ("script", "code"),
    [
        ("git reset --hard HEAD", "repository_history_rewrite"),
        ("git clean -fdx", "repository_clean"),
        ("git checkout -- README.md", "repository_worktree_discard"),
        ("git switch -f topic", "repository_worktree_discard"),
        ("git restore README.md", "repository_worktree_discard"),
        ("git restore --staged --worktree README.md", "repository_worktree_discard"),
        ("git rm -f README.md", "repository_worktree_discard"),
        ("git rm -f -- --cached", "repository_worktree_discard"),
        ("git rm -f --pathspec-from-file --cached", "repository_worktree_discard"),
        ("git restore -- --staged", "repository_worktree_discard"),
        ("git restore --pathspec-from-file --staged", "repository_worktree_discard"),
        ("git mv -f old.txt new.txt", "repository_worktree_discard"),
        ("git checkout-index -f README.md", "repository_worktree_discard"),
        ("git read-tree --reset -u HEAD", "repository_worktree_discard"),
        ("git worktree remove --force ../review", "repository_deletion"),
        ("git clean -i", "repository_clean"),
        ("git clean -f -e -n", "repository_clean"),
        ("git push -o -n origin main", "external_publication"),
        ("git push --dry-run --no-dry-run origin main", "external_publication"),
        ("git prune --expire=now", "repository_recovery_prune"),
        ("git reflog expire --expire=now --all", "repository_recovery_prune"),
        ("git push origin main", "external_publication"),
        ('git rebase --exec="echo run" main', "git_external_execution"),
        ('git submodule foreach "echo run"', "git_external_execution"),
        ("git bisect run ./test.sh", "git_external_execution"),
    ],
)
def test_git_relaxation_keeps_content_loss_and_external_effects_visible(script, code, dialect):
    decision = _git_decision(script, dialect)
    assert (decision.disposition, decision.code) == ("ask", code)


@pytest.mark.parametrize("dialect", ["powershell", "cmd"])
@pytest.mark.parametrize(
    "script",
    [
        "git status > report.txt",
        "git status | unknown-command",
        "git status && unknown-command",
        "git status && git custom-alias",
        "git -c alias.inspect=!evil inspect",
    ],
)
def test_git_relaxation_does_not_approve_unclassified_shell_effects(script, dialect):
    assert _git_decision(script, dialect).disposition == "ask"


def test_git_relaxation_preserves_explicit_managed_rules():
    engine = PolicyEngine(blocked_substrings=("git branch",))
    assert _git_decision("git branch -d topic", "powershell", engine).disposition == "deny"


def test_git_relaxation_does_not_hide_a_normalized_privilege_wrapper():
    decision = _evaluate_action(
        PolicyEngine(), tool_name="bash",
        exec_request=ExecRequest(command=("sudo", "git", "status"), cwd="/tmp"),
    )
    assert (decision.disposition, decision.code) == ("ask", "privilege_escalation")


def test_cmd_does_not_treat_multiline_quoted_text_as_one_literal_git_invocation():
    assert _git_decision('git commit -m "summary\ngit push origin main"', "cmd").disposition == "ask"


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
            "repository_worktree_discard",
        ),
        ("git checkout -- README.md", "repository_worktree_discard"),
        ("git diff --ext-diff", "git_external_execution"),
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
