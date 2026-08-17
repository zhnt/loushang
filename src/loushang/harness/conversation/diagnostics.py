from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ConversationSeverity = Literal["warning", "error"]


@dataclass(frozen=True)
class ConversationDiagnostic:
    """A recoverable conversation-structure problem.

    Physical source details remain ``JournalDiagnostic`` values at the file
    boundary. This type is reserved for parent-linked conversation semantics.
    """

    code: str
    message: str
    severity: ConversationSeverity = "warning"
    record_id: str | None = None
    details: dict[str, object] = field(default_factory=dict)


__all__ = ["ConversationDiagnostic", "ConversationSeverity"]
