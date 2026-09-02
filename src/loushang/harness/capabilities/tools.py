from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import suppress
from dataclasses import dataclass
from functools import wraps
from threading import RLock
from typing import Any, Concatenate, Generic, ParamSpec, TypeVar

from loushang.harness.capabilities.tool_intent import IntentEngineMode

T = TypeVar("T")
P = ParamSpec("P")
R = TypeVar("R")

ToolNameResolver = Callable[[T], str]
ToolActivationPredicate = Callable[[str, T], bool]


class StaleToolActivationPublicationError(RuntimeError):
    """Raised when legacy reconciliation no longer matches the current view."""


class StaleToolActivationCheckpointError(RuntimeError):
    """Raised when rollback would overwrite a newer legacy mutation."""


def _synchronized(
    method: Callable[Concatenate[Any, P], R],
) -> Callable[Concatenate[Any, P], R]:
    @wraps(method)
    def call(self: Any, *args: P.args, **kwargs: P.kwargs) -> R:
        with self._lock:
            return method(self, *args, **kwargs)

    return call


@dataclass(frozen=True)
class LegacyPositiveIntentState:
    """Isolated exact positive-list state retained until the P1B cutover."""

    revision: int
    requested_names: tuple[str, ...]


@dataclass(frozen=True)
class LegacyToolActivationCheckpoint(Generic[T]):
    """Exact rollback state for one legacy publication transaction."""

    coordinator_token: object
    revision: int
    intent: LegacyPositiveIntentState
    available: tuple[tuple[str, T], ...]
    active_names: tuple[str, ...]
    seen_available_names: frozenset[str]
    automatic_request_revisions: tuple[tuple[str, int], ...]
    seen_available_revisions: tuple[tuple[str, int], ...]
    explicit_touch_revisions: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class ToolActivationSnapshot:
    revision: int
    available_names: tuple[str, ...]
    requested_names: tuple[str, ...]
    active_names: tuple[str, ...]
    missing_requested_names: tuple[str, ...]


@dataclass(frozen=True)
class ToolActivationDiff:
    available_added: tuple[str, ...] = ()
    available_removed: tuple[str, ...] = ()
    available_replaced: tuple[str, ...] = ()
    requested_added: tuple[str, ...] = ()
    requested_removed: tuple[str, ...] = ()
    activated: tuple[str, ...] = ()
    deactivated: tuple[str, ...] = ()
    available_order_changed: bool = False
    requested_order_changed: bool = False
    active_order_changed: bool = False

    @property
    def changed(self) -> bool:
        return bool(
            self.available_added
            or self.available_removed
            or self.available_replaced
            or self.requested_added
            or self.requested_removed
            or self.activated
            or self.deactivated
            or self.available_order_changed
            or self.requested_order_changed
            or self.active_order_changed
        )


@dataclass(frozen=True)
class ToolActivationResolution(Generic[T]):
    names: tuple[str, ...]
    items: tuple[T, ...]
    missing_names: tuple[str, ...]


@dataclass(frozen=True)
class ToolActivationChange(Generic[T]):
    previous: ToolActivationSnapshot
    current: ToolActivationSnapshot
    diff: ToolActivationDiff
    active_items: tuple[T, ...]


ToolRebinder = Callable[[ToolActivationChange[T]], None]


