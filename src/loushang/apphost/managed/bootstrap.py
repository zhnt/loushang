"""Optional child-process control composition; no Product selection or CLI.

Open/close are synchronous bootstrap operations, outside an application event
loop. A trusted process entry retains this owner before opening resources and
retains its bound child owner until application cleanup has completed.
"""

from __future__ import annotations

import asyncio
import os
import socket
import sys
from pathlib import Path
from threading import RLock, current_thread, main_thread
from time import monotonic

from loushang.appservice.managed_mux import ManagedMuxServiceBindingV1
from loushang.hosting.service import LinuxServiceObserverV1

from ._files import ManagedStorageError, PrivateManagedDirectory, _check_deadline
from ._lifetime import _ChildLifetime
from ._process import _ChildProcess
from .child import ManagedChildApplicationPortV1, ManagedChildApplicationV1
from .contracts import (
    _HEX32,
    ManagedContractError,
    ManagedInstanceRefV1,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
    _match,
)
from .event_log import ManagedLifecycleEventV1, ManagedLifecycleLogV1
from .handoff import ManagedChildControlV1
from .lifecycle import ManagedServiceJournalV1
from .mux_management import ManagedMuxManagerV1
from .output_capture import ManagedOutputCaptureFactory
from .paths import ManagedDeploymentPathsV1, resolve_managed_paths
from .registry import ManagedRegistryV1
from .storage_budget import ManagedStorageBudgetV1
from .trace_buffer import ManagedTraceBuffer
from .trace_log import ManagedTraceLog


