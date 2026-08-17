from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Literal
from unicodedata import category

from loushang.ai.auth.credentials import (
    ApiKeyAuth,
    AuthCredential,
    OAuthBearerAuth,
    OAuthCredential,
)
from loushang.ai.prepared_request import PreparedRequestCommitter, PreparedRequestLimits
from loushang.ai.structured import StructuredOutputOptions

PairingMode = Literal["strict", "repair"]

ThinkingLevel = Literal["minimal", "low", "medium", "high", "xhigh"]


CacheRetention = Literal["none", "short", "long"]


ToolChoice = str | Mapping[str, object]

_TOOL_CHOICE_STRINGS = frozenset({"auto", "none", "required", "any"})
_THINKING_LEVELS = frozenset({"minimal", "low", "medium", "high", "xhigh"})


@dataclass(frozen=True, slots=True)
class ReasoningOptions:
    enabled: bool | None = None
    effort: ThinkingLevel | None = None
    budget_tokens: int | None = None
    expose_summary: bool = False

    def __post_init__(self) -> None:
        if self.enabled is not None and not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean or None")
        if self.effort is not None and self.effort not in _THINKING_LEVELS:
            raise ValueError(f"Unsupported reasoning effort: {self.effort!r}")
        if self.budget_tokens is not None and (
            isinstance(self.budget_tokens, bool)
            or not isinstance(self.budget_tokens, int)
            or self.budget_tokens <= 0
        ):
            raise ValueError("budget_tokens must be a positive integer or None")
        if not isinstance(self.expose_summary, bool):
            raise TypeError("expose_summary must be a boolean")


@dataclass(frozen=True, slots=True)
class RetryOptions:
    max_attempts: int = 1
    max_delay_seconds: float = 30.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or self.max_attempts < 1
        ):
            raise ValueError(
                "max_attempts must be an integer greater than or equal to 1"
            )
        if (
            isinstance(self.max_delay_seconds, bool)
            or not isinstance(self.max_delay_seconds, int | float)
            or not isfinite(self.max_delay_seconds)
            or self.max_delay_seconds < 0
        ):
            raise ValueError("max_delay_seconds must be a finite non-negative number")


