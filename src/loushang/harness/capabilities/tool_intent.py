"""Revisioned Product defaults and session Tool Intent semantics.

This module implements the governed-v1 intent state introduced by Tool
Governance P1A.  It deliberately does not perform Catalog publication, Policy
evaluation, Agent rebinding, or per-call Tool Plan construction.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from enum import StrEnum
from hashlib import sha256
from threading import RLock

from loushang.harness.capabilities.tool_profiles import (
    DefaultToolProfileAssembler,
    DefaultToolProfileChange,
    DefaultToolProfileContributionSnapshot,
    DefaultToolProfilePolicyChange,
    DefaultToolProfileSnapshot,
    StaleDefaultProfileRevisionError,
    ToolDefaultProfileContributorHandle,
)


class IntentSelectionMode(StrEnum):
    """How Product defaults participate in resolved Tool Intent."""

    INHERIT_DEFAULTS = "inherit_defaults"
    EXPLICIT_ONLY = "explicit_only"


class IntentEngineMode(StrEnum):
    """The one authoritative Tool Intent engine for a session."""

    LEGACY_POSITIVE = "legacy_positive"
    GOVERNED_V1 = "governed_v1"


class StaleToolIntentRevisionError(RuntimeError):
    """Raised when an intent compare-and-swap expectation is stale."""


class StaleToolCatalogObservationError(RuntimeError):
    """Raised when reconciliation receives an older cursor in one epoch."""


class ToolIntentReconciliationError(RuntimeError):
    """Raised when bounded reconciliation cannot commit a coherent decision."""


@dataclass(frozen=True)
class ToolCatalogCursor:
    """The minimum Catalog observation identity needed by P1A."""

    catalog_epoch: str
    catalog_epoch_generation: int
    catalog_revision: int

    def __post_init__(self) -> None:
        _require_non_empty(self.catalog_epoch, "catalog_epoch")
        _require_non_negative(
            self.catalog_epoch_generation,
            "catalog_epoch_generation",
        )
        _require_non_negative(self.catalog_revision, "catalog_revision")


@dataclass(frozen=True)
class ToolCatalogCandidate:
    """A published logical name observed by default selection.

    ``legacy_default_selection_eligible`` preserves the current registry
    ``enabled`` meaning.  It is selection metadata and never Catalog
    availability.
    """

    tool_name: str
    candidate_fingerprint: str
    legacy_default_selection_eligible: bool = True

    def __post_init__(self) -> None:
        _require_tool_name(self.tool_name)
        _require_non_empty(self.candidate_fingerprint, "candidate_fingerprint")
        if type(self.legacy_default_selection_eligible) is not bool:
            raise TypeError("legacy_default_selection_eligible must be a bool")


@dataclass(frozen=True)
class ToolCatalogObservation:
    """One committed Catalog view supplied to the separate reconciler."""

    cursor: ToolCatalogCursor
    candidates: tuple[ToolCatalogCandidate, ...]
    observation_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.cursor, ToolCatalogCursor):
            raise TypeError("cursor must be a ToolCatalogCursor")
        candidates = tuple(self.candidates)
        if any(not isinstance(item, ToolCatalogCandidate) for item in candidates):
            raise TypeError("candidates must contain ToolCatalogCandidate values")
        names = tuple(item.tool_name for item in candidates)
        if len(names) != len(set(names)):
            raise ValueError("Catalog observation contains duplicate Tool Names")
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(
            self,
            "observation_fingerprint",
            _catalog_observation_fingerprint(candidates),
        )


@dataclass(frozen=True)
class ToolIntentNameDecision:
    """One ordered explicit enable or disable decision."""

    tool_name: str
    mutation_sequence: int

    def __post_init__(self) -> None:
        _require_tool_name(self.tool_name)
        _require_positive(self.mutation_sequence, "mutation_sequence")


@dataclass(frozen=True)
class AutomaticSelectionDecision:
    """The durable-in-session first-seen Product decision for one Tool Name."""

    tool_name: str
    first_seen_sequence: int
    decision_profile_revision: int
    candidate_fingerprint: str
    selected_by_default: bool

    def __post_init__(self) -> None:
        _require_tool_name(self.tool_name)
        _require_positive(self.first_seen_sequence, "first_seen_sequence")
        _require_non_negative(
            self.decision_profile_revision,
            "decision_profile_revision",
        )
        _require_non_empty(self.candidate_fingerprint, "candidate_fingerprint")
        if type(self.selected_by_default) is not bool:
            raise TypeError("selected_by_default must be a bool")


@dataclass(frozen=True)
class ToolIntentSnapshot:
    """The complete in-memory governed-v1 Tool Intent source state."""

    session_id: str
    intent_revision: int
    bound_profile: DefaultToolProfileSnapshot
    selection_mode: IntentSelectionMode
    explicit_enabled: tuple[ToolIntentNameDecision, ...] = ()
    explicit_disabled: tuple[ToolIntentNameDecision, ...] = ()
    automatic_decisions: tuple[AutomaticSelectionDecision, ...] = ()
    observed_catalog_cursor: ToolCatalogCursor | None = None
    observed_catalog_fingerprint: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty(self.session_id, "session_id")
        _require_non_negative(self.intent_revision, "intent_revision")
        if not isinstance(self.bound_profile, DefaultToolProfileSnapshot):
            raise TypeError("bound_profile must be a DefaultToolProfileSnapshot")
        if not isinstance(self.selection_mode, IntentSelectionMode):
            raise TypeError("selection_mode must be an IntentSelectionMode")
        explicit_enabled = tuple(self.explicit_enabled)
        explicit_disabled = tuple(self.explicit_disabled)
        automatic_decisions = tuple(self.automatic_decisions)
        _validate_name_decisions(explicit_enabled, "explicit_enabled")
        _validate_name_decisions(explicit_disabled, "explicit_disabled")
        _validate_automatic_decisions(automatic_decisions)
        object.__setattr__(self, "explicit_enabled", explicit_enabled)
        object.__setattr__(self, "explicit_disabled", explicit_disabled)
        object.__setattr__(self, "automatic_decisions", automatic_decisions)
        enabled_names = {item.tool_name for item in self.explicit_enabled}
        disabled_names = {item.tool_name for item in self.explicit_disabled}
        if enabled_names & disabled_names:
            raise ValueError("a Tool Name cannot be explicitly enabled and disabled")
        if self.observed_catalog_cursor is not None and not isinstance(
            self.observed_catalog_cursor,
            ToolCatalogCursor,
        ):
            raise TypeError("observed_catalog_cursor must be a ToolCatalogCursor")
        if (self.observed_catalog_cursor is None) != (
            self.observed_catalog_fingerprint is None
        ):
            raise ValueError(
                "observed Catalog cursor and fingerprint must be present together"
            )
        if self.observed_catalog_fingerprint is not None:
            _require_non_empty(
                self.observed_catalog_fingerprint,
                "observed_catalog_fingerprint",
            )
        _validate_global_sequence_identity(
            explicit_enabled,
            explicit_disabled,
            automatic_decisions,
        )

    @property
    def bound_profile_id(self) -> str:
        return self.bound_profile.profile_id

    @property
    def bound_profile_revision(self) -> int:
        return self.bound_profile.profile_revision


@dataclass(frozen=True)
class ResolvedToolIntent:
    """Immutable ordered positive and negative intent projection."""

    session_id: str
    intent_revision: int
    bound_profile_id: str
    bound_profile_revision: int
    selection_mode: IntentSelectionMode
    requested_names: tuple[str, ...]
    explicitly_disabled_names: tuple[str, ...]


@dataclass(frozen=True)
class ToolIntentAvailabilityResolution:
    """Compatibility projection of resolved intent against current names."""

    active_names: tuple[str, ...]
    pending_names: tuple[str, ...]


@dataclass(frozen=True)
class ToolIntentDiff:
    explicit_enabled_added: tuple[str, ...] = ()
    explicit_enabled_removed: tuple[str, ...] = ()
    explicit_disabled_added: tuple[str, ...] = ()
    explicit_disabled_removed: tuple[str, ...] = ()
    automatic_decisions_added: tuple[str, ...] = ()
    automatic_decisions_removed: tuple[str, ...] = ()
    explicit_enabled_replaced: tuple[str, ...] = ()
    explicit_disabled_replaced: tuple[str, ...] = ()
    automatic_decisions_replaced: tuple[str, ...] = ()
    explicit_enabled_order_changed: bool = False
    explicit_disabled_order_changed: bool = False
    automatic_decision_order_changed: bool = False
    selection_mode_changed: bool = False
    bound_profile_changed: bool = False
    observed_catalog_cursor_changed: bool = False
    observed_catalog_fingerprint_changed: bool = False

    @property
    def changed(self) -> bool:
        return bool(
            self.explicit_enabled_added
            or self.explicit_enabled_removed
            or self.explicit_disabled_added
            or self.explicit_disabled_removed
            or self.automatic_decisions_added
            or self.automatic_decisions_removed
            or self.explicit_enabled_replaced
            or self.explicit_disabled_replaced
            or self.automatic_decisions_replaced
            or self.explicit_enabled_order_changed
            or self.explicit_disabled_order_changed
            or self.automatic_decision_order_changed
            or self.selection_mode_changed
            or self.bound_profile_changed
            or self.observed_catalog_cursor_changed
            or self.observed_catalog_fingerprint_changed
        )


@dataclass(frozen=True)
class ToolIntentChange:
    previous: ToolIntentSnapshot
    current: ToolIntentSnapshot
    diff: ToolIntentDiff


@dataclass(frozen=True)
class _AutomaticSelectionProposal:
    candidate: ToolCatalogCandidate
    selected_by_default: bool


class GovernedToolIntentCoordinator:
    """Own one session's revisioned governed-v1 Tool Intent state."""

    engine_mode = IntentEngineMode.GOVERNED_V1

    def __init__(
        self,
        *,
        session_id: str,
        bound_profile: DefaultToolProfileSnapshot,
        selection_mode: IntentSelectionMode = IntentSelectionMode.INHERIT_DEFAULTS,
    ) -> None:
        _require_non_empty(session_id, "session_id")
        if not isinstance(bound_profile, DefaultToolProfileSnapshot):
            raise TypeError("bound_profile must be a DefaultToolProfileSnapshot")
        if not isinstance(selection_mode, IntentSelectionMode):
            raise TypeError("selection_mode must be an IntentSelectionMode")
        self._lock = RLock()
        self._snapshot = ToolIntentSnapshot(
            session_id=session_id,
            intent_revision=0,
            bound_profile=bound_profile,
            selection_mode=selection_mode,
        )
        self._next_sequence = 1

    @classmethod
    def from_legacy_positive(
        cls,
        *,
        session_id: str,
        bound_profile: DefaultToolProfileSnapshot,
        requested_names: Iterable[str],
    ) -> GovernedToolIntentCoordinator:
        """Characterize the P1B one-way conversion without performing cutover."""

        names = _unique_tool_names(requested_names)
        coordinator = cls(
            session_id=session_id,
            bound_profile=bound_profile,
            selection_mode=IntentSelectionMode.EXPLICIT_ONLY,
        )
        with coordinator._lock:
            decisions = tuple(
                coordinator._new_name_decision(name) for name in names
            )
            coordinator._snapshot = replace(
                coordinator._snapshot,
                explicit_enabled=decisions,
            )
        return coordinator

    @classmethod
    def from_snapshot(
        cls,
        snapshot: ToolIntentSnapshot,
    ) -> GovernedToolIntentCoordinator:
        """Rehydrate one coordinator before it begins accepting live mutations."""

        if not isinstance(snapshot, ToolIntentSnapshot):
            raise TypeError("snapshot must be a ToolIntentSnapshot")
        coordinator = cls(
            session_id=snapshot.session_id,
            bound_profile=snapshot.bound_profile,
            selection_mode=snapshot.selection_mode,
        )
        with coordinator._lock:
            coordinator._snapshot = snapshot
            coordinator._next_sequence = max(_largest_sequence(snapshot) + 1, 1)
        return coordinator

    def snapshot(self) -> ToolIntentSnapshot:
        with self._lock:
            return self._snapshot

    def resolve_intent(self) -> ResolvedToolIntent:
        return resolve_tool_intent(self.snapshot())

    def activator(self) -> ToolIntentActivator:
        return ToolIntentActivator(self)

    def user_editor(self) -> ToolIntentUserEditor:
        return ToolIntentUserEditor(self)

    def restorer(self) -> CompleteToolIntentRestorer:
        return CompleteToolIntentRestorer(self)

    def profile_publisher(
        self,
        assembler: DefaultToolProfileAssembler,
    ) -> ToolDefaultProfilePublisher:
        return ToolDefaultProfilePublisher(self, assembler)

    def _activate_tool_names(
        self,
        names: Iterable[str],
        *,
        expected_revision: int | None,
    ) -> ToolIntentChange:
        supplied = _unique_tool_names(names)
        with self._lock:
            previous = self._expect_revision(expected_revision)
            enabled = list(previous.explicit_enabled)
            enabled_names = {item.tool_name for item in enabled}
            disabled = [
                item
                for item in previous.explicit_disabled
                if item.tool_name not in supplied
            ]
            for name in supplied:
                if name in enabled_names:
                    continue
                enabled.append(self._new_name_decision(name))
                enabled_names.add(name)
            return self._commit(
                previous,
                explicit_enabled=tuple(enabled),
                explicit_disabled=tuple(disabled),
            )

    def _deactivate_tool_names(
        self,
        names: Iterable[str],
        *,
        expected_revision: int | None,
    ) -> ToolIntentChange:
        supplied = _unique_tool_names(names)
        with self._lock:
            previous = self._expect_revision(expected_revision)
            enabled = [
                item for item in previous.explicit_enabled if item.tool_name not in supplied
            ]
            disabled = list(previous.explicit_disabled)
            disabled_names = {item.tool_name for item in disabled}
            for name in supplied:
                if name in disabled_names:
                    continue
                disabled.append(self._new_name_decision(name))
                disabled_names.add(name)
            return self._commit(
                previous,
                explicit_enabled=tuple(enabled),
                explicit_disabled=tuple(disabled),
            )

    def _reset_tool_intent(
        self,
        names: Iterable[str],
        *,
        expected_revision: int | None,
    ) -> ToolIntentChange:
        supplied = set(_unique_tool_names(names))
        with self._lock:
            previous = self._expect_revision(expected_revision)
            return self._commit(
                previous,
                explicit_enabled=tuple(
                    item
                    for item in previous.explicit_enabled
                    if item.tool_name not in supplied
                ),
                explicit_disabled=tuple(
                    item
                    for item in previous.explicit_disabled
                    if item.tool_name not in supplied
                ),
            )

    def _set_explicit_only(
        self,
        names: Iterable[str],
        *,
        expected_revision: int,
    ) -> ToolIntentChange:
        supplied = _unique_tool_names(names)
        with self._lock:
            previous = self._expect_revision(expected_revision)
            current_positive = tuple(
                item.tool_name for item in previous.explicit_enabled
            )
            if (
                previous.selection_mode is IntentSelectionMode.EXPLICIT_ONLY
                and current_positive == supplied
            ):
                return _unchanged_intent(previous)
            enabled = tuple(self._new_name_decision(name) for name in supplied)
            return self._commit(
                previous,
                selection_mode=IntentSelectionMode.EXPLICIT_ONLY,
                explicit_enabled=enabled,
                explicit_disabled=tuple(
                    item
                    for item in previous.explicit_disabled
                    if item.tool_name not in supplied
                ),
            )

    def _reset_all_tool_intent(
        self,
        *,
        expected_revision: int,
    ) -> ToolIntentChange:
        with self._lock:
            previous = self._expect_revision(expected_revision)
            return self._commit(
                previous,
                selection_mode=IntentSelectionMode.INHERIT_DEFAULTS,
                explicit_enabled=(),
                explicit_disabled=(),
            )

    def _replace_tool_intent(
        self,
        snapshot: ToolIntentSnapshot,
        *,
        expected_revision: int,
    ) -> ToolIntentChange:
        if not isinstance(snapshot, ToolIntentSnapshot):
            raise TypeError("snapshot must be a ToolIntentSnapshot")
        with self._lock:
            previous = self._expect_revision(expected_revision)
            if snapshot.session_id != previous.session_id:
                raise ValueError("replacement Tool Intent belongs to another session")
            _validate_replacement_catalog_fence(previous, snapshot)
            candidate = replace(snapshot, intent_revision=previous.intent_revision)
            diff = _tool_intent_diff(previous, candidate)
            if not diff.changed:
                return _unchanged_intent(previous)
            current = replace(candidate, intent_revision=previous.intent_revision + 1)
            self._next_sequence = max(_largest_sequence(current) + 1, 1)
            self._snapshot = current
            return ToolIntentChange(
                previous=previous,
                current=current,
                diff=diff,
            )

    def _publish_profile(
        self,
        publication: DefaultToolProfileChange | DefaultToolProfilePolicyChange,
        *,
        assembler: DefaultToolProfileAssembler,
        expected_profile_revision: int,
        expected_intent_revision: int,
    ) -> ToolIntentChange:
        if not isinstance(
            publication,
            (DefaultToolProfileChange, DefaultToolProfilePolicyChange),
        ):
            raise TypeError("publication must be an assembler-issued profile change")
        assembler._validate_publication(publication)
        with self._lock:
            previous = self._expect_revision(expected_intent_revision)
            current_profile = previous.bound_profile
            if current_profile.profile_revision != expected_profile_revision:
                raise StaleDefaultProfileRevisionError(
                    "bound default profile revision changed: "
                    f"expected {expected_profile_revision}, "
                    f"found {current_profile.profile_revision}"
                )
            if publication.previous != current_profile:
                raise StaleDefaultProfileRevisionError(
                    "profile publication does not continue the bound revision stream"
                )
            profile = publication.current
            if profile.profile_id != current_profile.profile_id:
                raise ValueError("profile migration cannot change profile_id in P1A")
            if profile.profile_revision < current_profile.profile_revision:
                raise StaleDefaultProfileRevisionError(
                    "default profile revisions must not move backwards"
                )
            if (
                profile.profile_revision == current_profile.profile_revision
                and profile != current_profile
            ):
                raise ValueError(
                    "one default profile revision cannot identify different content"
                )
            return self._commit(previous, bound_profile=profile)

    def _record_automatic_decisions(
        self,
        proposals: tuple[_AutomaticSelectionProposal, ...],
        *,
        observation: ToolCatalogObservation,
        expected_revision: int,
    ) -> ToolIntentChange:
        with self._lock:
            previous = self._expect_revision(expected_revision)
            self._validate_catalog_observation(observation)
            decisions = list(previous.automatic_decisions)
            decided_names = {item.tool_name for item in decisions}
            for proposal in proposals:
                candidate = proposal.candidate
                if candidate.tool_name in decided_names:
                    continue
                decisions.append(
                    AutomaticSelectionDecision(
                        tool_name=candidate.tool_name,
                        first_seen_sequence=self._take_sequence(),
                        decision_profile_revision=(
                            previous.bound_profile.profile_revision
                        ),
                        candidate_fingerprint=candidate.candidate_fingerprint,
                        selected_by_default=proposal.selected_by_default,
                    )
                )
                decided_names.add(candidate.tool_name)
            change = self._commit(
                previous,
                automatic_decisions=tuple(decisions),
                observed_catalog_cursor=observation.cursor,
                observed_catalog_fingerprint=observation.observation_fingerprint,
            )
            return change

    def _validate_catalog_observation(
        self,
        observation: ToolCatalogObservation,
    ) -> None:
        with self._lock:
            _validate_catalog_cursor_progress(
                self._snapshot.observed_catalog_cursor,
                observation.cursor,
            )
            previous_cursor = self._snapshot.observed_catalog_cursor
            if (
                previous_cursor == observation.cursor
                and self._snapshot.observed_catalog_fingerprint
                != observation.observation_fingerprint
            ):
                raise StaleToolCatalogObservationError(
                    "one Catalog cursor cannot identify different observations"
                )

    def _expect_revision(self, expected_revision: int | None) -> ToolIntentSnapshot:
        previous = self._snapshot
        if expected_revision is not None and previous.intent_revision != expected_revision:
            raise StaleToolIntentRevisionError(
                "Tool Intent revision changed: "
                f"expected {expected_revision}, found {previous.intent_revision}"
            )
        return previous

    def _new_name_decision(self, name: str) -> ToolIntentNameDecision:
        return ToolIntentNameDecision(
            tool_name=name,
            mutation_sequence=self._take_sequence(),
        )

    def _take_sequence(self) -> int:
        sequence = self._next_sequence
        self._next_sequence += 1
        return sequence

    def _commit(
        self,
        previous: ToolIntentSnapshot,
        *,
        bound_profile: DefaultToolProfileSnapshot | None = None,
        selection_mode: IntentSelectionMode | None = None,
        explicit_enabled: tuple[ToolIntentNameDecision, ...] | None = None,
        explicit_disabled: tuple[ToolIntentNameDecision, ...] | None = None,
        automatic_decisions: tuple[AutomaticSelectionDecision, ...] | None = None,
        observed_catalog_cursor: ToolCatalogCursor | None = None,
        observed_catalog_fingerprint: str | None = None,
    ) -> ToolIntentChange:
        candidate = ToolIntentSnapshot(
            session_id=previous.session_id,
            intent_revision=previous.intent_revision,
            bound_profile=bound_profile or previous.bound_profile,
            selection_mode=selection_mode or previous.selection_mode,
            explicit_enabled=(
                previous.explicit_enabled
                if explicit_enabled is None
                else explicit_enabled
            ),
            explicit_disabled=(
                previous.explicit_disabled
                if explicit_disabled is None
                else explicit_disabled
            ),
            automatic_decisions=(
                previous.automatic_decisions
                if automatic_decisions is None
                else automatic_decisions
            ),
            observed_catalog_cursor=(
                previous.observed_catalog_cursor
                if observed_catalog_cursor is None
                else observed_catalog_cursor
            ),
            observed_catalog_fingerprint=(
                previous.observed_catalog_fingerprint
                if observed_catalog_fingerprint is None
                else observed_catalog_fingerprint
            ),
        )
        diff = _tool_intent_diff(previous, candidate)
        if not diff.changed:
            return _unchanged_intent(previous)
        current = replace(candidate, intent_revision=previous.intent_revision + 1)
        self._snapshot = current
        return ToolIntentChange(previous=previous, current=current, diff=diff)


