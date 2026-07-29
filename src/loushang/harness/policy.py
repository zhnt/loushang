from __future__ import annotations

import inspect
import os
import shlex
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from os.path import abspath, basename, isabs, join, normpath, realpath, samefile
from pathlib import Path
from shutil import which
from types import MappingProxyType
from typing import Literal, Protocol, TypeAlias, TypeVar, cast

from loushang.harness.effects import ToolEffect

PolicyDisposition = Literal["allow", "deny", "ask"]
PolicyChainStrategy = Literal[
    "first_non_allow",
    "most_restrictive",
    "first_decision",
]

T = TypeVar("T")
MaybeAwaitable: TypeAlias = T | Awaitable[T]

_SHELL_ENTRY_BASENAMES = frozenset(
    {
        "sh",
        "ash",
        "bash",
        "dash",
        "fish",
        "hush",
        "ksh",
        "msh",
        "rbash",
        "rzsh",
        "rksh",
        "zsh",
    }
)
_GENERIC_SHELL_ENTRY_BASENAMES = _SHELL_ENTRY_BASENAMES - {"fish"}
_STANDARD_EXECUTABLE_DIRECTORIES = ("/bin", "/usr/bin", "/usr/local/bin")
_MULTICALL_ENTRY_BASENAMES = frozenset({"busybox", "busybox.static", "toybox"})
_MULTICALL_CONTROL_APPLETS = _SHELL_ENTRY_BASENAMES | {"env"}
_STDIN_SCRIPT_PSEUDO_PATHS = frozenset(
    {
        "/dev/stdin",
        "/dev/fd/0",
        "/proc/self/fd/0",
        "/proc/thread-self/fd/0",
    }
)
_SHELL_VALUE_OPTIONS = frozenset(
    {
        "-O",
        "+O",
        "-o",
        "+o",
        "--init-file",
        "--rcfile",
    }
)
_SHELL_STARTUP_FILE_OPTIONS = frozenset({"--init-file", "--rcfile"})
_SHELL_STARTUP_ENVIRONMENT_NAMES = frozenset({"BASH_ENV", "ENV"})
_SHELL_SHORT_OPTIONS = frozenset("abefhkmnptuvxBCEHPTilrsDc")
_LEADING_WRAPPER_BASENAMES = frozenset({"env", "sudo"})
_ENV_NO_VALUE_OPTIONS = frozenset(
    {
        "-i",
        "--ignore-environment",
        "-0",
        "--null",
        "-v",
        "--debug",
        "--block-signal",
        "--default-signal",
        "--ignore-signal",
    }
)
_ENV_VALUE_OPTIONS = frozenset(
    {
        "-u",
        "--unset",
        "-C",
        "--chdir",
        "-S",
        "--split-string",
        "-a",
        "--argv0",
        "-f",
        "--file",
    }
)
_ENV_SHORT_VALUE_OPTIONS = frozenset(
    option[1]
    for option in _ENV_VALUE_OPTIONS
    if option.startswith("-") and not option.startswith("--") and len(option) == 2
)
_ENV_SHORT_NO_VALUE_OPTIONS = frozenset(
    option[1]
    for option in _ENV_NO_VALUE_OPTIONS
    if option.startswith("-") and not option.startswith("--") and len(option) == 2
)
_ENV_LONG_NO_VALUE_OPTIONS = frozenset(
    option for option in _ENV_NO_VALUE_OPTIONS if option.startswith("--")
)
_ENV_LONG_VALUE_OPTIONS = frozenset(
    option for option in _ENV_VALUE_OPTIONS if option.startswith("--")
)
_ENV_LONG_OPTIONS = _ENV_LONG_NO_VALUE_OPTIONS | _ENV_LONG_VALUE_OPTIONS
_SUDO_VALUE_OPTIONS = frozenset(
    {
        "-a",
        "--auth-type",
        "-c",
        "--login-class",
        "-u",
        "--user",
        "-g",
        "--group",
        "-h",
        "--host",
        "-p",
        "--prompt",
        "-r",
        "--role",
        "-t",
        "--type",
        "-C",
        "--close-from",
        "-D",
        "--chdir",
        "-R",
        "--chroot",
        "-T",
        "--command-timeout",
    }
)
_SUDO_SHORT_VALUE_OPTIONS = frozenset(
    option[1]
    for option in _SUDO_VALUE_OPTIONS
    if option.startswith("-") and not option.startswith("--") and len(option) == 2
)
_SUDO_SHORT_NO_VALUE_OPTIONS = frozenset(
    {
        "A",
        "b",
        "B",
        "E",
        "e",
        "H",
        "i",
        "K",
        "k",
        "l",
        "n",
        "P",
        "S",
        "s",
        "V",
        "v",
    }
)
_SUDO_SHELL_MODE_LONG_OPTIONS = frozenset({"--login", "--shell"})
_SUDO_NO_VALUE_LONG_OPTIONS = frozenset(
    {
        "--askpass",
        "--background",
        "--bell",
        "--edit",
        "--help",
        "--list",
        "--non-interactive",
        "--preserve-env",
        "--remove-timestamp",
        "--reset-timestamp",
        "--stdin",
        "--validate",
        "--version",
        *_SUDO_SHELL_MODE_LONG_OPTIONS,
    }
)
_SUDO_LONG_VALUE_OPTIONS = frozenset(
    option for option in _SUDO_VALUE_OPTIONS if option.startswith("--")
)
_SUDO_LONG_OPTIONS = _SUDO_NO_VALUE_LONG_OPTIONS | _SUDO_LONG_VALUE_OPTIONS


