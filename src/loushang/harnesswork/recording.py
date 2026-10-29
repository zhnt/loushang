"""Versioned recording contracts and append-confirmed read models.

These models describe recorded Work facts, not current business validity or
external effects. No Transcript or artifact reader is involved.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Literal, cast

from loushang.harnesswork.event_log import EventLogEntry
from loushang.harnesswork.run_projection import WorkRunReplayError, _RunProjector
from loushang.harnesswork.types import WorkRecordingPolicy, WorkRun


class WorkRecordingUnavailable(RuntimeError):
    """An append or observer failed; this owner cannot confirm its records."""


class WorkRecordingFormatError(ValueError):
    """A run's recording contract cannot be interpreted safely."""


class WorkRecordingVersionError(WorkRecordingFormatError):
    """The requested or recorded contract version is unsupported."""


@dataclass(frozen=True)
class WorkRecordingContract:
    version: Literal[1]
    capture: Literal["published_facts"]
    retention: Literal["memory", "persistent", "unknown"]
    require_persistence: bool


@dataclass(frozen=True)
class WorkRecording:
    run: WorkRun
    contract: WorkRecordingContract | None
    basis: Literal["acknowledged", "loaded"]
    observed_sequence: int
    source_event_id: str | None


def _require_version(version: object) -> None:
    if type(version) is not int or version != 1:
        raise WorkRecordingVersionError("only recording version 1 is supported")


def _freeze_contract(
    backend: object,
    policy: WorkRecordingPolicy,
    override: WorkRecordingPolicy | None,
) -> WorkRecordingContract:
    if (
        override is not None
        and policy.require_persistence
        and not override.require_persistence
    ):
        raise ValueError("Work recording policy cannot weaken the Product requirement")
    effective = override or policy
    retention = getattr(backend, "recording_retention", "unknown")
    if retention not in ("memory", "persistent", "unknown"):
        raise ValueError("invalid backend recording_retention declaration")
    if effective.require_persistence and retention != "persistent":
        raise ValueError("recording policy requires a persistent backend")
    return WorkRecordingContract(
        version=1,
        capture="published_facts",
        retention=cast(Literal["memory", "persistent", "unknown"], retention),
        require_persistence=effective.require_persistence,
    )


def _encode_contract(contract: WorkRecordingContract) -> dict[str, object]:
    return {
        "version": contract.version,
        "capture": contract.capture,
        "retention": contract.retention,
        "require_persistence": contract.require_persistence,
    }


def _decode_contract(entry: EventLogEntry) -> WorkRecordingContract | None:
    metadata = entry.payload.get("_harnesswork", {})
    if not isinstance(metadata, Mapping):
        raise WorkRecordingFormatError("invalid Work recording metadata")
    if "recording" not in metadata:
        return None
    raw = metadata["recording"]
    if not isinstance(raw, Mapping):
        raise WorkRecordingFormatError("invalid Work recording contract")
    _require_version(raw.get("version"))
    if (
        set(raw) != {"version", "capture", "retention", "require_persistence"}
        or raw["capture"] != "published_facts"
        or raw["retention"] not in ("memory", "persistent", "unknown")
        or type(raw["require_persistence"]) is not bool
        or (raw["require_persistence"] and raw["retention"] != "persistent")
    ):
        raise WorkRecordingFormatError("invalid version 1 Work recording contract")
    return WorkRecordingContract(
        version=1,
        capture="published_facts",
        retention=cast(Literal["memory", "persistent", "unknown"], raw["retention"]),
        require_persistence=raw["require_persistence"],
    )


class _RecordingObserver:
    """Keep only small derived states, never a second copy of event bodies."""

    def __init__(self, entries: Iterable[EventLogEntry]) -> None:
        self._projector = _RunProjector()
        self._records: dict[str, WorkRecording] = {}
        self._errors: dict[str, tuple[type[ValueError], str]] = {}
        self._unavailable = False
        for entry in entries:
            self.observe(entry, basis="loaded")

    def invalidate(self) -> None:
        self._unavailable = True

    def observe(
        self,
        entry: EventLogEntry,
        *,
        basis: Literal["acknowledged", "loaded"] = "acknowledged",
    ) -> None:
        if self._unavailable or entry.run_id in self._errors:
            return
        try:
            self._projector.apply(entry)
            contract = (
                _decode_contract(entry)
                if entry.entry_type == "operation"
                else self._records[entry.run_id].contract
            )
        except (WorkRunReplayError, WorkRecordingFormatError) as error:
            # Append already succeeded. A read-model failure is not a write error.
            # Do not retain exception tracebacks and their event payloads.
            self._errors[entry.run_id] = (type(error), str(error))
            return
        self._records[entry.run_id] = WorkRecording(
            run=self._projector.states[entry.run_id].run,
            contract=contract,
            basis=basis,
            observed_sequence=entry.sequence,
            source_event_id=entry.event_id,
        )

    def get(self, run_id: str) -> WorkRecording | None:
        if self._unavailable:
            raise WorkRecordingUnavailable(
                "Work recording cannot be confirmed"
            ) from None
        if run_id in self._errors:
            error_type, message = self._errors[run_id]
            raise error_type(message) from None
        record = self._records.get(run_id)
        if (
            record is not None
            and record.basis == "loaded"
            and record.run.status in {"accepted", "running", "cancelling"}
        ):
            return replace(record, run=replace(record.run, status="orphaned"))
        return record


__all__ = [
    "WorkRecording",
    "WorkRecordingContract",
    "WorkRecordingFormatError",
    "WorkRecordingUnavailable",
    "WorkRecordingVersionError",
]