class ToolIntentActivator:
    """Narrow capability that may only add named positive intent."""

    def __init__(self, coordinator: GovernedToolIntentCoordinator) -> None:
        self._coordinator = coordinator

    def activate_tool_names(
        self,
        names: Iterable[str],
        *,
        expected_revision: int | None = None,
    ) -> ToolIntentChange:
        return self._coordinator._activate_tool_names(
            names,
            expected_revision=expected_revision,
        )


class ToolIntentUserEditor(ToolIntentActivator):
    """Narrow capability for user-owned named and explicit-only mutations."""

    def deactivate_tool_names(
        self,
        names: Iterable[str],
        *,
        expected_revision: int | None = None,
    ) -> ToolIntentChange:
        return self._coordinator._deactivate_tool_names(
            names,
            expected_revision=expected_revision,
        )

    def reset_tool_intent(
        self,
        names: Iterable[str],
        *,
        expected_revision: int | None = None,
    ) -> ToolIntentChange:
        return self._coordinator._reset_tool_intent(
            names,
            expected_revision=expected_revision,
        )

    def set_explicit_only(
        self,
        names: Iterable[str],
        *,
        expected_revision: int,
    ) -> ToolIntentChange:
        return self._coordinator._set_explicit_only(
            names,
            expected_revision=expected_revision,
        )