@dataclass(frozen=True)
class PolicyDecision:
    """Product-neutral result from an injected policy evaluator."""

    disposition: PolicyDisposition
    reason: str | None = None
    code: str | None = None

    def __post_init__(self) -> None:
        if self.disposition not in {"allow", "deny", "ask"}:
            raise ValueError(f"Unsupported policy disposition: {self.disposition}")
        if self.reason is not None and not isinstance(self.reason, str):
            raise TypeError("PolicyDecision reason must be a string or None")
        if self.code is not None and not isinstance(self.code, str):
            raise TypeError("PolicyDecision code must be a string or None")

    @classmethod
    def allow(cls) -> PolicyDecision:
        return cls(disposition="allow")

    @classmethod
    def deny(cls, reason: str, *, code: str | None = None) -> PolicyDecision:
        return cls(disposition="deny", reason=reason, code=code)

    @classmethod
    def ask(cls, reason: str, *, code: str | None = None) -> PolicyDecision:
        return cls(disposition="ask", reason=reason, code=code)


@dataclass(frozen=True)
class CommandPolicySubject:
    command: tuple[str, ...]
    cwd: str | None
    direct_tokens: tuple[str, ...]
    shell_payload: str | None = None
    normalization_complete: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "command", _string_tuple(self.command, "command"))
        object.__setattr__(
            self,
            "direct_tokens",
            _string_tuple(self.direct_tokens, "direct_tokens"),
        )
        if not isinstance(self.normalization_complete, bool):
            raise TypeError("normalization_complete must be a boolean")


@dataclass(frozen=True)
class PathPolicySubject:
    raw_path: str
    resolved_path: str | None = None


@dataclass(frozen=True)
class ToolPolicySubject:
    tool_name: str
    arguments: Mapping[str, object]
    cwd: str | None = None
    command: CommandPolicySubject | None = None
    paths: tuple[PathPolicySubject, ...] = ()
    effects: tuple[ToolEffect, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.tool_name, str) or not self.tool_name:
            raise ValueError("tool_name must be a non-empty string")
        object.__setattr__(self, "arguments", _freeze_mapping(self.arguments))
        object.__setattr__(self, "paths", tuple(self.paths))
        object.__setattr__(self, "effects", tuple(self.effects))


@dataclass(frozen=True)
class CustomPolicySubject:
    kind: str
    value: object | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not self.kind:
            raise ValueError("kind must be a non-empty string")


PolicySubject: TypeAlias = (
    CommandPolicySubject | PathPolicySubject | ToolPolicySubject | CustomPolicySubject
)


class PolicyEvaluationError(RuntimeError):
    """Raised when an injected policy evaluator violates its contract."""


class PolicyEvaluator(Protocol):
    def evaluate(
        self,
        subject: PolicySubject,
        /,
    ) -> MaybeAwaitable[PolicyDecision | None]: ...


class PolicyMatcher(Protocol):
    def matches(self, subject: PolicySubject, /) -> bool: ...


@dataclass(frozen=True)
class PolicyRule:
    id: str
    matcher: PolicyMatcher
    decision: PolicyDecision

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("PolicyRule id must be a non-empty string")
        if not isinstance(self.decision, PolicyDecision):
            raise TypeError("PolicyRule decision must be a PolicyDecision")


@dataclass(frozen=True)
class RulePolicyEvaluator:
    rules: tuple[PolicyRule, ...]

    def __post_init__(self) -> None:
        normalized = tuple(self.rules)
        ids = [rule.id for rule in normalized]
        if len(ids) != len(set(ids)):
            raise ValueError("PolicyRule ids must be unique within an evaluator")
        object.__setattr__(self, "rules", normalized)

    def evaluate(self, subject: PolicySubject, /) -> PolicyDecision | None:
        for rule in self.rules:
            matched = rule.matcher.matches(subject)
            if not isinstance(matched, bool):
                raise TypeError(
                    f"Policy matcher for rule {rule.id!r} returned "
                    f"{type(matched).__name__}, expected bool"
                )
            if matched:
                return rule.decision
        return None


@dataclass(frozen=True)
class PolicyEvaluatorChain:
    evaluators: tuple[PolicyEvaluator, ...]
    strategy: PolicyChainStrategy = "most_restrictive"

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluators", tuple(self.evaluators))
        if self.strategy not in {
            "first_non_allow",
            "most_restrictive",
            "first_decision",
        }:
            raise ValueError(f"Unsupported policy chain strategy: {self.strategy}")

    async def evaluate(self, subject: PolicySubject, /) -> PolicyDecision | None:
        if self.strategy == "first_decision":
            for evaluator in self.evaluators:
                decision = await evaluate_policy(evaluator, subject)
                if decision is not None:
                    return decision
            return None

        first_allow: PolicyDecision | None = None
        first_ask: PolicyDecision | None = None
        first_deny: PolicyDecision | None = None
        for evaluator in self.evaluators:
            decision = await evaluate_policy(evaluator, subject)
            if decision is None:
                continue
            if self.strategy == "first_non_allow":
                if decision.disposition != "allow":
                    return decision
                if first_allow is None:
                    first_allow = decision
                continue
            if decision.disposition == "deny" and first_deny is None:
                first_deny = decision
            elif decision.disposition == "ask" and first_ask is None:
                first_ask = decision
            elif decision.disposition == "allow" and first_allow is None:
                first_allow = decision

        if self.strategy == "first_non_allow":
            return first_allow
        return first_deny or first_ask or first_allow


