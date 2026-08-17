from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar, cast, runtime_checkable

from loushang.foundation.json import JSONValue, dump_json_value, require_json_value

TDetails = TypeVar("TDetails", contravariant=True)

_PROJECTION_TARGETS = frozenset({"transcript", "event", "hook", "diagnostic"})
_MAX_PROJECTION_MESSAGE_BYTES = 1024
_MAX_PROJECTION_PATH_BYTES = 512
_MAX_PROJECTION_VALUE_TYPE_BYTES = 128
_TRUNCATED_METADATA_SUFFIX = "...[truncated]"


class ToolOutputProjectionError(TypeError):
    def __init__(
        self,
        target: str,
        message: str,
        *,
        path: str,
        value_type: str,
    ) -> None:
        safe_target = _sanitize_projection_target(target)
        safe_path = _sanitize_projection_metadata(
            path,
            fallback="tool_output.details",
            max_bytes=_MAX_PROJECTION_PATH_BYTES,
        )
        safe_value_type = _sanitize_projection_metadata(
            value_type,
            fallback="unknown",
            max_bytes=_MAX_PROJECTION_VALUE_TYPE_BYTES,
        )
        safe_message = _sanitize_projection_metadata(
            message,
            fallback="Tool output projection failed",
            max_bytes=_MAX_PROJECTION_MESSAGE_BYTES,
        )
        super().__init__(safe_message)
        self.target = safe_target
        self.path = safe_path
        self.value_type = safe_value_type


def _sanitize_projection_target(target: object) -> str:
    if type(target) is str and target in _PROJECTION_TARGETS:
        return cast(str, target)
    return "unknown"


def _sanitize_projection_metadata(
    value: object,
    *,
    fallback: str,
    max_bytes: int,
) -> str:
    if type(value) is not str:
        return fallback
    text = cast(str, value)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return fallback
    text = "".join(
        f"\\u{ord(character):04x}"
        if ord(character) < 32 or ord(character) == 127
        else character
        for character in text
    )
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    suffix = _TRUNCATED_METADATA_SUFFIX.encode("utf-8")
    prefix = encoded[: max_bytes - len(suffix)].decode("utf-8", errors="ignore")
    return prefix + _TRUNCATED_METADATA_SUFFIX


@dataclass(frozen=True)
class ToolOutputPreviewPolicy:
    max_bytes: int = 2 * 1024
    max_lines: int = 64

    def __post_init__(self) -> None:
        if self.max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        if self.max_lines < 1:
            raise ValueError("max_lines must be positive")


@runtime_checkable
class ToolOutputProjector(Protocol[TDetails]):
    def to_transcript_details(self, details: TDetails) -> JSONValue: ...

    def to_event_details(self, details: TDetails) -> JSONValue: ...

    def to_hook_details(self, details: TDetails) -> JSONValue: ...

    def log_preview(
        self,
        details: TDetails,
        policy: ToolOutputPreviewPolicy,
    ) -> str: ...


@dataclass(frozen=True)
class StrictJsonToolOutputProjector(Generic[TDetails]):
    def to_transcript_details(self, details: TDetails) -> JSONValue:
        return _strict_project(details, target="transcript")

    def to_event_details(self, details: TDetails) -> JSONValue:
        return _strict_project(details, target="event")

    def to_hook_details(self, details: TDetails) -> JSONValue:
        return _strict_project(details, target="hook")

    def log_preview(
        self,
        details: TDetails,
        policy: ToolOutputPreviewPolicy,
    ) -> str:
        projected = _strict_project(details, target="diagnostic")
        return bound_tool_output_preview(
            dump_json_value(projected, name="tool_output.details"),
            policy,
        )


ProjectDetails = Callable[[TDetails], object]
PreviewDetails = Callable[[TDetails, ToolOutputPreviewPolicy], str]


