"""Heuristic protected-resource effect detection for policy subjects.

Supports policy-generated approval choices and the unclassified-command
fallback (§5.4, §5.5) of
docs/internals/architecture/harness/policy-approval-redesign.md: inspects
command and tool subjects (shell payloads, git/GitHub/HTTP operations,
secret paths and environment) and reports typed effects from
`loushang.harness.effects`. Consumed by `loushang.harness.policy.engine`;
not a stable Product-facing contract.
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePath
from typing import Literal

from loushang.harness.effects import (
    FilesystemEffect,
    NetworkEffect,
    PublicationEffect,
)
from loushang.harness.policy.subjects import (
    CommandPolicySubject,
    PolicySubject,
    ToolPolicySubject,
)

from ._powershell import parse_simple_powershell_command

PolicyEffectKind = Literal[
    "destructive",
    "publication",
    "privilege",
    "secret_access",
    "external_effect",
]

_CONTROL_TOKENS = frozenset({";", "&&", "||", "|", "&", "\n", "(", ")"})
_SHELL_EXECUTABLES = frozenset(
    {"bash", "dash", "fish", "ksh", "rbash", "sh", "zsh"}
)
_PRIVILEGED_EXECUTABLES = frozenset(
    {
        "doas",
        "launchctl",
        "mount",
        "pkexec",
        "su",
        "sudo",
        "systemctl",
        "umount",
    }
)
_DELETION_EXECUTABLES = frozenset(
    {"rm", "rmdir", "shred", "truncate", "unlink"}
)
_PACKAGE_EXECUTABLES = frozenset(
    {"bun", "cargo", "npm", "pip", "pip3", "pnpm", "poetry", "uv", "yarn"}
)
_PACKAGE_MUTATIONS = frozenset(
    {
        "add",
        "ci",
        "install",
        "remove",
        "sync",
        "uninstall",
        "update",
        "upgrade",
    }
)
_SECRET_PATH_COMPONENTS = frozenset(
    {".aws", ".gnupg", ".kube", ".ssh", "secrets"}
)
_SECRET_FILE_NAMES = frozenset(
    {
        ".env",
        ".netrc",
        "credentials",
        "credentials.json",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "service-account.json",
    }
)
_SECRET_ENV_NAME = re.compile(
    r"(?:^|_)(?:API_?KEY|AUTH|CREDENTIALS?|PASSWORD|PRIVATE_?KEY|SECRET|TOKEN)(?:$|_)",
    re.IGNORECASE,
)
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*", re.DOTALL)
_POWERSHELL_SAFE_READ_ONLY = re.compile(
    r"""
    ^\s*(?:
        (?:Microsoft\.PowerShell\.Management\\)?Get-Location
        |
        (?:Microsoft\.PowerShell\.Utility\\)?Get-Date
        |
        (?:Microsoft\.PowerShell\.Management\\)?Get-Process
            (?:\s+-(?:Id\s+[0-9]+|Name\s+[A-Za-z0-9_.-]+))?
        |
        (?:Microsoft\.PowerShell\.Management\\)?Get-ChildItem
            (?:\s+-(?:Name|File|Directory|Force))*
    )\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)