async def evaluate_policy(
    evaluator: PolicyEvaluator,
    subject: PolicySubject,
) -> PolicyDecision | None:
    try:
        evaluate = getattr(evaluator, "evaluate", None)
        if not callable(evaluate):
            raise PolicyEvaluationError(
                f"Policy evaluator {type(evaluator).__name__} has no callable evaluate method"
            )
        result = evaluate(subject)
        if inspect.isawaitable(result):
            result = await result
    except PolicyEvaluationError:
        raise
    except Exception as exc:
        raise PolicyEvaluationError(
            f"Policy evaluator {type(evaluator).__name__} failed: {exc}"
        ) from exc
    if result is not None and not isinstance(result, PolicyDecision):
        raise PolicyEvaluationError(
            f"Policy evaluator {type(evaluator).__name__} returned "
            f"{type(result).__name__}, expected PolicyDecision or None"
        )
    if result is not None:
        try:
            result.__post_init__()
        except (TypeError, ValueError) as exc:
            raise PolicyEvaluationError(
                f"Policy evaluator {type(evaluator).__name__} returned an invalid "
                f"PolicyDecision: {exc}"
            ) from exc
    return result


@dataclass(frozen=True)
class ExactToolNameMatcher:
    tool_name: str

    def matches(self, subject: PolicySubject, /) -> bool:
        return (
            isinstance(subject, ToolPolicySubject)
            and subject.tool_name == self.tool_name
        )


@dataclass(frozen=True)
class CommandTokenSequenceMatcher:
    tokens: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "tokens", _string_tuple(self.tokens, "tokens"))

    def matches(self, subject: PolicySubject, /) -> bool:
        command = _command_subject(subject)
        if command is None or command.shell_payload is not None or not self.tokens:
            return False
        return _contains_token_sequence(command.direct_tokens, self.tokens)


@dataclass(frozen=True)
class ShellPayloadSubstringMatcher:
    substring: str

    def matches(self, subject: PolicySubject, /) -> bool:
        command = _command_subject(subject)
        return (
            command is not None
            and command.shell_payload is not None
            and self.substring in command.shell_payload
        )


@dataclass(frozen=True)
class CommandSubstringMatcher:
    """Match shell payload text or direct argv token sequences."""

    substring: str

    def matches(self, subject: PolicySubject, /) -> bool:
        command = _command_subject(subject)
        if command is None:
            return False
        if not command.normalization_complete and self.substring in " ".join(
            command.command
        ):
            return True
        if command.shell_payload is not None:
            return self.substring in command.shell_payload
        tokens = tuple(part for part in self.substring.split() if part)
        return bool(tokens) and _contains_token_sequence(command.direct_tokens, tokens)


@dataclass(frozen=True)
class IncompleteCommandMatcher:
    """Match commands whose platform-specific wrapper syntax is unresolved."""

    def matches(self, subject: PolicySubject, /) -> bool:
        command = _command_subject(subject)
        return command is not None and not command.normalization_complete


@dataclass(frozen=True)
class PathSubstringMatcher:
    substring: str

    def matches(self, subject: PolicySubject, /) -> bool:
        paths = (
            subject.paths
            if isinstance(subject, ToolPolicySubject)
            else (subject,)
            if isinstance(subject, PathPolicySubject)
            else ()
        )
        return any(
            self.substring in candidate
            for path in paths
            for candidate in (path.raw_path, path.resolved_path)
            if candidate is not None
        )


def normalize_command_subject(
    command: Sequence[str],
    *,
    cwd: str | None = None,
    assume_shell: bool = False,
    stdin: str | None = None,
    executable_search_path: str | None = None,
    environment_overrides: object | None = None,
    environment_is_complete: bool = False,
) -> CommandPolicySubject:
    normalized = _string_tuple(command, "command")
    unwrapped, normalization_complete = _unwrap_leading_wrappers(
        normalized,
        cwd=cwd,
        executable_search_path=executable_search_path,
    )
    payload, shell_complete = _shell_payload(
        unwrapped,
        assume_shell=assume_shell,
        cwd=cwd,
        stdin=stdin,
        executable_search_path=executable_search_path,
        environment_overrides=environment_overrides,
        environment_is_complete=environment_is_complete,
    )
    normalization_complete = normalization_complete and shell_complete
    direct_tokens = () if payload is not None else _direct_command_tokens(unwrapped)
    return CommandPolicySubject(
        command=normalized,
        cwd=cwd,
        direct_tokens=direct_tokens,
        shell_payload=payload,
        normalization_complete=normalization_complete,
    )


def executable_search_path_from_env(
    env: object,
    *,
    default: str | None = None,
) -> str | None:
    return environment_value_from_env(env, "PATH", default=default)


