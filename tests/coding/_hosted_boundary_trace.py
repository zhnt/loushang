"""Opt-in, bounded test-child observations; never part of Product logging.

Only shape/digests are recorded, not prompts, context, exceptions or credentials.
Each child owns one exclusive 0600 file in an explicitly supplied private root.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import time
import uuid
from pathlib import Path

TRACE_ENV = "LOUSHANG_TEST_BOUNDARY_TRACE"
MAX_RECORDS = 256
MAX_RECORD_BYTES = 2048
_request = contextvars.ContextVar("boundary_request", default=None)
_writer = None


def text_shape(text):
    return {
        "length": len(text),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "exact_hold": text == "hold",
        "stripped_hold": text.strip() == "hold",
    }


class BoundaryTrace:
    def __init__(self, root):
        # The caller creates the root; do not resolve user paths or create trees.
        self.path = Path(root) / f"boundary-{os.getpid()}-{uuid.uuid4().hex}.jsonl"
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        self.sequence = 0

    def emit(self, phase, **fields):
        if self.sequence >= MAX_RECORDS:
            return
        record = {
            "sequence": self.sequence,
            "pid": os.getpid(),
            "monotonic_ns": time.monotonic_ns(),
            "request": _request.get(),
            "phase": phase,
            **fields,
        }
        payload = (json.dumps(record, ensure_ascii=True) + "\n").encode()
        if len(payload) > MAX_RECORD_BYTES:
            raise ValueError("boundary observation exceeds fixed record budget")
        fd = os.open(
            self.path, os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            with os.fdopen(fd, "ab") as stream:
                stream.write(payload)
        finally:
            self.sequence += 1


def emit(phase, **fields):
    if _writer is not None:
        _writer.emit(phase, **fields)


def install():
    """Observe test-child boundaries; add IO overhead but no scheduling barriers."""
    global _writer
    root = os.environ.get(TRACE_ENV)
    if root is None or _writer is not None:
        return
    _writer = BoundaryTrace(root)

    from loushang.agent import Agent
    from loushang.appservice._operations import _OwnedAppOperations
    from loushang.appservice.client_scope import AppClientScopeV1
    from loushang.appservice.runtime import AppServiceV1
    from loushang.coding.appservice_adapter import CodingHostedSessionV1

    original_start = CodingHostedSessionV1.start_turn
    original_projection = CodingHostedSessionV1._observe_projection
    original_close = CodingHostedSessionV1.close
    original_release = _OwnedAppOperations._release
    original_admit = _OwnedAppOperations.admit
    original_finish = Agent._finish_run

    def wrap_rpc(original):
        async def rpc(self, request):
            token = _request.set(uuid.uuid4().hex)
            emit("rpc_received", input=text_shape(request.text))
            try:
                result = await original(self, request)
            except BaseException as error:
                emit("rpc_failed", error_type=type(error).__name__)
                raise
            else:
                emit("rpc_returned")
                return result
            finally:
                _request.reset(token)

        return rpc

    async def start(self, text):
        emit(
            "product_entered", session=self.identity.session_id, input=text_shape(text)
        )
        try:
            result = await original_start(self, text)
        except BaseException as error:
            emit("product_failed", error_type=type(error).__name__)
            raise
        else:
            emit("product_returned")
            return result

    def projection(self, projected, event):
        emit(
            "projection",
            kind=event.kind.value,
            cursor=event.cursor,
            session=event.session_id,
            text=text_shape(event.text or ""),
        )
        return original_projection(self, projected, event)

    async def close(self):
        emit("close_entered", session=self.identity.session_id)
        await original_close(self)
        emit("close_returned", session=self.identity.session_id)

    def release(self, entry):
        owned = entry in self._entries
        original_release(self, entry)
        if owned:
            emit("slot_released", session=entry.key, pending=list(self.pending_counts))

    def admit(self, operation, *, control=False, key=None):
        try:
            task = original_admit(self, operation, control=control, key=key)
        except BaseException as error:
            emit("slot_rejected", session=key, error_type=type(error).__name__)
            raise
        emit("slot_admitted", session=key, control=control)
        return task

    def finish(self):
        original_finish(self)
        emit("agent_run_released")

    AppClientScopeV1.start_turn = wrap_rpc(AppClientScopeV1.start_turn)
    AppServiceV1.start_turn = wrap_rpc(AppServiceV1.start_turn)
    CodingHostedSessionV1.start_turn = start
    CodingHostedSessionV1._observe_projection = projection
    CodingHostedSessionV1.close = close
    _OwnedAppOperations._release = release
    _OwnedAppOperations.admit = admit
    Agent._finish_run = finish