_POWERSHELL_INVOKE_EXPRESSION = re.compile(
    r"(?<![A-Za-z0-9_-])(?:Invoke-Expression|iex)(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
_POWERSHELL_DELETION = re.compile(
    r"(?<![A-Za-z0-9_-])(?:Remove-Item(?:Property)?|rm|ri|del|erase|rd|rmdir)"
    r"(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
_POWERSHELL_NESTED_SHELL = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:pwsh|powershell|cmd|wsl)(?:\.exe)?"
    r"(?![A-Za-z0-9_.-])",
    re.IGNORECASE,
)
_POWERSHELL_DOWNLOAD = re.compile(
    r"(?<![A-Za-z0-9_-])(?:Invoke-WebRequest|Invoke-RestMethod|iwr|irm|curl|wget)"
    r"(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
_POWERSHELL_SECURITY_TRANSLATION: dict[int, str] = {
    ord("\u2013"): "-",
    ord("\u2014"): "-",
    ord("\u2015"): "-",
    ord("\u2018"): "'",
    ord("\u2019"): "'",
    ord("\u201c"): '"',
    ord("\u201d"): '"',
}
_POWERSHELL_CLASSIFIED_GIT_OPERATIONS = frozenset(
    {
        "add",
        "blame",
        "cat-file",
        "clean",
        "commit",
        "describe",
        "diff",
        "fetch",
        "for-each-ref",
        "grep",
        "log",
        "ls-files",
        "ls-tree",
        "merge",
        "merge-base",
        "name-rev",
        "pull",
        "push",
        "reset",
        "rev-parse",
        "shortlog",
        "show",
        "show-ref",
        "status",
        "switch",
        "version",
        "whatchanged",
    }
)
_POWERSHELL_GIT_SAFE_GLOBAL_OPTIONS = frozenset(
    {"--literal-pathspecs", "--no-optional-locks", "--no-pager"}
)
_POWERSHELL_GIT_UNSAFE_SWITCH_OPTIONS = frozenset(
    {"--discard-changes", "--force", "-f"}
)
_POWERSHELL_GIT_EXTERNAL_DIFF_OPTIONS = frozenset({"--ext-diff", "--textconv"})
_POWERSHELL_ROUTINE_LITERAL_COMMANDS = frozenset(
    {
        "echo",
        "cat",
        "dir",
        "get-childitem",
        "get-command",
        "get-content",
        "get-date",
        "get-location",
        "get-process",
        "gci",
        "gc",
        "gi",
        "gl",
        "get-item",
        "ls",
        "pwd",
        "resolve-path",
        "select-string",
        "sls",
        "test-path",
        "type",
        "write-output",
    }
)
_POWERSHELL_PATH_READ_COMMANDS = frozenset(
    {
        "cat",
        "dir",
        "gc",
        "gci",
        "get-childitem",
        "get-content",
        "get-item",
        "gi",
        "ls",
        "resolve-path",
        "select-string",
        "sls",
        "test-path",
        "type",
    }
)
_POWERSHELL_CONTENT_READ_COMMANDS = frozenset(
    {"cat", "gc", "get-content", "select-string", "sls", "type"}
)
_POWERSHELL_ROUTINE_EXTERNAL_COMMANDS = frozenset(
    {
        "mypy",
        "mypy.exe",
        "pytest",
        "pytest.exe",
        "rg",
        "rg.exe",
        "ruff",
        "ruff.exe",
        "where.exe",
    }
)
_POWERSHELL_PYTHON_COMMANDS = frozenset({"py", "py.exe", "python", "python.exe"})
_POWERSHELL_SAFE_PYTHON_MODULES = frozenset({"mypy", "pytest", "ruff"})
_POWERSHELL_UV_COMMANDS = frozenset({"uv", "uv.exe"})
_POWERSHELL_UV_GLOBAL_VALUE_OPTIONS = frozenset({"--cache-dir"})
_POWERSHELL_UV_GLOBAL_FLAG_OPTIONS = frozenset(
    {"--no-cache", "--offline", "--quiet", "-q"}
)
_POWERSHELL_UV_RUN_VALUE_OPTIONS = frozenset({"--extra", "--group"})
_POWERSHELL_UV_RUN_FLAG_OPTIONS = frozenset(
    {"--frozen", "--locked", "--no-dev", "--no-sync", "--offline"}
)
_POWERSHELL_PROVIDER_PATH = re.compile(r"^([A-Za-z][A-Za-z0-9_.-]*):")


@dataclass(frozen=True, slots=True)
class DetectedPolicyEffect:
    kind: PolicyEffectKind
    code: str
    summary: str


@dataclass(frozen=True, slots=True)
class _Invocation:
    executable: str
    arguments: tuple[str, ...]


def detect_policy_effects(subject: PolicySubject) -> tuple[DetectedPolicyEffect, ...]:
    """Detect the small set of effects that interrupt the standard experience."""

    effects: list[DetectedPolicyEffect] = []
    tool_subject = subject if isinstance(subject, ToolPolicySubject) else None
    command = _command_subject(subject)

    if tool_subject is not None:
        _detect_declared_effects(tool_subject, effects)
        _detect_secret_path_effect(tool_subject, effects)
        _detect_secret_environment_effect(tool_subject, effects)

    if command is None:
        return tuple(effects)

    if command.dialect == "powershell":
        _detect_powershell_effects(command, effects)
        return tuple(effects)
    if command.dialect == "cmd":
        _append_effect(
            effects,
            DetectedPolicyEffect(
                "external_effect",
                "unclassified_cmd_command",
                "Cmd script requires approval because its effects were not classified",
            ),
        )
        return tuple(effects)

    invocations, has_pipeline = _command_invocations(command)
    if _has_privilege_wrapper(command) or any(
        invocation.executable in _PRIVILEGED_EXECUTABLES
        for invocation in invocations
    ):
        _append_effect(
            effects,
            DetectedPolicyEffect(
                "privilege",
                "privilege_escalation",
                "Privilege or system authority would be changed",
            ),
        )

    for invocation in invocations:
        _detect_invocation_effects(invocation, effects)

    if has_pipeline and any(
        invocation.executable in {"curl", "wget"} for invocation in invocations
    ) and any(
        invocation.executable in _SHELL_EXECUTABLES for invocation in invocations
    ):
        _append_effect(
            effects,
            DetectedPolicyEffect(
                "external_effect",
                "downloaded_code_execution",
                "Downloaded content would be executed",
            ),
        )

    if not command.normalization_complete:
        _detect_incomplete_command_effects(command, effects)
        if tool_subject is not None:
            unresolved_stdin = tool_subject.arguments.get("stdin")
            if isinstance(unresolved_stdin, str):
                _detect_incomplete_text_effects(unresolved_stdin, effects)
    return tuple(effects)


def _detect_powershell_effects(
    command: CommandPolicySubject,
    effects: list[DetectedPolicyEffect],
) -> None:
    script = command.shell_payload
    if script is None:
        _append_unclassified_powershell(effects)
        return
    normalized = _normalize_powershell_security_text(
        script,
        flavor=command.shell_flavor,
    )
    if command.normalization_complete and _POWERSHELL_SAFE_READ_ONLY.fullmatch(
        normalized
    ):
        return

    detected_count = len(effects)
    if _POWERSHELL_INVOKE_EXPRESSION.search(normalized):
        _append_effect(
            effects,
            DetectedPolicyEffect(
                "external_effect",
                "dynamic_code_execution",
                "PowerShell would dynamically execute command text",
            ),
        )
    if _POWERSHELL_DELETION.search(normalized):
        _append_effect(
            effects,
            DetectedPolicyEffect(
                "destructive",
                "filesystem_deletion",
                "PowerShell would delete filesystem or provider content",
            ),
        )
    if re.search(
        r"(?is)(?<![A-Za-z0-9_-])Start-Process(?![A-Za-z0-9_-]).*?"
        r"-Verb\s*:?[\s'\"]*RunAs(?![A-Za-z0-9_-])",
        normalized,
    ):
        _append_effect(
            effects,
            DetectedPolicyEffect(
                "privilege",
                "privilege_escalation",
                "PowerShell would launch a process with elevated authority",
            ),
        )
    if _POWERSHELL_NESTED_SHELL.search(normalized):
        _append_effect(
            effects,
            DetectedPolicyEffect(
                "external_effect",
                "nested_shell_execution",
                "PowerShell would launch a nested command interpreter",
            ),
        )
    if _POWERSHELL_DOWNLOAD.search(normalized):
        _append_effect(
            effects,
            DetectedPolicyEffect(
                "external_effect",
                "network_content_access",
                "PowerShell would access content from a remote service",
            ),
        )
    if len(effects) != detected_count:
        return

    tokens = parse_simple_powershell_command(script)
    invocation = _powershell_invocation(tokens)
    if invocation is not None:
        invocation_effect_count = len(effects)
        _detect_invocation_effects(invocation, effects)
        _detect_powershell_sensitive_read_effects(invocation, effects)
        if len(effects) != invocation_effect_count:
            return
        if _is_classified_powershell_invocation(invocation):
            return
    _append_unclassified_powershell(effects)


def _powershell_invocation(tokens: tuple[str, ...] | None) -> _Invocation | None:
    if not tokens:
        return None
    executable = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].casefold()
    if executable == "git.exe":
        executable = "git"
    return _Invocation(executable, tuple(tokens[1:]))