def environment_value_from_env(
    env: object,
    name: str,
    *,
    default: str | None = None,
) -> str | None:
    if isinstance(env, Mapping):
        value = env.get(name)
        return value if isinstance(value, str) else default
    if isinstance(env, str) or not isinstance(env, Sequence):
        return default
    for pair in reversed(tuple(env)):
        if isinstance(pair, str) or not isinstance(pair, Sequence):
            continue
        values = tuple(pair)
        if len(values) == 2 and values[0] == name and isinstance(values[1], str):
            return values[1]
    return default


def build_path_policy_subjects(
    arguments: Mapping[str, object],
    *,
    cwd: str | None = None,
) -> tuple[PathPolicySubject, ...]:
    raw_path = arguments.get("path", arguments.get("file_path"))
    if not isinstance(raw_path, str) or not raw_path:
        return ()
    resolved_path: str | None = None
    try:
        path = Path(raw_path).expanduser()
        if not path.is_absolute() and cwd:
            path = Path(cwd) / path
        resolved_path = str(path.resolve())
    except (OSError, RuntimeError, ValueError):
        pass
    return (PathPolicySubject(raw_path=raw_path, resolved_path=resolved_path),)


def build_tool_policy_subject(
    *,
    tool_name: str,
    arguments: Mapping[str, object],
    cwd: str | None = None,
    command: CommandPolicySubject | None = None,
    paths: tuple[PathPolicySubject, ...] | None = None,
    effects: tuple[ToolEffect, ...] = (),
) -> ToolPolicySubject:
    return ToolPolicySubject(
        tool_name=tool_name,
        arguments=arguments,
        cwd=cwd,
        command=command,
        paths=build_path_policy_subjects(arguments, cwd=cwd)
        if paths is None
        else paths,
        effects=effects,
    )


def _command_subject(subject: PolicySubject) -> CommandPolicySubject | None:
    if isinstance(subject, CommandPolicySubject):
        return subject
    if isinstance(subject, ToolPolicySubject):
        return subject.command
    return None


def _contains_token_sequence(
    values: tuple[str, ...],
    expected: tuple[str, ...],
) -> bool:
    if len(expected) == 1:
        return expected[0] in values
    window_size = len(expected)
    return any(
        values[index : index + window_size] == expected
        for index in range(len(values) - window_size + 1)
    )


def _shell_payload(
    command: tuple[str, ...],
    *,
    assume_shell: bool = False,
    cwd: str | None = None,
    stdin: str | None = None,
    executable_search_path: str | None = None,
    environment_overrides: object | None = None,
    environment_is_complete: bool = False,
) -> tuple[str | None, bool]:
    if not command:
        return None, True
    shell_family, executable_complete = _classify_shell_entrypoint(
        command[0],
        cwd=cwd,
        executable_search_path=executable_search_path,
    )
    if shell_family == "fish":
        payload, parser_complete = _fish_shell_payload(command, cwd=cwd, stdin=stdin)
        return payload, executable_complete and parser_complete
    if shell_family is None and not assume_shell:
        return None, executable_complete or stdin is None
    if shell_family is None:
        executable_complete = True
    payload, parser_complete = _generic_shell_payload(command, cwd=cwd, stdin=stdin)
    if environment_overrides is not None and _shell_startup_environment_active(
        environment_overrides,
        environment_is_complete=environment_is_complete,
    ):
        parser_complete = False
    return payload, executable_complete and parser_complete


def _shell_startup_environment_active(
    environment_overrides: object,
    *,
    environment_is_complete: bool,
) -> bool:
    return any(
        environment_value_from_env(
            environment_overrides,
            name,
            default=None if environment_is_complete else os.environ.get(name),
        )
        not in {None, ""}
        for name in _SHELL_STARTUP_ENVIRONMENT_NAMES
    )


def _generic_shell_payload(
    command: tuple[str, ...],
    *,
    cwd: str | None,
    stdin: str | None,
) -> tuple[str | None, bool]:
    startup_payloads: list[str] = []
    complete = True
    stdin_mode = False
    index = 1
    while index < len(command):
        token = command[index]
        if token == "--":
            if stdin_mode or index + 1 == len(command):
                return _merge_shell_payloads(startup_payloads, stdin), complete
            reads_stdin, path_complete = _classify_stdin_script_path(
                command[index + 1],
                cwd=cwd,
            )
            if reads_stdin:
                return _merge_shell_payloads(startup_payloads, stdin), (
                    complete and path_complete
                )
            return _merge_shell_payloads(startup_payloads), (complete and path_complete)
        if token == "-":
            return _merge_shell_payloads(startup_payloads, stdin), complete
        if token in _SHELL_STARTUP_FILE_OPTIONS:
            complete = False
            if index + 1 >= len(command):
                return _merge_shell_payloads(startup_payloads), False
            startup_path = command[index + 1]
            reads_stdin, path_complete = _classify_stdin_script_path(
                startup_path,
                cwd=cwd,
            )
            if reads_stdin and stdin is not None:
                startup_payloads.append(stdin)
            complete = complete and path_complete
            index += 2
            continue
        startup_option = next(
            (
                option
                for option in _SHELL_STARTUP_FILE_OPTIONS
                if token.startswith(f"{option}=")
            ),
            None,
        )
        if startup_option is not None:
            complete = False
            startup_path = token.removeprefix(f"{startup_option}=")
            reads_stdin, path_complete = _classify_stdin_script_path(
                startup_path,
                cwd=cwd,
            )
            if reads_stdin and stdin is not None:
                startup_payloads.append(stdin)
            complete = complete and path_complete
            index += 1
            continue
        if token in _SHELL_VALUE_OPTIONS:
            if index + 1 >= len(command):
                return _merge_shell_payloads(startup_payloads), False
            index += 2
            continue
        if any(
            token.startswith(f"{option}=")
            for option in _SHELL_VALUE_OPTIONS
            if option.startswith("--")
        ):
            index += 1
            continue
        if token.startswith(("-O", "+O", "-o", "+o")) and len(token) > 2:
            index += 1
            continue
        if token.startswith("--"):
            index += 1
            continue
        if token.startswith(("-", "+")) and len(token) > 1:
            options = token[1:]
            if any(option not in _SHELL_SHORT_OPTIONS for option in options):
                return _merge_shell_payloads(startup_payloads), False
            if "c" in options:
                payload_index = index + 1
                if payload_index < len(command) and command[payload_index] == "--":
                    payload_index += 1
                return (
                    _merge_shell_payloads(
                        startup_payloads,
                        command[payload_index]
                        if payload_index < len(command)
                        else None,
                    ),
                    complete,
                )
            if "s" in options:
                stdin_mode = True
            index += 1
            continue
        reads_stdin, path_complete = _classify_stdin_script_path(token, cwd=cwd)
        if reads_stdin:
            return _merge_shell_payloads(startup_payloads, stdin), (
                complete and path_complete
            )
        return _merge_shell_payloads(
            startup_payloads,
            stdin if stdin_mode else None,
        ), (complete and path_complete)
    return _merge_shell_payloads(startup_payloads, stdin), complete