class ToolActivationCoordinator(Generic[T]):
    """Legacy positive-list coordinator retained until governed-v1 cutover.

    ``active_names`` is a compatibility projection, not a per-call Tool Plan.
    New Product and user control paths must use the governed intent capabilities
    rather than gaining exact-list access here.
    """

    engine_mode = IntentEngineMode.LEGACY_POSITIVE

    def __init__(
        self,
        *,
        available: Iterable[T] = (),
        requested_names: Iterable[str] = (),
        name_of: ToolNameResolver[T] | None = None,
        allowed_names: Iterable[str] | None = None,
        should_activate_new: ToolActivationPredicate[T] | None = None,
        rebind: ToolRebinder[T] | None = None,
    ) -> None:
        self._lock = RLock()
        self._coordinator_token = object()
        self._name_of = name_of or _default_name
        self._allowed_names = (
            frozenset(_unique_names(allowed_names))
            if allowed_names is not None
            else None
        )
        self._should_activate_new = should_activate_new
        self._rebind = rebind
        self._available = self._index_available(available)
        self._legacy_intent = LegacyPositiveIntentState(
            revision=0,
            requested_names=self.filter_names(requested_names),
        )
        self._seen_available_names = set(self._available)
        self._automatic_request_revisions: dict[str, int] = {}
        self._seen_available_revisions = {name: 0 for name in self._available}
        self._explicit_touch_revisions: dict[str, int] = {}
        self._active_names = self._resolve_names(self._requested_names)
        self._revision = 0

    @property
    def _requested_names(self) -> tuple[str, ...]:
        return self._legacy_intent.requested_names

    @_requested_names.setter
    def _requested_names(self, names: tuple[str, ...]) -> None:
        previous = self._legacy_intent
        if names == previous.requested_names:
            return
        self._legacy_intent = LegacyPositiveIntentState(
            revision=previous.revision + 1,
            requested_names=names,
        )

    @_synchronized
    def legacy_intent_snapshot(self) -> LegacyPositiveIntentState:
        return self._legacy_intent

    @_synchronized
    def checkpoint(self) -> LegacyToolActivationCheckpoint[T]:
        return LegacyToolActivationCheckpoint(
            coordinator_token=self._coordinator_token,
            revision=self._revision,
            intent=self._legacy_intent,
            available=tuple(self._available.items()),
            active_names=self._active_names,
            seen_available_names=frozenset(self._seen_available_names),
            automatic_request_revisions=tuple(
                self._automatic_request_revisions.items()
            ),
            seen_available_revisions=tuple(self._seen_available_revisions.items()),
            explicit_touch_revisions=tuple(self._explicit_touch_revisions.items()),
        )

    def restore_checkpoint(
        self,
        checkpoint: LegacyToolActivationCheckpoint[T],
        *,
        expected_previous_revision: int,
        expected_revision: int,
        rebind: bool = True,
    ) -> None:
        if not isinstance(checkpoint, LegacyToolActivationCheckpoint):
            raise TypeError("checkpoint must be a LegacyToolActivationCheckpoint")
        if checkpoint.coordinator_token is not self._coordinator_token:
            raise ValueError("legacy activation checkpoint belongs to another session")
        if checkpoint.revision != expected_previous_revision:
            raise StaleToolActivationCheckpointError(
                "legacy activation checkpoint does not precede the publication: "
                f"checkpoint {checkpoint.revision}, "
                f"publication previous {expected_previous_revision}"
            )
        with self._lock:
            if self._revision != expected_revision:
                raise StaleToolActivationCheckpointError(
                    "legacy activation changed before rollback: "
                    f"expected {expected_revision}, found {self._revision}"
                )
            previous_available = dict(self._available)
            previous = self._snapshot_locked()
            if self._legacy_intent.requested_names != checkpoint.intent.requested_names:
                self._legacy_intent = LegacyPositiveIntentState(
                    revision=self._legacy_intent.revision + 1,
                    requested_names=checkpoint.intent.requested_names,
                )
            self._available = dict(checkpoint.available)
            self._active_names = checkpoint.active_names
            self._seen_available_names = set(checkpoint.seen_available_names)
            self._automatic_request_revisions = dict(
                checkpoint.automatic_request_revisions
            )
            self._seen_available_revisions = dict(
                checkpoint.seen_available_revisions
            )
            self._explicit_touch_revisions = dict(
                checkpoint.explicit_touch_revisions
            )
            change = self._finish_transition_locked(
                previous,
                previous_available=previous_available,
                force_revision=True,
            )
        self._dispatch_rebind(change, enabled=rebind)

    def compensate_failed_publication(
        self,
        checkpoint: LegacyToolActivationCheckpoint[T],
        *,
        publication_revision: int,
        rebind: bool = True,
    ) -> ToolActivationChange[T]:
        """Undo only legacy defaults introduced by one failed publication."""

        if not isinstance(checkpoint, LegacyToolActivationCheckpoint):
            raise TypeError("checkpoint must be a LegacyToolActivationCheckpoint")
        if checkpoint.coordinator_token is not self._coordinator_token:
            raise ValueError("legacy activation checkpoint belongs to another session")
        if publication_revision < checkpoint.revision:
            raise ValueError("publication revision cannot precede its checkpoint")
        checkpoint_automatic = dict(checkpoint.automatic_request_revisions)
        checkpoint_seen = dict(checkpoint.seen_available_revisions)
        with self._lock:
            previous_available = dict(self._available)
            previous = self._snapshot_locked()
            automatic_to_remove = {
                name
                for name, revision in self._automatic_request_revisions.items()
                if revision == publication_revision
                and checkpoint_automatic.get(name) != revision
                and self._explicit_touch_revisions.get(name, -1)
                <= publication_revision
            }
            seen_to_remove = {
                name
                for name, revision in self._seen_available_revisions.items()
                if revision == publication_revision
                and checkpoint_seen.get(name) != revision
            }
            if automatic_to_remove:
                self._requested_names = tuple(
                    name
                    for name in self._requested_names
                    if name not in automatic_to_remove
                )
                for name in automatic_to_remove:
                    self._automatic_request_revisions.pop(name, None)
            for name in seen_to_remove:
                self._seen_available_names.discard(name)
                self._seen_available_revisions.pop(name, None)
            self._active_names = self._resolve_names(self._requested_names)
            change = self._finish_transition_locked(
                previous,
                previous_available=previous_available,
                force_revision=bool(automatic_to_remove or seen_to_remove),
            )
        self._dispatch_rebind(change, enabled=rebind)
        return change

    @_synchronized
    def snapshot(self) -> ToolActivationSnapshot:
        return self._snapshot_locked()

    def _snapshot_locked(self) -> ToolActivationSnapshot:
        active_set = set(self._active_names)
        return ToolActivationSnapshot(
            revision=self._revision,
            available_names=tuple(self._available),
            requested_names=self._requested_names,
            active_names=self._active_names,
            missing_requested_names=tuple(
                name for name in self._requested_names if name not in active_set
            ),
        )

    def is_allowed(self, name: str) -> bool:
        return self._allowed_names is None or name in self._allowed_names

    def filter_names(self, names: Iterable[str]) -> tuple[str, ...]:
        return tuple(name for name in _unique_names(names) if self.is_allowed(name))

    def filter_items(self, items: Iterable[T]) -> tuple[T, ...]:
        return tuple(
            item for item in items if self.is_allowed(self._validated_name(item))
        )

    def resolve(self, names: Iterable[str]) -> ToolActivationResolution[T]:
        filtered_names = self.filter_names(names)
        with self._lock:
            resolved_names = tuple(
                name for name in filtered_names if name in self._available
            )
            resolved_set = set(resolved_names)
            return ToolActivationResolution(
                names=resolved_names,
                items=tuple(self._available[name] for name in resolved_names),
                missing_names=tuple(
                    name for name in filtered_names if name not in resolved_set
                ),
            )

    @_synchronized
    def active_items(self) -> tuple[T, ...]:
        return self._active_items_locked()

    def _active_items_locked(self) -> tuple[T, ...]:
        return tuple(self._available[name] for name in self._active_names)

    def request(
        self,
        names: Iterable[str],
        *,
        rebind: bool = True,
    ) -> ToolActivationChange[T]:
        requested_names = self.filter_names(names)
        with self._lock:
            previous_available = dict(self._available)
            previous = self._snapshot_locked()
            touched_names = set(self._requested_names) | set(requested_names)
            provenance_changed = bool(self._automatic_request_revisions)
            self._automatic_request_revisions.clear()
            self._requested_names = requested_names
            self._active_names = self._resolve_names(self._requested_names)
            change = self._finish_transition_locked(
                previous,
                previous_available=previous_available,
                force_revision=provenance_changed,
            )
            if change.current.revision != previous.revision:
                self._explicit_touch_revisions.update(
                    dict.fromkeys(touched_names, change.current.revision)
                )
        self._dispatch_rebind(change, enabled=rebind)
        return change

    def activate(
        self,
        names: Iterable[str],
        *,
        rebind: bool = True,
    ) -> ToolActivationChange[T]:
        """Add requested names without discarding deferred activation intent."""

        supplied_names = self.filter_names(names)
        with self._lock:
            previous_available = dict(self._available)
            previous = self._snapshot_locked()
            claimed_automatic = {
                name
                for name in supplied_names
                if name in self._automatic_request_revisions
            }
            for name in claimed_automatic:
                self._automatic_request_revisions.pop(name, None)
            self._requested_names = self.filter_names(
                (*self._requested_names, *supplied_names)
            )
            self._active_names = self._resolve_names(self._requested_names)
            change = self._finish_transition_locked(
                previous,
                previous_available=previous_available,
                force_revision=bool(claimed_automatic),
            )
            if change.current.revision != previous.revision:
                self._explicit_touch_revisions.update(
                    dict.fromkeys(supplied_names, change.current.revision)
                )
        self._dispatch_rebind(change, enabled=rebind)
        return change

    def refresh(
        self,
        available: Iterable[T],
        *,
        activate_new: bool = True,
        rebind: bool = True,
    ) -> ToolActivationChange[T]:
        """Publish a new available view without mutating selection intent.

        ``activate_new`` remains accepted for source compatibility but is no
        longer acted on here.  Products explicitly invoke
        :meth:`reconcile_default_selection` after the publication transition.
        """

        del activate_new
        indexed = self._index_available(available)
        with self._lock:
            previous_available = dict(self._available)
            previous = self._snapshot_locked()
            self._available = indexed
            self._active_names = self._resolve_names(self._requested_names)
            change = self._finish_transition_locked(
                previous,
                previous_available=previous_available,
            )
        self._dispatch_rebind(change, enabled=rebind)
        return change

    def reconcile_default_selection(
        self,
        publication: ToolActivationChange[T],
        *,
        eligible_names: Iterable[str] | None = None,
        enabled: bool = True,
        rebind: bool = True,
    ) -> ToolActivationChange[T]:
        """Apply legacy Product auto-selection after a Catalog-like refresh.

        First-seen outcomes are remembered separately from the positive list so
        withdrawal and republish do not re-run Product selection.  Governed-v1
        sessions use :class:`DefaultSelectionReconciler` instead.
        """

        if not isinstance(publication, ToolActivationChange):
            raise TypeError("publication must be a ToolActivationChange")
        if type(enabled) is not bool:
            raise TypeError("enabled must be a bool")
        eligible = (
            None if eligible_names is None else set(_unique_names(eligible_names))
        )
        with self._lock:
            previous_available = dict(self._available)
            previous = self._snapshot_locked()
            if publication.current != previous:
                raise StaleToolActivationPublicationError(
                    "legacy default reconciliation publication is stale"
                )
            base_revision = self._revision
            candidates = self._unseen_candidates_locked()
            requested = self._requested_names
        selected = self._select_default_candidates(
            candidates,
            requested_names=requested,
            eligible_names=eligible,
            enabled=enabled,
        )
        with self._lock:
            if self._revision != base_revision:
                raise StaleToolActivationPublicationError(
                    "legacy default reconciliation changed during selection"
                )
            self._commit_default_decisions_locked(candidates, selected)
            change = self._finish_transition_locked(
                previous,
                previous_available=previous_available,
                force_revision=bool(candidates),
            )
            self._record_default_decision_revisions_locked(
                candidates,
                selected,
                revision=change.current.revision,
            )
        self._dispatch_rebind(change, enabled=rebind)
        return change

    def refresh_and_reconcile_default_selection(
        self,
        available: Iterable[T],
        *,
        eligible_names: Iterable[str] | None = None,
        enabled: bool = True,
        rebind: bool = True,
    ) -> ToolActivationChange[T]:
        """Atomically publish and reconcile the transitional legacy view."""

        if type(enabled) is not bool:
            raise TypeError("enabled must be a bool")
        indexed = self._index_available(available)
        eligible = (
            None if eligible_names is None else set(_unique_names(eligible_names))
        )
        while True:
            with self._lock:
                previous_available = dict(self._available)
                previous = self._snapshot_locked()
                base_revision = self._revision
                candidates = tuple(
                    (name, item)
                    for name, item in indexed.items()
                    if name not in self._seen_available_names
                )
                requested = self._requested_names
            selected = self._select_default_candidates(
                candidates,
                requested_names=requested,
                eligible_names=eligible,
                enabled=enabled,
            )
            with self._lock:
                if self._revision != base_revision:
                    continue
                self._available = dict(indexed)
                self._commit_default_decisions_locked(candidates, selected)
                change = self._finish_transition_locked(
                    previous,
                    previous_available=previous_available,
                    force_revision=bool(candidates),
                )
                self._record_default_decision_revisions_locked(
                    candidates,
                    selected,
                    revision=change.current.revision,
                )
                break
        self._dispatch_rebind(change, enabled=rebind)
        return change

    def rebind(self) -> ToolActivationChange[T]:
        with self._lock:
            change = self._current_change_locked()
        self._dispatch_rebind(change, enabled=True)
        return change

    def _finish_transition_locked(
        self,
        previous: ToolActivationSnapshot,
        *,
        previous_available: dict[str, T],
        force_revision: bool = False,
    ) -> ToolActivationChange[T]:
        current_without_revision = self._snapshot_locked()
        diff = _activation_diff(
            previous,
            current_without_revision,
            previous_available=previous_available,
            current_available=self._available,
        )
        if diff.changed or force_revision:
            self._revision += 1
        current = self._snapshot_locked()
        return ToolActivationChange(
            previous=previous,
            current=current,
            diff=diff,
            active_items=self._active_items_locked(),
        )

    def _current_change_locked(self) -> ToolActivationChange[T]:
        snapshot = self._snapshot_locked()
        return ToolActivationChange(
            previous=snapshot,
            current=snapshot,
            diff=ToolActivationDiff(),
            active_items=self._active_items_locked(),
        )

    def _dispatch_rebind(
        self,
        change: ToolActivationChange[T],
        *,
        enabled: bool,
    ) -> None:
        if not enabled or self._rebind is None:
            return
        origin = change
        pending = change
        while True:
            with self._lock:
                if pending.current.revision != self._revision:
                    pending = self._current_change_locked()
            try:
                self._rebind(pending)
            except BaseException as error:
                with suppress(BaseException):
                    setattr(
                        error,
                        "_loushang_tool_activation_failure",
                        (
                            self._coordinator_token,
                            origin.previous.revision,
                            origin.current.revision,
                            pending.current.revision,
                        ),
                    )
                raise
            with self._lock:
                if self._revision == pending.current.revision:
                    return
                pending = self._current_change_locked()

    def failed_rebind_transition(
        self,
        error: BaseException,
    ) -> tuple[int, int, int] | None:
        marker = getattr(error, "_loushang_tool_activation_failure", None)
        if (
            isinstance(marker, tuple)
            and len(marker) == 4
            and marker[0] is self._coordinator_token
            and isinstance(marker[1], int)
            and isinstance(marker[2], int)
            and isinstance(marker[3], int)
        ):
            return marker[1], marker[2], marker[3]
        return None

    def _unseen_candidates_locked(self) -> tuple[tuple[str, T], ...]:
        return tuple(
            (name, item)
            for name, item in self._available.items()
            if name not in self._seen_available_names
        )

    def _select_default_candidates(
        self,
        candidates: tuple[tuple[str, T], ...],
        *,
        requested_names: tuple[str, ...],
        eligible_names: set[str] | None,
        enabled: bool,
    ) -> tuple[str, ...]:
        requested = set(requested_names)
        selected: list[str] = []
        for name, item in candidates:
            if (
                enabled
                and (eligible_names is None or name in eligible_names)
                and name not in requested
                and self._should_activate_new is not None
                and self._should_activate_new(name, item)
            ):
                selected.append(name)
                requested.add(name)
        return tuple(selected)

    def _commit_default_decisions_locked(
        self,
        candidates: tuple[tuple[str, T], ...],
        selected_names: tuple[str, ...],
    ) -> None:
        requested = list(self._requested_names)
        requested_set = set(requested)
        for name in selected_names:
            if name not in requested_set:
                requested.append(name)
                requested_set.add(name)
        self._seen_available_names.update(name for name, _item in candidates)
        self._requested_names = tuple(requested)
        self._active_names = self._resolve_names(self._requested_names)

    def _record_default_decision_revisions_locked(
        self,
        candidates: tuple[tuple[str, T], ...],
        selected_names: tuple[str, ...],
        *,
        revision: int,
    ) -> None:
        self._seen_available_revisions.update(
            dict.fromkeys((name for name, _item in candidates), revision)
        )
        self._automatic_request_revisions.update(
            dict.fromkeys(selected_names, revision)
        )

    def _resolve_names(self, names: Iterable[str]) -> tuple[str, ...]:
        return tuple(name for name in names if name in self._available)

    def _index_available(self, items: Iterable[T]) -> dict[str, T]:
        indexed: dict[str, T] = {}
        for item in items:
            name = self._validated_name(item)
            if not self.is_allowed(name):
                continue
            if name in indexed:
                raise ValueError(f"duplicate available tool name: {name}")
            indexed[name] = item
        return indexed

    def _validated_name(self, item: T) -> str:
        name = self._name_of(item)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("tool names must be non-empty strings")
        return name


