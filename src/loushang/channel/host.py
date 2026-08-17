"""Injected stdio host for the standard Channel JSONL protocol."""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Protocol, TextIO

from loushang.channel.rpc_jsonl import (
    ChannelError,
    ChannelEventDelivery,
    ChannelOperationAccepted,
    ChannelOperationCancelled,
    ChannelOperationCancelRequest,
    ChannelOperationRequest,
    ChannelRpcFrame,
    decode_rpc_jsonl_frame,
    encode_rpc_jsonl_frame,
)
from loushang.channel.types import ChannelEnvelope
from loushang.harness.host.product_host import ProductHostRuntime

ChannelDelivery = ChannelEventDelivery | ChannelError
ChannelDeliveryListener = Callable[[ChannelDelivery], Awaitable[None] | None]
ChannelUnsubscribe = Callable[[], None]


class ChannelHostPort(Protocol):
    """Product-supplied operation, cancellation, and event-delivery port."""

    async def accept_operation(
        self, request: ChannelOperationRequest
    ) -> ChannelOperationAccepted | ChannelError: ...

    async def cancel_operation(
        self, request: ChannelOperationCancelRequest
    ) -> ChannelOperationCancelled | ChannelError: ...

    def subscribe_deliveries(
        self, listener: ChannelDeliveryListener
    ) -> ChannelUnsubscribe: ...


class ChannelHost:
    """Run standard Channel JSONL over injected Product behaviors."""

    def __init__(
        self,
        *,
        port: ChannelHostPort,
        stdin: TextIO,
        stdout: TextIO,
        stderr: TextIO | None = None,
    ) -> None:
        self._port = port
        self._stdin = stdin
        self._stdout = stdout
        self._stderr = sys.stderr if stderr is None else stderr
        self._runtime = ProductHostRuntime(stdin=stdin)
        self._operation_requests: dict[str, str] = {}
        self._unsubscribe: ChannelUnsubscribe | None = None

    async def run(self) -> int:
        """Consume standard request frames until EOF or :meth:`stop`."""

        self._unsubscribe = self._port.subscribe_deliveries(self.deliver)
        try:
            return await self._runtime.run(
                self.handle_line,
                handle_failure=self._handle_host_failure,
            )
        finally:
            self.stop()

    async def handle_line(self, line: str) -> None:
        """Decode and dispatch one client-provided standard Channel frame."""

        try:
            frame = decode_rpc_jsonl_frame(line)
        except (TypeError, ValueError) as error:
            self._write_frame(ChannelError(code="invalid_frame", message=str(error)))
            return

        if isinstance(frame, ChannelOperationRequest):
            await self._accept_operation(frame)
            return
        if isinstance(frame, ChannelOperationCancelRequest):
            await self._cancel_operation(frame)
            return

        self._write_frame(
            ChannelError(
                code="unsupported_client_frame",
                message=f"clients cannot send {type(frame).__name__}",
                request_id=_frame_request_id(frame),
            )
        )

    def stop(self) -> None:
        """Stop input processing and release the Product event subscription."""

        self._runtime.stop()
        unsubscribe = self._unsubscribe
        self._unsubscribe = None
        if unsubscribe is not None:
            unsubscribe()

    def deliver(self, delivery: ChannelDelivery) -> None:
        """Deliver one Product-projected event or transport error to the client."""

        if not isinstance(delivery, ChannelEventDelivery | ChannelError):
            raise TypeError(
                "channel delivery must be an event delivery or channel error"
            )
        if isinstance(delivery, ChannelEventDelivery):
            delivery = self._correlate_event_delivery(delivery)
        self._write_frame(delivery)

    async def _accept_operation(self, request: ChannelOperationRequest) -> None:
        try:
            result = await self._port.accept_operation(request)
        except Exception as error:
            self._write_frame(
                ChannelError(
                    code="operation_rejected",
                    message=str(error) or type(error).__name__,
                    request_id=request.request_id,
                )
            )
            return

        if isinstance(result, ChannelError):
            self._write_frame(_with_request_id(result, request.request_id))
            return
        if not isinstance(result, ChannelOperationAccepted):
            self._write_frame(_invalid_port_result(request.request_id))
            return
        operation_id = request.envelope.payload.operation_id
        if (
            result.request_id != request.request_id
            or result.operation_id != operation_id
        ):
            self._write_frame(_invalid_port_result(request.request_id))
            return
        self._operation_requests[operation_id] = request.request_id
        self._write_frame(result)

    async def _cancel_operation(self, request: ChannelOperationCancelRequest) -> None:
        try:
            result = await self._port.cancel_operation(request)
        except Exception as error:
            self._write_frame(
                ChannelError(
                    code="cancellation_rejected",
                    message=str(error) or type(error).__name__,
                    request_id=request.request_id,
                )
            )
            return

        if isinstance(result, ChannelError):
            self._write_frame(_with_request_id(result, request.request_id))
            return
        if not isinstance(result, ChannelOperationCancelled):
            self._write_frame(_invalid_port_result(request.request_id))
            return
        if (
            result.request_id != request.request_id
            or result.operation_id != request.operation_id
        ):
            self._write_frame(_invalid_port_result(request.request_id))
            return
        self._write_frame(result)

    async def _handle_host_failure(self, error: Exception) -> None:
        self._write_frame(
            ChannelError(
                code="host_failure", message=str(error) or type(error).__name__
            )
        )

    def _correlate_event_delivery(
        self, delivery: ChannelEventDelivery
    ) -> ChannelEventDelivery:
        if delivery.request_id is not None:
            return delivery
        operation_id = _event_operation_id(delivery.envelope)
        if operation_id is None:
            return delivery
        request_id = self._operation_requests.get(operation_id)
        if request_id is None:
            return delivery
        return replace(delivery, request_id=request_id)

    def _write_frame(self, frame: ChannelRpcFrame) -> None:
        self._stdout.write(encode_rpc_jsonl_frame(frame) + "\n")
        flush = getattr(self._stdout, "flush", None)
        if callable(flush):
            flush()


def _with_request_id(error: ChannelError, request_id: str) -> ChannelError:
    if error.request_id in (None, request_id):
        return replace(error, request_id=request_id)
    return _invalid_port_result(request_id)


def _invalid_port_result(request_id: str) -> ChannelError:
    return ChannelError(
        code="invalid_port_result",
        message="channel host port returned an invalid correlation result",
        request_id=request_id,
    )


def _frame_request_id(frame: ChannelRpcFrame) -> str | None:
    return getattr(frame, "request_id", None)


def _event_operation_id(envelope: ChannelEnvelope) -> str | None:
    payload = envelope.payload
    operation_id = getattr(payload, "operation_id", None)
    if isinstance(operation_id, str):
        return operation_id
    correlation_id = getattr(payload, "correlation_id", None)
    return correlation_id if isinstance(correlation_id, str) else None


__all__ = [
    "ChannelDelivery",
    "ChannelDeliveryListener",
    "ChannelHost",
    "ChannelHostPort",
    "ChannelUnsubscribe",
]
