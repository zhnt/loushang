from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..json import JSONValue
from ._router import (
    emit_debug_event,
    emit_log,
    emit_problem,
    is_debug_event_enabled,
)
from ._time import monotonic_ms, utc_now_iso
from .context import current_context
from .projection import project_diagnostic_mapping
from .records import DebugEventRecord, ProblemRecord, ProblemSeverity


@dataclass(frozen=True)
class ObservabilityLog:
    module: str
    component: str | None = None

    def bind(self, *, component: str | None = None) -> ObservabilityLog:
        return ObservabilityLog(
            module=self.module,
            component=self.component if component is None else component,
        )

    def debug(self, message: str, **details: JSONValue) -> None:
        self._log("debug", message, details)

    def info(self, message: str, **details: JSONValue) -> None:
        self._log("info", message, details)

    def warning(self, message: str, **details: JSONValue) -> None:
        self._log("warning", message, details)

    def error(self, message: str, **details: JSONValue) -> None:
        self._log("error", message, details)

    def problem(
        self,
        code: str,
        *,
        message: str | None = None,
        severity: ProblemSeverity = "error",
        source: str | None = None,
        recoverable: bool = False,
        exc: BaseException | None = None,
        details: Mapping[str, object] | None = None,
        **extra_details: JSONValue,
    ) -> ProblemRecord:
        merged_details: dict[str, object] = {}
        if details is not None:
            merged_details.update(details)
        merged_details.update(extra_details)

        context = current_context()
        exception_message = str(exc) if exc is not None else None
        record = ProblemRecord(
            code=code,
            severity=severity,
            source=source,
            message=message if message is not None else (exception_message or ""),
            recoverable=recoverable,
            details=project_diagnostic_mapping(merged_details),
            exception_type=type(exc).__name__ if exc is not None else None,
            exception_message=exception_message,
            time=utc_now_iso(),
            monotonic_ms=monotonic_ms(),
            module=self.module,
            component=self.component,
            session_id=context.session_id,
            run_id=context.run_id,
            cwd=context.cwd,
            mode=context.mode,
        )
        emit_problem(record)
        return record

    def problem_from_exception(
        self,
        exc: BaseException,
        *,
        code: str | None = None,
        message: str | None = None,
        severity: ProblemSeverity = "error",
        source: str | None = None,
        recoverable: bool = False,
        details: Mapping[str, object] | None = None,
        **extra_details: JSONValue,
    ) -> ProblemRecord:
        return self.problem(
            code or _exception_code(exc),
            message=message,
            severity=severity,
            source=source,
            recoverable=recoverable,
            exc=exc,
            details=details,
            **extra_details,
        )

    def debug_event(self, scope: str, name: str, **data: JSONValue) -> None:
        if not is_debug_event_enabled(scope):
            return

        context = current_context()
        record = DebugEventRecord(
            scope=scope,
            name=name,
            data=project_diagnostic_mapping(data, name="data"),
            time=utc_now_iso(),
            monotonic_ms=monotonic_ms(),
            module=self.module,
            component=self.component,
            session_id=context.session_id,
            run_id=context.run_id,
            cwd=context.cwd,
            mode=context.mode,
        )
        emit_debug_event(record)

    def _log(self, level: str, message: str, details: Mapping[str, object]) -> None:
        emit_log(
            level=level,
            module=self.module,
            component=self.component,
            message=message,
            details=project_diagnostic_mapping(details),
        )


def get_log(module: str) -> ObservabilityLog:
    return ObservabilityLog(module=module)


def _exception_code(exc: BaseException) -> str:
    name = type(exc).__name__
    chars: list[str] = []
    for index, char in enumerate(name):
        if char.isupper() and index > 0:
            chars.append("_")
        chars.append(char.lower())
    return "".join(chars)
