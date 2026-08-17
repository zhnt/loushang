"""Optional bridge from Foundation Observability facts to session diagnostics.

The diagnostics core stays independent of
:mod:`loushang.foundation.observability`. Products that opt into both systems
can use this adapter to retain an observability problem record and publish its
normalized diagnostic counterpart.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, cast

from loushang.foundation.observability.records import ProblemRecord
from loushang.foundation.observability.runtime import InMemoryProblemStore
from loushang.harness.diagnostics.types import (
    DiagnosticPhase,
    DiagnosticRecord,
    DiagnosticSource,
)


class DiagnosticRecorder(Protocol):
    """Minimal diagnostics port required by :class:`DiagnosticsProblemStore`."""

    def record(self, diagnostic: DiagnosticRecord) -> object: ...


DiagnosticPhaseResolver = Callable[[ProblemRecord], DiagnosticPhase]
DiagnosticSourceResolver = Callable[[ProblemRecord], DiagnosticSource]


class DiagnosticsProblemStore(InMemoryProblemStore):
    """Store problems and publish one normalized diagnostic for each problem.

    Both direct ``record()`` calls and observability's ``record_problem()`` path
    use this method.  The base implementation of ``record_problem()`` delegates
    to ``record()``, so each problem is forwarded exactly once per call.
    """

    def __init__(
        self,
        diagnostics: DiagnosticRecorder,
        *,
        phase_resolver: DiagnosticPhaseResolver | None = None,
        source_resolver: DiagnosticSourceResolver | None = None,
    ) -> None:
        super().__init__()
        self._diagnostics = diagnostics
        self._phase_resolver = phase_resolver or diagnostic_phase_for_problem
        self._source_resolver = source_resolver or diagnostic_source_for_problem

    def record(self, record: ProblemRecord) -> None:
        super().record(record)
        self._diagnostics.record(
            problem_to_diagnostic(
                record,
                phase_resolver=self._phase_resolver,
                source_resolver=self._source_resolver,
            )
        )


def problem_to_diagnostic(
    record: ProblemRecord,
    *,
    phase_resolver: DiagnosticPhaseResolver | None = None,
    source_resolver: DiagnosticSourceResolver | None = None,
) -> DiagnosticRecord:
    """Normalize one observability problem without applying product policy."""

    return DiagnosticRecord(
        type=record.severity,
        code=record.code,
        message=record.message,
        phase=(phase_resolver or diagnostic_phase_for_problem)(record),
        source=(source_resolver or diagnostic_source_for_problem)(record),
        timestamp=record.time,
        session_id=record.session_id,
        details=_diagnostic_details(record),
    )


def diagnostic_phase_for_problem(record: ProblemRecord) -> DiagnosticPhase:
    """Map standard observability modes to the neutral diagnostic phases."""

    if record.mode == "startup":
        return "startup"
    if record.mode == "resource_loading":
        return "resource_loading"
    return "runtime"


def diagnostic_source_for_problem(record: ProblemRecord) -> DiagnosticSource:
    """Preserve a recognized source, otherwise use the generic diagnostics one."""

    source = record.source or "diagnostics"
    if source in _DIAGNOSTIC_SOURCES:
        return cast(DiagnosticSource, source)
    return "diagnostics"


def _diagnostic_details(record: ProblemRecord) -> dict[str, object]:
    details: dict[str, object] = dict(record.details)
    details["problem_source"] = record.source
    details["recoverable"] = record.recoverable
    if record.mode is not None:
        details["mode"] = record.mode
    if record.run_id is not None:
        details["run_id"] = record.run_id
    if record.exception_type is not None:
        details["exception_type"] = record.exception_type
    if record.exception_message is not None:
        details["exception_message"] = record.exception_message
    return details


_DIAGNOSTIC_SOURCES = frozenset(
    {
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
    }
)


__all__ = [
    "DiagnosticPhaseResolver",
    "DiagnosticRecorder",
    "DiagnosticSourceResolver",
    "DiagnosticsProblemStore",
    "diagnostic_phase_for_problem",
    "diagnostic_source_for_problem",
    "problem_to_diagnostic",
]
