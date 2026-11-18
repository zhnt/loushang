"""Explicit frozen pre-A171 process transport observations.

Real client methods and Task.cancel during write/wait, controlled stream IO and
request duration clock. No native process or default PR discovery claim.
"""

import asyncio
import gzip
import json
from contextlib import suppress
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from loushang.coding.lsp.client import LspClient
from loushang.harness.workspace.process import ProcessExit

EXPECTED = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "process_json_rpc_custody_v1.json.gz"
)
CASES = (
    "write",
    "write-budget",
    "write-error",
    "fragments",
    "two-frames",
    "header-budget",
    "length-missing",
    "length-negative",
    "length-invalid",
    "json-invalid",
    "json-array",
    "eof",
    "mid-frame",
    "method-invalid",
    "response-id-bool",
    "response-unknown",
    "request-ok",
    "request-error",
    "request-transient",
    "request-timeout",
    "cancel-write",
    "cancel-wait",
    "closed-request",
    "capacity",
    "shutdown",
    "graceful",
    "abort",
    "close-fault",
    "settle-fault",
    "both-close-faults",
    "closed-abort",
    "reader-eof",
    "reader-error",
    "reader-callback-error",
    "reader-cancel",
)


def exception_value(error, seen=None):
    if error is None:
        return None
    seen = set() if seen is None else seen
    if id(error) in seen:
        return {"cycle": True}
    seen.add(id(error))
    return {
        "type": type(error).__module__ + "." + type(error).__qualname__,
        "message": str(error),
        "notes": getattr(error, "__notes__", []),
        "cause": exception_value(error.__cause__, seen.copy()),
        "context": exception_value(error.__context__, seen.copy()),
        "suppress": error.__suppress_context__,
    }


def packet(value):
    body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    return f"Content-Length: {len(body)}\r\n\r\n".encode() + body