class ManagedChildBootstrapV1:
    """Own one child's control dependencies, without owning its run waiter.

    Namespace and instance values are lookups, not authority. Only the child's
    existing durable/native handoff may permit application activation. Failed
    admissions keep their containers; successful dependencies are never swapped.
    """

    def __init__(
        self, namespace: ManagedNamespaceV1, service: ManagedServiceKeyV1,
        instance: ManagedInstanceRefV1, attempt_id: str, endpoint: socket.socket,
        *, runtime_root: str, temporary_override: str | None = None,
        diagnostics: bool = False,
    ) -> None:
        paths = resolve_managed_paths(namespace, service, instance, runtime_root=runtime_root,
                                      temporary_override=temporary_override)
        _match(attempt_id, _HEX32)
        if namespace.user_id != os.geteuid() or type(endpoint) is not socket.socket or type(diagnostics) is not bool:
            raise ManagedContractError()
        try:
            if (endpoint.family != socket.AF_UNIX or endpoint.fileno() < 3
                    or endpoint.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM):
                raise ManagedContractError()
            endpoint.getpeername()
            endpoint.set_inheritable(False)
        except OSError:
            raise ManagedContractError() from None
        self._namespace, self._service = namespace, service
        self._instance, self._attempt = instance, attempt_id
        self._paths = paths
        self._diagnostics_enabled = diagnostics
        self._log_directory = PrivateManagedDirectory(Path(paths.logs), defer_open=True) if diagnostics else None
        self._log_writer: ManagedLifecycleLogV1 | None = None
        self._log_attempted = self._log_failed = False
        self._log_open_attempted = self._log_opened = False
        self._trace_buffer: ManagedTraceBuffer | None = None
        self._trace_writer: ManagedTraceLog | None = None
        self._trace_failed = False
        self._trace_sink_installed = False
        self._endpoint: socket.socket | None = endpoint
        self._registry: ManagedRegistryV1 | None = None
        self._capture_directory: PrivateManagedDirectory | None = None
        self._capture_factory: ManagedOutputCaptureFactory | None = None
        self._journal: ManagedServiceJournalV1 | None = None
        self._observer: LinuxServiceObserverV1 | None = None
        self._control: ManagedChildControlV1 | None = None
        self._child: ManagedChildApplicationV1 | None = None
        self._lifetime: _ChildLifetime | None = None
        self._process: _ChildProcess | None = None
        self._mux_manager: ManagedMuxManagerV1 | None = None
        self._registry_ready = self._journal_ready = False
        self._native_attempted = self._native_uncertain = False
        self._observer_close_uncertain = self._endpoint_close_uncertain = False
        self._opened = self._closing = False
        self._deadline: float | None = None
        self._mutex = RLock()

    @property
    def paths(self) -> ManagedDeploymentPathsV1:
        return self._paths

    @property
    def cleanup_pending(self) -> bool:
        return self._application_cleanup_pending() or bool(self._process is not None and self._process.cleanup_pending)

    def _application_cleanup_pending(self) -> bool:
        return self._resources_pending() or bool(self._lifetime is not None and self._lifetime.cleanup_pending)

    def _resources_pending(self) -> bool:
        return bool(
            self._endpoint is not None or self._registry is not None or self._journal is not None
            or self._log_directory is not None
            or self._capture_directory is not None
            or self._observer is not None or self._control is not None or self._native_uncertain
            or (self._child is not None and self._child.cleanup_pending)
        )

    def open(self, *, deadline: float) -> None:
        """Admit existing paths with one frozen absolute bootstrap deadline.

        A retry may finish an earlier failed admission, never extend its budget,
        replace successful dependencies, recapture uncertain native resources or
        change the durable service generation. Caller owns scheduling retries.
        """
        if type(deadline) not in (int, float) or not 0 < deadline <= 1e12:
            raise ManagedContractError()
        _outside_loop()
        if not self._mutex.acquire(blocking=False):
            raise ManagedStorageError("busy")
        try:
            if self._closing or self._opened or self._child is not None:
                raise ManagedStorageError("closed")
            _check_deadline(deadline)
            self._deadline = deadline if self._deadline is None else min(deadline, self._deadline)
            deadline = self._deadline
            _check_deadline(deadline)
            if self._native_uncertain:
                raise ManagedStorageError("unavailable")
            if not self._registry_ready:
                if self._registry is not None:
                    self._registry.close()
                    self._registry = None
                _check_deadline(deadline)
                self._registry = ManagedRegistryV1(Path(self._paths.registry), self._namespace, defer_open=True)
                self._registry.open(deadline=deadline)
                self._registry_ready = True
            assert self._registry is not None
            if not self._journal_ready:
                if self._journal is not None:
                    self._journal.close()
                    self._journal = None
                _check_deadline(deadline)
                self._journal = ManagedServiceJournalV1(
                    self._registry, self._namespace, self._service, Path(self._paths.lifecycle), defer_open=True,
                )
                self._journal.open(deadline=deadline)
                self._journal_ready = True
            assert self._journal is not None
            _check_deadline(deadline)
            if not self._native_attempted:
                self._native_attempted = True
                try:
                    self._observer = LinuxServiceObserverV1.capture(os.getpid())
                except BaseException:
                    # The capture factory may have acquired native descriptors
                    # before failing; absent a returned owner, do not invent a
                    # clean receipt or repeat the native effect in this process.
                    self._native_uncertain = True
                    raise
            assert self._observer is not None
            state = self._journal.read(deadline=deadline)
            if (state is None or state.handoff.instance != self._instance
                    or state.handoff.attempt_id != self._attempt
                    or (state.native_identity is not None and state.native_identity != self._observer.identity)):
                raise ManagedStorageError("conflict")
            _check_deadline(deadline)
            if self._control is None:
                assert self._endpoint is not None
                self._control = ManagedChildControlV1(
                    self._journal, self._instance, self._attempt, self._observer.identity, self._endpoint,
                )
                self._endpoint = None  # The control now owns the same socket.
            _check_deadline(deadline)
            self._opened = True
        finally:
            self._mutex.release()

    def managed_mux_binding(self, *, application_id: str) -> ManagedMuxServiceBindingV1:
        """Borrow admitted control storage before binding the application.

        This pure binding neither issues a permit nor claims COMMITTED. The
        original manager rechecks durable authority at each creation admission;
        its dependencies remain owned here through child application cleanup.
        """
        if not self._mutex.acquire(blocking=False):
            raise ManagedStorageError("busy")
        try:
            if self._closing or not self._opened or self._child is not None:
                raise ManagedStorageError("closed")
            assert self._registry is not None and self._journal is not None and self._observer is not None
            if self._mux_manager is None:
                self._mux_manager = ManagedMuxManagerV1(
                    self._registry, self._journal, self._namespace, self._service,
                    self._instance, application_id=application_id,
                    startup_attempt_id=self._attempt, startup_native_identity=self._observer.identity,
                )
            binding = self._mux_manager.binding()
            if binding.application_id != application_id:
                raise ManagedStorageError("conflict")
            return binding
        finally:
            self._mutex.release()

    def output_capture_factory(self, *, deadline: float) -> ManagedOutputCaptureFactory:
        """Open the admitted instance scratch root before binding its Product."""
        _outside_loop()
        if not self._mutex.acquire(blocking=False):
            raise ManagedStorageError("busy")
        try:
            if self._closing or not self._opened or self._child is not None:
                raise ManagedStorageError("closed")
            if self._capture_factory is None:
                if self._capture_directory is None:
                    self._capture_directory = PrivateManagedDirectory(Path(self._paths.temporary), defer_open=True)
                self._capture_directory.open(deadline=deadline)
                assert self._registry is not None
                self._capture_factory = ManagedOutputCaptureFactory(
                    self._capture_directory, ManagedStorageBudgetV1(self._registry),
                    service_id=self._service.service_id, instance_id=self._instance.instance_id,
                )
            return self._capture_factory
        finally:
            self._mutex.release()

    def prepare_trace(self, *, deadline: float) -> ManagedTraceBuffer:
        """Freeze one explicit trace window before binding; no filesystem IO."""
        _outside_loop()
        _check_deadline(deadline)
        if not self._mutex.acquire(blocking=False):
            raise ManagedStorageError("busy")
        try:
            if self._closing or not self._opened or self._child is not None:
                raise ManagedStorageError("closed")
            if self._trace_buffer is not None:
                if self._trace_buffer.deadline != deadline:
                    raise ManagedStorageError("conflict")
                return self._trace_buffer
            self._trace_buffer = ManagedTraceBuffer(self._instance.instance_id, deadline)
            if self._log_directory is None:
                self._log_directory = PrivateManagedDirectory(Path(self._paths.logs), defer_open=True)
            return self._trace_buffer
        finally:
            self._mutex.release()

    def trace_sink_installed(self, buffer: ManagedTraceBuffer) -> None:
        """Trusted dedicated-process composition confirms its installed sink.

        Call inside the public observability context, after bind and before run.
        This is not an applied receipt: native storage and publication happen
        later on the original child diagnostics worker.
        """
        _outside_loop()
        if not self._mutex.acquire(blocking=False):
            raise ManagedStorageError("busy")
        try:
            if (self._closing or self._child is None or buffer is not self._trace_buffer
                    or self._process is not None or self._lifetime is not None):
                raise ManagedStorageError("conflict")
            self._trace_sink_installed = True
        finally:
            self._mutex.release()

    def bind(
        self, application: ManagedChildApplicationPortV1, *, startup_timeout: float = 30.0,
        settlement_timeout: float = 30.0,
    ) -> ManagedChildApplicationV1:
        """Adopt an unstarted application once; this operation does no native IO."""
        if not self._mutex.acquire(blocking=False):
            raise ManagedStorageError("busy")
        try:
            if self._closing or not self._opened or self._child is not None:
                raise ManagedStorageError("closed")
            assert self._control is not None
            child = ManagedChildApplicationV1(
                application, self._control, startup_timeout=startup_timeout, settlement_timeout=settlement_timeout,
                diagnostic=self._record_lifecycle if self._diagnostics_enabled else None,
                trace_buffer=self._trace_buffer,
                trace_write=self._record_trace if self._trace_buffer is not None else None,
                trace_initialize=self._apply_trace if self._trace_buffer is not None else None,
            )
            self._child = child
            return child
        finally:
            self._mutex.release()

    def _record_lifecycle(self, event: str, code: str | None) -> None:
        """One original diagnostic job; identity check releases before log IO.

        Native process/scope lifetime still prevents successor activation while
        this job runs. Log records themselves never establish that authority.
        """
        _outside_loop()
        if self._log_failed:
            raise ManagedStorageError("closed")
        deadline = monotonic() + 2
        try:
            assert self._journal is not None and self._observer is not None and self._registry is not None
            state = self._journal.read(deadline=deadline, wait_for_lock=True)
            if (state is None or state.handoff.instance != self._instance
                    or state.handoff.attempt_id != self._attempt
                    or state.native_identity != self._observer.identity):
                raise ManagedStorageError("conflict")
            # No journal/service fence crosses directory admission or writing.
            directory = self._log_directory
            assert directory is not None
            if not self._log_attempted:
                self._log_attempted = True
                self._open_log_directory(deadline)
                self._log_writer = ManagedLifecycleLogV1(directory, ManagedStorageBudgetV1(self._registry),
                                                        self._service.service_id)
            assert self._log_writer is not None
            self._log_writer.write(ManagedLifecycleEventV1(event, self._instance.instance_id, code), deadline=deadline)
        except BaseException:
            self._log_failed = True
            raise

    def _open_log_directory(self, deadline: float) -> None:
        # Both formats run on the same diagnostic slot and borrow this single
        # one-shot native admission. A failed open is never retried by its peer.
        if self._log_opened:
            return
        if self._log_open_attempted:
            raise ManagedStorageError("closed")
        self._log_open_attempted = True
        assert self._log_directory is not None
        self._log_directory.open(deadline=deadline)
        self._log_opened = True

    def _apply_trace(self) -> None:
        """Admit storage, then publish an exact historical application fact."""
        _outside_loop()
        if self._trace_failed:
            raise ManagedStorageError("closed")
        try:
            if not self._trace_sink_installed or self._trace_buffer is None or self._child is None:
                raise ManagedStorageError("conflict")
            deadline = self._trace_buffer.deadline
            _check_deadline(deadline)
            assert self._journal is not None and self._observer is not None and self._registry is not None
            state = self._journal.read(deadline=min(deadline, monotonic() + 2), wait_for_lock=True)
            if (state is None or state.handoff.instance != self._instance
                    or state.handoff.attempt_id != self._attempt or state.handoff.stop_requested
                    or state.native_identity != self._observer.identity):
                raise ManagedStorageError("conflict")
            self._open_log_directory(deadline)
            assert self._log_directory is not None
            if self._trace_writer is None:
                self._trace_writer = ManagedTraceLog(self._log_directory, ManagedStorageBudgetV1(self._registry),
                                                    self._service.service_id)
            self._trace_writer.prepare(deadline=deadline)
            # Directory locks have left scope before the original service fence.
            self._journal.record_trace_application(self._instance, self._attempt,
                native_identity=self._observer.identity, trace_deadline_ms=round(deadline * 1000),
                deadline=deadline)
        except BaseException:
            self._trace_failed = True
            raise

    def _record_trace(self, frame: bytes, deadline: float) -> None:
        _outside_loop()
        if self._trace_failed:
            raise ManagedStorageError("closed")
        try:
            if self._trace_buffer is None or deadline != self._trace_buffer.deadline:
                raise ManagedStorageError("conflict")
            _check_deadline(deadline)
            assert self._journal is not None and self._observer is not None and self._registry is not None
            state = self._journal.read(deadline=min(deadline, monotonic() + 2), wait_for_lock=True)
            if (state is None or state.handoff.instance != self._instance
                    or state.handoff.attempt_id != self._attempt
                    or state.native_identity != self._observer.identity):
                raise ManagedStorageError("conflict")
            self._open_log_directory(deadline)
            assert self._log_directory is not None
            if self._trace_writer is None:
                self._trace_writer = ManagedTraceLog(self._log_directory, ManagedStorageBudgetV1(self._registry),
                                                    self._service.service_id)
            self._trace_writer.write(frame, deadline=deadline)
        except BaseException:
            self._trace_failed = True
            raise

    async def run(self) -> int:
        """Run the bound child and await complete settlement on the same loop.

        Waiter cancellation does not stop the service. The process composition
        must keep this loop alive and rejoin; it may exit only after a result.
        Returns 0 for clean success, 1 for a failure that ultimately settled.
        Permanent unknown cleanup debt intentionally has no exit result.
        """
        if not self._mutex.acquire(blocking=False):
            raise ManagedStorageError("busy")
        try:
            if self._process is not None and not self._process.accepts_loop(asyncio.get_running_loop()):
                raise ManagedStorageError("conflict")
            if self._lifetime is None:
                if self._closing or not self._opened or self._child is None:
                    raise ManagedStorageError("closed")
                self._lifetime = _ChildLifetime(self._child, self)
            lifetime = self._lifetime
        finally:
            self._mutex.release()
        return await lifetime.run()

    def run_process(self) -> int:
        """Run once in a dedicated Linux child, owning signals until OS exit.

        Must be called after bind and before any run waiter. The existing
        application driver settles first, then this process shell settles its
        Runner. INT/TERM remain graceful-only and HUP remains ignored after
        return; the caller may finalize diagnostics and exit, not reuse this
        process for another application. Embedded callers must use run(), which
        does not alter signal policy. Neither cleanup domain may hide the other.
        """
        _outside_loop()
        if sys.platform != "linux" or current_thread() is not main_thread():
            raise ManagedStorageError("unsupported")
        if not self._mutex.acquire(blocking=False):
            raise ManagedStorageError("busy")
        try:
            if self._closing or not self._opened or self._child is None or self._lifetime is not None or self._process is not None:
                raise ManagedStorageError("closed")
            self._process = _ChildProcess(self, self._child)
        finally:
            self._mutex.release()
        return self._process.run()

    def close(self) -> None:
        """Release borrowed dependencies only after the bound child has settled.

        Partial close permanently fences open/bind. Failed resource objects stay
        retained, and a failed journal close keeps its registry dependency live.
        Native observer/socket close ambiguity is debt, not a retryable fd right.
        """
        _outside_loop()
        if not self._mutex.acquire(blocking=False):
            raise ManagedStorageError("busy")
        try:
            if self._child is not None and self._child.cleanup_pending:
                raise ManagedStorageError("busy")
            if self._capture_factory is not None and not self._capture_factory.settled:
                self._capture_factory.close_unstarted()
            self._closing = True
            if self._trace_buffer is not None:
                self._trace_buffer.discard()
            errors: list[BaseException] = []
            if self._capture_directory is not None:
                try:
                    self._capture_directory.close()
                    self._capture_directory = None
                    self._capture_factory = None
                except BaseException as error:
                    errors.append(error)
            if self._log_directory is not None:
                try:
                    self._log_directory.close()
                    self._log_directory = None
                    self._log_writer = None
                    self._trace_writer = None
                except BaseException as error:
                    errors.append(error)
            if self._control is not None:
                try:
                    self._control.close()
                    self._control = None
                except BaseException as error:
                    errors.append(error)
            if self._endpoint is not None and not self._endpoint_close_uncertain:
                try:
                    self._endpoint.close()
                    self._endpoint = None
                except BaseException as error:
                    self._endpoint_close_uncertain = True
                    errors.append(error)
            if (self._log_directory is None and self._capture_directory is None
                    and self._observer is not None and not self._observer_close_uncertain):
                try:
                    self._observer.close()
                    self._observer = None
                except BaseException as error:
                    self._observer_close_uncertain = True
                    errors.append(error)
            if self._log_directory is None and self._capture_directory is None and self._journal is not None:
                try:
                    self._journal.close()
                    self._journal = None
                except BaseException as error:
                    errors.append(error)
            if self._journal is None and self._capture_directory is None and self._registry is not None:
                try:
                    self._registry.close()
                    self._registry = None
                except BaseException as error:
                    errors.append(error)
            for failure in errors:
                if not isinstance(failure, Exception):
                    failure.add_note("managed_bootstrap_cleanup_incomplete")
                    raise failure
            if (self._resources_pending() or (self._lifetime is not None and self._lifetime.close_unknown)
                    or (self._process is not None and self._process.unknown)):
                raise ManagedStorageError("unavailable") from None
        finally:
            self._mutex.release()


def _outside_loop() -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise ManagedStorageError("busy")


__all__ = ["ManagedChildBootstrapV1"]
