"""Read and publish verification evidence using the existing Session and Work owners."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import ClassVar, Protocol, TypeVar

from loushang.harness.artifacts import (
    SessionBlobHealth,
    SessionBlobStore,
)
from loushang.harness.artifacts.references import session_blob_authority_id
from loushang.harness.session.bash import (
    _execute_bash_with_complete_error,
    bash_verification_output_refs,
    build_bash_verification_report,
    check_bash_verification_report,
)
from loushang.harnesswork.event_log import EventLogBackend, EventLogEntry
from loushang.harnesswork.ports import WorkExecutionContext
from loushang.harnesswork.run_projection import project_work_runs
from loushang.harnesswork.runtime import UnknownWorkRunError
from loushang.harnesswork.types import (
    WorkCancellationOutcome,
    WorkOperation,
    WorkRun,
)

from .evidence import EvidenceRecord, SupportReference, WorkEvidenceCodec


@dataclass(frozen=True)
class VerificationProfile:
    operation: str
    domain: str
    output_kind: str
    output_source: str
    evidence_kind_prefix: str
    evidence_source: str
    wrong_run: str
    invalid_document: str


class _VerificationSession(Protocol):
    @property
    def session_id(self) -> str: ...

    async def execute_bash(
        self, command: str, **options: object
    ) -> dict[str, object]: ...


def _json_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, allow_nan=False
    ).encode("utf-8")


def _document(content: bytes, profile: VerificationProfile) -> dict[str, object]:
    value = json.loads(content)
    if (
        not isinstance(value, dict)
        or type(value.get("version")) is not int
        or value["version"] != 1
    ):
        raise ValueError(profile.invalid_document)
    return value


@dataclass(frozen=True)
class VerificationEvidence:
    run: WorkRun
    records: tuple[EvidenceRecord, ...]
    health: tuple[SessionBlobHealth, ...]
    support: tuple[SupportReference, ...]
    passed: bool | None
    issues: tuple[str, ...]


VerificationEvidenceT = TypeVar("VerificationEvidenceT", bound=VerificationEvidence)


def inspect_verification(
    profile: VerificationProfile,
    codec: WorkEvidenceCodec,
    result_type: type[VerificationEvidenceT],
    entries: Iterable[EventLogEntry],
    *,
    run_id: str,
    blobs: SessionBlobStore,
    support_bindings: Mapping[str, tuple[str, int]] | None = None,
) -> VerificationEvidenceT:
    """Consume log associations and reread the retained documents and outputs.

    Missing bytes produce no verdict; a failed command produces False. Byte
    availability and document validity remain separate. Busy/I/O races propagate
    through the original store rather than turning a stale preview into success.
    """
    history = tuple(entries)
    runs = project_work_runs(history)
    run = next((item for item in runs if item.run_id == run_id), None)
    if run is None:
        raise UnknownWorkRunError(f"unknown work run: {run_id}")
    selected = tuple(entry for entry in history if entry.run_id == run_id)
    if selected[0].payload.get("kind") != profile.operation or run.domain != profile.domain:
        raise ValueError(profile.wrong_run)
    if blobs.session_id != session_blob_authority_id(run.session_id):
        raise ValueError("verification reader belongs to another Session")
    records = codec.project_work_evidence(selected)
    support = codec.deviation_support(selected, records, bindings=support_bindings)
    health = blobs.inspect(record.blob for record in records)
    roles = {
        role: tuple(r for r in records if r.role == role)
        for role in ("report", "validation")
    }
    issues = [
        f"{role}_missing_or_ambiguous"
        for role, values in roles.items()
        if len(values) != 1
    ]
    if any(item.state != "available" for item in health):
        issues.append("evidence_unavailable")
    if issues:
        return result_type(run, records, health, support, None, tuple(issues))
    report_ref, validation_ref = roles["report"][0].blob, roles["validation"][0].blob
    report_content = blobs.read_bytes(report_ref)
    validation_content = blobs.read_bytes(validation_ref)
    try:
        report = _document(report_content, profile)
        validation = _document(validation_content, profile)
        outputs = bash_verification_output_refs(report)
    except (ValueError, TypeError, KeyError):
        return result_type(
            run, records, health, support, None, ("invalid_verification_document",)
        )
    output_health = blobs.inspect(outputs)
    health = (*health, *output_health)
    if any(item.state != "available" for item in output_health):
        return result_type(
            run, records, health, support, None, ("output_unavailable",)
        )
    expected = check_bash_verification_report(blobs, report, outputs)
    operation_payload = selected[0].payload.get("payload")
    command = (
        operation_payload.get("command")
        if isinstance(operation_payload, Mapping)
        else None
    )
    consistent = (
        isinstance(command, str)
        and bool(command.strip())
        and report.get("command") == command
        and validation.get("report_sha256") == report_ref.sha256
        and type(validation.get("passed")) is bool
        and validation["passed"] == expected
    )
    if not consistent:
        return result_type(
            run, records, health, support, None, ("verification_mismatch",)
        )
    # A reported success before cancellation or a failed terminal is not success.
    passed = expected if not expected or run.status == "completed" else None
    return result_type(
        run,
        records,
        health,
        support,
        passed,
        () if passed is not None else ("work_not_completed",),
    )


class VerificationExecutor:
    """One explicitly bound Session/Blob authority and single Work log writer."""

    _profile: ClassVar[VerificationProfile]
    _evidence: ClassVar[WorkEvidenceCodec]
    _failure: ClassVar[type[RuntimeError]]

    def __init__(
        self,
        *,
        session: _VerificationSession,
        blobs: SessionBlobStore,
        event_log: EventLogBackend,
        cancel_command: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        if blobs.session_id != session_blob_authority_id(session.session_id):
            raise ValueError("verification writer belongs to another Session")
        self._session = session
        self._blobs = blobs
        self._log = event_log
        self._cancel_command = cancel_command

    async def cancel_and_wait(self, operation, context) -> WorkCancellationOutcome:
        if self._cancel_command is None:
            return WorkCancellationOutcome.unsupported()
        if operation.session_id != self._session.session_id:
            raise ValueError("verification cancellation Session changed")
        await self._cancel_command()
        return WorkCancellationOutcome.settled()

    async def execute(
        self, operation: WorkOperation, context: WorkExecutionContext
    ) -> None:
        if (
            operation.kind != self._profile.operation
            or operation.domain != self._profile.domain
            or operation.session_id != self._session.session_id
        ):
            raise ValueError("verification Session or operation changed")
        if context.step_id == "report":
            command = operation.payload["command"]
            if not isinstance(command, str):
                raise ValueError("invalid verification command")
            options = operation.payload.get("execution", {})
            if not isinstance(options, Mapping) or set(options) - {
                "stdin",
                "cwd",
                "env",
            }:
                raise ValueError("invalid verification execution options")
            result = await _execute_bash_with_complete_error(
                self._session, command, options
            )
            if operation.session_id != self._session.session_id:
                raise ValueError("verification Session changed during command")
            report = build_bash_verification_report(
                command,
                result,
                blobs=self._blobs,
                output_kind=self._profile.output_kind,
                output_source=self._profile.output_source,
            )
            self._publish(_json_bytes(report), "report", operation, context)
        elif context.step_id == "validation":
            reports = tuple(
                record
                for record in self._evidence.project_work_evidence(
                    self._log.query(run_id=context.run_id)
                )
                if record.role == "report"
            )
            if len(reports) != 1:
                raise self._failure(
                    "verification report is missing or ambiguous"
                )
            report_ref = reports[0].blob
            report = _document(self._blobs.read_bytes(report_ref), self._profile)
            passed = check_bash_verification_report(
                self._blobs, report, bash_verification_output_refs(report)
            )
            validation = {
                "version": 1,
                "report_sha256": report_ref.sha256,
                "passed": passed,
            }
            self._publish(_json_bytes(validation), "validation", operation, context)
            if not passed:
                raise self._failure(
                    "command or retained output did not pass verification"
                )
        else:
            raise ValueError("unknown verification step")

    def _publish(
        self,
        content: bytes,
        role: str,
        operation: WorkOperation,
        context: WorkExecutionContext,
    ) -> None:
        if operation.session_id != self._session.session_id:
            raise ValueError("verification Session changed during execution")
        blob = self._blobs.put_bytes(
            content,
            logical_name=f"verification/{role}.json",
            kind=f"{self._profile.evidence_kind_prefix}{role}",
            media_type="application/json",
            source=self._profile.evidence_source,
        )
        self._blobs.read_bytes(blob)
        fact = self._evidence.work_evidence_fact(blob, role=role, reported_step_id=context.step_id)
        self._evidence.validate_evidence_fact(fact, session_id=operation.session_id)
        context.publish(fact)
