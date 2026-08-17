"""Product-neutral bindings for standard session RPC operations.

The Channel owns JSONL framing and correlation while Products own their wire
response shape.  This module owns the operation grammar and maps a validated
RPC-shaped payload to :class:`SessionOperationRuntime` calls without importing
Channel or any Product package.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from loushang.harness.runtime import SessionOperationResult
from loushang.harness.session.operations import (
    SessionOperationRuntime,
    SessionPromptRequest,
)
from loushang.harness.session.transcript_lifecycle import (
    require_session_operation_session,
)


class SessionRpcOperationBinding:
    """Bind a Product RPC command surface to standard session operations.

    The binding deliberately does not serialize responses or decide whether a
    command is exposed.  Those decisions remain in the Product protocol
    adapter.  It only performs the shared payload grammar and operation call,
    including rebinding the active session after lifecycle transitions.
    """

    def __init__(
        self,
        *,
        get_operations: Callable[[], SessionOperationRuntime],
        bind_session: Callable[[object], None],
    ) -> None:
        self._get_operations = get_operations
        self._bind_session = bind_session

    def prompt_request(
        self, payload: Mapping[str, object], *, source: str | None = "rpc"
    ) -> SessionPromptRequest:
        message = self._require_string(payload, "message")
        behavior = payload.get("streamingBehavior", payload.get("streaming_behavior"))
        streaming_behavior = behavior if isinstance(behavior, str) else None
        images = self._coerce_images(payload.get("images"))
        return SessionPromptRequest(
            text=message,
            images=cast(tuple, tuple(images or ())),
            streaming_behavior=streaming_behavior,
            source=source,
        )

    def steer(self, payload: Mapping[str, object]) -> None:
        self._get_operations().steer(
            self._require_string(payload, "message"),
            images=cast(tuple, tuple(self._coerce_images(payload.get("images")) or ())),
        )

    def follow_up(self, payload: Mapping[str, object]) -> None:
        self._get_operations().follow_up(
            self._require_string(payload, "message"),
            images=cast(tuple, tuple(self._coerce_images(payload.get("images")) or ())),
        )

    def abort(self) -> bool:
        return self._get_operations().abort_turn()

    async def new_session(
        self, payload: Mapping[str, object]
    ) -> SessionOperationResult[Any, Any]:
        cwd = self._optional_path(payload.get("cwd"))
        operation = await self._get_operations().new_session(
            cwd=str(cwd) if cwd is not None else None,
            parent_session=self._optional_string(
                payload, "parentSession", "parent_session"
            ),
        )
        self._bind_session(require_session_operation_session(operation))
        return operation

    async def switch_session(
        self, payload: Mapping[str, object]
    ) -> SessionOperationResult[Any, Any]:
        session_ref = payload.get(
            "sessionId", payload.get("session_id", payload.get("sessionPath"))
        )
        if not isinstance(session_ref, str) or not session_ref:
            raise ValueError("switch_session requires sessionId")
        operation = await self._get_operations().restore_session(session_ref)
        self._bind_session(require_session_operation_session(operation))
        return operation

    async def fork(
        self, payload: Mapping[str, object]
    ) -> SessionOperationResult[Any, Any]:
        entry_id = payload.get("entryId", payload.get("entry_id"))
        if not isinstance(entry_id, str) or not entry_id:
            raise ValueError("fork requires entryId")
        position = payload.get("position", "before")
        if position not in {"before", "at"}:
            raise ValueError("fork position must be 'before' or 'at'")
        operation = await self._get_operations().fork_session(
            entry_id,
            position=cast(str, position),
        )
        self._bind_session(require_session_operation_session(operation))
        return operation

    async def clone(
        self, payload: Mapping[str, object] | None = None
    ) -> SessionOperationResult[Any, Any]:
        del payload
        operation = await self._get_operations().clone_session()
        self._bind_session(require_session_operation_session(operation))
        return operation

    async def compact(self, payload: Mapping[str, object]) -> object:
        return await self._get_operations().compact(
            self._optional_string(payload, "customInstructions", "custom_instructions")
        )

    def set_auto_retry(self, payload: Mapping[str, object]) -> None:
        self._get_operations().set_auto_retry_enabled(
            self._require_bool(payload, "enabled", command="set_auto_retry")
        )

    def abort_retry(self) -> None:
        self._get_operations().abort_retry()

    def set_auto_compaction(self, payload: Mapping[str, object]) -> None:
        self._get_operations().set_auto_compaction_enabled(
            self._require_bool(payload, "enabled", command="set_auto_compaction")
        )

    @staticmethod
    def _require_string(payload: Mapping[str, object], *keys: str) -> str:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        raise ValueError(f"missing required string field: {keys[0]}")

    @staticmethod
    def _optional_string(
        payload: Mapping[str, object], *keys: str
    ) -> str | None:
        for key in keys:
            value = payload.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                return value
            raise ValueError(f"{key} must be a string")
        return None

    @staticmethod
    def _require_bool(
        payload: Mapping[str, object], key: str, *, command: str
    ) -> bool:
        value = payload.get(key)
        if not isinstance(value, bool):
            raise ValueError(f"{command} requires boolean {key}")
        return value

    @staticmethod
    def _coerce_images(images: object) -> list[object] | None:
        if images is None:
            return None
        if not isinstance(images, list):
            raise ValueError("images must be a list")
        return images

    @staticmethod
    def _optional_path(value: object) -> str | Path | None:
        if value is None:
            return None
        if isinstance(value, str | Path):
            return value
        raise ValueError("cwd must be a string")