def _is_classified_powershell_invocation(invocation: _Invocation) -> bool:
    executable = invocation.executable
    if executable in _POWERSHELL_ROUTINE_LITERAL_COMMANDS:
        return _powershell_literal_arguments_are_safe(invocation)
    if executable in _POWERSHELL_ROUTINE_EXTERNAL_COMMANDS:
        return not (
            executable in {"rg", "rg.exe"}
            and any(
                argument == "--pre" or argument.startswith("--pre=")
                for argument in invocation.arguments
            )
        )
    if executable in _POWERSHELL_PYTHON_COMMANDS:
        return _is_classified_python_check(invocation.arguments)
    if executable in _POWERSHELL_UV_COMMANDS:
        return _is_classified_uv_run(invocation.arguments)
    if executable != "git":
        return False
    operation_and_arguments = _powershell_git_operation(invocation.arguments)
    if operation_and_arguments is None:
        return False
    operation, arguments = operation_and_arguments
    if operation not in _POWERSHELL_CLASSIFIED_GIT_OPERATIONS:
        return _is_classified_git_inspection(operation, arguments)
    if operation == "switch" and any(
        argument in _POWERSHELL_GIT_UNSAFE_SWITCH_OPTIONS for argument in arguments
    ):
        return False
    if operation == "clean" and not any(
        argument == "--dry-run" or (argument.startswith("-") and "n" in argument[1:])
        for argument in arguments
    ):
        return False
    if operation in {"diff", "log", "show", "whatchanged"} and any(
        argument in _POWERSHELL_GIT_EXTERNAL_DIFF_OPTIONS for argument in arguments
    ):
        return False
    return True


