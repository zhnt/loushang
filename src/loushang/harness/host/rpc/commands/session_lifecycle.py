"""Session discovery and replacement commands for the shared RPC host."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from loushang.harness.host.rpc.arguments import (
    optional_bool,
    optional_int,
    optional_string,
)
from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.host.rpc.routing import LegacyRpcHandler
from loushang.harness.host.rpc.wire import project_session_listing_item
from loushang.harness.session import SessionRpcOperationBinding
from loushang.harness.transcript import SessionQuery


class _SessionLifecycleRuntime(Protocol):
    """Only the standard discovery/index capabilities consumed here."""

    def refresh_session_index(self) -> object: ...

    def refresh_all_session_indexes(self) -> object: ...

    def find_session_summaries(self, query: SessionQuery) -> object: ...

    def find_all_session_summaries(self, query: SessionQuery) -> object: ...

    def find_indexed_session_summaries(self, query: SessionQuery) -> object: ...

    def find_all_indexed_session_summaries(self, query: SessionQuery) -> object: ...


class RpcSessionLifecycleCommands:
    """Keep legacy session wire semantics outside the RPC event loop."""

    def __init__(
        self,
        *,
        runtime: _SessionLifecycleRuntime,
        get_session: Callable[[], object],
        operations: SessionRpcOperationBinding,
        output: RpcOutput,
    ) -> None:
        self._runtime = runtime
        self._get_session = get_session
        self._operations = operations
        self._output = output

    def bindings(self) -> tuple[tuple[str, LegacyRpcHandler], ...]:
        return (
            ("list_sessions", self.list_sessions),
            ("new_session", self.new_session),
            ("switch_session", self.switch_session),
            ("fork", self.fork),
            ("clone", self.clone),
        )

    def list_sessions(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        try:
            query = _session_query_from_payload(payload)
        except ValueError as error:
            self._output.error(
                request_id=command_id,
                command="list_sessions",
                error=str(error),
            )
            return
        all_sessions = payload.get("allSessions", payload.get("all_sessions", False))
        if not isinstance(all_sessions, bool):
            raise ValueError("list_sessions allSessions must be boolean")
        use_index = payload.get("useIndex", payload.get("use_index", False))
        refresh_index = payload.get("refreshIndex", payload.get("refresh_index", False))
        if not isinstance(use_index, bool):
            raise ValueError("list_sessions useIndex must be boolean")
        if not isinstance(refresh_index, bool):
            raise ValueError("list_sessions refreshIndex must be boolean")
        use_index = use_index or refresh_index
        if refresh_index and not self._refresh_index(
            command_id=command_id,
            all_sessions=all_sessions,
        ):
            return
        lister = self._resolve_lister(
            query=query,
            all_sessions=all_sessions,
            use_index=use_index,
        )
        if lister is None:
            self._output.error(
                request_id=command_id,
                command="list_sessions",
                error="Session listing is not available.",
            )
            return
        try:
            raw_sessions = lister()
        except Exception as error:
            self._output.error(
                request_id=command_id,
                command="list_sessions",
                error=f"Failed to list sessions: {error}",
            )
            return
        if not isinstance(raw_sessions, list):
            self._output.error(
                request_id=command_id,
                command="list_sessions",
                error="Session listing returned an invalid response.",
            )
            return
        sessions = []
        for session in raw_sessions:
            try:
                sessions.append(project_session_listing_item(session))
            except Exception:
                continue
        self._output.success(
            request_id=command_id,
            command="list_sessions",
            data={"sessions": sessions},
        )

    async def new_session(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        previous = self._get_session()
        try:
            operation = await self._operations.new_session(payload)
        except Exception as error:
            self._output.error(
                request_id=command_id,
                command="new_session",
                error=f"Failed to create new session: {error}",
            )
            return
        self._output.success(
            request_id=command_id,
            command="new_session",
            data={"cancelled": operation.current is previous},
        )

    async def switch_session(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        previous = self._get_session()
        try:
            operation = await self._operations.switch_session(payload)
        except Exception as error:
            self._output.error(
                request_id=command_id,
                command="switch_session",
                error=f"Failed to switch session: {error}",
            )
            return
        self._output.success(
            request_id=command_id,
            command="switch_session",
            data={"cancelled": operation.current is previous},
        )

    async def fork(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        previous = self._get_session()
        try:
            operation = await self._operations.fork(payload)
        except Exception as error:
            self._output.error(
                request_id=command_id,
                command="fork",
                error=f"Failed to fork session: {error}",
            )
            return
        self._output.success(
            request_id=command_id,
            command="fork",
            data={
                "cancelled": operation.current is previous,
                "text": operation.payload,
            },
        )

    async def clone(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        del payload
        previous = self._get_session()
        try:
            operation = await self._operations.clone()
        except Exception as error:
            self._output.error(
                request_id=command_id,
                command="clone",
                error=f"Failed to clone session: {error}",
            )
            return
        self._output.success(
            request_id=command_id,
            command="clone",
            data={"cancelled": operation.current is previous},
        )

    def _refresh_index(
        self,
        *,
        command_id: str | None,
        all_sessions: bool,
    ) -> bool:
        refresher = getattr(
            self._runtime,
            (
                "refresh_all_session_indexes"
                if all_sessions
                else "refresh_session_index"
            ),
            None,
        )
        if not callable(refresher):
            self._output.error(
                request_id=command_id,
                command="list_sessions",
                error="Session index refresh is not available.",
            )
            return False
        try:
            refresher()
        except Exception as error:
            self._output.error(
                request_id=command_id,
                command="list_sessions",
                error=f"Failed to refresh session index: {error}",
            )
            return False
        return True

    def _resolve_lister(
        self,
        *,
        query: SessionQuery,
        all_sessions: bool,
        use_index: bool,
    ) -> Callable[[], object] | None:
        finder = (
            getattr(
                self._runtime,
                (
                    "find_all_indexed_session_summaries"
                    if use_index
                    else "find_all_session_summaries"
                ),
                None,
            )
            if all_sessions
            else None
        )
        if not callable(finder):
            finder = getattr(
                self._runtime,
                (
                    "find_indexed_session_summaries"
                    if use_index
                    else "find_session_summaries"
                ),
                None,
            )
        if callable(finder):
            return lambda: finder(query)
        if all_sessions:
            lister = getattr(
                self._runtime,
                (
                    "list_all_indexed_session_summaries"
                    if use_index
                    else "list_all_session_summaries"
                ),
                None,
            )
        else:
            lister = getattr(
                self._runtime,
                (
                    "list_indexed_session_summaries"
                    if use_index
                    else "list_session_summaries"
                ),
                None,
            )
        if not callable(lister) and not use_index:
            lister = getattr(self._runtime, "list_sessions", None)
        return lister if callable(lister) else None


def _session_query_from_payload(payload: dict[str, Any]) -> SessionQuery:
    limit = optional_int(payload, "limit")
    if limit is not None and limit < 0:
        raise ValueError("Session limit must be non-negative.")
    return SessionQuery(
        cwd=optional_string(payload, "cwd"),
        name=optional_string(payload, "name"),
        parent_session=optional_string(
            payload,
            "parentSession",
            "parent_session",
        ),
        text=optional_string(payload, "text", "query"),
        has_diagnostics=optional_bool(
            payload,
            "hasDiagnostics",
            "has_diagnostics",
        ),
        limit=limit,
    )


__all__ = ["RpcSessionLifecycleCommands"]
