"""Strict JSONL response writer for the RPC runtime."""

from __future__ import annotations

import json
from typing import TextIO

from loushang.harness.host.json_projection import project_host_value

_UNSET = object()


class RpcOutput:
    """Own serialization, fallback shaping, and stream flushing."""

    def __init__(self, stdout: TextIO) -> None:
        self._stdout = stdout

    def success(
        self,
        *,
        command: str,
        request_id: str | None = None,
        data: object = _UNSET,
    ) -> None:
        payload: dict[str, object] = {
            "type": "response",
            "command": command,
            "success": True,
        }
        if request_id is not None:
            payload["id"] = request_id
        if data is not _UNSET:
            payload["data"] = data
        self.write(payload)

    def error(
        self,
        *,
        command: str,
        error: str,
        request_id: str | None = None,
        code: str | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "type": "response",
            "command": command,
            "success": False,
            "error": error,
        }
        if request_id is not None:
            payload["id"] = request_id
        if code is not None:
            payload["errorCode"] = code
            payload["errorInfo"] = {
                "code": code,
                "message": error,
                "command": command,
            }
        self.write(payload)

    def write(self, payload: object) -> None:
        try:
            serialized = project_host_value(payload, name="rpc_output", surface="RPC")
            line = json.dumps(serialized, ensure_ascii=False)
        except Exception:
            fallback_id, fallback_command = _fallback_fields(payload)
            fallback_payload: dict[str, object] = {
                "type": "response",
                "command": fallback_command or "response",
                "success": False,
                "error": "Failed to serialize RPC output.",
            }
            if fallback_id is not None:
                fallback_payload["id"] = fallback_id
            line = json.dumps(
                project_host_value(
                    fallback_payload, name="rpc_fallback", surface="RPC"
                ),
                ensure_ascii=False,
                allow_nan=False,
            )
        self._stdout.write(line + "\n")
        flush = getattr(self._stdout, "flush", None)
        if callable(flush):
            flush()


def _fallback_fields(payload: object) -> tuple[str | None, str | None]:
    if not isinstance(payload, dict):
        return None, None
    return (
        _strict_fallback_string(payload.get("id")),
        _strict_fallback_string(payload.get("command")),
    )


def _strict_fallback_string(value: object) -> str | None:
    if type(value) is not str:
        return None
    try:
        projected = project_host_value(value, name="rpc_fallback", surface="RPC")
    except Exception:
        return None
    return projected if isinstance(projected, str) else None


__all__ = ["RpcOutput"]