def _powershell_literal_arguments_are_safe(invocation: _Invocation) -> bool:
    if any(
        len(argument) > 1
        and argument.startswith("/")
        and argument[1].isalpha()
        for argument in invocation.arguments
    ):
        return False
    if invocation.executable not in _POWERSHELL_PATH_READ_COMMANDS:
        return True
    for argument in invocation.arguments:
        for path_value in _powershell_path_values(argument):
            if _powershell_provider_name(path_value) is not None:
                return False
            if (
                invocation.executable in _POWERSHELL_CONTENT_READ_COMMANDS
                and any(marker in path_value for marker in ("*", "?"))
            ):
                return False
    return True


def _is_classified_python_check(arguments: tuple[str, ...]) -> bool:
    if arguments in {("--version",), ("-V",), ("-VV",)}:
        return True
    return (
        len(arguments) >= 2
        and arguments[0] == "-m"
        and arguments[1].casefold() in _POWERSHELL_SAFE_PYTHON_MODULES
    )


def _is_classified_uv_run(arguments: tuple[str, ...]) -> bool:
    remaining = _consume_powershell_options(
        arguments,
        value_options=_POWERSHELL_UV_GLOBAL_VALUE_OPTIONS,
        flag_options=_POWERSHELL_UV_GLOBAL_FLAG_OPTIONS,
    )
    if remaining is None or not remaining or remaining[0] != "run":
        return False
    remaining = _consume_powershell_options(
        remaining[1:],
        value_options=_POWERSHELL_UV_RUN_VALUE_OPTIONS,
        flag_options=_POWERSHELL_UV_RUN_FLAG_OPTIONS,
    )
    if remaining is None:
        return False
    nested = _powershell_invocation(remaining)
    if nested is None:
        return False
    if nested.executable in _POWERSHELL_ROUTINE_EXTERNAL_COMMANDS:
        return True
    if nested.executable in _POWERSHELL_PYTHON_COMMANDS:
        return _is_classified_python_check(nested.arguments)
    return False


def _consume_powershell_options(
    arguments: tuple[str, ...],
    *,
    value_options: frozenset[str],
    flag_options: frozenset[str],
) -> tuple[str, ...] | None:
    values = list(arguments)
    while values and values[0].startswith("-"):
        value = values.pop(0)
        option, separator, _ = value.partition("=")
        if option in flag_options and not separator:
            continue
        if option not in value_options:
            return None
        if not separator:
            if not values:
                return None
            values.pop(0)
    return tuple(values)


def _detect_powershell_sensitive_read_effects(
    invocation: _Invocation,
    effects: list[DetectedPolicyEffect],
) -> None:
    if invocation.executable not in _POWERSHELL_PATH_READ_COMMANDS:
        return
    for argument in invocation.arguments:
        for path_value in _powershell_path_values(argument):
            provider = _powershell_provider_name(path_value)
            if provider == "env":
                _append_effect(
                    effects,
                    DetectedPolicyEffect(
                        "secret_access",
                        "secret_environment",
                        "Process environment secrets could be exposed",
                    ),
                )
                return
            if _looks_like_secret_path(path_value):
                _append_effect(
                    effects,
                    DetectedPolicyEffect(
                        "secret_access",
                        "secret_access",
                        "A credential or secret-bearing file would be read",
                    ),
                )
                return


def _powershell_path_values(argument: str) -> tuple[str, ...]:
    if not argument.startswith("-"):
        return (argument,)
    for separator in (":", "="):
        _, found, value = argument.partition(separator)
        if found and value:
            return (value,)
    return ()


def _powershell_provider_name(value: str) -> str | None:
    match = _POWERSHELL_PROVIDER_PATH.match(value)
    if match is None:
        return None
    name = match.group(1).casefold()
    # A single-letter prefix is a Windows filesystem drive, not a PowerShell
    # provider such as Env:, Variable:, Cert:, HKCU:, or HKLM:.
    return None if len(name) == 1 else name


def _powershell_git_operation(
    arguments: tuple[str, ...],
) -> tuple[str, tuple[str, ...]] | None:
    values = list(arguments)
    while values and values[0] in _POWERSHELL_GIT_SAFE_GLOBAL_OPTIONS:
        values.pop(0)
    if len(values) == 1 and values[0] in {"--version", "-v"}:
        return "version", ()
    if not values or values[0].startswith("-"):
        return None
    # Git subcommands and aliases are case-sensitive even on Windows.  Folding
    # here could misclassify a user-defined ``STATUS`` shell alias as builtin
    # ``status`` and execute it without approval.
    return values[0], tuple(values[1:])


