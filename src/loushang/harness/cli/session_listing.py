"""Shared CLI session-catalog operation and stable listing projection."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from loushang.harness.transcript.session_catalog import (
    SessionQuery,
    try_project_session_record,
)

SessionListingFormat = Literal["tsv", "json"]


class SessionListingError(RuntimeError):
    """Raised when a session catalog cannot satisfy a CLI listing request."""


@dataclass(frozen=True, slots=True)
class SessionListingRequest:
    """Product-neutral session catalog selection."""

    query: SessionQuery | None = None
    all_sessions: bool = False
    indexed: bool = False
    refresh_index: bool = False


def build_session_query(
    *,
    cwd: str | None = None,
    name: str | None = None,
    parent_session: str | None = None,
    text: str | None = None,
    has_diagnostics: bool | None = None,
    limit: int | None = None,
) -> SessionQuery | None:
    """Build a query without depending on a Product CLI argument object."""

    if limit is not None and limit < 0:
        raise ValueError("Session query limit must be non-negative")
    if all(
        value is None
        for value in (cwd, name, parent_session, text, has_diagnostics, limit)
    ):
        return None
    return SessionQuery(
        cwd=cwd,
        name=name,
        parent_session=parent_session,
        text=text,
        has_diagnostics=has_diagnostics,
        limit=limit,
    )


def list_session_records(
    runtime: object,
    request: SessionListingRequest,
    *,
    record_projector: Callable[[object], dict[str, object] | None]
    | None = None,
) -> list[dict[str, object]]:
    """Read and project session summaries from an injected catalog runtime."""

    if request.refresh_index:
        refresher_name = (
            "refresh_all_session_indexes"
            if request.all_sessions
            else "refresh_session_index"
        )
        refresher = getattr(runtime, refresher_name, None)
        if not callable(refresher):
            raise SessionListingError("session index refresh is not available.")
        try:
            refresher()
        except Exception as error:
            raise SessionListingError(str(error)) from error

    query = request.query
    indexed = request.indexed
    if request.all_sessions and query is not None:
        method_name = (
            "find_all_indexed_session_summaries"
            if indexed
            else "find_all_session_summaries"
        )
        call_lister = _resolve_callable(runtime, method_name, query)
    elif query is not None:
        method_name = (
            "find_indexed_session_summaries"
            if indexed
            else "find_session_summaries"
        )
        call_lister = _resolve_callable(runtime, method_name, query)
    elif request.all_sessions:
        method_name = (
            "list_all_indexed_session_summaries"
            if indexed
            else "list_all_session_summaries"
        )
        call_lister = _resolve_callable(runtime, method_name)
    else:
        method_name = (
            "list_indexed_session_summaries"
            if indexed
            else "list_session_summaries"
        )
        call_lister = _resolve_callable(runtime, method_name)
        if call_lister is None and not indexed:
            call_lister = _resolve_callable(runtime, "list_sessions")

    if call_lister is None:
        raise SessionListingError("session listing is not available.")
    try:
        records = call_lister()
    except Exception as error:
        raise SessionListingError(str(error)) from error
    if not isinstance(records, list):
        raise SessionListingError("session listing returned an invalid response.")
    project = record_projector or try_project_session_record
    return [
        projected
        for record in records
        if (projected := project(record)) is not None
    ]


def format_session_records(
    records: list[dict[str, object]],
    output_format: SessionListingFormat,
) -> str:
    """Render the stable JSON or tab-separated session listing."""

    if output_format == "json":
        return json.dumps(records, ensure_ascii=False) + "\n"
    lines: list[str] = []
    for record in records:
        metadata = record["metadata"]
        name = metadata["name"] if isinstance(metadata, dict) else ""
        name = name if isinstance(name, str) else ""
        lines.append(
            f"{record['session_id']}\t{record['session_file']}\t{record['cwd']}\t"
            f"{metadata['updated_at'] if isinstance(metadata, dict) else ''}\t{name}"
        )
    return "\n".join(lines) + ("\n" if lines else "")


def _resolve_callable(
    runtime: object,
    method_name: str,
    *arguments: object,
) -> Callable[[], Any] | None:
    method = getattr(runtime, method_name, None)
    if not callable(method):
        return None
    return lambda: method(*arguments)


__all__ = [
    "SessionListingError",
    "SessionListingFormat",
    "SessionListingRequest",
    "build_session_query",
    "format_session_records",
    "list_session_records",
]
