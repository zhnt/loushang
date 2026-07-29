"""Channel-owned binding for the canonical session Work runtime."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, TextIO

from loushang.channel import (
    ChannelDelivery,
    ChannelDeliveryListener,
    ChannelError,
    ChannelEventDelivery,
    ChannelHost,
    ChannelOperationAccepted,
    ChannelOperationCancelled,
    ChannelOperationCancelRequest,
    ChannelOperationRequest,
)
from loushang.channel.types import ChannelEnvelope
from loushang.work.session import (
    SessionOperationInProgressError,
    SessionPromptPort,
    SessionWorkRuntime,
)
from loushang.work.types import WorkEvent, WorkOperation

Unsubscribe = Callable[[], None]
RuntimeEnvelopeProjector = Callable[
    [object, str | None],
    Sequence[ChannelEnvelope],
]


class SessionWorkChannelSession(SessionPromptPort, Protocol):
    """Session shape required by the shared Work-to-Channel binding."""

    @property
    def session_id(self) -> str: ...


@dataclass(frozen=True, slots=True)
class SessionWorkChannelProfile:
    """Product vocabulary for one Channel-exposed session operation."""

    product_name: str
    domain: str
    operation_kind: str

    def __post_init__(self) -> None:
        if not self.product_name.strip():
            raise ValueError("Channel product name must not be empty")
        if not self.domain.strip():
            raise ValueError("Channel operation domain must not be empty")
        if not self.operation_kind.strip():
            raise ValueError("Channel operation kind must not be empty")


class SessionWorkChannelPort:
    """Expose one session Work runtime through the standard Channel protocol."""

    def __init__(
        self,
        *,
        session: SessionWorkChannelSession,
        runtime: SessionWorkRuntime,
        profile: SessionWorkChannelProfile,
        project_runtime_envelopes: RuntimeEnvelopeProjector,
    ) -> None:
        self._session = session
        self._runtime = runtime
        self._profile = profile
        self._project_runtime_envelopes = project_runtime_envelopes
        self._work_runtime = runtime.work_runtime
        self._listeners: list[ChannelDeliveryListener] = []
        self._runtime_unsubscribe: Unsubscribe | None = None
        self._work_unsubscribe = self._work_runtime.subscribe_events(
            self._on_work_event
        )
        self._close_task: asyncio.Task[None] | None = None

    async def accept_operation(
        self,
        request: ChannelOperationRequest,
    ) -> ChannelOperationAccepted | ChannelError:
        operation = request.envelope.payload
        if not isinstance(operation, WorkOperation):
            return self._error(
                request,
                code="invalid_operation_payload",
                message="Channel operation payload must be a WorkOperation.",
            )
        if operation.domain != self._profile.domain:
            return self._error(
                request,
                code="unsupported_domain",
                message=(
                    f"{self._profile.product_name} Channel accepts only operations "
                    f"in the {self._profile.domain} domain."
                ),
            )
        if operation.kind != self._profile.operation_kind:
            return self._error(
                request,
                code="unsupported_operation",
                message=(
                    f"{self._profile.product_name} Channel supports only "
                    f"{self._profile.operation_kind}."
                ),
            )
        if operation.session_id not in (None, self._session.session_id):
            return self._error(
                request,
                code="session_mismatch",
                message=(
                    "operation session_id does not match the active "
                    f"{self._profile.product_name} session."
                ),
            )
        if self._work_runtime.active_runs(session_id=self._session.session_id):
            return self._error(
                request,
                code="operation_in_progress",
                message=(
                    f"the active {self._profile.product_name} session already has "
                    "a Channel operation."
                ),
                retryable=True,
            )
        try:
            _turn_payload(
                operation.payload,
                operation_kind=self._profile.operation_kind,
            )
        except ValueError as error:
            return self._error(
                request,
                code="invalid_operation_payload",
                message=str(error),
            )
        try:
            accepted = await self._runtime.accept_operation(operation)
        except SessionOperationInProgressError:
            return self._error(
                request,
                code="operation_in_progress",
                message=(
                    f"the active {self._profile.product_name} session already has "
                    "a Channel operation."
                ),
                retryable=True,
            )
        return ChannelOperationAccepted(
            request_id=request.request_id,
            operation_id=operation.operation_id,
            run_id=accepted.run_id,
        )

    async def cancel_operation(
        self,
        request: ChannelOperationCancelRequest,
    ) -> ChannelOperationCancelled | ChannelError:
        run = self._work_runtime.get_run_for_operation(request.operation_id)
        if run is None or run.status in {
            "completed",
            "failed",
            "cancelled",
            "orphaned",
        }:
            return ChannelError(
                code="unknown_operation",
                message=(
                    f"the {self._profile.product_name} session has no active "
                    "operation with this id."
                ),
                request_id=request.request_id,
            )
        try:
            await self._work_runtime.cancel(run.run_id)
        except Exception as error:
            return ChannelError(
                code="cancellation_failed",
                message=str(error) or type(error).__name__,
                request_id=request.request_id,
            )
        return ChannelOperationCancelled(
            request_id=request.request_id,
            operation_id=request.operation_id,
        )

    def subscribe_deliveries(
        self,
        listener: ChannelDeliveryListener,
    ) -> Unsubscribe:
        self._listeners.append(listener)
        if self._runtime_unsubscribe is None:
            self._runtime_unsubscribe = self._session.subscribe_runtime_events(
                self._on_runtime_event
            )

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)
            if not self._listeners:
                self._release_runtime_subscription()

        return unsubscribe

    def close(self) -> None:
        self._listeners.clear()
        self._release_runtime_subscription()
        self._work_unsubscribe()
        if self._work_runtime.active_runs() and self._close_task is None:
            self._close_task = asyncio.get_running_loop().create_task(
                self._work_runtime.dispose()
            )

    async def aclose(self) -> None:
        self.close()
        if self._close_task is not None:
            await self._close_task

    def _on_runtime_event(self, event: object) -> None:
        active_runs = self._work_runtime.active_runs(
            session_id=self._session.session_id
        )
        operation_id = active_runs[0].operation_id if active_runs else None
        for envelope in self._project_runtime_envelopes(event, operation_id):
            self._publish(ChannelEventDelivery(envelope=envelope))

    def _on_work_event(self, event: WorkEvent) -> None:
        self._publish(
            ChannelEventDelivery(
                envelope=ChannelEnvelope(
                    envelope_id=f"channel:work:{event.event_id}",
                    kind="event",
                    payload=event,
                )
            )
        )

    def _publish(self, delivery: ChannelDelivery) -> None:
        for listener in tuple(self._listeners):
            result = listener(delivery)
            if inspect.isawaitable(result):
                asyncio.ensure_future(result)

    def _release_runtime_subscription(self) -> None:
        unsubscribe = self._runtime_unsubscribe
        self._runtime_unsubscribe = None
        if unsubscribe is not None:
            unsubscribe()

    @staticmethod
    def _error(
        request: ChannelOperationRequest,
        *,
        code: str,
        message: str,
        retryable: bool = False,
    ) -> ChannelError:
        return ChannelError(
            code=code,
            message=message,
            request_id=request.request_id,
            retryable=retryable,
        )


async def run_session_work_channel_host(
    *,
    session: SessionWorkChannelSession,
    runtime: SessionWorkRuntime,
    profile: SessionWorkChannelProfile,
    project_runtime_envelopes: RuntimeEnvelopeProjector,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO | None = None,
) -> int:
    """Run the existing Channel host over one bound session Work runtime."""

    port = SessionWorkChannelPort(
        session=session,
        runtime=runtime,
        profile=profile,
        project_runtime_envelopes=project_runtime_envelopes,
    )
    host = ChannelHost(port=port, stdin=stdin, stdout=stdout, stderr=stderr)
    try:
        return await host.run()
    finally:
        await port.aclose()


def _turn_payload(
    payload: object,
    *,
    operation_kind: str,
) -> tuple[str, str | None]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{operation_kind} payload must be a JSON object.")
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{operation_kind} payload requires non-empty text.")
    streaming_behavior = payload.get("streaming_behavior")
    if streaming_behavior is None:
        return text, None
    if not isinstance(streaming_behavior, str) or not streaming_behavior:
        raise ValueError("streaming_behavior must be a non-empty string when set.")
    return text, streaming_behavior


__all__ = [
    "RuntimeEnvelopeProjector",
    "SessionWorkChannelPort",
    "SessionWorkChannelProfile",
    "SessionWorkChannelSession",
    "run_session_work_channel_host",
]
