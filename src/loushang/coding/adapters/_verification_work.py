"""Opt-in local Coding SDK verification, using the existing Work executor.

This private Product adapter has no model loop, queue, storage root selection or
remote event binding. Its verdict describes one command, never a completed Goal.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import uuid4

from loushang.agent.types import AgentToolResult, TextPart
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
    SessionBlobRef,
    SessionBlobStore,
)
from loushang.harness.artifacts.references import session_blob_authority_id
from loushang.harness.session.bash import bash_result_from_tool_result
from loushang.harnesswork.event_log import EventLogBackend, EventLogEntry
from loushang.harnesswork.ports import WorkExecutionContext
from loushang.harnesswork.run_projection import project_work_runs
from loushang.harnesswork.runtime import UnknownWorkRunError, WorkRuntime
from loushang.harnesswork.types import WorkOperation, WorkRun, WorkRunSpec, WorkStepSpec

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


def _output_refs(report: Mapping[str, object]) -> tuple[SessionBlobRef, ...]:
    required = {
        "version",
        "command",
        "exit_code",
        "cancelled",
        "truncated",
        "stdio_complete",
        "stdio_drain_reason",
        "retention_error",
        "output_basis",
        "output_complete",
        "outputs",
    }
    if not required <= report.keys():
        raise ValueError("verification report fields are missing")
    if (
        report["output_basis"] not in {"sdk-text-view", "sdk-retained-streams"}
        or any(
            type(report[key]) is not bool
            for key in ("cancelled", "truncated", "stdio_complete", "output_complete")
        )
        or (
            report["stdio_drain_reason"] is not None
            and not isinstance(report["stdio_drain_reason"], str)
        )
    ):
        raise ValueError("invalid verification report flags")
    values = report.get("outputs")
    if not isinstance(values, list):
        raise ValueError("invalid verification outputs")
    if any(not isinstance(value, Mapping) for value in values):
        raise ValueError("invalid verification output references")
    return tuple(SessionBlobRef.from_manifest_entry(value) for value in values)


def _check_report(store: SessionBlobStore, report: Mapping[str, object]) -> bool:
    outputs = _output_refs(report)
    for reference in outputs:
        store.read_bytes(reference)  # Exact authority/membership/digest, not preview.
    code = report.get("exit_code")
    complete_material = (
        len(outputs) == 2
        if report["output_basis"] == "sdk-retained-streams"
        else len(outputs) == 1 and report["truncated"] is False
    )
    return (
        complete_material
        and type(code) is int
        and code == 0
        and report.get("cancelled") is False
        and report.get("retention_error") is None
        and report.get("output_complete") is True
        and report["stdio_complete"] is True
        and report["stdio_drain_reason"] is None
    )


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
        outputs = _output_refs(report)
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
    expected = _check_report(blobs, report)
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
    ) -> None:
        if blobs.session_id != session_blob_authority_id(session.session_id):
            raise ValueError("verification writer belongs to another Session")
        self._session = session
        self._blobs = blobs
        self._log = event_log

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
            preview = ""

            def observe(chunk):
                nonlocal preview
                # The original SDK forwards cumulative tool previews, not raw
                # byte deltas. Never concatenate them or parse exception text.
                preview = chunk.text

            try:
                result = await self._session.execute_bash(
                    command,
                    **dict(options),
                    **({"on_output": observe} if options else {}),
                )
            except RuntimeError as error:
                details = getattr(error, "tool_result_details", None)
                if not options or not isinstance(details, Mapping):
                    raise
                counts = [
                    details.get("stdout_total_bytes"),
                    details.get("stderr_total_bytes"),
                ]
                if (
                    type(details.get("exit_code")) is not int
                    or details["exit_code"] == 0
                    or details.get("timed_out") is not False
                    or details.get("cancelled") is not False
                    or details.get("truncated") is not False
                    or details.get("stdio_complete") is not True
                    or details.get("stdio_drain_reason") is not None
                    or details.get("artifact_retention_error") is not None
                    or any(type(n) is not int or n < 0 for n in counts)
                    or sum(cast(list[int], counts)) != len(preview.encode("utf-8"))
                ):
                    raise
                result = bash_result_from_tool_result(
                    AgentToolResult(
                        content=[TextPart(type="text", text=preview)],
                        details=dict(details),
                    )
                )
            if operation.session_id != self._session.session_id:
                raise ValueError("verification Session changed during command")
            truncated = result.get("truncated")
            cancelled = result.get("cancelled")
            stdio_complete = result.get("stdio_complete")
            drain_reason = result.get("stdio_drain_reason")
            if any(
                type(value) is not bool
                for value in (truncated, cancelled, stdio_complete)
            ):
                raise ValueError(
                    "SDK must explicitly report truncation, cancellation and stdio completeness"
                )
            if drain_reason is not None and not isinstance(drain_reason, str):
                raise ValueError("invalid SDK stdio drain reason")
            outputs = []
            for key in ("stdout_blob", "stderr_blob"):
                value = result.get(key)
                if value is not None:
                    if isinstance(value, SessionBlobRef):
                        reference = value
                    elif isinstance(value, Mapping):
                        reference = SessionBlobRef.from_manifest_entry(value)
                    else:
                        raise ValueError("invalid SDK output reference")
                    self._blobs.read_bytes(reference)
                    outputs.append(reference)
            basis = "sdk-retained-streams"
            output_view = result.get("output")
            if (
                not outputs
                and not truncated
                and stdio_complete
                and drain_reason is None
                and isinstance(output_view, str)
            ):
                # Legacy SDK short output has no stream Blob. This is explicitly
                # a complete SDK text view, not a claim about original OS bytes.
                outputs.append(
                    self._blobs.put_bytes(
                        output_view.encode("utf-8"),
                        logical_name="verification/sdk-output.txt",
                        kind="coding-sdk-output",
                        media_type="text/plain; charset=utf-8",
                        source="coding-sdk:command-result",
                    )
                )
                basis = "sdk-text-view"
            report = {
                "version": 1,
                "command": command,
                "exit_code": result.get("exit_code"),
                "cancelled": cancelled,
                "truncated": truncated,
                "stdio_complete": stdio_complete,
                "stdio_drain_reason": drain_reason,
                "retention_error": result.get("artifact_retention_error"),
                "output_basis": basis,
                "output_complete": bool(
                    stdio_complete
                    and drain_reason is None
                    and (
                        (basis == "sdk-retained-streams" and len(outputs) == 2)
                        or (
                            basis == "sdk-text-view"
                            and len(outputs) == 1
                            and not truncated
                        )
                    )
                ),
                "outputs": [ref.manifest_entry() for ref in outputs],
            }
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
            passed = _check_report(self._blobs, report)
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
