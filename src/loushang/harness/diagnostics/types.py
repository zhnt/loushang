from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal

DiagnosticLevel = Literal["info", "warning", "error"]
DiagnosticPhase = Literal["startup", "resource_loading", "runtime"]
DiagnosticSource = Literal[
    "bootstrap",
    "loader",
    "package",
    "extensions",
    "session",
    "policy",
    "exec",
    "tool",
    "diagnostics",
    "provider",
    "model",
    "agent",
]

_EMPTY_DETAILS: Mapping[str, object] = MappingProxyType({})


@dataclass(frozen=True)
class DiagnosticDraft:
    """Unstamped diagnostic data awaiting runtime scope and severity."""

    code: str
    message: str
    source_path: Path | None = None
    details: Mapping[str, object] = field(default_factory=lambda: _EMPTY_DETAILS)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "details",
            MappingProxyType(dict(self.details)) if self.details else _EMPTY_DETAILS,
        )


@dataclass(frozen=True)
class DiagnosticRecord:
    type: DiagnosticLevel
    code: str
    message: str
    phase: DiagnosticPhase
    source: DiagnosticSource
    timestamp: str
    session_id: str | None = None
    entry_id: str | None = None
    source_path: Path | None = None
    details: dict[str, object] = field(default_factory=dict)
    fingerprint: str | None = field(default=None, compare=False)
    occurrence_count: int = 1


@dataclass(frozen=True)
class ErrorReport:
    primary: DiagnosticRecord
    related: tuple[DiagnosticRecord, ...] = ()


@dataclass(frozen=True)
class DiagnosticSummary:
    total_count: int
    error_count: int
    warning_count: int
    info_count: int
    by_code: dict[str, int] = field(default_factory=dict)
    by_source: dict[str, int] = field(default_factory=dict)
    by_phase: dict[str, int] = field(default_factory=dict)
    latest_error: DiagnosticRecord | None = None


@dataclass(frozen=True, kw_only=True)
class DiagnosticsQuery:
    phase: DiagnosticPhase | None = None
    source: DiagnosticSource | None = None
    level: DiagnosticLevel | None = None
    session_id: str | None = None
    entry_id: str | None = None
    tool_call_id: str | None = None
    code: str | None = None
    limit: int | None = None


@dataclass(frozen=True)
class StartupCheckResult:
    name: str
    ok: bool
    message: str = ""
    code: str | None = None
    level: DiagnosticLevel | None = None
    source: DiagnosticSource = "bootstrap"
    source_path: Path | None = None
    details: dict[str, object] = field(default_factory=dict)


StartupCheck = Callable[[], StartupCheckResult | DiagnosticRecord | None]


def directory_available_startup_check(
    *,
    name: str,
    path: str | Path,
    code: str,
    message: str,
    detail_key: str,
    level: DiagnosticLevel = "warning",
    source: DiagnosticSource = "bootstrap",
) -> StartupCheck:
    """Build a standard startup check for one required directory."""

    candidate = Path(path).expanduser()

    def check() -> StartupCheckResult | None:
        if candidate.is_dir():
            return None
        return StartupCheckResult(
            name=name,
            ok=False,
            code=code,
            level=level,
            source=source,
            message=message,
            details={detail_key: str(candidate)},
        )

    return check


__all__ = [
    "DiagnosticDraft",
    "DiagnosticLevel",
    "DiagnosticPhase",
    "DiagnosticRecord",
    "DiagnosticSource",
    "DiagnosticSummary",
    "DiagnosticsQuery",
    "ErrorReport",
    "StartupCheck",
    "StartupCheckResult",
    "directory_available_startup_check",
]