@pytest.mark.parametrize("case", CASES)
def test_transport(case, monkeypatch):
    trace = []
    captured = []
    entered = None

    async def exercise():
        nonlocal entered
        entered = asyncio.Event()
        read_block = asyncio.Event()
        incoming = []
        message = {"jsonrpc": "2.0", "id": 9, "result": {"x": "汉"}}
        raw = packet(message)
        if case == "fragments":
            incoming.extend([raw[:7], raw[7:19], raw[19:]])
        if case == "two-frames":
            incoming.append(raw + packet({"id": 10, "result": False}))
        if case == "header-budget":
            incoming.extend([b"x" * 17, b""])
        if case == "length-missing":
            incoming.append(b"Other: 2\r\n\r\n{}")
        if case == "length-negative":
            incoming.append(b"Content-Length: -1\r\n\r\n")
        if case == "length-invalid":
            incoming.append(b"Content-Length: x\r\n\r\n")
        if case == "json-invalid":
            incoming.append(b"Content-Length: 1\r\n\r\nx")
        if case == "json-array":
            incoming.append(b"Content-Length: 2\r\n\r\n[]")
        if case == "mid-frame":
            incoming.extend([b"Content-Length: 5\r\n\r\nxx", b""])
        ticks = iter([10.0, 10.007])
        monkeypatch.setitem(
            LspClient._request.__globals__,
            "time",
            SimpleNamespace(monotonic=lambda: next(ticks)),
        )
        # Pin both the original global limit and the receiver data binding when present.
        for method, name, attr, value in [
            (
                LspClient._write_message,
                "_MAX_MESSAGE_BYTES",
                "_max_message_bytes",
                16 if case == "write-budget" else 4 * 1024 * 1024,
            ),
            (LspClient._read_message, "_MAX_HEADER_BYTES", "_max_header_bytes", 16),
            (
                LspClient._request,
                "_MAX_PENDING_REQUESTS",
                "_max_pending_requests",
                1 if case == "capacity" else 128,
            ),
        ]:
            if name in method.__globals__:
                monkeypatch.setitem(method.__globals__, name, value)
            if hasattr(LspClient, attr):
                monkeypatch.setattr(LspClient, attr, value)

        class Handle:
            closed = False

            async def write_stdin(self, body):
                trace.append(["write", body.hex()])
                entered.set()
                if case == "write-error":
                    raise OSError("write failure")
                if case == "cancel-write":
                    await asyncio.Event().wait()
                data = json.loads(body.partition(b"\r\n\r\n")[2])
                if "id" in data:
                    captured.extend(client._pending.values())
                    if case in {"request-ok", "graceful"}:
                        await client._dispatch({"id": data["id"], "result": "ok"})
                    elif case in {"request-error", "request-transient"}:
                        await client._dispatch(
                            {
                                "id": data["id"],
                                "error": {
                                    "code": -32801
                                    if case == "request-transient"
                                    else -32000
                                },
                            }
                        )

            async def read_stdout(self, max_bytes=65536):
                trace.append(["read", max_bytes])
                if case == "reader-error":
                    raise OSError("read failure")
                if case == "reader-cancel":
                    await read_block.wait()
                return incoming.pop(0) if incoming else b""

            async def close(self):
                trace.append(["close"])
                self.closed = True
                if case in {"close-fault", "both-close-faults"}:
                    raise RuntimeError("close failure")

            async def wait(self):
                trace.append(["wait"])
                return ProcessExit(0)

        def on_close():
            trace.append(["on-close", client._state])
            if case == "reader-callback-error":
                raise ValueError("callback failure")

        handle = Handle()
        client = LspClient(
            handle,
            request_timeout_seconds=0.002,
            shutdown_timeout_seconds=0.02,
            on_close=on_close,
        )
        result = None
        failure = None
        try:
            if case.startswith("write"):
                await client._write_message(MappingProxyType({"汉": (1, 2), 4: "x"}))
            elif case in {
                "fragments",
                "two-frames",
                "header-budget",
                "length-missing",
                "length-negative",
                "length-invalid",
                "json-invalid",
                "json-array",
                "eof",
                "mid-frame",
            }:
                result = await client._read_message()
                if case == "two-frames":
                    result = [result, await client._read_message()]
            elif case in {"method-invalid", "response-id-bool", "response-unknown"}:
                await client._dispatch(
                    {"method": 8}
                    if case == "method-invalid"
                    else {"id": True if case == "response-id-bool" else 4, "result": 0}
                )
            elif case.startswith("reader-"):
                reader = asyncio.create_task(
                    client._reader_loop(), name="frozen-reader"
                )
                client._reader_task = reader
                pending = asyncio.get_running_loop().create_future()
                client._pending[1] = pending
                captured.append(pending)
                if case == "reader-cancel":
                    await asyncio.sleep(0)
                    reader.cancel()
                try:
                    await reader
                except asyncio.CancelledError:
                    trace.append(["reader-cancelled"])
                await (
                    client.abort()
                )  # Preserve old closed-abort short circuit after fatal reads.
            elif case in {
                "shutdown",
                "graceful",
                "abort",
                "close-fault",
                "settle-fault",
                "both-close-faults",
                "closed-abort",
            }:
                for key in [1, 2]:
                    future = asyncio.get_running_loop().create_future()
                    client._pending[key] = future
                    captured.append(future)
                client._next_request_id = 3
                if case in {"settle-fault", "both-close-faults"}:

                    async def failed():
                        raise RuntimeError("reader settlement failure")

                    client._reader_task = asyncio.create_task(failed())
                    await asyncio.sleep(0)
                if case == "closed-abort":
                    client._state = "closed"
                if case == "graceful":
                    client._initialized = True
                await (
                    client.abort()
                    if case in {"abort", "closed-abort"}
                    else client.shutdown()
                )
            else:
                if case == "closed-request":
                    client._state = "closed"
                if case == "capacity":
                    client._pending[99] = asyncio.get_running_loop().create_future()
                    captured.append(client._pending[99])
                if case.startswith("cancel-"):
                    task = asyncio.create_task(
                        client._request(
                            "example",
                            {"x": 1},
                            timeout_seconds=None,
                            allow_closing=False,
                        )
                    )
                    await entered.wait()
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError as exc:
                        failure = exception_value(exc)
                else:
                    result = await client._request(
                        "example", {"x": 1}, timeout_seconds=None, allow_closing=False
                    )
        except BaseException as exc:
            failure = exception_value(exc)
        futures = []
        for future in captured:
            futures.append(
                {
                    "done": future.done(),
                    "cancelled": future.cancelled(),
                    "error": exception_value(future.exception())
                    if future.done() and not future.cancelled()
                    else None,
                }
            )
        observed = {
            "result": result,
            "error": failure,
            "trace": trace,
            "state": client._state,
            "is_closed": client.is_closed,
            "handle_closed": handle.closed,
            "buffer": bytes(client._buffer).hex(),
            "pending": sorted(client._pending),
            "count": client.request_count,
            "timeout_count": client.timeout_count,
            "duration_ms": client.last_request_duration_ms,
            "last_error": client.last_error,
            "futures": futures,
        }
        for future in captured:
            if not future.done():
                future.cancel()
        if client._reader_task is not None and not client._reader_task.done():
            client._reader_task.cancel()
            with suppress(BaseException):
                await client._reader_task
        return observed

    observed = asyncio.run(exercise())
    if case in {"request-ok", "graceful"}:
        assert observed["error"] is None, observed
    if case in {"cancel-write", "cancel-wait"}:
        assert observed["error"]["type"] == "asyncio.exceptions.CancelledError"
    expected = json.loads(gzip.decompress(EXPECTED.read_bytes()))
    assert observed == expected[case]
