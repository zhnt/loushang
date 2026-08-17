from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Generic, Literal, TypeVar

H = TypeVar("H")
R = TypeVar("R")
JournalSeverity = Literal["warning", "error"]
HeaderMode = Literal["required", "none"]
InvalidValueBehavior = Literal["raise", "skip"]
PartialTailBehavior = Literal["raise", "skip", "repair"]


@dataclass(frozen=True)
class JournalDiagnostic:
    code: str
    message: str
    severity: JournalSeverity = "warning"
    source_path: Path | None = None
    line_number: int | None = None
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class JournalFormatProfile:
    encoding: str = "utf-8"
    newline: str = "\n"
    ensure_ascii: bool = True
    sort_keys: bool = False
    separators: tuple[str, str] | None = None


@dataclass(frozen=True)
class JournalDurabilityProfile:
    locking: bool = True
    lock_suffix: str = ".lock"
    flush: bool = True
    fsync: bool = True


@dataclass(frozen=True)
class JournalLoadPolicy:
    header: HeaderMode = "none"
    invalid_header: InvalidValueBehavior = "raise"
    invalid_record: InvalidValueBehavior = "raise"
    partial_tail: PartialTailBehavior = "raise"


@dataclass(frozen=True)
class JsonlSnapshot(Generic[H, R]):
    header: H | None
    records: tuple[R, ...]
    diagnostics: tuple[JournalDiagnostic, ...] = ()


DEFAULT_JSONL_FORMAT = JournalFormatProfile()
SORTED_UNICODE_JSONL_FORMAT = JournalFormatProfile(
    ensure_ascii=False,
    sort_keys=True,
)
DURABLE_LOCKED_JOURNAL = JournalDurabilityProfile()
PROCESS_LOCAL_JOURNAL = JournalDurabilityProfile(
    locking=False,
    flush=False,
    fsync=False,
)


__all__ = [
    "DEFAULT_JSONL_FORMAT",
    "DURABLE_LOCKED_JOURNAL",
    "HeaderMode",
    "InvalidValueBehavior",
    "JournalDiagnostic",
    "JournalDurabilityProfile",
    "JournalFormatProfile",
    "JournalLoadPolicy",
    "JournalSeverity",
    "JsonlSnapshot",
    "PartialTailBehavior",
    "PROCESS_LOCAL_JOURNAL",
    "SORTED_UNICODE_JSONL_FORMAT",
]