def _merge_shell_payloads(
    payloads: Sequence[str],
    additional: str | None = None,
) -> str | None:
    values = [*payloads]
    if additional is not None:
        values.append(additional)
    return "\n".join(values) if values else None


def _classify_shell_entrypoint(
    executable: str,
    *,
    cwd: str | None,
    executable_search_path: str | None,
) -> tuple[Literal["generic", "fish"] | None, bool]:
    candidate = _resolve_executable_path(
        executable,
        cwd=cwd,
        executable_search_path=executable_search_path,
    )
    if candidate is None:
        if "/" not in executable and executable in _SHELL_ENTRY_BASENAMES:
            return _shell_family_for_name(executable), True
        return None, False

    if _is_known_multicall_candidate(candidate):
        entry_name = basename(executable)
        if entry_name in _SHELL_ENTRY_BASENAMES:
            return _shell_family_for_name(entry_name), True
        return None, True

    matching_families = {
        family
        for family, shell_paths in _known_shell_paths().items()
        if any(_paths_refer_to_same_file(candidate, path) for path in shell_paths)
    }
    if len(matching_families) == 1:
        family = matching_families.pop()
        if (
            basename(executable) in _SHELL_ENTRY_BASENAMES
            or basename(realpath(candidate)) in _SHELL_ENTRY_BASENAMES
        ):
            return family, True
        return None, False
    if matching_families:
        return None, False

    try:
        samefile(candidate, candidate)
    except OSError:
        if basename(executable) in _SHELL_ENTRY_BASENAMES:
            return _shell_family_for_name(basename(executable)), False
        return None, False
    if basename(executable) in _SHELL_ENTRY_BASENAMES:
        return _shell_family_for_name(basename(executable)), False
    return None, True


def _resolve_executable_path(
    executable: str,
    *,
    cwd: str | None,
    executable_search_path: str | None,
) -> str | None:
    if "/" in executable:
        if isabs(executable) or cwd is None:
            return executable
        return join(cwd, executable)
    search_path = executable_search_path
    if search_path is None:
        search_path = os.environ.get("PATH")
    if search_path is not None:
        base_dir = abspath(cwd or ".")
        search_path = os.pathsep.join(
            entry if isabs(entry) else join(base_dir, entry or ".")
            for entry in search_path.split(os.pathsep)
        )
    return which(executable, path=search_path)


def _shell_family_for_name(name: str) -> Literal["generic", "fish"]:
    return "fish" if name == "fish" else "generic"


@lru_cache(maxsize=1)
def _known_shell_paths() -> dict[Literal["generic", "fish"], tuple[str, ...]]:
    return {
        "generic": _known_executable_paths(_GENERIC_SHELL_ENTRY_BASENAMES),
        "fish": _known_executable_paths(frozenset({"fish"})),
    }


@lru_cache(maxsize=1)
def _known_wrapper_paths() -> dict[Literal["env", "sudo"], tuple[str, ...]]:
    return {
        "env": _known_executable_paths(frozenset({"env"})),
        "sudo": _known_executable_paths(frozenset({"sudo"})),
    }


@lru_cache(maxsize=1)
def _known_multicall_paths() -> tuple[str, ...]:
    return _known_executable_paths(_MULTICALL_ENTRY_BASENAMES)


def _known_executable_paths(names: frozenset[str]) -> tuple[str, ...]:
    paths: list[str] = []
    for name in sorted(names):
        for directory in _STANDARD_EXECUTABLE_DIRECTORIES:
            path = f"{directory}/{name}"
            if os.path.exists(path):
                paths.append(path)
    return tuple(dict.fromkeys(paths))


def _paths_refer_to_same_file(first: str, second: str) -> bool:
    try:
        return samefile(first, second)
    except OSError:
        return False


