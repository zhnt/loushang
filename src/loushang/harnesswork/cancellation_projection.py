"""Read cancellation observations without changing Work lifecycle replay."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal, cast

from loushang.harnesswork.event_log import EventLogEntry
from loushang.harnesswork.run_projection import project_work_runs
from loushang.harnesswork.types import WorkCancellationRecord, WorkCancellationStatus

_OWNER_KEY = "_harnesswork"
_VERSION_KEY = "cancellation_observation_version"
_TERMINAL_KINDS = {"WorkRunCompleted", "WorkRunFailed", "WorkRunCancelled"}


class WorkCancellationReplayError(ValueError):
    """A supported cancellation observation is malformed or contradictory."""


def project_work_cancellations(
    entries: Iterable[EventLogEntry],
) -> tuple[WorkCancellationRecord, ...]:
    """Project a complete single-writer history in operation insertion order.

    Lifecycle validation takes precedence over observation decoding. Legacy,
    future-version and incomplete histories give unknown observations, never a
    guessed successful cancellation.
    """

    history = tuple(entries)
    project_work_runs(history)
    grouped: dict[str, list[EventLogEntry]] = {}
    for entry in history:
        grouped.setdefault(entry.run_id, []).append(entry)
    return tuple(_project_run(run_entries) for run_entries in grouped.values())


def _project_run(entries: list[EventLogEntry]) -> WorkCancellationRecord:
    operation, last = entries[0], entries[-1]
    if _OWNER_KEY not in operation.payload:
        return _unknown(last, "legacy_unrecorded")
    owner = operation.payload[_OWNER_KEY]
    if not isinstance(owner, Mapping):
        raise WorkCancellationReplayError("operation owner metadata must be an object")
    if _VERSION_KEY not in owner:
        return _unknown(last, "legacy_unrecorded")
    version = owner[_VERSION_KEY]
    if type(version) is not int or version < 1:
        raise WorkCancellationReplayError("invalid cancellation observation version")
    if version > 1:
        return _unknown(last, "unsupported_version")
    if last.entry_type != "event" or last.payload.get("kind") not in _TERMINAL_KINDS:
        return _unknown(last, "incomplete_history")
    return _decode_terminal(
        last,
        cancellation_started=any(
            entry.payload.get("kind") == "WorkRunCancelling" for entry in entries[1:]
        ),
    )


def _unknown(entry: EventLogEntry, reason: str) -> WorkCancellationRecord:
    return WorkCancellationRecord(
        operation_id=entry.operation_id,
        run_id=entry.run_id,
        session_id=entry.session_id,
        status="unknown",
        reason_code=reason,
        reported_status=None,
        basis="journal",
        observed_sequence=entry.sequence,
        source_event_id=entry.event_id,
    )


def _decode_terminal(
    entry: EventLogEntry, *, cancellation_started: bool
) -> WorkCancellationRecord:
    owner = entry.payload.get(_OWNER_KEY)
    value = owner.get("cancellation") if isinstance(owner, Mapping) else None
    if not isinstance(value, Mapping):
        raise WorkCancellationReplayError("terminal cancellation must be an object")
    if type(value.get("version")) is not int or value["version"] != 1:
        raise WorkCancellationReplayError("terminal cancellation version must be 1")
    if not {"status", "reason_code", "reported_status"} <= value.keys():
        raise WorkCancellationReplayError("terminal cancellation fields are missing")
    status, reason, report = (
        value["status"],
        value["reason_code"],
        value["reported_status"],
    )
    if (
        not isinstance(status, str)
        or not isinstance(reason, str)
        or (report is not None and not isinstance(report, str))
    ):
        raise WorkCancellationReplayError("invalid cancellation field types")
    kind = entry.payload.get("kind")
    valid = False
    if not cancellation_started:
        valid = (status, reason, report) == (
            "not_requested",
            "none",
            None,
        ) and kind in {"WorkRunCompleted", "WorkRunFailed"}
    elif kind == "WorkRunCancelled":
        valid = (status, reason, report) in {
            ("settled", "domain_reported", "settled"),
            ("unsupported", "domain_reported", "unsupported"),
            ("unsupported", "no_capability", None),
            ("unknown", "executor_interrupted", None),
            ("unknown", "cancellation_not_driven", None),
        }
    elif kind == "WorkRunFailed" and status == "failed":
        valid = (
            (reason == "domain_failure" and report == "failed")
            or (reason in {"domain_exception", "invalid_return"} and report is None)
            or (
                reason in {"domain_timeout", "execution_timeout"}
                and report in {None, "settled", "unsupported", "failed"}
            )
        )
    if not valid:
        raise WorkCancellationReplayError("cancellation contradicts terminal lifecycle")
    return WorkCancellationRecord(
        operation_id=entry.operation_id,
        run_id=entry.run_id,
        session_id=entry.session_id,
        status=cast(
            Literal["not_requested", "settled", "unsupported", "failed", "unknown"],
            status,
        ),
        reason_code=reason,
        reported_status=cast(WorkCancellationStatus | None, report),
        basis="journal",
        observed_sequence=entry.sequence,
        source_event_id=entry.event_id,
    )


__all__ = ["WorkCancellationReplayError", "project_work_cancellations"]