@dataclass(frozen=True, slots=True)
class CallOptions:
    cancellation: object | None = None
    auth: AuthCredential | None = None
    credential: OAuthCredential | None = field(default=None, repr=False)
    credential_file: str | Path | None = None
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    cache_retention: CacheRetention | None = None
    cache_key: str | None = None
    max_output_tokens: int | None = None
    temperature: float | int | None = None
    timeout_seconds: float | int | None = None
    idle_timeout_seconds: float | int | None = None
    retry: RetryOptions | None = None
    trace: object | None = None
    # Default to repair so interrupted/partial transcripts (e.g. a run killed
    # mid-tool-call) recover automatically instead of failing the whole request.
    # Callers that need strict validation (e.g. new-session message flow) can
    # set pairing_mode="strict" explicitly.
    pairing_mode: PairingMode = "repair"
    reasoning: ReasoningOptions | None = None
    tool_choice: ToolChoice | None = None
    output: StructuredOutputOptions | None = None
    request_limits: PreparedRequestLimits | None = None
    prepared_request_committer: PreparedRequestCommitter | None = field(
        default=None,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.auth is not None and not isinstance(
            self.auth, (ApiKeyAuth, OAuthBearerAuth)
        ):
            raise TypeError("auth must be ApiKeyAuth, OAuthBearerAuth, or None")
        if self.credential is not None and not isinstance(
            self.credential, OAuthCredential
        ):
            raise TypeError("credential must be OAuthCredential or None")
        if self.credential_file is not None and not isinstance(
            self.credential_file, (str, Path)
        ):
            raise TypeError("credential_file must be a path string, Path, or None")
        if isinstance(self.credential_file, str) and not self.credential_file.strip():
            raise ValueError("credential_file must be non-empty")
        object.__setattr__(
            self,
            "headers",
            MappingProxyType(_validate_headers(self.headers, "headers")),
        )
        if self.cache_key is not None:
            if not isinstance(self.cache_key, str):
                raise TypeError("cache_key must be a string or None")
            if not self.cache_key.strip():
                raise ValueError("cache_key must be non-empty")
            if any(category(character) == "Cc" for character in self.cache_key):
                raise ValueError("cache_key must not contain control characters")
        if self.max_output_tokens is not None and (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens <= 0
        ):
            raise ValueError("max_output_tokens must be a positive integer or None")
        if self.temperature is not None and (
            isinstance(self.temperature, bool)
            or not isinstance(self.temperature, int | float)
            or not isfinite(self.temperature)
        ):
            raise ValueError("temperature must be a finite number or None")
        if self.cache_retention not in {None, "none", "short", "long"}:
            raise ValueError(f"Unsupported cache_retention: {self.cache_retention!r}")
        if self.pairing_mode not in {"strict", "repair"}:
            raise ValueError(f"Unsupported pairing_mode: {self.pairing_mode!r}")
        _validate_optional_positive_number(self.timeout_seconds, "timeout_seconds")
        _validate_optional_positive_number(
            self.idle_timeout_seconds,
            "idle_timeout_seconds",
        )
        if self.retry is not None and not isinstance(self.retry, RetryOptions):
            raise TypeError("retry must be RetryOptions")
        if self.reasoning is not None and not isinstance(
            self.reasoning, ReasoningOptions
        ):
            raise TypeError("reasoning must be ReasoningOptions")
        if self.prepared_request_committer is not None and not isinstance(
            self.prepared_request_committer,
            PreparedRequestCommitter,
        ):
            raise TypeError(
                "prepared_request_committer must implement "
                "commit_prepared_request"
            )
        if self.request_limits is not None and not isinstance(
            self.request_limits,
            PreparedRequestLimits,
        ):
            raise TypeError("request_limits must be PreparedRequestLimits or None")
        _validate_tool_choice(self.tool_choice)


def _validate_optional_positive_number(value: object, field_name: str) -> None:
    if value is None:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{field_name} must be a finite positive number or None")


def _validate_headers(value: object, field_name: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping of strings")
    headers: dict[str, str] = {}
    normalized_names: set[str] = set()
    for key, entry in value.items():
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(entry, str)
            or not entry
        ):
            raise ValueError(
                f"{field_name} must contain non-empty string names and values"
            )
        if "\r" in key or "\n" in key or "\r" in entry or "\n" in entry:
            raise ValueError(f"{field_name} must not contain CR or LF")
        normalized = key.casefold()
        if normalized in normalized_names:
            raise ValueError(f"{field_name} contains duplicate header names")
        normalized_names.add(normalized)
        headers[key] = entry
    return headers


def _validate_tool_choice(value: ToolChoice | None) -> None:
    if value is None:
        return
    if isinstance(value, str):
        if value not in _TOOL_CHOICE_STRINGS:
            raise ValueError(f"Unsupported tool_choice: {value!r}")
        return
    if not isinstance(value, Mapping):
        raise TypeError("tool_choice must be a supported string or mapping")

    choice_type = value.get("type")
    if isinstance(choice_type, str) and choice_type in _TOOL_CHOICE_STRINGS:
        allowed = {"type", "disable_parallel_tool_use"}
        disable_parallel = value.get("disable_parallel_tool_use")
        if set(value) <= allowed and (
            disable_parallel is None or isinstance(disable_parallel, bool)
        ):
            return
    if (
        choice_type == "tool"
        and set(value) == {"type", "name"}
        and isinstance(value.get("name"), str)
        and value["name"]
    ):
        return
    if choice_type == "function":
        if (
            set(value) == {"type", "name"}
            and isinstance(value.get("name"), str)
            and value["name"]
        ):
            return
        if set(value) == {"type", "function"}:
            function = value.get("function")
            if (
                isinstance(function, Mapping)
                and set(function) == {"name"}
                and isinstance(function.get("name"), str)
                and function["name"]
            ):
                return
    raise ValueError("tool_choice mapping has an unsupported shape")


def get_max_output_tokens(options: object | None) -> int | None:
    if options is None:
        return None
    value = getattr(options, "max_output_tokens", None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def get_reasoning_options(options: object | None) -> ReasoningOptions | None:
    if options is None:
        return None
    value = getattr(options, "reasoning", None)
    return value if isinstance(value, ReasoningOptions) else None


def get_reasoning_effort(options: object | None) -> str | None:
    if options is None:
        return None
    reasoning = getattr(options, "reasoning", None)
    if isinstance(reasoning, ReasoningOptions):
        return reasoning.effort if isinstance(reasoning.effort, str) else None
    return None


def get_reasoning_summary(options: object | None) -> str | None:
    if options is None:
        return None
    reasoning = get_reasoning_options(options)
    if reasoning is not None and reasoning.expose_summary:
        return "auto"
    return None


def get_reasoning_budget_tokens(options: object | None) -> int | None:
    if options is None:
        return None
    reasoning = get_reasoning_options(options)
    if reasoning is not None and isinstance(reasoning.budget_tokens, int):
        return reasoning.budget_tokens
    return None


def is_reasoning_requested(options: object | None) -> bool:
    if options is None:
        return False
    reasoning = get_reasoning_options(options)
    if reasoning is not None:
        if reasoning.enabled is False:
            return False
        return bool(
            reasoning.enabled
            or reasoning.effort
            or reasoning.budget_tokens
            or reasoning.expose_summary
        )
    return False


def get_timeout_seconds(options: object | None) -> float | int | None:
    if options is None:
        return None
    value = getattr(options, "timeout_seconds", None)
    return (
        value
        if isinstance(value, int | float)
        and not isinstance(value, bool)
        and isfinite(value)
        and value > 0
        else None
    )


def get_idle_timeout_seconds(options: object | None) -> float | int | None:
    if options is None:
        return None
    value = getattr(options, "idle_timeout_seconds", None)
    return (
        value
        if isinstance(value, int | float)
        and not isinstance(value, bool)
        and isfinite(value)
        and value > 0
        else None
    )


def get_retry_attempts(options: object | None) -> int | None:
    if options is None:
        return None
    retry = getattr(options, "retry", None)
    if isinstance(retry, RetryOptions):
        return retry.max_attempts
    return None


def get_retry_max_delay_ms(options: object | None) -> int | None:
    if options is None:
        return None
    retry = getattr(options, "retry", None)
    if isinstance(retry, RetryOptions):
        return int(retry.max_delay_seconds * 1000)
    return None


__all__ = [
    "CacheRetention",
    "CallOptions",
    "PairingMode",
    "ReasoningOptions",
    "PreparedRequestLimits",
    "RetryOptions",
    "StructuredOutputOptions",
    "ThinkingLevel",
    "ToolChoice",
]