def _fish_shell_payload(
    command: tuple[str, ...],
    *,
    cwd: str | None = None,
    stdin: str | None = None,
) -> tuple[str | None, bool]:
    payloads: list[str] = []
    complete = True
    command_mode = False
    script_operand = False
    index = 1
    long_value_options = frozenset({"--command", "--init-command"})
    long_no_value_options = frozenset(
        {
            "--interactive",
            "--login",
            "--no-config",
            "--no-execute",
            "--private",
        }
    )
    while index < len(command):
        token = command[index]
        if token == "--":
            if index + 1 < len(command):
                operand = command[index + 1]
                reads_stdin, path_complete = _classify_stdin_script_path(
                    operand,
                    cwd=cwd,
                )
                if not command_mode and reads_stdin and stdin is not None:
                    payloads.append(stdin)
                    script_operand = True
                else:
                    script_operand = True
                complete = complete and path_complete
            break
        if not command_mode and token == "-":
            if stdin is not None:
                payloads.append(stdin)
            script_operand = True
            break
        if token.startswith("--"):
            option_name, separator, attached_value = token.partition("=")
            option = _resolve_long_option(
                option_name,
                long_value_options | long_no_value_options,
            )
            if option in long_value_options:
                command_mode = command_mode or option == "--command"
                if separator:
                    payloads.append(attached_value)
                    index += 1
                elif index + 1 < len(command):
                    payloads.append(command[index + 1])
                    index += 2
                else:
                    complete = False
                    break
                continue
            if option is None:
                complete = False
            index += 1
            continue
        if token.startswith("-") and len(token) > 1:
            cluster = token[1:]
            value_position = next(
                (
                    position
                    for position, option in enumerate(cluster)
                    if option in {"c", "C"}
                ),
                None,
            )
            if value_position is None:
                if any(option not in {"i", "l", "N", "P"} for option in cluster):
                    complete = False
                index += 1
                continue
            command_mode = command_mode or cluster[value_position] == "c"
            if any(
                option not in {"i", "l", "N", "P"}
                for option in cluster[:value_position]
            ):
                complete = False
            attached_value = cluster[value_position + 1 :]
            if attached_value:
                payloads.append(attached_value)
                index += 1
            elif index + 1 < len(command):
                payloads.append(command[index + 1])
                index += 2
            else:
                complete = False
                break
            continue
        reads_stdin, path_complete = _classify_stdin_script_path(token, cwd=cwd)
        if not command_mode and reads_stdin and stdin is not None:
            payloads.append(stdin)
        complete = complete and path_complete
        script_operand = True
        break
    if stdin is not None and not command_mode and not script_operand:
        payloads.append(stdin)
    return ("\n".join(payloads) if payloads else None), complete


def _classify_stdin_script_path(
    operand: str,
    *,
    cwd: str | None,
) -> tuple[bool, bool]:
    unresolved_candidate = (
        operand
        if isabs(operand)
        else join(cwd, operand)
        if cwd is not None
        else operand
    )
    normalized = normpath(abspath(unresolved_candidate))
    if normalized.startswith("//"):
        normalized = "/" + normalized.lstrip("/")
    folded = _fold_proc_root_alias(normalized)
    if folded in _STDIN_SCRIPT_PSEUDO_PATHS:
        return True, True

    uncertain = False
    for pseudo_path in _STDIN_SCRIPT_PSEUDO_PATHS:
        try:
            if samefile(unresolved_candidate, pseudo_path):
                return True, True
        except FileNotFoundError:
            continue
        except OSError:
            uncertain = True
    if uncertain and _looks_like_stdin_alias(normalized):
        return False, False
    return False, True


def _fold_proc_root_alias(path: str) -> str:
    prefixes = ("/proc/self/root/", "/proc/thread-self/root/")
    folded = path
    while True:
        prefix = next(
            (candidate for candidate in prefixes if folded.startswith(candidate)),
            None,
        )
        if prefix is None:
            return folded
        folded = normpath("/" + folded[len(prefix) :].lstrip("/"))


def _looks_like_stdin_alias(path: str) -> bool:
    parts = tuple(part for part in path.split("/") if part)
    if not parts:
        return False
    if parts[-1] == "stdin":
        return True
    return len(parts) >= 2 and parts[-2] == "fd" and parts[-1].lstrip("0") == ""


def _is_env_assignment(token: str) -> bool:
    if "=" not in token:
        return False
    name, _, _ = token.partition("=")
    return (
        bool(name)
        and (name[0].isalpha() or name[0] == "_")
        and all(ch.isalnum() or ch == "_" for ch in name[1:])
    )


def _is_env_operand(token: str) -> bool:
    return "=" in token


def _env_operand_changes_command_projection(token: str) -> bool:
    name, separator, _ = token.partition("=")
    return bool(separator) and name in {
        "PATH",
        *_SHELL_STARTUP_ENVIRONMENT_NAMES,
    }


def _split_env_string(value: str, remainder: tuple[str, ...]) -> tuple[str, ...]:
    try:
        split_tokens = tuple(shlex.split(value))
    except ValueError:
        return ("sh", "-lc", value, *remainder)
    return (*split_tokens, *remainder)


