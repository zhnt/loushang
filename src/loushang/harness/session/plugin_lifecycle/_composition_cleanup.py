"""Original Plugin composition cleanup, using the adopted facade state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial
from typing import Protocol

from loushang.harness.session._cleanup import run_cleanup_steps


class _Closeable(Protocol):
    def close(self) -> None: ...


class _CleanupFlags(Protocol):
    _runtime_closed: bool
    _management_released: bool
    _state_cleaned: bool
    _private_state_cleaned: bool
    _closed: bool


class _RetirementFlag(Protocol):
    _runtime_retired: bool


class _CompositionCleanup:
    __slots__ = ()
    runtime: _Closeable
    management_leases: Mapping[str, _Closeable]
    management_state_cleanup: Callable[[], None] | None
    state_cleanup: Callable[[], None] | None
    private_state_cleanup: Callable[[], None] | None
    _runtime_closed: bool
    _management_released: bool
    _state_cleaned: bool
    _private_state_cleaned: bool
    _closed: bool
    _cleanup_label: str

    def _close_runtime(self) -> None:
        state: _CleanupFlags = self
        if not self._runtime_closed:
            self.runtime.close()
            state._runtime_closed = True

    def _clean_management_state(self) -> None:
        state: _CleanupFlags = self
        if self.management_state_cleanup is not None:
            self.management_state_cleanup()
        state._management_released = True

    def _clean_composition_state(self) -> None:
        state: _CleanupFlags = self
        if self.state_cleanup is not None:
            self.state_cleanup()
        state._state_cleaned = True

    def _clean_private_state(self) -> None:
        state: _CleanupFlags = self
        if self.private_state_cleanup is not None:
            self.private_state_cleanup()
        state._private_state_cleaned = True

    def _release_management_leases(self) -> None:
        error = run_cleanup_steps(
            None,
            tuple(
                (f"{plugin_id} Session lifecycle release", lease.close)
                for plugin_id, lease in reversed(tuple(self.management_leases.items()))
            ),
        )
        if error is not None:
            raise error
        self._clean_management_state()


class _PreparationFailureCleanup(_CompositionCleanup):
    __slots__ = ()
    _released_plugin_ids: set[str]

    def adopt_cleanup_callbacks(
        self,
        *,
        management_state_cleanup: Callable[[], None] | None,
        state_cleanup: Callable[[], None] | None,
        private_state_cleanup: Callable[[], None] | None,
    ) -> None:
        for name, callback in (
            ("management_state_cleanup", management_state_cleanup),
            ("state_cleanup", state_cleanup),
            ("private_state_cleanup", private_state_cleanup),
        ):
            current = getattr(self, name)
            if current is not None and callback is not None and current is not callback:
                raise RuntimeError(
                    f"{self._cleanup_label} cleanup callback ownership changed"
                )
            if current is None:
                setattr(self, name, callback)

    def _release_failure_lease(self, plugin_id: str, lease: _Closeable) -> None:
        lease.close()
        self._released_plugin_ids.add(plugin_id)

    def close(self) -> None:
        # Runtime failure originally prevents every later cleanup stage.
        self._close_runtime()
        error = run_cleanup_steps(
            None,
            tuple(
                (
                    f"{plugin_id} Session lifecycle release",
                    partial(self._release_failure_lease, plugin_id, lease),
                )
                for plugin_id, lease in reversed(tuple(self.management_leases.items()))
                if plugin_id not in self._released_plugin_ids
            ),
        )
        if (
            len(self._released_plugin_ids) == len(self.management_leases)
            and not self._management_released
        ):
            error = run_cleanup_steps(
                error,
                (
                    (
                        f"{self._cleanup_label} management-state cleanup",
                        self._clean_management_state,
                    ),
                ),
            )
        if self._management_released and not self._state_cleaned:
            error = run_cleanup_steps(
                error,
                (
                    (
                        f"{self._cleanup_label} composition-state cleanup",
                        self._clean_composition_state,
                    ),
                ),
            )
        if self._state_cleaned and not self._private_state_cleaned:
            error = run_cleanup_steps(
                error,
                (
                    (
                        f"{self._cleanup_label} private-state cleanup",
                        self._clean_private_state,
                    ),
                ),
            )
        if error is not None:
            raise error


class _PreparedCompositionCleanup(_CompositionCleanup):
    __slots__ = ()
    _transferred: bool

    def close(self) -> None:
        state: _CleanupFlags = self
        if self._closed or self._transferred:
            return
        self._close_runtime()
        if not self._management_released:
            self._release_management_leases()
        if not self._state_cleaned:
            self._clean_composition_state()
        if not self._private_state_cleaned:
            self._clean_private_state()
        state._closed = (
            self._runtime_closed
            and self._management_released
            and self._state_cleaned
            and self._private_state_cleaned
        )


class _PublishedCompositionCleanup(_CompositionCleanup):
    __slots__ = ()
    _runtime_retired: bool

    def close(self) -> None:
        """Release verified revision handles before ownership transfers to Session."""
        state: _CleanupFlags = self

        if self._closed:
            return
        self._close_runtime()
        # Composition state is evidence for graph publication, not lifecycle
        # management state.  Once runtime evidence closes after publication it
        # can retire independently; management/private roots remain gated on
        # graph and owner retirement.
        if not self._state_cleaned:
            self._clean_composition_state()
        state._closed = self._runtime_closed and self._state_cleaned

    def confirm_runtime_retirement(
        self,
        *,
        graph_closed: bool,
        runtime_was_published: bool,
        graph_has_pending_retirements: bool,
        owner_generations_remaining: bool,
        component_generations_remaining: bool,
    ) -> None:
        """Accept cleanup eligibility only from a completely retired Session."""
        retirement: _RetirementFlag = self

        if (
            (runtime_was_published and not graph_closed)
            or graph_has_pending_retirements
            or owner_generations_remaining
            or component_generations_remaining
        ):
            raise RuntimeError(
                f"{self._cleanup_label} Plugin runtime retirement remains incomplete"
            )
        retirement._runtime_retired = True

    def release_management(self) -> None:
        if self._management_released:
            return
        if not self._runtime_retired:
            raise RuntimeError(
                f"{self._cleanup_label} Plugin management cannot release before retirement"
            )
        if not self._runtime_closed:
            raise RuntimeError(
                f"{self._cleanup_label} Plugin management cannot release before "
                "runtime evidence closes"
            )
        self._release_management_leases()

    def abort_unpublished(self) -> None:
        """Release an assembly that never published a Session graph."""
        state: _CleanupFlags = self
        retirement: _RetirementFlag = self

        retirement._runtime_retired = True
        self._close_runtime()
        self.release_management()
        if not self._state_cleaned:
            self._clean_composition_state()
        self.cleanup_private_state()
        state._closed = True

    def cleanup_private_state(self) -> None:
        """Delete disposable private data only after Provider retirement."""

        if self._private_state_cleaned:
            return
        if (
            not self._runtime_retired
            or not self._management_released
            or not self._state_cleaned
        ):
            raise RuntimeError(
                f"{self._cleanup_label} Plugin private state requires retirement evidence"
            )
        self._clean_private_state()
