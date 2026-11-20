"""Verify and hash one selected root-to-leaf transcript path."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256

from loushang.harness.transcript.types import AgentTranscriptRecord


class SelectedAncestry:
    def __init__(self, domain: bytes) -> None:
        self._digest = sha256(domain)
        self._parent_id: str | None = None
        self._seen: set[str] = set()

    def require_next(self, record: AgentTranscriptRecord, *, error: str) -> None:
        if record.parent_id != self._parent_id or record.record_id in self._seen:
            raise ValueError(error)
        self._seen.add(record.record_id)

    def advance(
        self, record: AgentTranscriptRecord, encode: Callable[[object], bytes]
    ) -> None:
        identity = encode({"recordId": record.record_id, "parentId": record.parent_id})
        self._digest.update(len(identity).to_bytes(4, "big"))
        self._digest.update(identity)
        self._parent_id = record.record_id

    def hexdigest(self) -> str:
        return self._digest.hexdigest()