def _unwrap_env_short_options(
    token: str,
    remainder: tuple[str, ...],
) -> tuple[tuple[str, ...], bool]:
    complete = True
    cluster = token[1:]
    if not cluster:
        return remainder, False
    for index, option in enumerate(cluster):
        if option == "i":
            complete = False
        if option not in _ENV_SHORT_VALUE_OPTIONS:
            if option not in _ENV_SHORT_NO_VALUE_OPTIONS:
                complete = False
            continue
        attached_value = cluster[index + 1 :]
        if option == "S":
            if attached_value:
                return _split_env_string(attached_value, remainder), False
            if not remainder:
                return (), False
            return _split_env_string(remainder[0], remainder[1:]), False
        if option == "C":
            complete = False
        if option == "f":
            complete = False
        if option == "a":
            complete = False
        if option == "u" and (
            attached_value in {"PATH", *_SHELL_STARTUP_ENVIRONMENT_NAMES}
            or (
                not attached_value
                and remainder
                and remainder[0] in {"PATH", *_SHELL_STARTUP_ENVIRONMENT_NAMES}
            )
        ):
            complete = False
        if attached_value:
            return remainder, complete
        if not remainder:
            return (), complete
        return remainder[1:], complete
    return remainder, complete


def _unwrap_env_command(
    command: tuple[str, ...],
) -> tuple[tuple[str, ...], bool]:
    complete = True
    while command:
        head = command[0]
        if head == "--":
            command = command[1:]
            while command and _is_env_operand(command[0]):
                if _env_operand_changes_command_projection(command[0]):
                    complete = False
                command = command[1:]
            return command, complete
        if head in _ENV_NO_VALUE_OPTIONS:
            if head in {"-i", "--ignore-environment"}:
                complete = False
            command = command[1:]
            continue
        if head == "-S":
            if len(command) < 2:
                return (), False
            command = _split_env_string(command[1], command[2:])
            complete = False
            continue
        if head.startswith("-S") and len(head) > 2:
            command = _split_env_string(head[2:], command[1:])
            complete = False
            continue
        if head in _ENV_VALUE_OPTIONS and not head.startswith("--"):
            if head == "-C":
                complete = False
            if len(command) < 2:
                return (), complete
            if head in {"-a", "-f"} or (
                head == "-u"
                and command[1] in {"PATH", *_SHELL_STARTUP_ENVIRONMENT_NAMES}
            ):
                complete = False
            command = command[2:]
            continue
        if head.startswith("--"):
            option_name, separator, attached_value = head.partition("=")
            option = _resolve_long_option(option_name, _ENV_LONG_OPTIONS)
            if option == "--split-string":
                complete = False
                if separator:
                    command = _split_env_string(attached_value, command[1:])
                elif len(command) < 2:
                    return (), False
                else:
                    command = _split_env_string(command[1], command[2:])
                continue
            if option in _ENV_LONG_VALUE_OPTIONS:
                if option == "--chdir":
                    complete = False
                option_value = (
                    attached_value
                    if separator
                    else (command[1] if len(command) >= 2 else None)
                )
                if option in {"--argv0", "--file"} or (
                    option == "--unset"
                    and option_value in {"PATH", *_SHELL_STARTUP_ENVIRONMENT_NAMES}
                ):
                    complete = False
                if separator:
                    command = command[1:]
                elif len(command) < 2:
                    return (), complete
                else:
                    command = command[2:]
                continue
            if option is None:
                complete = False
            command = command[1:]
            continue
        if head.startswith("-") and not head.startswith("--"):
            command, option_complete = _unwrap_env_short_options(
                head,
                command[1:],
            )
            complete = complete and option_complete
            continue
        if _env_operand_changes_command_projection(head):
            complete = False
            command = command[1:]
            continue
        if head.startswith("-") or _is_env_operand(head):
            command = command[1:]
            continue
        break
    return command, complete


def _unwrap_leading_wrappers(
    command: tuple[str, ...],
    *,
    cwd: str | None,
    executable_search_path: str | None,
) -> tuple[tuple[str, ...], bool]:
    complete = True
    while command:
        multicall = _unwrap_multicall_control_applet(
            command,
            cwd=cwd,
            executable_search_path=executable_search_path,
        )
        if multicall is not None:
            command, multicall_complete = multicall
            complete = complete and multicall_complete
            if command and command[0] == "env":
                command, env_complete = _unwrap_env_command(command[1:])
                complete = complete and env_complete
            continue
        wrapper, wrapper_identity_complete = _classify_leading_wrapper(
            command[0],
            cwd=cwd,
            executable_search_path=executable_search_path,
        )
        complete = complete and wrapper_identity_complete
        if wrapper is None:
            break
        command = command[1:]
        if wrapper == "env":
            command, wrapper_complete = _unwrap_env_command(command)
            complete = complete and wrapper_complete
            continue
        command, shell_mode, wrapper_complete = _unwrap_sudo_command(command)
        complete = complete and wrapper_complete
        while command and _is_env_assignment(command[0]):
            if _env_operand_changes_command_projection(command[0]):
                complete = False
            command = command[1:]
        if shell_mode:
            complete = False
            return (
                (("sh", "-c", shlex.join(command)) if command else ()),
                complete,
            )
    return command, complete


