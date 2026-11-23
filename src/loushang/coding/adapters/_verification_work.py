"""Opt-in local Coding SDK verification, using the existing Work executor.

This private Product adapter has no model loop, queue, storage root selection or
remote event binding. Its verdict describes one command, never a completed Goal.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from loushang.coding.adapters._work_evidence import (
    EvidenceRecord,
    SupportReference,
    deviation_support,
    project_work_evidence,
    validate_evidence_fact,
    work_evidence_fact,
)
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
from loushang.harnesswork.runtime import UnknownWorkRunError, WorkRuntime
from loushang.harnesswork.types import (
    WorkCancellationOutcome,
    WorkOperation,
    WorkRun,
    WorkRunSpec,
    WorkStepSpec,
)

_OPERATION = "VerifyCodingCommand"


class CodingVerificationFailed(RuntimeError):
    """The command or its required evidence failed verification."""


class _CodingSession(Protocol):
    @property
    def session_id(self) -> str: ...

    async def execute_bash(
        self, command: str, **options: object
    ) -> dict[str, object]: ...


def _json_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, allow_nan=False
    ).encode("utf-8")


def _document(content: bytes) -> dict[str, object]:
    value = json.loads(content)
    if (
        not isinstance(value, dict)
        or type(value.get("version")) is not int
        or value["version"] != 1
    ):
        raise ValueError("invalid Coding verification document")
    return value


@dataclass(frozen=True)
class VerificationEvidence:
    run: WorkRun
    records: tuple[EvidenceRecord, ...]
    health: tuple[SessionBlobHealth, ...]
    support: tuple[SupportReference, ...]
    passed: bool | None
    issues: tuple[str, ...]


def inspect_verification(
    entries: Iterable[EventLogEntry],
    *,
    run_id: str,
    blobs: SessionBlobStore,
    support_bindings: Mapping[str, tuple[str, int]] | None = None,
) -> VerificationEvidence:
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
    if selected[0].payload.get("kind") != _OPERATION or run.domain != "coding":
        raise ValueError("run is not a Coding verification")
    if blobs.session_id != session_blob_authority_id(run.session_id):
        raise ValueError("verification reader belongs to another Session")
    records = project_work_evidence(selected)
    support = deviation_support(selected, records, bindings=support_bindings)
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
        return VerificationEvidence(run, records, health, support, None, tuple(issues))
    report_ref, validation_ref = roles["report"][0].blob, roles["validation"][0].blob
    report_content = blobs.read_bytes(report_ref)
    validation_content = blobs.read_bytes(validation_ref)
    try:
        report = _document(report_content)
        validation = _document(validation_content)
        outputs = bash_verification_output_refs(report)
    except (ValueError, TypeError, KeyError):
        return VerificationEvidence(
            run, records, health, support, None, ("invalid_verification_document",)
        )
    output_health = blobs.inspect(outputs)
    health = (*health, *output_health)
    if any(item.state != "available" for item in output_health):
        return VerificationEvidence(
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
        return VerificationEvidence(
            run, records, health, support, None, ("verification_mismatch",)
        )
    # A reported success before cancellation or a failed terminal is not success.
    passed = expected if not expected or run.status == "completed" else None
    return VerificationEvidence(
        run,
        records,
        health,
        support,
        passed,
        () if passed is not None else ("work_not_completed",),
    )


class CodingVerificationExecutor:
    """One explicitly bound Session/Blob authority and single Work log writer."""

    def __init__(
        self,
        *,
        session: _CodingSession,
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
            operation.kind != _OPERATION
            or operation.domain != "coding"
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
                output_kind="coding-sdk-output",
                output_source="coding-sdk:command-result",
            )
            self._publish(_json_bytes(report), "report", operation, context)
        elif context.step_id == "validation":
            reports = tuple(
                record
                for record in project_work_evidence(
                    self._log.query(run_id=context.run_id)
                )
                if record.role == "report"
            )
            if len(reports) != 1:
                raise CodingVerificationFailed(
                    "verification report is missing or ambiguous"
                )
            report_ref = reports[0].blob
            report = _document(self._blobs.read_bytes(report_ref))
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
                raise CodingVerificationFailed(
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
            kind=f"coding-{role}",
            media_type="application/json",
            source="coding-sdk:verification",
        )
        self._blobs.read_bytes(blob)
        fact = work_evidence_fact(blob, role=role, reported_step_id=context.step_id)
        validate_evidence_fact(fact, session_id=operation.session_id)
        context.publish(fact)


class CodingVerificationWork(CodingVerificationExecutor):
    """Standalone convenience wrapper; shared compositions borrow only executor."""

    def __init__(
        self,
        *,
        session: _CodingSession,
        blobs: SessionBlobStore,
        event_log: EventLogBackend,
    ) -> None:
        super().__init__(session=session, blobs=blobs, event_log=event_log)
        self.runtime = WorkRuntime(executor=self, event_log=event_log)

    async def run(
        self,
        command: str,
        *,
        operation_id: str | None = None,
        run_id: str | None = None,
    ) -> WorkRun:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("verification command must be non-empty")
        operation_id = operation_id or f"coding-verification-{uuid4().hex}"
        run = await self.runtime.accept(
            WorkOperation(
                operation_id,
                _OPERATION,
                self._session.session_id,
                "coding",
                {"command": command},
            ),
            spec=WorkRunSpec(
                run_id=run_id,
                plan_id=f"verification:{operation_id}",
                steps=(WorkStepSpec("report"), WorkStepSpec("validation")),
            ),
        )
        return await self.runtime.wait(run.run_id)
