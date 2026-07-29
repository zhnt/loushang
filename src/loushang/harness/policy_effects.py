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
from loushang.harness.policy import (
    CommandPolicySubject,
    PolicySubject,
    ToolPolicySubject,
)

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