def _activation_diff(
    previous: ToolActivationSnapshot,
    current: ToolActivationSnapshot,
    *,
    previous_available: dict[str, T],
    current_available: dict[str, T],
) -> ToolActivationDiff:
    previous_available_names = set(previous.available_names)
    current_available_names = set(current.available_names)
    previous_requested_names = set(previous.requested_names)
    current_requested_names = set(current.requested_names)
    previous_active_names = set(previous.active_names)
    current_active_names = set(current.active_names)
    common_available = previous_available_names & current_available_names
    return ToolActivationDiff(
        available_added=tuple(
            name
            for name in current.available_names
            if name not in previous_available_names
        ),
        available_removed=tuple(
            name
            for name in previous.available_names
            if name not in current_available_names
        ),
        available_replaced=tuple(
            name
            for name in current.available_names
            if name in common_available
            and previous_available[name] is not current_available[name]
        ),
        requested_added=tuple(
            name
            for name in current.requested_names
            if name not in previous_requested_names
        ),
        requested_removed=tuple(
            name
            for name in previous.requested_names
            if name not in current_requested_names
        ),
        activated=tuple(
            name for name in current.active_names if name not in previous_active_names
        ),
        deactivated=tuple(
            name for name in previous.active_names if name not in current_active_names
        ),
        available_order_changed=(
            previous.available_names != current.available_names
            and previous_available_names == current_available_names
        ),
        requested_order_changed=(
            previous.requested_names != current.requested_names
            and previous_requested_names == current_requested_names
        ),
        active_order_changed=(
            previous.active_names != current.active_names
            and previous_active_names == current_active_names
        ),
    )


def _unique_names(names: Iterable[str]) -> tuple[str, ...]:
    unique: list[str] = []
    seen: set[str] = set()
    for name in names:
        if not isinstance(name, str):
            raise TypeError("tool names must be strings")
        if not name or name in seen:
            continue
        seen.add(name)
        unique.append(name)
    return tuple(unique)


def _default_name(item: T) -> str:
    return getattr(item, "name", "")


__all__ = [
    "LegacyPositiveIntentState",
    "LegacyToolActivationCheckpoint",
    "StaleToolActivationCheckpointError",
    "StaleToolActivationPublicationError",
    "ToolActivationChange",
    "ToolActivationCoordinator",
    "ToolActivationDiff",
    "ToolActivationResolution",
    "ToolActivationSnapshot",
]
