"""Original Plugin composition cleanup, using the adopted facade state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial
from typing import TYPE_CHECKING, ClassVar, Protocol, Self

from loushang.harness.session._cleanup import run_cleanup_steps

from ._publication import OwnerReceiptGroups, _OwnerLeaseSet

if TYPE_CHECKING:
    from loushang.harness.capabilities.component_host import CapabilityComponentHost
    from loushang.harness.session.capability_composition_inputs import (
        SessionCapabilityCompositionInputs,
    )
    from loushang.harness.session.tool_owner_binding import _ReservedToolPackOwner

    from ._session_lease import _PluginSessionLease


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
    _failure_attribute: ClassVar[str]

    @classmethod
    def retained_on(cls, error: BaseException) -> Self | None:
        """Find the original cleanup owner through an exception chain."""
        current: BaseException | None = error
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            owner = getattr(current, cls._failure_attribute, None)
            if isinstance(owner, cls):
                return owner
            current = current.__cause__ or current.__context__
        return None

    def retain_on(self, error: BaseException) -> None:
        setattr(error, self._failure_attribute, self)

    def finish_failed_preparation(
        self,
        error: BaseException,
        *,
        cleanup_note_prefix: str,
        management_state_cleanup: Callable[[], None] | None,
        state_cleanup: Callable[[], None] | None,
        private_state_cleanup: Callable[[], None] | None,
    ) -> None:
        """Adopt remaining cleanup, retaining this owner if release fails."""
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
        try:
            self.close()
        except BaseException as cleanup_error:
            error.add_note(f"{cleanup_note_prefix}{cleanup_error}")
            self.retain_on(error)

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


class _PublishedCapabilityComposition(_PublishedCompositionCleanup):
    """Drive the same management leases for initial and on-demand publication."""

    __slots__ = ()
    management_leases: Mapping[str, _PluginSessionLease]
    component_host: CapabilityComponentHost
    session_inputs: SessionCapabilityCompositionInputs
    tool_owners: Mapping[str, _ReservedToolPackOwner]

    def claim_runtime(self, runtime_claim_id: str) -> None:
        for lease in self.management_leases.values():
            lease.claim_runtime(runtime_claim_id)

    def prepare_owner_generations(self, receipts: OwnerReceiptGroups) -> None:
        _OwnerLeaseSet(self.management_leases).prepare_owner_generations(receipts)

    def publish_owner_generations(self, receipts: OwnerReceiptGroups) -> None:
        _OwnerLeaseSet(self.management_leases).publish_owner_generations(receipts)

    def retire_owner_generations(self, receipts: OwnerReceiptGroups) -> None:
        _OwnerLeaseSet(self.management_leases).retire_owner_generations(receipts)


def share_startup_cleanup(
    release_startup: Callable[[], None],
    cleanup_state: Callable[[], None],
    *,
    primary: bool,
    eager: bool,
    deferred: bool,
) -> tuple[Callable[[], None] | None, Callable[[], None] | None, Callable[[], None] | None]:
    """Transfer one disposable startup root across successful consumers."""

    remaining = sum((primary, eager, deferred))
    cleanup_done = False

    def create_claim() -> Callable[[], None]:
        released = False

        def release() -> None:
            nonlocal remaining, cleanup_done, released
            if not released:
                remaining -= 1
                released = True
            if remaining == 0 and not cleanup_done:
                release_startup()
                cleanup_state()
                cleanup_done = True

        return release

    return (
        create_claim() if primary else None,
        create_claim() if eager else None,
        create_claim() if deferred else None,
    )
