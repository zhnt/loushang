"""Optional Product-neutral Resume input observation; no retry authority."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol

from .protocol import SessionSnapshotRequestV1

_IDENTIFIER = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
ResumeInputLookupStatusV1 = Literal["committed", "not_committed_verified", "unknown", "conflict"]


@dataclass(frozen=True, slots=True)
class ResumeInputLookupQueryV1:
    input_id: str
    record_digest: str

    def __post_init__(self) -> None:
        if type(self.input_id) is not str or _IDENTIFIER.fullmatch(self.input_id) is None:
            raise ValueError("invalid Resume input id")
        if type(self.record_digest) is not str or _DIGEST.fullmatch(self.record_digest) is None:
            raise ValueError("invalid Resume input record digest")


@dataclass(frozen=True, slots=True)
class ResumeInputLookupResultV1:
    input_id: str
    record_id: str | None
    status: ResumeInputLookupStatusV1

    def __post_init__(self) -> None:
        if type(self.input_id) is not str or _IDENTIFIER.fullmatch(self.input_id) is None:
            raise ValueError("invalid Resume input id")
        if self.record_id is not None and (
            type(self.record_id) is not str or _IDENTIFIER.fullmatch(self.record_id) is None
        ):
            raise ValueError("invalid Resume input record id")
        if type(self.status) is not str or self.status not in {
            "committed", "not_committed_verified", "unknown", "conflict",
        }:
            raise ValueError("invalid Resume lookup status")
        if self.status in {"committed", "not_committed_verified"} and self.record_id is None:
            raise ValueError("verified Resume lookup requires a record id")


class ResumeInputLookupClientV1(Protocol):
    """Borrowed negotiated read capability, separate from legacy AppClientV1."""

    async def lookup_resume_input(
        self, control: SessionSnapshotRequestV1, expected_instance_id: str,
        query: ResumeInputLookupQueryV1,
    ) -> ResumeInputLookupResultV1: ...