def _unwrap_multicall_control_applet(
    command: tuple[str, ...],
    *,
    cwd: str | None,
    executable_search_path: str | None,
) -> tuple[tuple[str, ...], bool] | None:
    if (
        len(command) < 2
        or basename(command[0]) not in _MULTICALL_ENTRY_BASENAMES
        or command[1] not in _MULTICALL_CONTROL_APPLETS
    ):
        return None
    candidate = _resolve_executable_path(
        command[0],
        cwd=cwd,
        executable_search_path=executable_search_path,
    )
    identity_complete = bool(
        candidate is not None
        and basename(realpath(candidate)) in _MULTICALL_ENTRY_BASENAMES
        and _is_known_multicall_candidate(candidate)
    )
    return command[1:], identity_complete


def _classify_leading_wrapper(
    executable: str,
    *,
    cwd: str | None,
    executable_search_path: str | None,
) -> tuple[Literal["env", "sudo"] | None, bool]:
    candidate = _resolve_executable_path(
        executable,
        cwd=cwd,
        executable_search_path=executable_search_path,
    )
    entry_name = basename(executable)
    if candidate is None:
        if "/" not in executable and entry_name in _LEADING_WRAPPER_BASENAMES:
            return cast(Literal["env", "sudo"], entry_name), True
        return None, entry_name not in _LEADING_WRAPPER_BASENAMES

    if entry_name == "env" and _is_known_multicall_candidate(candidate):
        return "env", True

    if entry_name not in _LEADING_WRAPPER_BASENAMES:
        resolved_name = basename(realpath(candidate))
        return None, resolved_name not in _LEADING_WRAPPER_BASENAMES

    wrapper = cast(Literal["env", "sudo"], entry_name)
    if basename(realpath(candidate)) == entry_name and any(
        _paths_refer_to_same_file(candidate, path)
        for path in _known_wrapper_paths()[wrapper]
    ):
        return wrapper, True

    shell_family, shell_complete = _classify_shell_entrypoint(
        executable,
        cwd=cwd,
        executable_search_path=executable_search_path,
    )
    if shell_family is not None:
        return None, shell_complete
    return None, False


def _is_known_multicall_candidate(candidate: str) -> bool:
    return any(
        _paths_refer_to_same_file(candidate, path) for path in _known_multicall_paths()
    )


def _unwrap_sudo_command(
    command: tuple[str, ...],
) -> tuple[tuple[str, ...], bool, bool]:
    shell_mode = False
    complete = True
    while command:
        head = command[0]
        if head == "--":
            return command[1:], shell_mode, complete
        if not head.startswith("-"):
            return command, shell_mode, complete
        if head.startswith("--"):
            option_name, separator, _ = head.partition("=")
            option = _resolve_long_option(option_name, _SUDO_LONG_OPTIONS)
            if option is None:
                complete = False
            if option in {"--chdir", "--chroot"}:
                complete = False
            if option in _SUDO_SHELL_MODE_LONG_OPTIONS:
                shell_mode = True
            if option in _SUDO_LONG_VALUE_OPTIONS and not separator:
                if len(command) < 2:
                    return (), shell_mode, complete
                command = command[2:]
            else:
                command = command[1:]
            continue
        command, token_shell_mode, token_complete = _unwrap_sudo_short_options(
            head,
            command[1:],
        )
        shell_mode = shell_mode or token_shell_mode
        complete = complete and token_complete
    return command, shell_mode, complete


def _unwrap_sudo_short_options(
    token: str,
    remainder: tuple[str, ...],
) -> tuple[tuple[str, ...], bool, bool]:
    shell_mode = False
    complete = True
    cluster = token[1:]
    for index, option in enumerate(cluster):
        if option in _SUDO_SHORT_VALUE_OPTIONS:
            if option in {"D", "R"}:
                complete = False
            if index < len(cluster) - 1:
                return remainder, shell_mode, complete
            if not remainder:
                return (), shell_mode, complete
            return remainder[1:], shell_mode, complete
        if option in {"i", "s"}:
            shell_mode = True
        elif option not in _SUDO_SHORT_NO_VALUE_OPTIONS:
            complete = False
    return remainder, shell_mode, complete


def _resolve_long_option(
    option_name: str,
    options: frozenset[str],
) -> str | None:
    if option_name in options:
        return option_name
    matches = tuple(option for option in options if option.startswith(option_name))
    return matches[0] if len(matches) == 1 else None


def _direct_command_tokens(command: tuple[str, ...]) -> tuple[str, ...]:
    if not command:
        return ()
    return (basename(command[0]), *command[1:])


def _string_tuple(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be a sequence of strings, not a string")
    normalized = tuple(values)
    if not all(isinstance(value, str) for value in normalized):
        raise TypeError(f"{field_name} must be a sequence of strings")
    return normalized


def _freeze_mapping(values: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(values, Mapping):
        raise TypeError("arguments must be a mapping")
    return MappingProxyType(
        {
            _require_policy_mapping_key(key): _freeze_value(value)
            for key, value in values.items()
        }
    )


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                _require_policy_mapping_key(key): _freeze_value(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item) for item in value)
    if value is None or isinstance(value, str | bool | int | float):
        return value
    raise TypeError(
        "policy argument values must be JSON-compatible mappings, sequences, "
        "strings, numbers, booleans, or null"
    )


def _require_policy_mapping_key(key: object) -> str:
    if not isinstance(key, str):
        raise TypeError("policy argument mapping keys must be strings")
    return key
