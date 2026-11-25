"""Narrow data contract for observing one admitted Resume input.

The digest describes the complete record fixed before commit, including its
Binding, resource evidence and target. It is an identity check, not admission.
Current read authorization remains with the calling Hosted service owner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from loushang.harness.resume_effects import is_resume_digest, is_resume_identifier
from loushang.harness.transcript._resume_records import input_record_digest
from loushang.harness.transcript.types import AgentTranscriptRecord

_INPUT_RECORD_DIGEST_DOMAIN = b"loushang.coding.resume-input-record/v1\0"


@dataclass(frozen=True, slots=True)
class CodingResumeInputLookupQueryV1:
    input_id: str
    record_digest: str

    def __post_init__(self) -> None:
        if not is_resume_identifier(self.input_id):
            raise ValueError("Resume lookup input id is invalid")
        if not is_resume_digest(self.record_digest):
            raise ValueError("Resume lookup record digest is invalid")


@dataclass(frozen=True, slots=True)
class CodingResumeInputLookupResultV1:
    input_id: str
    record_id: str | None
    status: Literal["committed", "not_committed_verified", "unknown", "conflict"]


def coding_resume_input_record_digest(record: AgentTranscriptRecord) -> str:
    """Identify exact persisted payload, metadata, timestamp and branch parent."""

    return input_record_digest(record, digest_domain=_INPUT_RECORD_DIGEST_DOMAIN)
