from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from loushang.harness.cli import (
    SessionListingError,
    SessionListingRequest,
    build_session_query,
    format_session_records,
    list_session_records,
)


@dataclass
class _Metadata:
    created_at: str = "2026-01-01T00:00:00Z"
    updated_at: str = "2026-01-02T00:00:00Z"
    name: str | None = "draft"


@dataclass
class _Record:
    session_id: str = "session-1"
    cwd: str = "/tmp/project"
    session_file: Path = Path("/tmp/session-1.jsonl")
    parent_session: str | None = None
    leaf_id: str | None = "leaf-1"
    metadata: _Metadata = field(default_factory=_Metadata)


class _Runtime:
    def __init__(self) -> None:
        self.refresh_calls = 0
        self.queries: list[object] = []

    def refresh_session_index(self) -> None:
        self.refresh_calls += 1

    def list_session_summaries(self) -> list[_Record]:
        return [_Record()]

    def find_session_summaries(self, query: object) -> list[_Record]:
        self.queries.append(query)
        return [_Record()]


def test_listing_runtime_selects_query_and_projects_json_records() -> None:
    runtime = _Runtime()
    query = build_session_query(cwd="/tmp/project", limit=2)

    records = list_session_records(
        runtime,
        SessionListingRequest(query=query, indexed=False, refresh_index=True),
    )

    assert runtime.refresh_calls == 1
    assert len(runtime.queries) == 1
    assert records[0]["session_id"] == "session-1"
    assert '"session_id": "session-1"' in format_session_records(records, "json")


def test_listing_runtime_keeps_tsv_shape_and_rejects_negative_limit() -> None:
    runtime = _Runtime()
    records = list_session_records(runtime, SessionListingRequest())

    assert format_session_records(records, "tsv") == (
        "session-1\t/tmp/session-1.jsonl\t/tmp/project\t"
        "2026-01-02T00:00:00Z\tdraft\n"
    )
    with pytest.raises(ValueError, match="non-negative"):
        build_session_query(limit=-1)


def test_listing_runtime_reports_missing_catalog_capability() -> None:
    with pytest.raises(SessionListingError, match="not available"):
        list_session_records(object(), SessionListingRequest())
