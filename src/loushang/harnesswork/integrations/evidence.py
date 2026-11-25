"""Session artifact evidence over the original Work log and plan projection."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar

from loushang.harness.artifacts.references import (
    SessionBlobRef,
    session_blob_authority_id,
)
from loushang.harnesswork.event_log import EventLogEntry
from loushang.harnesswork.plan_projection import project_work_plan_runs
from loushang.harnesswork.run_projection import project_work_runs
from loushang.harnesswork.types import WorkEventFact

_KIND = "WorkEvidenceReported"


@dataclass(frozen=True)
class EvidenceRecord:
    operation_id: str
    run_id: str
    session_id: str
    sequence: int
    event_id: str | None
    role: str
    reported_step_id: str | None
    blob: SessionBlobRef

    @property
    def key(self) -> tuple[str, int]:
        return self.run_id, self.sequence


@dataclass(frozen=True)
class SupportReference:
    """An existing deviation edge, not an additional independent proof."""

    run_id: str
    step_id: str
    reference: str
    target: tuple[str, int] | None


RecordT = TypeVar("RecordT", bound=EvidenceRecord)
SupportT = TypeVar("SupportT", bound=SupportReference)


class WorkEvidenceCodec(Generic[RecordT, SupportT]):
    """Use the shared evidence wire format and preserve Product value types."""

    def __init__(
        self,
        record_type: type[RecordT],
        support_type: type[SupportT],
        *,
        invalid: type[ValueError],
        unsupported_version: type[ValueError],
        invalid_kind_message: str,
    ) -> None:
        self._record_type = record_type
        self._support_type = support_type
        self._invalid = invalid
        self._unsupported_version = unsupported_version
        self._invalid_kind_message = invalid_kind_message

    def _labels(self, role: object, step: object) -> None:
        if (
            not isinstance(role, str)
            or not role
            or len(role) > 128
            or any(unicodedata.category(char) == "Cc" for char in role)
        ):
            raise self._invalid("invalid evidence role")
        if step is not None and (not isinstance(step, str) or not step):
            raise self._invalid("invalid reported step")


    def work_evidence_fact(
        self, blob: SessionBlobRef, *, role: str, reported_step_id: str | None = None
    ) -> WorkEventFact:
        self._labels(role, reported_step_id)
        if not isinstance(blob, SessionBlobRef):
            raise self._invalid("evidence requires a SessionBlobRef")
        return WorkEventFact(
            kind=_KIND,
            payload={
                "evidence": {
                    "version": 1,
                    "role": role,
                    "reported_step_id": reported_step_id,
                    "blob": blob.manifest_entry(),
                }
            },
        )


    def validate_evidence_fact(
        self, fact: WorkEventFact, *, session_id: str
    ) -> tuple[str, str | None, SessionBlobRef]:
        """Validate before publish; generic Work publication remains unchanged."""
        if fact.kind != _KIND:
            raise self._invalid(self._invalid_kind_message)
        return self._decode_payload(fact.payload, session_id=session_id)


    def _decode_payload(
        self, payload: object, *, session_id: str
    ) -> tuple[str, str | None, SessionBlobRef]:
        if not isinstance(payload, Mapping):
            raise self._invalid("evidence payload must be an object")
        value = payload.get("evidence")
        if not isinstance(value, Mapping):
            raise self._invalid("evidence must be an object")
        version = value.get("version")
        if type(version) is not int or version < 1:
            raise self._invalid("invalid evidence version")
        if version > 1:
            raise self._unsupported_version("unsupported evidence version")
        if set(payload) != {"evidence"}:
            raise self._invalid("v1 evidence payload has unexpected top-level keys")
        if not {"version", "role", "reported_step_id", "blob"} <= value.keys():
            raise self._invalid("v1 evidence fields are missing")
        role, step = value["role"], value["reported_step_id"]
        self._labels(role, step)
        raw_blob = value["blob"]
        if not isinstance(raw_blob, Mapping):
            raise self._invalid("evidence blob must be an object")
        try:
            blob = SessionBlobRef.from_manifest_entry(raw_blob)
            authority = session_blob_authority_id(session_id)
        except (TypeError, ValueError) as error:
            raise self._invalid(
                "invalid evidence blob or Session authority"
            ) from error
        if blob.session_id != authority:
            raise self._invalid("evidence belongs to another Session authority")
        # _labels validates both values; keep the return narrowing explicit.
        assert isinstance(role, str)
        assert step is None or isinstance(step, str)
        return role, step, blob


    def project_work_evidence(
        self, entries: Iterable[EventLogEntry],
    ) -> tuple[RecordT, ...]:
        history = tuple(entries)
        project_work_runs(history)  # Original lifecycle errors retain precedence.
        records: list[RecordT] = []
        for entry in history:
            if entry.entry_type != "event" or entry.payload.get("kind") != _KIND:
                continue
            role, step, blob = self._decode_payload(
                entry.payload.get("payload"), session_id=entry.session_id
            )
            records.append(
                self._record_type(
                    operation_id=entry.operation_id,
                    run_id=entry.run_id,
                    session_id=entry.session_id,
                    sequence=entry.sequence,
                    event_id=entry.event_id,
                    role=role,
                    reported_step_id=step,
                    blob=blob,
                )
            )
        return tuple(records)


    def deviation_support(
        self, entries: Iterable[EventLogEntry],
        records: Iterable[EvidenceRecord],
        *,
        bindings: Mapping[str, tuple[str, int]] | None = None,
    ) -> tuple[SupportT, ...]:
        """Preserve legacy edges; resolve only caller-supplied explicit bindings.

        No path/URI/digest inference and no second report registration. Project
        each run independently because Method plan ids may repeat across runs.
        """
        history = tuple(entries)
        project_work_runs(history)
        keys = {record.key for record in records}
        grouped: dict[str, list[EventLogEntry]] = {}
        for entry in history:
            grouped.setdefault(entry.run_id, []).append(entry)
        result: list[SupportT] = []
        for run_id, run_entries in grouped.items():
            for plan in project_work_plan_runs(run_entries):
                for step in plan.steps:
                    if step.deviation is None:
                        continue
                    for reference in step.deviation.evidence_refs:
                        target = bindings.get(reference) if bindings is not None else None
                        result.append(
                            self._support_type(
                                run_id,
                                step.step_id,
                                reference,
                                target if target in keys else None,
                            )
                        )
        return tuple(result)
