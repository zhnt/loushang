"""Coding SDK bindings for Work command verification and its original evidence."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from uuid import uuid4

from loushang.harness.artifacts import SessionBlobStore
from loushang.harnesswork.event_log import EventLogBackend, EventLogEntry
from loushang.harnesswork.integrations.verification import (
    VerificationEvidence as _VerificationEvidence,
)
from loushang.harnesswork.integrations.verification import (
    VerificationExecutor,
    VerificationProfile,
    _VerificationSession,
)
from loushang.harnesswork.integrations.verification import (
    inspect_verification as _inspect_verification,
)
from loushang.harnesswork.runtime import WorkRuntime
from loushang.harnesswork.types import WorkOperation, WorkRun, WorkRunSpec, WorkStepSpec

from ._work_evidence import EVIDENCE_CODEC

_OPERATION = "VerifyCodingCommand"
_PROFILE = VerificationProfile(
    operation=_OPERATION,
    domain="coding",
    output_kind="coding-sdk-output",
    output_source="coding-sdk:command-result",
    evidence_kind_prefix="coding-",
    evidence_source="coding-sdk:verification",
    wrong_run="run is not a Coding verification",
    invalid_document="invalid Coding verification document",
)


class CodingVerificationFailed(RuntimeError):
    """The command or its required evidence failed verification."""


@dataclass(frozen=True)
class VerificationEvidence(_VerificationEvidence):
    pass


def inspect_verification(
    entries: Iterable[EventLogEntry],
    *,
    run_id: str,
    blobs: SessionBlobStore,
    support_bindings: Mapping[str, tuple[str, int]] | None = None,
) -> VerificationEvidence:
    return _inspect_verification(
        _PROFILE, EVIDENCE_CODEC, VerificationEvidence, entries,
        run_id=run_id, blobs=blobs, support_bindings=support_bindings,
    )


class CodingVerificationExecutor(VerificationExecutor):
    """Coding's command and artifact identity over the shared executor."""

    _profile = _PROFILE
    _evidence = EVIDENCE_CODEC
    _failure = CodingVerificationFailed


class CodingVerificationWork(CodingVerificationExecutor):
    """Standalone convenience wrapper; shared compositions borrow only executor."""

    def __init__(
        self,
        *,
        session: _VerificationSession,
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
