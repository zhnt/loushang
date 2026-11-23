"""Bounded stdout and lifecycle observations for one explicitly selected process."""

from __future__ import annotations

import asyncio
from typing import Literal, Protocol

from loushang.foundation._owned_tasks import _try_settle_owned_closes

from .contracts import (
    HostingObservation,
    HostingObservationSink,
    LaunchPreparationPort,
    ProcessExit,
    ProcessHostingPort,
    ProcessLaunchRequest,
    ProcessLease,
)


class _ProcessHostFactory(Protocol):
    def __call__(
        self, *, observation_sink: HostingObservationSink | None = None
    ) -> ProcessHostingPort: ...


class _ProcessProbeOutputError(ValueError):
    def __init__(self, reason: Literal["oversize", "trailing_data"]) -> None:
        super().__init__(reason)
        self.reason = reason


class _ProcessProbe:
    """Keep process custody until both the lease and host have settled."""

    def __init__(
        self,
        host_factory: _ProcessHostFactory,
        *,
        max_output_bytes: int,
        max_transitions: int,
    ) -> None:
        self._host_factory = host_factory
        self._max_output_bytes = max_output_bytes
        self._max_transitions = max_transitions
        self._host: ProcessHostingPort | None = None
        self._lease: ProcessLease | None = None
        self._close_lock = asyncio.Lock()
        self.closed = False
        self.overflow = False
        self.transitions: list[str] = []
        self._backend_ids: list[str] = []

    def observe(self, observation: HostingObservation) -> None:
        if (
            type(observation) is not HostingObservation
            or len(self.transitions) >= self._max_transitions
        ):
            self.overflow = True
            return
        self.transitions.append(observation.transition.value)
        if (
            observation.backend_id is not None
            and observation.backend_id not in self._backend_ids
        ):
            self._backend_ids.append(observation.backend_id)

    def backend_id(self) -> str | None:
        return self._backend_ids[0] if len(self._backend_ids) == 1 else None

    async def run(
        self,
        request: ProcessLaunchRequest,
        preparation: LaunchPreparationPort,
        *,
        timeout_seconds: float,
    ) -> tuple[bytes, ProcessExit]:
        self._host = self._host_factory(observation_sink=self)
        async with asyncio.timeout(timeout_seconds):
            lease = await self._host.start(request, preparation)
            self._lease = lease
            output = await self._read_stdout(lease)
            exited = await lease.wait()
        return output, exited

    async def close(self) -> bool:
        async with self._close_lock:
            if self.closed:
                return True
            lease, host = self._lease, self._host
            if not await _try_settle_owned_closes(
                (lambda: lease.close()) if lease is not None else None,
                (lambda: host.close()) if host is not None else None,
            ):
                return False
            self.closed = True
            self._lease = None
            self._host = None
            return True

    async def _read_stdout(self, lease: ProcessLease) -> bytes:
        output = bytearray()
        while len(output) <= self._max_output_bytes and b"\n" not in output:
            chunk = await lease.read_stdout(self._max_output_bytes + 1 - len(output))
            if not chunk:
                break
            output.extend(chunk)
        if len(output) > self._max_output_bytes:
            raise _ProcessProbeOutputError("oversize")
        if b"\n" in output and await lease.read_stdout(1):
            raise _ProcessProbeOutputError("trailing_data")
        return bytes(output)
