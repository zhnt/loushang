from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from loushang.harness.diagnostics.types import (
    DiagnosticDraft,
    DiagnosticLevel,
    DiagnosticPhase,
    DiagnosticRecord,
    DiagnosticSource,
    DiagnosticsQuery,
    DiagnosticSummary,
    ErrorReport,
    StartupCheck,
    StartupCheckResult,
    directory_available_startup_check,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class DiagnosticsService:
    def __init__(self, *, max_records: int = 200) -> None:
        self._max_records = max_records
        self._records: list[DiagnosticRecord] = []

    def record(self, diagnostic: DiagnosticRecord) -> DiagnosticRecord:
        normalized = _with_fingerprint(diagnostic)
        existing_index = _find_duplicate_index(self._records, normalized)
        if existing_index is not None:
            existing = self._records[existing_index]
            stored = replace(
                existing,
                timestamp=normalized.timestamp,
                occurrence_count=existing.occurrence_count + normalized.occurrence_count,
            )
            self._records[existing_index] = stored
        else:
            stored = normalized
            self._records.append(stored)
        if len(self._records) > self._max_records:
            self._records = self._records[-self._max_records :]
        return stored

    def record_many(self, diagnostics: Iterable[DiagnosticRecord]) -> None:
        for diagnostic in diagnostics:
            self.record(diagnostic)

    def normalize_diagnostic(
        self,
        diagnostic: DiagnosticDraft,
        *,
        phase: DiagnosticPhase,
        source: DiagnosticSource,
        session_id: str | None = None,
        entry_id: str | None = None,
        level: DiagnosticLevel = "warning",
        details: Mapping[str, object] | None = None,
    ) -> DiagnosticRecord:
        merged_details = dict(diagnostic.details)
        if details:
            merged_details.update(details)
        return DiagnosticRecord(
            type=level,
            code=diagnostic.code,
            message=diagnostic.message,
            phase=phase,
            source=source,
            timestamp=_now_iso(),
            session_id=session_id,
            entry_id=entry_id,
            source_path=diagnostic.source_path,
            details=merged_details,
        )

    def record_drafts(
        self,
        diagnostics: Iterable[DiagnosticDraft],
        *,
        phase: DiagnosticPhase,
        source: DiagnosticSource,
        session_id: str | None = None,
        entry_id: str | None = None,
        level: DiagnosticLevel = "warning",
    ) -> list[DiagnosticRecord]:
        """Normalize and record diagnostic drafts with one shared scope."""

        records = [
            self.normalize_diagnostic(
                diagnostic,
                phase=phase,
                source=source,
                session_id=session_id,
                entry_id=entry_id,
                level=level,
            )
            for diagnostic in diagnostics
        ]
        self.record_many(records)
        return records

    def normalize_exception(
        self,
        *,
        code: str,
        exc: Exception | str,
        phase: DiagnosticPhase,
        source: DiagnosticSource,
        level: DiagnosticLevel = "error",
        session_id: str | None = None,
        entry_id: str | None = None,
        source_path=None,
        details: dict[str, object] | None = None,
    ) -> DiagnosticRecord:
        message = str(exc)
        return DiagnosticRecord(
            type=level,
            code=code,
            message=message,
            phase=phase,
            source=source,
            timestamp=_now_iso(),
            session_id=session_id,
            entry_id=entry_id,
            source_path=source_path,
            details=details or {},
        )

    def normalize_error(
        self,
        *,
        code: str,
        error: Exception | str,
        phase: DiagnosticPhase,
        source: DiagnosticSource,
        level: DiagnosticLevel = "error",
        session_id: str | None = None,
        entry_id: str | None = None,
        source_path=None,
        details: dict[str, object] | None = None,
    ) -> DiagnosticRecord:
        return self.normalize_exception(
            code=code,
            exc=error,
            phase=phase,
            source=source,
            level=level,
            session_id=session_id,
            entry_id=entry_id,
            source_path=source_path,
            details=details,
        )

    def capture_failure(
        self,
        *,
        code: str,
        error: Exception | str,
        phase: DiagnosticPhase,
        source: DiagnosticSource,
        level: DiagnosticLevel = "error",
        session_id: str | None = None,
        entry_id: str | None = None,
        source_path=None,
        details: dict[str, object] | None = None,
    ) -> DiagnosticRecord:
        record = self.normalize_error(
            code=code,
            error=error,
            phase=phase,
            source=source,
            level=level,
            session_id=session_id,
            entry_id=entry_id,
            source_path=source_path,
            details=details,
        )
        return self.record(record)

    def normalize_startup_check_result(
        self,
        result: StartupCheckResult,
        *,
        session_id: str | None = None,
        entry_id: str | None = None,
    ) -> DiagnosticRecord:
        level = result.level
        if level is None:
            level = "info" if result.ok else "error"
        code = result.code
        if code is None:
            code = "startup_check_passed" if result.ok else "startup_check_failed"
        message = result.message
        if not message:
            status = "passed" if result.ok else "failed"
            message = f"Startup check '{result.name}' {status}."
        details = {"check": result.name, "ok": result.ok}
        details.update(result.details)
        return DiagnosticRecord(
            type=level,
            code=code,
            message=message,
            phase="startup",
            source=result.source,
            timestamp=_now_iso(),
            session_id=session_id,
            entry_id=entry_id,
            source_path=result.source_path,
            details=details,
        )

    def run_startup_checks(
        self,
        checks: Iterable[StartupCheck],
        *,
        session_id: str | None = None,
        entry_id: str | None = None,
    ) -> list[DiagnosticRecord]:
        records: list[DiagnosticRecord] = []
        for index, check in enumerate(checks, start=1):
            check_name = getattr(check, "__name__", f"startup_check_{index}")
            try:
                result = check()
            except Exception as exc:
                record = self.normalize_error(
                    code="startup_check_exception",
                    error=exc,
                    phase="startup",
                    source="diagnostics",
                    session_id=session_id,
                    entry_id=entry_id,
                    details={"check": check_name, "exception_type": type(exc).__name__},
                )
            else:
                if result is None:
                    continue
                if isinstance(result, DiagnosticRecord):
                    record = result
                else:
                    record = self.normalize_startup_check_result(
                        result,
                        session_id=session_id,
                        entry_id=entry_id,
                    )
            records.append(self.record(record))
        return records
    def get_last_diagnostics(self, limit: int = 50) -> list[DiagnosticRecord]:
        if limit <= 0:
            return []
        return list(self._records[-limit:])

    def get_diagnostics(
        self,
        *,
        phase: DiagnosticPhase | None = None,
        source: DiagnosticSource | None = None,
        type: DiagnosticLevel | None = None,
        session_id: str | None = None,
        entry_id: str | None = None,
        code: str | None = None,
        limit: int | None = None,
        query: DiagnosticsQuery | None = None,
    ) -> list[DiagnosticRecord]:
        if query is not None:
            phase = query.phase if query.phase is not None else phase
            source = query.source if query.source is not None else source
            type = query.level if query.level is not None else type
            session_id = query.session_id if query.session_id is not None else session_id
            entry_id = query.entry_id if query.entry_id is not None else entry_id
            code = query.code if query.code is not None else code
            limit = query.limit if query.limit is not None else limit
            tool_call_id = query.tool_call_id
        else:
            tool_call_id = None

        diagnostics = list(self._records)
        if phase is not None:
            diagnostics = [record for record in diagnostics if record.phase == phase]
        if source is not None:
            diagnostics = [record for record in diagnostics if record.source == source]
        if type is not None:
            diagnostics = [record for record in diagnostics if record.type == type]
        if session_id is not None:
            diagnostics = [record for record in diagnostics if record.session_id == session_id]
        if entry_id is not None:
            diagnostics = [record for record in diagnostics if record.entry_id == entry_id]
        if tool_call_id is not None:
            diagnostics = [record for record in diagnostics if _diagnostic_tool_call_id(record) == tool_call_id]
        if code is not None:
            diagnostics = [record for record in diagnostics if record.code == code]
        if limit is not None:
            if limit <= 0:
                return []
            diagnostics = diagnostics[-limit:]
        return diagnostics

    def get_last_error_report(self) -> ErrorReport | None:
        errors = [record for record in self._records if record.type == "error"]
        if not errors:
            return None
        primary = errors[-1]
        related = tuple(_dedupe_related(record for record in self._records if record is not primary))
        return ErrorReport(primary=primary, related=related)

    def get_diagnostics_summary(self, query: DiagnosticsQuery | None = None) -> DiagnosticSummary:
        records = self.get_diagnostics(query=query)
        return _summarize_diagnostics(records)

    def clear_runtime_diagnostics(self) -> None:
        self._records = [record for record in self._records if record.phase != "runtime"]


def run_standard_startup_checks(
    diagnostics_service: DiagnosticsService,
    *,
    cwd: str,
    package_roots: Iterable[str] = (),
    additional_checks: Iterable[StartupCheck] = (),
    session_id: str | None = None,
) -> list[DiagnosticRecord]:
    """Run the shared cwd and package-root startup checks."""

    cwd_path = Path(cwd).expanduser()
    checks = [
        directory_available_startup_check(
            name="cwd",
            path=cwd_path,
            code="cwd_unavailable",
            message=f"Session cwd is not an available directory: {cwd_path}",
            detail_key="cwd",
        ),
        *(
            directory_available_startup_check(
                name="package_root",
                path=Path(root).expanduser(),
                code="package_root_unavailable",
                message=(
                    "Package root is not an available directory: "
                    f"{Path(root).expanduser()}"
                ),
                detail_key="package_root",
            )
            for root in package_roots
        ),
        *additional_checks,
    ]
    return diagnostics_service.run_startup_checks(checks, session_id=session_id)


def _with_fingerprint(record: DiagnosticRecord) -> DiagnosticRecord:
    if record.fingerprint:
        return record
    return replace(record, fingerprint=_diagnostic_fingerprint(record))


def _find_duplicate_index(records: list[DiagnosticRecord], record: DiagnosticRecord) -> int | None:
    for index in range(len(records) - 1, -1, -1):
        candidate = records[index]
        if candidate.fingerprint == record.fingerprint:
            return index
    return None


def _dedupe_related(records: Iterable[DiagnosticRecord]) -> list[DiagnosticRecord]:
    seen: set[str] = set()
    deduped: list[DiagnosticRecord] = []
    for record in records:
        normalized = _with_fingerprint(record)
        fingerprint = normalized.fingerprint or ""
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(normalized)
    return deduped


def _diagnostic_tool_call_id(record: DiagnosticRecord) -> str | None:
    value = record.details.get("tool_call_id", record.details.get("toolCallId"))
    return value if isinstance(value, str) else None


def _summarize_diagnostics(records: list[DiagnosticRecord]) -> DiagnosticSummary:
    by_code: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_phase: dict[str, int] = {}
    latest_error: DiagnosticRecord | None = None
    error_count = 0
    warning_count = 0
    info_count = 0

    for record in records:
        occurrences = max(record.occurrence_count, 1)
        by_code[record.code] = by_code.get(record.code, 0) + occurrences
        by_source[record.source] = by_source.get(record.source, 0) + occurrences
        by_phase[record.phase] = by_phase.get(record.phase, 0) + occurrences
        if record.type == "error":
            error_count += occurrences
            latest_error = record
        elif record.type == "warning":
            warning_count += occurrences
        elif record.type == "info":
            info_count += occurrences

    return DiagnosticSummary(
        total_count=error_count + warning_count + info_count,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        by_code=by_code,
        by_source=by_source,
        by_phase=by_phase,
        latest_error=latest_error,
    )


def _diagnostic_fingerprint(record: DiagnosticRecord) -> str:
    payload = {
        "type": record.type,
        "code": record.code,
        "message": record.message,
        "phase": record.phase,
        "source": record.source,
        "session_id": record.session_id,
        "source_path": str(record.source_path) if record.source_path is not None else None,
        "details": _json_safe(record.details),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_safe(value: object) -> object:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        if isinstance(value, dict):
            return {str(key): _json_safe(item) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return [_json_safe(item) for item in value]
        return repr(value)
    return value


__all__ = ["DiagnosticsService"]
