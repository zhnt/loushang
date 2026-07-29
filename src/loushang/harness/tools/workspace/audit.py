from __future__ import annotations

import re
import shlex
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from loushang.harness.authorization import EffectiveExecutionProfile
from loushang.harness.effects import effect_audit_summary, effect_capability
from loushang.harness.policy import CommandPolicySubject, ToolPolicySubject

_SAFE_NAME = re.compile(r"[A-Za-z0-9_.+-]{1,64}")
_SAFE_LONG_FLAG = re.compile(r"--[A-Za-z0-9][A-Za-z0-9-]{0,63}")
_SAFE_SHORT_FLAG = re.compile(r"-[A-Za-z]")
_KNOWN_OPERATIONS: dict[str, frozenset[str]] = {
    "git": frozenset(
        {
            "add",
            "branch",
            "checkout",
            "cherry-pick",
            "clone",
            "commit",
            "diff",
            "fetch",
            "log",
            "merge",
            "pull",
            "push",
            "rebase",
            "reset",
            "restore",
            "show",
            "status",
            "switch",
            "tag",
            "worktree",
        }
    ),
    "gh": frozenset({"api", "auth", "issue", "pr", "release", "repo", "run"}),
    "npm": frozenset({"install", "publish", "run", "test", "view"}),
    "uv": frozenset({"add", "lock", "pip", "run", "sync"}),
}
_KNOWN_EXECUTABLES = frozenset(
    {
        "bash",
        "cargo",
        "cat",
        "curl",
        "docker",
        "echo",
        "gh",
        "git",
        "go",
        "grep",
        "ls",
        "make",
        "node",
        "npm",
        "npx",
        "python",
        "python3",
        "rg",
        "rm",
        "ruff",
        "sed",
        "sh",
        "sudo",
        "uv",
        "wget",
    }
)
_CAPABILITY_RANK = {
    "process.execute": 0,
    "filesystem.read": 5,
    "filesystem.write": 15,
    "git.read": 10,
    "git.write": 20,
    "network.request": 30,
    "network.mutate": 45,
    "github.request": 40,
    "git.remote_write": 50,
    "repository.publish": 55,
    "filesystem.delete": 60,
    "privilege.escalate": 70,
}


def build_action_audit_details(
    *,
    tool_name: str,
    arguments: Mapping[str, object],
    cwd: str | None,
    policy_subject: ToolPolicySubject | None,
) -> dict[str, object]:
    capability, command = _classify_capability(tool_name, policy_subject)
    details: dict[str, object] = {
        "capability": capability,
        "action_summary": {
            "argument_count": len(arguments),
            "has_environment": "env" in arguments,
            "has_stdin": arguments.get("stdin") is not None,
            "resource": _resource_summary(arguments, cwd=cwd),
        },
    }
    if command is not None:
        details["command_summary"] = command
    if policy_subject is not None and policy_subject.effects:
        details["declared_effects"] = tuple(
            effect_audit_summary(effect) for effect in policy_subject.effects
        )
    return details


def execution_profile_audit_summary(
    profile: EffectiveExecutionProfile | None,
) -> dict[str, object]:
    if profile is None:
        return {"configured": False}
    return {
        "configured": True,
        "readable_root_count": len(profile.readable_roots),
        "writable_root_count": len(profile.writable_roots),
        "denied_root_count": len(profile.denied_roots),
        "network": profile.network,
    }


def execution_failure_outcome(error: BaseException) -> str:
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, PermissionError):
        return "denied"
    if type(error).__name__ == "CancelledError":
        return "cancelled"
    return "error"


def snapshot_audit_event(event: Mapping[str, object]) -> dict[str, object]:
    """Detach one strict-JSON audit event before handing it to an observer."""

    return {
        str(key): _snapshot_json_value(value, path=str(key))
        for key, value in event.items()
    }


def _classify_capability(
    tool_name: str,
    subject: ToolPolicySubject | None,
) -> tuple[str, dict[str, object] | None]:
    declared = (
        [effect_capability(effect) for effect in subject.effects]
        if subject is not None
        else []
    )
    if tool_name == "read":
        return _highest_capability([*declared, "filesystem.read"]), None
    if tool_name in {"write", "edit"}:
        return _highest_capability([*declared, "filesystem.write"]), None
    if tool_name != "bash":
        return (
            _highest_capability(declared)
            if declared
            else f"tool.{_safe_name(tool_name)}"
        ), None

    command = subject.command if subject is not None else None
    summary = _command_summary(command)
    capabilities = declared + [
        _signature_capability(executable, operation)
        for executable, operation in _command_signatures(command)
    ]
    if summary.get("privilege_wrapper") is True:
        capabilities.append("privilege.escalate")
    capability = _highest_capability(capabilities or ["process.execute"])
    return capability, summary


def _highest_capability(capabilities: list[str]) -> str:
    return max(capabilities, key=lambda value: _CAPABILITY_RANK.get(value, 0))


