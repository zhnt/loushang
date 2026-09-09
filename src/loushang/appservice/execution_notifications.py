"""Bounded synchronous Product lifecycle delivery, outside content mailboxes."""

import asyncio
from collections.abc import Callable

from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError

from .execution_contract import ExecutionObservationV1, ExecutionOutcomeV1


def observe_execution_task(task: asyncio.Task[ExecutionOutcomeV1]) -> None:
    if not task.cancelled():
        task.exception()


class ExecutionObserversV1:
    def __init__(self) -> None:
        self._listeners: set[Callable[[ExecutionObservationV1], None]] = set()

    def subscribe(
        self, listener: Callable[[ExecutionObservationV1], None],
    ) -> Callable[[], None]:
        if not callable(listener):
            raise TypeError("execution observer must be callable")
        if len(self._listeners) >= 8:
            raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    def emit(self, observation: ExecutionObservationV1) -> None:
        for listener in tuple(self._listeners):
            try:
                listener(observation)
            except (Exception, asyncio.CancelledError) as error:
                asyncio.get_running_loop().call_exception_handler({
                    "message": "execution lifecycle observer failed",
                    "exception": error,
                })