def _is_classified_git_inspection(
    operation: str,
    arguments: tuple[str, ...],
) -> bool:
    if operation == "branch":
        return not any(
            argument
            in {
                "--copy",
                "--delete",
                "--edit-description",
                "--force",
                "--move",
                "--set-upstream-to",
                "--unset-upstream",
                "-C",
                "-D",
                "-M",
                "-c",
                "-d",
                "-f",
                "-m",
                "-u",
            }
            for argument in arguments
        )
    if operation == "tag":
        return not any(
            argument in {"--delete", "--force", "-d", "-f"} for argument in arguments
        )
    if operation == "remote":
        return not arguments or arguments[0] in {"-v", "get-url", "show"}
    if operation == "worktree":
        return bool(arguments) and arguments[0] == "list"
    if operation == "stash":
        return bool(arguments) and arguments[0] in {"list", "show"}
    return False


def _append_unclassified_powershell(
    effects: list[DetectedPolicyEffect],
) -> None:
    _append_effect(
        effects,
        DetectedPolicyEffect(
            "external_effect",
            "unclassified_powershell_command",
            "PowerShell script requires approval because its effects were not classified",
        ),
    )


def _normalize_powershell_security_text(script: str, *, flavor: str | None) -> str:
    normalized = script.translate(_POWERSHELL_SECURITY_TRANSLATION)
    normalized = normalized.replace("`", "")
    if flavor == "windows-powershell":
        normalized = re.sub(r"(?<!\S)/(?=[A-Za-z])", "-", normalized)
    return normalized


def _detect_declared_effects(
    subject: ToolPolicySubject,
    effects: list[DetectedPolicyEffect],
) -> None:
    for effect in subject.effects:
        if isinstance(effect, FilesystemEffect) and effect.operation == "delete":
            _append_effect(
                effects,
                DetectedPolicyEffect(
                    "destructive",
                    "filesystem_deletion",
                    "Filesystem content would be deleted or truncated",
                ),
            )
        elif isinstance(effect, NetworkEffect) and effect.mutation:
            _append_effect(
                effects,
                DetectedPolicyEffect(
                    "external_effect",
                    "external_system_effect",
                    "An external system would be changed",
                ),
            )
        elif isinstance(effect, PublicationEffect):
            _append_effect(
                effects,
                DetectedPolicyEffect(
                    "publication",
                    "external_publication",
                    "Content or repository state would be published",
                ),
            )


def _detect_secret_path_effect(
    subject: ToolPolicySubject,
    effects: list[DetectedPolicyEffect],
) -> None:
    if any(
        _looks_like_secret_path(candidate)
        for path in subject.paths
        for candidate in (path.raw_path, path.resolved_path)
        if candidate is not None
    ):
        _append_effect(
            effects,
            DetectedPolicyEffect(
                "secret_access",
                "secret_access",
                "A credential or secret-bearing file would be accessed",
            ),
        )


def _detect_secret_environment_effect(
    subject: ToolPolicySubject,
    effects: list[DetectedPolicyEffect],
) -> None:
    environment = subject.arguments.get("env")
    values = (
        tuple(environment.items())
        if isinstance(environment, Mapping)
        else environment
    )
    if isinstance(values, str) or not isinstance(values, (list, tuple)):
        return
    for item in values:
        if isinstance(item, str) or not isinstance(item, (list, tuple)):
            continue
        pair = tuple(item)
        if len(pair) == 2 and isinstance(pair[0], str) and _SECRET_ENV_NAME.search(
            pair[0]
        ):
            _append_effect(
                effects,
                DetectedPolicyEffect(
                    "secret_access",
                    "secret_environment",
                    "A secret-bearing environment value would be exposed",
                ),
            )
            return