def _command_summary(command: CommandPolicySubject | None) -> dict[str, object]:
    if command is None:
        return {"form": "unknown", "executable": "unknown", "argument_count": 0}
    tokens = (
        _safe_shell_tokens(command.shell_payload)
        if command.shell_payload is not None
        else command.direct_tokens
    )
    executable_index = _executable_index(tokens)
    executable = (
        _safe_executable(tokens[executable_index])
        if executable_index is not None
        else "unknown"
    )
    operation = _safe_operation(executable, tokens, executable_index)
    summary: dict[str, object] = {
        "form": "shell" if command.shell_payload is not None else "argv",
        "executable": executable,
        "argument_count": max(
            0,
            len(tokens) - (executable_index + 1 if executable_index is not None else 0),
        ),
        "flags": _safe_flags(tokens),
        "normalization_complete": command.normalization_complete,
    }
    if _has_privilege_wrapper(command):
        summary["privilege_wrapper"] = True
    if operation is not None:
        summary["operation"] = operation
    signatures = _command_signatures(command)
    summary["command_count"] = len(signatures)
    summary["executables"] = tuple(
        dict.fromkeys(executable for executable, _operation in signatures)
    )
    return summary


def _has_privilege_wrapper(command: CommandPolicySubject) -> bool:
    for token in command.command:
        name = Path(token).name
        if name == "sudo":
            return True
        if name == "env" or (
            "=" in token and not token.startswith(("-", "/"))
        ):
            continue
        return False
    return False


def _command_signatures(
    command: CommandPolicySubject | None,
) -> tuple[tuple[str, str | None], ...]:
    if command is None:
        return ()
    token_groups = (
        _shell_token_groups(command.shell_payload)
        if command.shell_payload is not None
        else (command.direct_tokens,)
    )
    signatures: list[tuple[str, str | None]] = []
    for tokens in token_groups:
        executable_index = _executable_index(tokens)
        if executable_index is None:
            continue
        executable = _safe_executable(tokens[executable_index])
        signatures.append(
            (
                executable,
                _safe_operation(executable, tokens, executable_index),
            )
        )
    return tuple(signatures)


def _shell_token_groups(payload: str | None) -> tuple[tuple[str, ...], ...]:
    if not payload:
        return ()
    groups: list[tuple[str, ...]] = []
    for segment in re.split(r"(?:\r?\n|&&|\|\||[;|&])", payload):
        tokens = _safe_shell_tokens(segment)
        if tokens:
            groups.append(tokens)
    return tuple(groups)


def _signature_capability(executable: str, operation: str | None) -> str:
    if executable == "sudo":
        return "privilege.escalate"
    if executable == "rm":
        return "filesystem.delete"
    if executable in {"curl", "wget"}:
        return "network.request"
    if executable == "git" and operation == "push":
        return "git.remote_write"
    if executable == "git" and operation in {
        "diff",
        "fetch",
        "log",
        "show",
        "status",
    }:
        return "git.read"
    if executable == "git":
        return "git.write"
    if executable == "gh" and operation in {"api", "issue", "pr", "release"}:
        return "github.request"
    return "process.execute"


def _safe_shell_tokens(payload: str | None) -> tuple[str, ...]:
    if not payload:
        return ()
    try:
        return tuple(shlex.split(payload, posix=True))
    except ValueError:
        return ()


def _executable_index(tokens: Sequence[str]) -> int | None:
    for index, token in enumerate(tokens):
        if "=" in token and not token.startswith(("-", "/")):
            name, _, _value = token.partition("=")
            if _SAFE_NAME.fullmatch(name):
                continue
        return index
    return None


def _safe_executable(value: str) -> str:
    name = Path(value).name
    return name if name in _KNOWN_EXECUTABLES else "other"


def _safe_operation(
    executable: object,
    tokens: Sequence[str],
    executable_index: int | None,
) -> str | None:
    if not isinstance(executable, str) or executable_index is None:
        return None
    allowed = _KNOWN_OPERATIONS.get(executable)
    if allowed is None:
        return None
    for token in tokens[executable_index + 1 :]:
        if token.startswith("-"):
            continue
        return token if token in allowed else "other"
    return None


def _safe_flags(tokens: Sequence[str]) -> tuple[str, ...]:
    flags: list[str] = []
    for token in tokens:
        candidate = token.partition("=")[0]
        if not (
            _SAFE_LONG_FLAG.fullmatch(candidate)
            or _SAFE_SHORT_FLAG.fullmatch(candidate)
        ):
            continue
        if candidate not in flags:
            flags.append(candidate)
        if len(flags) == 12:
            break
    return tuple(flags)


def _resource_summary(
    arguments: Mapping[str, object],
    *,
    cwd: str | None,
) -> dict[str, object]:
    value = arguments.get("path", arguments.get("file_path"))
    if not isinstance(value, str):
        return {"kind": "none"}
    try:
        path = Path(value).expanduser().resolve(strict=False)
        base = Path(cwd).expanduser().resolve(strict=False) if cwd else None
        scope = (
            "workspace"
            if base is not None and (path == base or path.is_relative_to(base))
            else "external"
        )
    except (OSError, RuntimeError, ValueError):
        scope = "unknown"
    return {"kind": "file", "scope": scope}


def _safe_name(value: str) -> str:
    return value if _SAFE_NAME.fullmatch(value) else "other"


def _snapshot_json_value(value: Any, *, path: str) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _snapshot_json_value(item, path=f"{path}.{key}")
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _snapshot_json_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    raise TypeError(
        f"audit event value at {path} must be strict JSON, got "
        f"{type(value).__name__}"
    )


__all__ = [
    "build_action_audit_details",
    "execution_failure_outcome",
    "execution_profile_audit_summary",
    "snapshot_audit_event",
]