class CompleteToolIntentRestorer:
    """Complete-truth capability for whole-session reset or replacement."""

    def __init__(self, coordinator: GovernedToolIntentCoordinator) -> None:
        self._coordinator = coordinator

    def reset_all_tool_intent(self, *, expected_revision: int) -> ToolIntentChange:
        return self._coordinator._reset_all_tool_intent(
            expected_revision=expected_revision
        )

    def replace_tool_intent(
        self,
        snapshot: ToolIntentSnapshot,
        *,
        expected_revision: int,
    ) -> ToolIntentChange:
        return self._coordinator._replace_tool_intent(
            snapshot,
            expected_revision=expected_revision,
        )


class ToolDefaultProfilePublisher:
    """Complete-truth capability for binding one exact Product profile."""

    def __init__(
        self,
        coordinator: GovernedToolIntentCoordinator,
        assembler: DefaultToolProfileAssembler,
    ) -> None:
        self._coordinator = coordinator
        self._assembler = assembler

    def publish_profile(
        self,
        publication: DefaultToolProfileChange | DefaultToolProfilePolicyChange,
        *,
        expected_profile_revision: int,
        expected_intent_revision: int,
    ) -> ToolIntentChange:
        return self._coordinator._publish_profile(
            publication,
            assembler=self._assembler,
            expected_profile_revision=expected_profile_revision,
            expected_intent_revision=expected_intent_revision,
        )