def _detect_invocation_effects(
    invocation: _Invocation,
    effects: list[DetectedPolicyEffect],
) -> None:
    executable = invocation.executable
    arguments = invocation.arguments
    if executable in _DELETION_EXECUTABLES:
        _append_effect(
            effects,
            DetectedPolicyEffect(
                "destructive",
                "filesystem_deletion",
                "Filesystem content would be deleted or truncated",
            ),
        )
    if executable == "find" and "-delete" in arguments:
        _append_effect(
            effects,
            DetectedPolicyEffect(
                "destructive",
                "filesystem_deletion",
                "Filesystem content would be deleted",
            ),
        )
    if executable == "git":
        _detect_git_effects(arguments, effects)
    if executable == "gh":
        _detect_github_effects(arguments, effects)
    if executable in {"curl", "wget"}:
        _detect_http_effects(executable, arguments, effects)
    if executable in {"scp", "sftp", "ssh"} or (
        executable == "rsync" and any(":" in value for value in arguments)
    ):
        _append_effect(
            effects,
            DetectedPolicyEffect(
                "external_effect",
                "remote_system_effect",
                "A remote system would be contacted or changed",
            ),
        )
    if executable in _PACKAGE_EXECUTABLES:
        operation = _first_operand(arguments)
        if executable == "uv" and operation == "pip":
            operation = _first_operand(_operation(arguments)[1])
        if operation in _PACKAGE_MUTATIONS:
            _append_effect(
                effects,
                DetectedPolicyEffect(
                    "external_effect",
                    "external_code_installation",
                    "External package code would be installed or changed",
                ),
            )
        if operation == "publish":
            _append_publication(effects, "A package would be published")
    if executable in {"twine"} and _first_operand(arguments) == "upload":
        _append_publication(effects, "A package would be uploaded")
    if executable == "docker" and _first_operand(arguments) == "push":
        _append_publication(effects, "A container image would be published")
    if executable in {"kubectl", "terraform"} and _first_operand(arguments) in {
        "apply",
        "delete",
        "destroy",
        "replace",
    }:
        _append_effect(
            effects,
            DetectedPolicyEffect(
                "external_effect",
                "infrastructure_mutation",
                "External infrastructure would be changed",
            ),
        )
    if executable in {"env", "printenv"} and (
        not arguments or any(_SECRET_ENV_NAME.search(value) for value in arguments)
    ):
        _append_effect(
            effects,
            DetectedPolicyEffect(
                "secret_access",
                "secret_environment",
                "Process environment secrets could be exposed",
            ),
        )
    if executable in {"cat", "head", "less", "more", "sed", "tail"} and any(
        _looks_like_secret_path(value) for value in arguments
    ):
        _append_effect(
            effects,
            DetectedPolicyEffect(
                "secret_access",
                "secret_access",
                "A credential or secret-bearing file would be read",
            ),
        )
    if executable in {"python", "python3"} and any(
        marker in value
        for value in arguments
        for marker in ("os.environ", "os.getenv(", "shutil.rmtree(", "os.remove(")
    ):
        kind: PolicyEffectKind = (
            "secret_access"
            if any(
                marker in value
                for value in arguments
                for marker in ("os.environ", "os.getenv(")
            )
            else "destructive"
        )
        _append_effect(
            effects,
            DetectedPolicyEffect(
                kind,
                "secret_environment" if kind == "secret_access" else "filesystem_deletion",
                (
                    "Process environment secrets could be exposed"
                    if kind == "secret_access"
                    else "Filesystem content would be deleted"
                ),
            ),
        )
    for nested_payload in _nested_shell_payloads(invocation):
        nested_subject = CommandPolicySubject(
            command=(executable, "-c", nested_payload),
            cwd=None,
            direct_tokens=(),
            shell_payload=nested_payload,
            normalization_complete=True,
        )
        for effect in detect_policy_effects(nested_subject):
            _append_effect(effects, effect)


def _detect_git_effects(
    arguments: tuple[str, ...],
    effects: list[DetectedPolicyEffect],
) -> None:
    operation, operation_arguments = _git_operation(arguments)
    if operation == "push":
        _append_publication(effects, "Commits or refs would be published")
    if operation == "reset" and "--hard" in operation_arguments:
        _append_effect(
            effects,
            DetectedPolicyEffect(
                "destructive",
                "repository_history_rewrite",
                "Local repository or working-tree changes could be discarded",
            ),
        )
    if operation == "clean" and any(
        value == "--force" or (value.startswith("-") and "f" in value[1:])
        for value in operation_arguments
    ) and not any(
        value == "--dry-run" or (value.startswith("-") and "n" in value[1:])
        for value in operation_arguments
    ):
        _append_effect(
            effects,
            DetectedPolicyEffect(
                "destructive",
                "repository_clean",
                "Untracked repository content would be deleted",
            ),
        )
    if (
        operation == "branch"
        and (
            "-D" in operation_arguments
            or _has_short_or_long_flag(operation_arguments, "f", "--force")
        )
    ) or (
        operation == "tag" and any(value in {"-d", "--delete"} for value in operation_arguments)
    ) or (
        operation == "stash" and _first_operand(operation_arguments) in {"clear", "drop"}
    ) or (
        operation == "worktree"
        and _first_operand(operation_arguments) == "remove"
        and _has_short_or_long_flag(operation_arguments, "f", "--force")
    ):
        _append_effect(
            effects,
            DetectedPolicyEffect(
                "destructive",
                "repository_deletion",
                "Repository state would be deleted",
            ),
        )


def _has_short_or_long_flag(
    arguments: tuple[str, ...],
    short: str,
    long: str,
) -> bool:
    return any(
        value == long
        or (
            value.startswith("-")
            and not value.startswith("--")
            and short in value[1:]
        )
        for value in arguments
    )


