"""Startup handoff from a local application command to its ready deployment."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from secrets import token_hex
from typing import Protocol

from loushang.appserver.local_record import (
    LocalConnectionDirectoryV1,
    LocalConnectionRecordV1,
    LocalRecordScopeV1,
)
from loushang.appserver.managed_mux import ManagedMuxCreatedV1, ManagedMuxCreateV1
from loushang.appservice.managed_mux import CommitMux, ManagedMuxServiceBindingV1
from loushang.hosting.foreground_service import foreground_stop_signals

from . import local
from .application import HostedApplicationError
from .continuity import HostedApplicationContinuityRuntimeV1
from .local import _LocalStartup, _require_budget, _wait


def publish_local_service_endpoint(endpoint: Path, value: dict[str, object]) -> None:
    """Publish the endpoint after the same deployment has signalled readiness."""
    temporary = endpoint.with_suffix(".tmp")
    temporary.write_text(json.dumps(value) + "\n")
    temporary.replace(endpoint)


@dataclass
class _ForegroundMuxAdmission:
    owner: ForegroundNamedMuxProvisioner
    request: ManagedMuxCreateV1

    async def acquire(self) -> None:
        if self.owner.fenced or self.owner.issued.get(self.request.operation_id) != self.request:
            raise ValueError("foreground_mux_fenced")

    def check_creation(self, previous: ManagedMuxCreatedV1 | None) -> None:
        if previous is not None and (previous.operation_id, previous.name) != (
            self.request.operation_id, self.request.name,
        ):
            raise ValueError("foreground_mux_conflict")

    async def close(self) -> None:
        # This permit borrows process-local authority without a native lease.
        return None


class ForegroundNamedMuxProvisioner:
    """Fenced process-local admission for named Mux continuity and replay."""

    def __init__(self, application_root: Path, *, application_id: str) -> None:
        self.service = sha256(str(application_root).encode()).hexdigest()
        self.instance = token_hex(16)
        self.fenced = False
        self.issued: dict[str, ManagedMuxCreateV1] = {}
        self.binding = ManagedMuxServiceBindingV1(
            application_id, self.service, self.instance, self.prepare,
            ensure_named=self.ensure_named,
        )

    def fence(self) -> None:
        self.fenced = True

    def prepare(self, request: ManagedMuxCreateV1) -> _ForegroundMuxAdmission:
        if self.fenced or self.issued.get(request.operation_id) != request:
            raise ValueError("foreground_mux_not_admitted")
        return _ForegroundMuxAdmission(self, request)

    async def ensure_named(self, name: str, commit: CommitMux) -> None:
        operation = sha256(("foreground-named-mux/v1:" + name).encode()).hexdigest()[:32]
        request = self.issued.setdefault(operation, ManagedMuxCreateV1(
            self.service, self.instance, operation, name, token_hex(32),
        ))
        await commit(request)


class _LocalLaunchFacts(Protocol):
    """Only facts consumed by the shared local application lifetime."""

    @property
    def connection_root(self) -> Path: ...

    @property
    def endpoint(self) -> str: ...

    @property
    def session_discovery(self) -> bool: ...

    @property
    def scopes(self) -> tuple[LocalRecordScopeV1, ...]: ...


class _ApplicationAttempt(Protocol):
    async def open(self) -> HostedApplicationContinuityRuntimeV1: ...
    async def close(self) -> None: ...


class _LocalApplicationStartup(_LocalStartup):
    """Own an application attempt until its existing local deployment adopts it.

    This is the same command instance and retained tasks, never a second owner.
    Product subclasses select launch facts, attempt construction and root policy.
    """

    _launch: _LocalLaunchFacts
    _directory: LocalConnectionDirectoryV1
    _attempt: _ApplicationAttempt

    def __init__(self, startup_timeout: float, settlement_timeout: float) -> None:
        super().__init__(startup_timeout, settlement_timeout)
        self._application: HostedApplicationContinuityRuntimeV1 | None = None
        self._local: local.HostedLocalRuntimeV1 | None = None

    def _startup_accepting(self) -> bool:
        return self._local is not None and self._local.accepting

    def _prepare_session_roots(self) -> None:
        raise NotImplementedError

    def _session_execution(self) -> bool:
        raise NotImplementedError

    def _connection_instance(self) -> str | None:
        raise NotImplementedError

    def _mux_management(self) -> bool:
        raise NotImplementedError

    def _app_tunnel(self) -> LocalConnectionRecordV1 | None:
        return None

    def _check_retry_budget(self, value: float) -> None:
        _require_budget(value)

    @property
    def cleanup_pending(self) -> bool:
        return not self._settled

    async def _start_once(self) -> None:
        self._remaining_startup()
        await asyncio.to_thread(self._prepare_session_roots)
        self._remaining_startup()
        self._application = await self._attempt.open()
        self._remaining_startup()
        self._local = local.HostedLocalRuntimeV1(
            self._application,
            self._directory,
            self._launch.endpoint,
            scopes=self._launch.scopes,
            settlement_timeout=self._timeout,
            session_discovery=self._launch.session_discovery,
            session_execution=self._session_execution(),
            connection_instance=self._connection_instance(),
            mux_management=self._mux_management(),
            app_tunnel=self._app_tunnel(),
        )
        self._application = None  # AppHost has adopted both application and directory.
        await self._local.prepare(deadline=self._startup_deadline)
        self._remaining_startup()
        self._prepared = True

    async def _activate_once(self) -> None:
        self._remaining_startup()
        assert self._local is not None
        await self._local.activate()
        self._remaining_startup()

    async def wait_closed(self) -> None:
        if self._local is None:
            raise HostedApplicationError(f"{self._startup_error_prefix}_not_ready")
        await self._local.wait_closed()
        await self.close()

    async def run(self, *, ready: Callable[[], None] | None = None) -> None:
        try:
            await self.start()
            if ready is not None:
                ready()
            await self.wait_closed()
        finally:
            await self.close()

    async def run_under_service_manager(
        self, *, ready: Callable[[], None], include_interrupt: bool = False,
        fence_external_admission: Callable[[], None] | None = None,
    ) -> None:
        """Fence this startup on native stop and settle its original owner."""
        task = asyncio.current_task()
        assert task is not None
        stopping = False

        def stop() -> None:
            nonlocal stopping
            if stopping and not include_interrupt:
                return
            stopping = True
            if fence_external_admission is not None:
                fence_external_admission()
            self.fence()
            task.cancel()

        with foreground_stop_signals(stop, include_interrupt=include_interrupt):
            try:
                await self.run(ready=ready)
            except asyncio.CancelledError:
                if not stopping:
                    raise
                if fence_external_admission is None:
                    await self.close()
            finally:
                if fence_external_admission is not None:
                    fence_external_admission()
                    await self.close()

    async def close(self, *, retry_timeout: float | None = None) -> None:
        if retry_timeout is not None:
            self._check_retry_budget(retry_timeout)
        if self._settled:
            return
        self.fence()
        if self._deadline is None:
            self._deadline = asyncio.get_running_loop().time() + self._timeout
        await asyncio.shield(
            self._schedule_close(lambda: self._close_once(retry_timeout), retry_timeout)
        )

    def fence(self) -> None:
        """Revoke startup and client admission without creating a cleanup task."""
        self._closing = True
        if self._local is not None:
            # Fence lower-level activation before scheduling our close task.
            # An already queued activate must not publish in the intervening turn.
            self._local.fence()

    async def _close_once(self, retry_timeout: float | None) -> None:
        assert self._deadline is not None
        if self._local is not None:
            # Do not await the outer startup task first: it can itself be
            # waiting for this adopted deployment's start/close settlement.
            await self._local.close(retry_timeout=retry_timeout)
        await self._wait_for_startup_settlement(self._deadline)
        if self._local is None:
            self._directory.close()
            await self._phase(
                "application",
                self._application.close
                if self._application is not None
                else self._attempt.close,
            )
        self._settled = True

    async def _phase(
        self, name: str, operation: Callable[[], Coroutine[object, object, None]]
    ) -> None:
        assert self._deadline is not None
        await self._run_local_phase(name, operation, self._deadline)

    async def _wait_for_phase(self, task: asyncio.Task[None], deadline: float) -> None:
        await _wait(task, deadline, error_prefix=self._startup_error_prefix)
