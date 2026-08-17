"""Product-neutral text projections for recorded observability problems."""

from __future__ import annotations

from typing import Protocol

from .records import ProblemRecord


class ProblemRecordReader(Protocol):
    """Read-only view required to render recent problem summaries."""

    def all(self) -> list[ProblemRecord]: ...


def format_problem_summary(record: ProblemRecord) -> str:
    """Return the concise, stable text form used by debug surfaces."""

    parts = [
        "PROBLEM",
        record.severity,
        record.code,
        f"source={record.source}" if record.source else "",
        record.message,
    ]
    return " ".join(part for part in parts if part)


def recent_problem_store_lines(
    store: ProblemRecordReader,
    *,
    limit: int = 8,
) -> list[str]:
    """Render the latest problem records, tolerating a failed problem store."""

    if limit <= 0:
        return []
    try:
        records = store.all()
    except Exception:
        return []
    return [format_problem_summary(record) for record in records[-limit:]]


def is_problem_log_line(line: str) -> bool:
    """Whether a line belongs in a short problem-focused debug summary."""

    stripped = line.strip()
    if not stripped:
        return False
    tokens = stripped.split()
    return " PROBLEM " in f" {stripped} " or "WARNING" in tokens or "ERROR" in tokens


__all__ = [
    "ProblemRecordReader",
    "format_problem_summary",
    "is_problem_log_line",
    "recent_problem_store_lines",
]