def _detect_github_effects(
    arguments: tuple[str, ...],
    effects: list[DetectedPolicyEffect],
) -> None:
    group, remainder = _github_operation(arguments)
    operation = _first_operand(remainder)
    read_operations = {
        "auth": {"status"},
        "issue": {"list", "status", "view"},
        "pr": {"checks", "diff", "list", "status", "view"},
        "release": {"download", "list", "view"},
        "repo": {"clone", "list", "view"},
        "run": {"download", "list", "view", "watch"},
    }
    if group == "api":
        if _http_arguments_mutate(remainder, short_field_mutates=True):
            _append_effect(
                effects,
                DetectedPolicyEffect(
                    "external_effect",
                    "external_api_mutation",
                    "A remote API would be changed",
                ),
            )
        return
    if group == "auth" and operation in {"login", "logout", "refresh", "token"}:
        _append_effect(
            effects,
            DetectedPolicyEffect(
                "secret_access",
                "credential_mutation",
                "Authentication credentials would be accessed or changed",
            ),
        )
        return
    if group in read_operations and operation in read_operations[group]:
        return
    if group in read_operations and operation is not None:
        _append_effect(
            effects,
            DetectedPolicyEffect(
                "external_effect",
                "external_service_mutation",
                "A GitHub resource would be changed",
            ),
        )


def _detect_http_effects(
    executable: str,
    arguments: tuple[str, ...],
    effects: list[DetectedPolicyEffect],
) -> None:
    if _http_arguments_mutate(arguments) or (
        executable == "wget"
        and any(
            value.startswith(("--post-data", "--post-file", "--method"))
            for value in arguments
        )
    ):
        _append_effect(
            effects,
            DetectedPolicyEffect(
                "external_effect",
                "external_api_mutation",
                "A remote HTTP resource would be changed or uploaded",
            ),
        )
    if any(
        marker in value.lower()
        for value in arguments
        for marker in (
            "authorization:",
            "cookie:",
            "x-api-key:",
            "--oauth2-bearer",
            "--user",
        )
    ):
        _append_effect(
            effects,
            DetectedPolicyEffect(
                "secret_access",
                "credential_transmission",
                "Credentials would be transmitted to a remote service",
            ),
        )


def _http_arguments_mutate(
    arguments: tuple[str, ...],
    *,
    short_field_mutates: bool = False,
) -> bool:
    mutation_flags = (
        "--data",
        "--data-ascii",
        "--data-binary",
        "--data-raw",
        "--form",
        "--json",
        "--raw-field",
        "--field",
        "--input",
        "--upload-file",
    )
    for index, value in enumerate(arguments):
        if value in {"-d", "-F", "-T"} or (
            short_field_mutates and value == "-f"
        ) or value.startswith(
            tuple(f"{flag}=" for flag in mutation_flags)
        ) or value in mutation_flags:
            return True
        if (
            value in {"-X", "--request", "--method"}
            and index + 1 < len(arguments)
            and arguments[index + 1].upper() not in {"GET", "HEAD", "OPTIONS"}
        ):
            return True
        for prefix in ("--request=", "--method="):
            if value.startswith(prefix) and value.removeprefix(prefix).upper() not in {
                "GET",
                "HEAD",
                "OPTIONS",
            }:
                return True
    return False


def _detect_incomplete_command_effects(
    command: CommandPolicySubject,
    effects: list[DetectedPolicyEffect],
) -> None:
    _detect_incomplete_text_effects("\n".join(command.command), effects)


def _detect_incomplete_text_effects(
    value: str,
    effects: list[DetectedPolicyEffect],
) -> None:
    lowered = value.lower()
    fragments = (
        ("rm -", "destructive", "filesystem_deletion", "Filesystem content would be deleted"),
        (
            "git reset --hard",
            "destructive",
            "repository_history_rewrite",
            "Local repository or working-tree changes could be discarded",
        ),
        ("git push", "publication", "external_publication", "Commits or refs would be published"),
        (
            "sudo",
            "privilege",
            "privilege_escalation",
            "Privilege or system authority would be changed",
        ),
    )
    for fragment, kind, code, summary in fragments:
        if fragment in lowered:
            _append_effect(
                effects,
                DetectedPolicyEffect(kind, code, summary),  # type: ignore[arg-type]
            )


def _command_subject(subject: PolicySubject) -> CommandPolicySubject | None:
    if isinstance(subject, CommandPolicySubject):
        return subject
    if isinstance(subject, ToolPolicySubject):
        return subject.command
    return None