@dataclass(frozen=True)
class FunctionalToolOutputProjector(Generic[TDetails]):
    transcript: ProjectDetails
    event: ProjectDetails | None = None
    hook: ProjectDetails | None = None
    preview: PreviewDetails | None = None

    def to_transcript_details(self, details: TDetails) -> JSONValue:
        return _project_callback(self.transcript, details, target="transcript")

    def to_event_details(self, details: TDetails) -> JSONValue:
        callback = self.event if self.event is not None else self.transcript
        return _project_callback(callback, details, target="event")

    def to_hook_details(self, details: TDetails) -> JSONValue:
        callback = (
            self.hook
            if self.hook is not None
            else self.event
            if self.event is not None
            else self.transcript
        )
        return _project_callback(callback, details, target="hook")

    def log_preview(
        self,
        details: TDetails,
        policy: ToolOutputPreviewPolicy,
    ) -> str:
        if self.preview is not None:
            try:
                preview = self.preview(details, policy)
            except Exception as exc:
                raise ToolOutputProjectionError(
                    "diagnostic",
                    f"Tool output diagnostic projector raised {type(exc).__name__}",
                    path="tool_output.details",
                    value_type=type(details).__name__,
                ) from exc
            return bound_tool_output_preview(preview, policy)
        callback = self.event if self.event is not None else self.transcript
        projected = _project_callback(
            callback,
            details,
            target="diagnostic",
        )
        return bound_tool_output_preview(
            dump_json_value(projected, name="tool_output.details"),
            policy,
        )


STRICT_JSON_TOOL_OUTPUT_PROJECTOR: ToolOutputProjector[object] = (
    StrictJsonToolOutputProjector()
)


def _strict_project(details: object, *, target: str) -> JSONValue:
    try:
        return require_json_value(details, name="tool_output.details")
    except TypeError as exc:
        path = getattr(exc, "path", "tool_output.details")
        value_type = getattr(exc, "value_type", type(details).__name__)
        raise ToolOutputProjectionError(
            target,
            f"Tool output {target} projection failed at {path}: {value_type}",
            path=path,
            value_type=value_type,
        ) from exc


def _project_callback(
    callback: Callable[[TDetails], object],
    details: TDetails,
    *,
    target: str,
) -> JSONValue:
    try:
        projected = callback(details)
    except Exception as exc:
        raise ToolOutputProjectionError(
            target,
            f"Tool output {target} projector raised {type(exc).__name__}",
            path="tool_output.details",
            value_type=type(details).__name__,
        ) from exc
    return _strict_project(projected, target=target)


def bound_tool_output_preview(
    preview: object,
    policy: ToolOutputPreviewPolicy,
) -> str:
    if not isinstance(preview, str):
        raise ToolOutputProjectionError(
            "diagnostic",
            "Tool output diagnostic projector must return str",
            path="tool_output.preview",
            value_type=type(preview).__name__,
        )
    try:
        validated_preview = require_json_value(
            preview,
            name="tool_output.preview",
        )
    except TypeError as exc:
        raise ToolOutputProjectionError(
            "diagnostic",
            "Tool output diagnostic preview must be valid UTF-8",
            path=getattr(exc, "path", "tool_output.preview"),
            value_type=getattr(exc, "value_type", "str"),
        ) from exc
    return _truncate_preview(cast(str, validated_preview), policy)


def _truncate_preview(text: str, policy: ToolOutputPreviewPolicy) -> str:
    suffix = "\n[... preview truncated ...]"
    lines = text.splitlines()
    if len(lines) > policy.max_lines:
        text = "\n".join(lines[: policy.max_lines]) + suffix
    encoded = text.encode("utf-8")
    if len(encoded) <= policy.max_bytes:
        return text
    suffix_bytes = suffix.encode("utf-8")
    if len(suffix_bytes) >= policy.max_bytes:
        return suffix_bytes[: policy.max_bytes].decode("utf-8", errors="ignore")
    budget = policy.max_bytes - len(suffix_bytes)
    prefix = encoded[:budget].decode("utf-8", errors="ignore")
    return prefix + suffix


__all__ = [
    "FunctionalToolOutputProjector",
    "STRICT_JSON_TOOL_OUTPUT_PROJECTOR",
    "StrictJsonToolOutputProjector",
    "ToolOutputPreviewPolicy",
    "ToolOutputProjectionError",
    "ToolOutputProjector",
]
