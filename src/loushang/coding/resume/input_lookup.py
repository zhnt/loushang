"""Narrow data contract for observing one admitted Resume input.

The digest describes the complete record fixed before commit, including its
Binding, resource evidence and target. It is an identity check, not admission.
Current read authorization remains with the calling Hosted service owner.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from loushang.harness.transcript._resume_records import input_record_digest
from loushang.harness.transcript.types import AgentTranscriptRecord

_IDENTIFIER = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_INPUT_RECORD_DIGEST_DOMAIN = b"loushang.coding.resume-input-record/v1\0"


@dataclass(frozen=True, slots=True)
class CodingResumeInputLookupQueryV1:
    input_id: str
    record_digest: str

    def __post_init__(self) -> None:
        if type(self.input_id) is not str or _IDENTIFIER.fullmatch(self.input_id) is None:
            raise ValueError("Resume lookup input id is invalid")
        if type(self.record_digest) is not str or _DIGEST.fullmatch(self.record_digest) is None:
            raise ValueError("Resume lookup record digest is invalid")


@dataclass(frozen=True, slots=True)
class CodingResumeInputLookupResultV1:
    input_id: str
    record_id: str | None
    status: Literal["committed", "not_committed_verified", "unknown", "conflict"]


def coding_resume_input_record_digest(record: AgentTranscriptRecord) -> str:
    """Identify exact persisted payload, metadata, timestamp and branch parent."""

    return input_record_digest(record, digest_domain=_INPUT_RECORD_DIGEST_DOMAIN)