def _command_invocations(
    command: CommandPolicySubject,
) -> tuple[tuple[_Invocation, ...], bool]:
    if command.shell_payload is None:
        invocation = _invocation(command.direct_tokens)
        return ((invocation,) if invocation is not None else ()), False
    try:
        lexer = shlex.shlex(
            command.shell_payload,
            posix=True,
            punctuation_chars=";&|()\n",
        )
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        tokens = tuple(lexer)
    except ValueError:
        return (), "|" in command.shell_payload
    groups: list[tuple[str, ...]] = []
    current: list[str] = []
    has_pipeline = False
    for token in tokens:
        if token in _CONTROL_TOKENS:
            if current:
                groups.append(tuple(current))
                current.clear()
            has_pipeline = has_pipeline or "|" in token
            continue
        current.append(token)
    if current:
        groups.append(tuple(current))
    return (
        tuple(
            invocation
            for group in groups
            if (invocation := _invocation(group)) is not None
        ),
        has_pipeline,
    )


def _invocation(tokens: tuple[str, ...]) -> _Invocation | None:
    values = list(tokens)
    while values and values[0] in {"!", "do", "if", "then", "until", "while"}:
        values.pop(0)
    while values and _ASSIGNMENT.fullmatch(values[0]):
        values.pop(0)
    while values and os.path.basename(values[0]) in {"builtin", "command", "exec", "nohup"}:
        values.pop(0)
        while values and values[0].startswith("-"):
            values.pop(0)
    if values and os.path.basename(values[0]) == "env":
        values.pop(0)
        while values:
            value = values[0]
            if _ASSIGNMENT.fullmatch(value):
                values.pop(0)
                continue
            if value == "--":
                values.pop(0)
                break
            if value in {"-u", "--unset", "-C", "--chdir"} and len(values) > 1:
                del values[:2]
                continue
            if value.startswith("-"):
                values.pop(0)
                continue
            break
    if not values:
        return None
    return _Invocation(os.path.basename(values[0]), tuple(values[1:]))


def _has_privilege_wrapper(command: CommandPolicySubject) -> bool:
    for index, value in enumerate(command.command[:6]):
        name = os.path.basename(value)
        if name in _PRIVILEGED_EXECUTABLES:
            return True
        if index == 0 and name == "env":
            continue
        if value.startswith("-") or _ASSIGNMENT.fullmatch(value):
            continue
        if index > 0:
            return False
    return False


def _nested_shell_payloads(invocation: _Invocation) -> tuple[str, ...]:
    if invocation.executable not in _SHELL_EXECUTABLES:
        return ()
    arguments = invocation.arguments
    for index, value in enumerate(arguments):
        if value == "--":
            continue
        if value.startswith("-") and "c" in value[1:] and index + 1 < len(arguments):
            return (arguments[index + 1],)
    return ()


def _operation(arguments: tuple[str, ...]) -> tuple[str | None, tuple[str, ...]]:
    for index, value in enumerate(arguments):
        if value == "--":
            if index + 1 < len(arguments):
                return arguments[index + 1], arguments[index + 2 :]
            return None, ()
        if value.startswith("-"):
            continue
        return value, arguments[index + 1 :]
    return None, ()


def _git_operation(arguments: tuple[str, ...]) -> tuple[str | None, tuple[str, ...]]:
    values = list(arguments)
    value_options = {"-C", "-c", "--exec-path", "--git-dir", "--namespace", "--work-tree"}
    while values:
        value = values.pop(0)
        option = value.partition("=")[0]
        if option in value_options:
            if "=" not in value and values:
                values.pop(0)
            continue
        if value.startswith("-"):
            continue
        return value, tuple(values)
    return None, ()


def _github_operation(arguments: tuple[str, ...]) -> tuple[str | None, tuple[str, ...]]:
    values = list(arguments)
    value_options = {"-R", "--hostname", "--repo"}
    while values:
        value = values.pop(0)
        option = value.partition("=")[0]
        if option in value_options:
            if "=" not in value and values:
                values.pop(0)
            continue
        if value.startswith("-"):
            continue
        return value, tuple(values)
    return None, ()


def _first_operand(arguments: tuple[str, ...]) -> str | None:
    return _operation(arguments)[0]


def _looks_like_secret_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    parts = tuple(part.lower() for part in PurePath(normalized).parts)
    name = parts[-1] if parts else normalized.lower()
    if name in {".env.example", ".env.sample", ".env.template"}:
        return False
    return (
        name in _SECRET_FILE_NAMES
        or (name.startswith(".env.") and not name.endswith((".example", ".sample", ".template")))
        or any(part in _SECRET_PATH_COMPONENTS for part in parts)
    )


def _append_publication(
    effects: list[DetectedPolicyEffect],
    summary: str,
) -> None:
    _append_effect(
        effects,
        DetectedPolicyEffect(
            "publication",
            "external_publication",
            summary,
        ),
    )


def _append_effect(
    effects: list[DetectedPolicyEffect],
    effect: DetectedPolicyEffect,
) -> None:
    if effect not in effects:
        effects.append(effect)


__all__ = [
    "DetectedPolicyEffect",
    "PolicyEffectKind",
    "detect_policy_effects",
]
