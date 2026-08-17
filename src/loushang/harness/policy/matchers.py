"""Concrete product-neutral policy matchers."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.policy.subjects import (
    PathPolicySubject,
    PolicySubject,
    ToolPolicySubject,
    _command_subject,
    _contains_token_sequence,
    _string_tuple,
)


@dataclass(frozen=True)
class ExactToolNameMatcher:
    tool_name: str

    def matches(self, subject: PolicySubject, /) -> bool:
        return (
            isinstance(subject, ToolPolicySubject)
            and subject.tool_name == self.tool_name
        )


@dataclass(frozen=True)
class CapabilityIdMatcher:
    capability_id: str

    def matches(self, subject: PolicySubject, /) -> bool:
        return (
            isinstance(subject, ToolPolicySubject)
            and subject.capability_id == self.capability_id
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
