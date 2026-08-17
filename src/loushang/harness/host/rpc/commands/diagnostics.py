"""Diagnostics commands for the shared RPC host."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from loushang.harness.diagnostics.types import DiagnosticsQuery
from loushang.harness.host.rpc.arguments import optional_string
from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.host.rpc.projections import RpcDiagnosticsProjection
from loushang.harness.host.rpc.routing import LegacyRpcHandler


class _DiagnosticsUnavailable(RuntimeError):
    pass


class _DiagnosticsQueries(Protocol):
    """Semantic diagnostics capabilities consumed by this command group."""

    def get_diagnostics(
        self, query: DiagnosticsQuery, *, fallback_limit: int
    ) -> object: ...

    def get_session_diagnostics(
        self, query: DiagnosticsQuery, *, fallback_limit: int
    ) -> object: ...

    def get_diagnostics_summary(self, query: DiagnosticsQuery) -> object: ...

    def get_session_diagnostics_summary(
        self, query: DiagnosticsQuery
    ) -> object: ...

    def get_last_error_report(self) -> object: ...


class _DynamicDiagnosticsQueries:
    """Resolve optional Product capabilities at the invocation boundary."""

    def __init__(
        self, *, runtime: object, get_session: Callable[[], object]
    ) -> None:
        self._runtime = runtime
        self._get_session = get_session

    def get_diagnostics(
        self, query: DiagnosticsQuery, *, fallback_limit: int
    ) -> object:
        method = self._resolve("get_diagnostics")
        if method is not None:
            return method(query=query)
        fallback = self._resolve_session("get_last_diagnostics")
        if fallback is not None:
            return fallback(limit=fallback_limit)
        raise _DiagnosticsUnavailable

    def get_session_diagnostics(
        self, query: DiagnosticsQuery, *, fallback_limit: int
    ) -> object:
        del fallback_limit
        return self._invoke("get_session_diagnostics", query=query)

    def get_diagnostics_summary(self, query: DiagnosticsQuery) -> object:
        return self._invoke("get_diagnostics_summary", query=query)

    def get_session_diagnostics_summary(
        self, query: DiagnosticsQuery
    ) -> object:
        return self._invoke("get_session_diagnostics_summary", query=query)

    def get_last_error_report(self) -> object:
        method = self._resolve_session("get_last_error_report")
        if method is None:
            raise _DiagnosticsUnavailable
        return method()

    def _invoke(self, name: str, **kwargs: object) -> object:
        method = self._resolve(name)
        if method is None:
            raise _DiagnosticsUnavailable
        return method(**kwargs)

    def _resolve(self, name: str) -> Callable[..., object] | None:
        method = getattr(self._runtime, name, None)
        if callable(method):
            return method
        return self._resolve_session(name)

    def _resolve_session(self, name: str) -> Callable[..., object] | None:
        method = getattr(self._get_session(), name, None)
        return method if callable(method) else None


class RpcDiagnosticsCommands:
    """Project runtime/session diagnostics through the existing RPC wire."""

    def __init__(
        self,
        *,
        runtime: object,
        get_session: Callable[[], object],
        output: RpcOutput,
        projection: RpcDiagnosticsProjection,
    ) -> None:
        self._queries: _DiagnosticsQueries = _DynamicDiagnosticsQueries(
            runtime=runtime,
            get_session=get_session,
        )
        self._output = output
        self._projection = projection

    def bindings(self) -> tuple[tuple[str, LegacyRpcHandler], ...]:
        return (
            ("get_diagnostics", self.get_diagnostics),
            ("get_session_diagnostics", self.get_session_diagnostics),
            ("get_diagnostics_summary", self.get_diagnostics_summary),
            (
                "get_session_diagnostics_summary",
                self.get_session_diagnostics_summary,
            ),
            ("get_last_error_report", self.get_last_error_report),
        )

    def get_diagnostics(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        self._query_records(
            command_id=command_id,
            payload=payload,
            command="get_diagnostics",
            fetch=self._queries.get_diagnostics,
        )

    def get_session_diagnostics(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        self._query_records(
            command_id=command_id,
            payload=payload,
            command="get_session_diagnostics",
            fetch=self._queries.get_session_diagnostics,
        )

    def get_diagnostics_summary(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        self._query_summary(
            command_id=command_id,
            payload=payload,
            command="get_diagnostics_summary",
            fetch=self._queries.get_diagnostics_summary,
        )

    def get_session_diagnostics_summary(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        self._query_summary(
            command_id=command_id,
            payload=payload,
            command="get_session_diagnostics_summary",
            fetch=self._queries.get_session_diagnostics_summary,
        )

    def get_last_error_report(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        try:
            report = self._queries.get_last_error_report()
        except _DiagnosticsUnavailable:
            self._output.error(
                request_id=command_id,
                command="get_last_error_report",
                error="Diagnostics are not available.",
            )
            return
        try:
            report = self._projection.serialize_error_report(report)
        except Exception as error:
            self._output.error(
                request_id=command_id,
                command="get_last_error_report",
                error=f"Failed to query last error report: {error}",
            )
            return
        self._output.success(
            request_id=command_id,
            command="get_last_error_report",
            data={"report": report},
        )

    def _query_records(
        self,
        *,
        command_id: str | None,
        payload: dict[str, Any],
        command: str,
        fetch: Callable[..., object],
    ) -> None:
        raw_limit = payload.get("limit", 50)
        if not isinstance(raw_limit, int) or raw_limit <= 0:
            self._output.error(
                request_id=command_id,
                command=command,
                error="Diagnostic limit must be a positive integer.",
            )
            return

        query = _query_from_payload(payload, default_limit=raw_limit)
        try:
            raw_diagnostics = fetch(query, fallback_limit=raw_limit)
        except _DiagnosticsUnavailable:
            self._output.error(
                request_id=command_id,
                command=command,
                error="Diagnostics are not available.",
            )
            return
        except Exception as error:
            self._output.error(
                request_id=command_id,
                command=command,
                error=f"Failed to query diagnostics: {error}",
            )
            return
        if not isinstance(raw_diagnostics, list):
            self._output.error(
                request_id=command_id,
                command=command,
                error="Diagnostics returned an invalid response.",
            )
            return

        diagnostics = []
        for record in raw_diagnostics:
            try:
                diagnostics.append(self._projection.serialize_diagnostic(record))
            except Exception:
                continue
        self._output.success(
            request_id=command_id,
            command=command,
            data={"diagnostics": diagnostics},
        )

    def _query_summary(
        self,
        *,
        command_id: str | None,
        payload: dict[str, Any],
        command: str,
        fetch: Callable[[DiagnosticsQuery], object],
    ) -> None:
        try:
            query = _query_from_payload(payload, default_limit=None)
        except ValueError as error:
            self._output.error(
                request_id=command_id, command=command, error=str(error)
            )
            return
        try:
            summary = fetch(query)
        except _DiagnosticsUnavailable:
            self._output.error(
                request_id=command_id,
                command=command,
                error="Diagnostics are not available.",
            )
            return
        except Exception as error:
            self._output.error(
                request_id=command_id,
                command=command,
                error=f"Failed to query diagnostics: {error}",
            )
            return
        try:
            summary = self._projection.serialize_diagnostic_summary(summary)
        except Exception as error:
            self._output.error(
                request_id=command_id,
                command=command,
                error=f"Failed to query diagnostics: {error}",
            )
            return
        self._output.success(
            request_id=command_id,
            command=command,
            data={"summary": summary},
        )


def _query_from_payload(
    payload: dict[str, Any], *, default_limit: int | None
) -> DiagnosticsQuery:
    raw_limit = payload.get("limit", default_limit)
    if raw_limit is not None and (not isinstance(raw_limit, int) or raw_limit <= 0):
        raise ValueError("Diagnostic limit must be a positive integer.")
    return DiagnosticsQuery(
        phase=optional_string(payload, "phase"),  # type: ignore[arg-type]
        source=optional_string(payload, "source"),  # type: ignore[arg-type]
        level=optional_string(
            payload, "level", "diagnosticType", "diagnostic_type"
        ),  # type: ignore[arg-type]
        session_id=optional_string(payload, "sessionId", "session_id"),
        entry_id=optional_string(payload, "entryId", "entry_id"),
        tool_call_id=optional_string(payload, "toolCallId", "tool_call_id"),
        code=optional_string(payload, "code"),
        limit=raw_limit,
    )


__all__ = ["RpcDiagnosticsCommands"]