DefaultSelectionPredicate = Callable[
    [DefaultToolProfileSnapshot, ToolCatalogCandidate],
    bool,
]


class DefaultSelectionReconciler:
    """Observe Catalog commits and write first-seen decisions by separate CAS."""

    def __init__(
        self,
        coordinator: GovernedToolIntentCoordinator,
        *,
        should_select: DefaultSelectionPredicate,
        max_attempts: int = 4,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self._coordinator = coordinator
        self._should_select = should_select
        self._max_attempts = max_attempts

    def reconcile(self, observation: ToolCatalogObservation) -> ToolIntentChange:
        if not isinstance(observation, ToolCatalogObservation):
            raise TypeError("observation must be a ToolCatalogObservation")
        last_stale: StaleToolIntentRevisionError | None = None
        for _attempt in range(self._max_attempts):
            snapshot = self._coordinator.snapshot()
            self._coordinator._validate_catalog_observation(observation)
            decided_names = {
                item.tool_name for item in snapshot.automatic_decisions
            }
            proposals = tuple(
                _AutomaticSelectionProposal(
                    candidate=candidate,
                    selected_by_default=(
                        snapshot.bound_profile.automatic_selection_enabled
                        and candidate.tool_name
                        not in snapshot.bound_profile.automatic_selection_excluded_names
                        and candidate.legacy_default_selection_eligible
                        and self._should_select(snapshot.bound_profile, candidate)
                    ),
                )
                for candidate in observation.candidates
                if candidate.tool_name not in decided_names
            )
            try:
                return self._coordinator._record_automatic_decisions(
                    proposals,
                    observation=observation,
                    expected_revision=snapshot.intent_revision,
                )
            except StaleToolIntentRevisionError as exc:
                last_stale = exc
        raise ToolIntentReconciliationError(
            "Tool Intent kept changing during default-selection reconciliation"
        ) from last_stale


def resolve_tool_intent(snapshot: ToolIntentSnapshot) -> ResolvedToolIntent:
    """Resolve defaults and explicit decisions without consulting availability."""

    if not isinstance(snapshot, ToolIntentSnapshot):
        raise TypeError("snapshot must be a ToolIntentSnapshot")
    enabled = tuple(
        item.tool_name
        for item in sorted(
            snapshot.explicit_enabled,
            key=lambda item: item.mutation_sequence,
        )
    )
    disabled = tuple(
        item.tool_name
        for item in sorted(
            snapshot.explicit_disabled,
            key=lambda item: item.mutation_sequence,
        )
    )
    disabled_set = set(disabled)
    if snapshot.selection_mode is IntentSelectionMode.EXPLICIT_ONLY:
        requested = tuple(name for name in enabled if name not in disabled_set)
    else:
        automatic = tuple(
            item.tool_name
            for item in sorted(
                snapshot.automatic_decisions,
                key=lambda item: item.first_seen_sequence,
            )
            if item.selected_by_default
        )
        requested = tuple(
            name
            for name in _unique_tool_names(
                (
                    *snapshot.bound_profile.static_default_names,
                    *automatic,
                    *enabled,
                )
            )
            if name not in disabled_set
        )
    return ResolvedToolIntent(
        session_id=snapshot.session_id,
        intent_revision=snapshot.intent_revision,
        bound_profile_id=snapshot.bound_profile.profile_id,
        bound_profile_revision=snapshot.bound_profile.profile_revision,
        selection_mode=snapshot.selection_mode,
        requested_names=requested,
        explicitly_disabled_names=disabled,
    )


def resolve_tool_intent_availability(
    intent: ResolvedToolIntent,
    *,
    available_names: Iterable[str],
) -> ToolIntentAvailabilityResolution:
    """Project resolved intent against availability without changing intent."""

    if not isinstance(intent, ResolvedToolIntent):
        raise TypeError("intent must be a ResolvedToolIntent")
    available = set(_unique_tool_names(available_names))
    return ToolIntentAvailabilityResolution(
        active_names=tuple(name for name in intent.requested_names if name in available),
        pending_names=tuple(
            name for name in intent.requested_names if name not in available
        ),
    )


def _validate_catalog_cursor_progress(
    previous: ToolCatalogCursor | None,
    current: ToolCatalogCursor,
) -> None:
    if previous is None:
        return
    if current.catalog_epoch_generation < previous.catalog_epoch_generation:
        raise StaleToolCatalogObservationError(
            "Catalog epoch generation moved backwards: "
            f"{current.catalog_epoch_generation} < "
            f"{previous.catalog_epoch_generation}"
        )
    if current.catalog_epoch_generation == previous.catalog_epoch_generation:
        if current.catalog_epoch != previous.catalog_epoch:
            raise StaleToolCatalogObservationError(
                "one Catalog epoch generation cannot identify different epochs"
            )
    elif current.catalog_epoch == previous.catalog_epoch:
        raise StaleToolCatalogObservationError(
            "a Catalog epoch identity cannot be reused at a new generation"
        )
    else:
        return
    if current.catalog_revision < previous.catalog_revision:
        raise StaleToolCatalogObservationError(
            "Catalog observation moved backwards in one epoch: "
            f"{current.catalog_revision} < {previous.catalog_revision}"
        )


def _tool_intent_diff(
    previous: ToolIntentSnapshot,
    current: ToolIntentSnapshot,
) -> ToolIntentDiff:
    previous_enabled = {item.tool_name for item in previous.explicit_enabled}
    current_enabled = {item.tool_name for item in current.explicit_enabled}
    previous_disabled = {item.tool_name for item in previous.explicit_disabled}
    current_disabled = {item.tool_name for item in current.explicit_disabled}
    previous_automatic = {item.tool_name for item in previous.automatic_decisions}
    current_automatic = {item.tool_name for item in current.automatic_decisions}
    previous_enabled_by_name = {
        item.tool_name: item for item in previous.explicit_enabled
    }
    previous_disabled_by_name = {
        item.tool_name: item for item in previous.explicit_disabled
    }
    previous_automatic_by_name = {
        item.tool_name: item for item in previous.automatic_decisions
    }
    previous_enabled_order = tuple(item.tool_name for item in previous.explicit_enabled)
    current_enabled_order = tuple(item.tool_name for item in current.explicit_enabled)
    previous_disabled_order = tuple(
        item.tool_name for item in previous.explicit_disabled
    )
    current_disabled_order = tuple(item.tool_name for item in current.explicit_disabled)
    previous_automatic_order = tuple(
        item.tool_name for item in previous.automatic_decisions
    )
    current_automatic_order = tuple(
        item.tool_name for item in current.automatic_decisions
    )
    return ToolIntentDiff(
        explicit_enabled_added=tuple(
            item.tool_name
            for item in current.explicit_enabled
            if item.tool_name not in previous_enabled
        ),
        explicit_enabled_removed=tuple(
            item.tool_name
            for item in previous.explicit_enabled
            if item.tool_name not in current_enabled
        ),
        explicit_disabled_added=tuple(
            item.tool_name
            for item in current.explicit_disabled
            if item.tool_name not in previous_disabled
        ),
        explicit_disabled_removed=tuple(
            item.tool_name
            for item in previous.explicit_disabled
            if item.tool_name not in current_disabled
        ),
        automatic_decisions_added=tuple(
            item.tool_name
            for item in current.automatic_decisions
            if item.tool_name not in previous_automatic
        ),
        automatic_decisions_removed=tuple(
            item.tool_name
            for item in previous.automatic_decisions
            if item.tool_name not in current_automatic
        ),
        explicit_enabled_replaced=tuple(
            item.tool_name
            for item in current.explicit_enabled
            if item.tool_name in previous_enabled_by_name
            and item != previous_enabled_by_name[item.tool_name]
        ),
        explicit_disabled_replaced=tuple(
            item.tool_name
            for item in current.explicit_disabled
            if item.tool_name in previous_disabled_by_name
            and item != previous_disabled_by_name[item.tool_name]
        ),
        automatic_decisions_replaced=tuple(
            item.tool_name
            for item in current.automatic_decisions
            if item.tool_name in previous_automatic_by_name
            and item != previous_automatic_by_name[item.tool_name]
        ),
        explicit_enabled_order_changed=(
            previous_enabled_order != current_enabled_order
            and previous_enabled == current_enabled
        ),
        explicit_disabled_order_changed=(
            previous_disabled_order != current_disabled_order
            and previous_disabled == current_disabled
        ),
        automatic_decision_order_changed=(
            previous_automatic_order != current_automatic_order
            and previous_automatic == current_automatic
        ),
        selection_mode_changed=previous.selection_mode is not current.selection_mode,
        bound_profile_changed=previous.bound_profile != current.bound_profile,
        observed_catalog_cursor_changed=(
            previous.observed_catalog_cursor != current.observed_catalog_cursor
        ),
        observed_catalog_fingerprint_changed=(
            previous.observed_catalog_fingerprint
            != current.observed_catalog_fingerprint
        ),
    )


def _validate_replacement_catalog_fence(
    previous: ToolIntentSnapshot,
    replacement: ToolIntentSnapshot,
) -> None:
    previous_cursor = previous.observed_catalog_cursor
    replacement_cursor = replacement.observed_catalog_cursor
    if previous_cursor is not None and replacement_cursor is None:
        raise StaleToolCatalogObservationError(
            "live Tool Intent replacement cannot clear the Catalog fence"
        )
    if replacement_cursor is None:
        return
    _validate_catalog_cursor_progress(previous_cursor, replacement_cursor)
    if (
        previous_cursor == replacement_cursor
        and previous.observed_catalog_fingerprint
        != replacement.observed_catalog_fingerprint
    ):
        raise StaleToolCatalogObservationError(
            "live Tool Intent replacement changed one Catalog observation"
        )


def _unchanged_intent(snapshot: ToolIntentSnapshot) -> ToolIntentChange:
    return ToolIntentChange(
        previous=snapshot,
        current=snapshot,
        diff=ToolIntentDiff(),
    )


def _largest_sequence(snapshot: ToolIntentSnapshot) -> int:
    return max(
        (
            *(item.mutation_sequence for item in snapshot.explicit_enabled),
            *(item.mutation_sequence for item in snapshot.explicit_disabled),
            *(item.first_seen_sequence for item in snapshot.automatic_decisions),
        ),
        default=0,
    )


def _validate_name_decisions(
    values: tuple[ToolIntentNameDecision, ...],
    field_name: str,
) -> None:
    if any(not isinstance(item, ToolIntentNameDecision) for item in values):
        raise TypeError(f"{field_name} must contain ToolIntentNameDecision values")
    names = tuple(item.tool_name for item in values)
    if len(names) != len(set(names)):
        raise ValueError(f"{field_name} contains duplicate Tool Names")
    sequences = tuple(item.mutation_sequence for item in values)
    if sequences != tuple(sorted(sequences)) or len(sequences) != len(set(sequences)):
        raise ValueError(f"{field_name} must have strictly increasing sequences")


def _validate_automatic_decisions(
    values: tuple[AutomaticSelectionDecision, ...],
) -> None:
    if any(not isinstance(item, AutomaticSelectionDecision) for item in values):
        raise TypeError(
            "automatic_decisions must contain AutomaticSelectionDecision values"
        )
    names = tuple(item.tool_name for item in values)
    if len(names) != len(set(names)):
        raise ValueError("automatic_decisions contains duplicate Tool Names")
    sequences = tuple(item.first_seen_sequence for item in values)
    if sequences != tuple(sorted(sequences)) or len(sequences) != len(set(sequences)):
        raise ValueError(
            "automatic_decisions must have strictly increasing sequences"
        )


def _validate_global_sequence_identity(
    explicit_enabled: tuple[ToolIntentNameDecision, ...],
    explicit_disabled: tuple[ToolIntentNameDecision, ...],
    automatic_decisions: tuple[AutomaticSelectionDecision, ...],
) -> None:
    sequences = (
        *(item.mutation_sequence for item in explicit_enabled),
        *(item.mutation_sequence for item in explicit_disabled),
        *(item.first_seen_sequence for item in automatic_decisions),
    )
    if len(sequences) != len(set(sequences)):
        raise ValueError("Tool Intent decision sequences must be globally unique")


def _catalog_observation_fingerprint(
    candidates: tuple[ToolCatalogCandidate, ...],
) -> str:
    payload = tuple(
        (
            item.tool_name,
            item.candidate_fingerprint,
            item.legacy_default_selection_eligible,
        )
        for item in candidates
    )
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    return sha256(serialized.encode("utf-8")).hexdigest()


def _unique_tool_names(names: Iterable[str]) -> tuple[str, ...]:
    return _unique_identifiers(names, "Tool Name")


def _unique_identifiers(values: Iterable[str], label: str) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{label} values must be an iterable, not one string")
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise TypeError(f"{label} values must be strings")
        if not value:
            raise ValueError(f"{label} values must be non-empty strings")
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return tuple(unique)


def _require_tool_name(value: str) -> None:
    _require_non_empty(value, "tool_name")


def _require_non_empty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_non_negative(value: int, field_name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def _require_positive(value: int, field_name: str) -> None:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")


__all__ = [
    "AutomaticSelectionDecision",
    "CompleteToolIntentRestorer",
    "DefaultSelectionPredicate",
    "DefaultSelectionReconciler",
    "DefaultToolProfileAssembler",
    "DefaultToolProfileChange",
    "DefaultToolProfileContributionSnapshot",
    "DefaultToolProfilePolicyChange",
    "DefaultToolProfileSnapshot",
    "GovernedToolIntentCoordinator",
    "IntentEngineMode",
    "IntentSelectionMode",
    "ResolvedToolIntent",
    "StaleDefaultProfileRevisionError",
    "StaleToolCatalogObservationError",
    "StaleToolIntentRevisionError",
    "ToolCatalogCandidate",
    "ToolCatalogCursor",
    "ToolCatalogObservation",
    "ToolDefaultProfileContributorHandle",
    "ToolDefaultProfilePublisher",
    "ToolIntentActivator",
    "ToolIntentAvailabilityResolution",
    "ToolIntentChange",
    "ToolIntentDiff",
    "ToolIntentNameDecision",
    "ToolIntentReconciliationError",
    "ToolIntentSnapshot",
    "ToolIntentUserEditor",
    "resolve_tool_intent",
    "resolve_tool_intent_availability",
]
