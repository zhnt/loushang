from __future__ import annotations

import gc
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from weakref import ref

import pytest

from loushang.harness.capabilities.tool_intent import (
    DefaultSelectionReconciler,
    DefaultToolProfileAssembler,
    DefaultToolProfileSnapshot,
    GovernedToolIntentCoordinator,
    IntentSelectionMode,
    StaleToolCatalogObservationError,
    StaleToolIntentRevisionError,
    ToolCatalogCandidate,
    ToolCatalogCursor,
    ToolCatalogObservation,
    ToolDefaultProfileContributorHandle,
    ToolIntentSnapshot,
    resolve_tool_intent_availability,
)


def _profile(
    *static_names: str,
    revision: int = 1,
    automatic: bool = True,
    automatic_exclusions: tuple[str, ...] = (),
) -> DefaultToolProfileSnapshot:
    return DefaultToolProfileSnapshot(
        profile_id="coding.tools.default",
        profile_revision=revision,
        static_default_names=static_names,
        automatic_selection_policy_fingerprint="coding.tools.auto.v1",
        automatic_selection_enabled=automatic,
        automatic_selection_excluded_names=automatic_exclusions,
    )


def _catalog(
    revision: int,
    *candidates: ToolCatalogCandidate,
    epoch: str = "catalog:test",
    epoch_generation: int = 1,
) -> ToolCatalogObservation:
    return ToolCatalogObservation(
        cursor=ToolCatalogCursor(
            catalog_epoch=epoch,
            catalog_epoch_generation=epoch_generation,
            catalog_revision=revision,
        ),
        candidates=candidates,
    )


def _candidate(
    name: str,
    *,
    fingerprint: str | None = None,
    eligible: bool = True,
) -> ToolCatalogCandidate:
    return ToolCatalogCandidate(
        tool_name=name,
        candidate_fingerprint=fingerprint or f"{name}:v1",
        legacy_default_selection_eligible=eligible,
    )


def test_static_and_explicit_intent_remain_pending_until_publication() -> None:
    coordinator = GovernedToolIntentCoordinator(
        session_id="session-1",
        bound_profile=_profile("read", "late"),
    )
    coordinator.user_editor().activate_tool_names(("manual",))

    before = resolve_tool_intent_availability(
        coordinator.resolve_intent(),
        available_names=("read", "manual"),
    )
    after = resolve_tool_intent_availability(
        coordinator.resolve_intent(),
        available_names=("read", "manual", "late"),
    )

    assert before.active_names == ("read", "manual")
    assert before.pending_names == ("late",)
    assert after.active_names == ("read", "late", "manual")
    assert after.pending_names == ()


def test_additive_activation_clears_only_named_suppression() -> None:
    coordinator = GovernedToolIntentCoordinator(
        session_id="session-1",
        bound_profile=_profile("read", "bash", "grep"),
    )
    editor = coordinator.user_editor()
    editor.deactivate_tool_names(("bash", "grep"))

    coordinator.activator().activate_tool_names(("bash", "manual", "manual"))

    snapshot = coordinator.snapshot()
    resolved = coordinator.resolve_intent()
    assert tuple(item.tool_name for item in snapshot.explicit_disabled) == ("grep",)
    assert resolved.requested_names == ("read", "bash", "manual")
    assert resolved.explicitly_disabled_names == ("grep",)


def test_explicit_disable_survives_catalog_withdrawal_and_republish() -> None:
    coordinator = GovernedToolIntentCoordinator(
        session_id="session-1",
        bound_profile=_profile("read"),
    )
    coordinator.user_editor().deactivate_tool_names(("plugin",))
    reconciler = DefaultSelectionReconciler(
        coordinator,
        should_select=lambda _profile, candidate: candidate.tool_name == "plugin",
    )

    reconciler.reconcile(_catalog(1, _candidate("plugin")))
    reconciler.reconcile(_catalog(2))
    reconciler.reconcile(
        _catalog(3, _candidate("plugin", fingerprint="plugin:new-owner"))
    )

    snapshot = coordinator.snapshot()
    decision = snapshot.automatic_decisions[0]
    assert decision.selected_by_default is True
    assert decision.candidate_fingerprint == "plugin:v1"
    assert coordinator.resolve_intent().requested_names == ("read",)
    assert coordinator.resolve_intent().explicitly_disabled_names == ("plugin",)


def test_first_seen_decision_is_independent_of_suppression_and_reset_restores_it() -> (
    None
):
    coordinator = GovernedToolIntentCoordinator(
        session_id="session-1",
        bound_profile=_profile(),
    )
    editor = coordinator.user_editor()
    editor.deactivate_tool_names(("plugin",))
    reconciler = DefaultSelectionReconciler(
        coordinator,
        should_select=lambda _profile, _candidate: True,
    )

    reconciler.reconcile(_catalog(1, _candidate("plugin")))

    assert coordinator.snapshot().automatic_decisions[0].selected_by_default is True
    assert coordinator.resolve_intent().requested_names == ()

    editor.reset_tool_intent(("plugin",))

    assert coordinator.resolve_intent().requested_names == ("plugin",)


def test_rejected_automatic_decision_is_not_recomputed_on_republish() -> None:
    calls: list[str] = []
    coordinator = GovernedToolIntentCoordinator(
        session_id="session-1",
        bound_profile=_profile(),
    )
    reconciler = DefaultSelectionReconciler(
        coordinator,
        should_select=lambda _profile, candidate: (
            calls.append(candidate.candidate_fingerprint) or False
        ),
    )

    reconciler.reconcile(_catalog(1, _candidate("plugin")))
    reconciler.reconcile(_catalog(2))
    reconciler.reconcile(
        _catalog(3, _candidate("plugin", fingerprint="plugin:v2"))
    )

    assert calls == ["plugin:v1"]
    assert coordinator.snapshot().automatic_decisions[0].selected_by_default is False
    assert coordinator.resolve_intent().requested_names == ()


def test_on_demand_catalog_tool_is_available_and_manually_activatable() -> None:
    coordinator = GovernedToolIntentCoordinator(
        session_id="session-1",
        bound_profile=_profile(),
    )
    reconciler = DefaultSelectionReconciler(
        coordinator,
        should_select=lambda _profile, _candidate: True,
    )
    observation = _catalog(1, _candidate("semantic", eligible=False))

    reconciler.reconcile(observation)
    assert coordinator.snapshot().automatic_decisions[0].selected_by_default is False
    assert coordinator.resolve_intent().requested_names == ()

    coordinator.user_editor().activate_tool_names(("semantic",))
    resolution = resolve_tool_intent_availability(
        coordinator.resolve_intent(),
        available_names=(candidate.tool_name for candidate in observation.candidates),
    )

    assert resolution.active_names == ("semantic",)


def test_profile_automatic_exclusions_are_applied_before_product_selector() -> None:
    coordinator = GovernedToolIntentCoordinator(
        session_id="session-1",
        bound_profile=_profile(automatic_exclusions=("builtin",)),
    )
    DefaultSelectionReconciler(
        coordinator,
        should_select=lambda _profile, _candidate: True,
    ).reconcile(_catalog(1, _candidate("builtin"), _candidate("plugin")))

    assert tuple(
        (item.tool_name, item.selected_by_default)
        for item in coordinator.snapshot().automatic_decisions
    ) == (("builtin", False), ("plugin", True))


def test_stale_intent_compare_and_swap_cannot_overwrite_newer_mutation() -> None:
    coordinator = GovernedToolIntentCoordinator(
        session_id="session-1",
        bound_profile=_profile("read"),
    )
    editor = coordinator.user_editor()

    editor.activate_tool_names(("bash",), expected_revision=0)

    with pytest.raises(StaleToolIntentRevisionError):
        editor.deactivate_tool_names(("read",), expected_revision=0)
    assert coordinator.resolve_intent().requested_names == ("read", "bash")


def test_stale_complete_intent_replacement_fails_without_changing_memory() -> None:
    coordinator = GovernedToolIntentCoordinator(
        session_id="session-1",
        bound_profile=_profile("read"),
    )
    stale = coordinator.snapshot()
    coordinator.user_editor().activate_tool_names(("bash",), expected_revision=0)
    current = coordinator.snapshot()

    with pytest.raises(StaleToolIntentRevisionError):
        coordinator.restorer().replace_tool_intent(stale, expected_revision=0)

    assert coordinator.snapshot() is current


def test_explicit_only_mode_is_exact_and_global_reset_restores_bound_profile() -> None:
    coordinator = GovernedToolIntentCoordinator(
        session_id="session-1",
        bound_profile=_profile("read", "bash"),
    )
    editor = coordinator.user_editor()

    editor.set_explicit_only(("manual",), expected_revision=0)

    assert coordinator.snapshot().selection_mode is IntentSelectionMode.EXPLICIT_ONLY
    assert coordinator.resolve_intent().requested_names == ("manual",)

    coordinator.restorer().reset_all_tool_intent(
        expected_revision=coordinator.snapshot().intent_revision
    )

    assert coordinator.snapshot().selection_mode is IntentSelectionMode.INHERIT_DEFAULTS
    assert coordinator.resolve_intent().requested_names == ("read", "bash")


def test_explicit_only_compare_and_swap_preserves_authoritative_order() -> None:
    coordinator = GovernedToolIntentCoordinator(
        session_id="session-1",
        bound_profile=_profile(),
    )
    editor = coordinator.user_editor()
    editor.set_explicit_only(("read", "bash"), expected_revision=0)

    change = editor.set_explicit_only(
        ("bash", "read"),
        expected_revision=coordinator.snapshot().intent_revision,
    )

    assert change.diff.explicit_enabled_order_changed is True
    assert coordinator.resolve_intent().requested_names == ("bash", "read")


def test_superseded_catalog_epoch_cannot_reconcile_again() -> None:
    coordinator = GovernedToolIntentCoordinator(
        session_id="session-1",
        bound_profile=_profile(),
    )
    reconciler = DefaultSelectionReconciler(
        coordinator,
        should_select=lambda _profile, _candidate: False,
    )
    reconciler.reconcile(_catalog(1, epoch="catalog:old"))
    reconciler.reconcile(
        _catalog(0, epoch="catalog:new", epoch_generation=2)
    )

    with pytest.raises(StaleToolCatalogObservationError):
        reconciler.reconcile(
            _catalog(2, epoch="catalog:old", epoch_generation=1)
        )


def test_profile_migration_preserves_existing_first_seen_decisions() -> None:
    assembler = DefaultToolProfileAssembler(
        profile_id="coding.tools.default",
        namespace_order=("base",),
        automatic_selection_policy_fingerprint="coding.tools.auto.v1",
        automatic_selection_enabled=True,
    )
    coordinator = GovernedToolIntentCoordinator(
        session_id="session-1",
        bound_profile=assembler.snapshot(),
    )
    reconciler = DefaultSelectionReconciler(
        coordinator,
        should_select=lambda _profile, _candidate: True,
    )
    reconciler.reconcile(_catalog(1, _candidate("plugin")))
    previous = coordinator.snapshot()
    base = assembler.contributor(
        namespace="base",
        contributor_id="coding.base",
    )
    contribution = base.replace_contribution(("read",), expected_revision=0)

    coordinator.profile_publisher(assembler).publish_profile(
        contribution,
        expected_profile_revision=0,
        expected_intent_revision=previous.intent_revision,
    )
    policy_change = assembler.migrate_automatic_selection_policy(
        automatic_selection_policy_fingerprint="coding.tools.auto.v2",
        automatic_selection_enabled=False,
        expected_profile_revision=1,
    )
    coordinator.profile_publisher(assembler).publish_profile(
        policy_change,
        expected_profile_revision=1,
        expected_intent_revision=coordinator.snapshot().intent_revision,
    )
    followup = base.replace_contribution(
        ("read", "bash"),
        expected_revision=1,
    )
    coordinator.profile_publisher(assembler).publish_profile(
        followup,
        expected_profile_revision=2,
        expected_intent_revision=coordinator.snapshot().intent_revision,
    )

    current = coordinator.snapshot()
    assert current.bound_profile.profile_revision == 3
    assert current.automatic_decisions == previous.automatic_decisions
    assert coordinator.resolve_intent().requested_names == (
        "read",
        "bash",
        "plugin",
    )


def test_legacy_positive_conversion_preserves_exact_order_and_pending_names() -> None:
    coordinator = GovernedToolIntentCoordinator.from_legacy_positive(
        session_id="session-1",
        bound_profile=_profile("default"),
        requested_names=("missing", "bash", "read", "bash"),
    )

    assert coordinator.snapshot().selection_mode is IntentSelectionMode.EXPLICIT_ONLY
    assert coordinator.resolve_intent().requested_names == (
        "missing",
        "bash",
        "read",
    )
    resolution = resolve_tool_intent_availability(
        coordinator.resolve_intent(),
        available_names=("bash", "read"),
    )
    assert resolution.pending_names == ("missing",)


def test_profile_contributors_replace_only_their_bound_slice() -> None:
    assembler = DefaultToolProfileAssembler(
        profile_id="coding.tools.default",
        namespace_order=("base", "multiagent"),
        automatic_selection_policy_fingerprint="coding.tools.auto.v1",
        automatic_selection_enabled=True,
    )
    base = assembler.contributor(namespace="base", contributor_id="coding.base")
    multiagent = assembler.contributor(
        namespace="multiagent",
        contributor_id="coding.multiagent",
    )
    start = Barrier(2)

    def publish_base() -> None:
        start.wait()
        base.replace_contribution(("read", "bash"), expected_revision=0)

    def publish_multiagent() -> None:
        start.wait()
        multiagent.replace_contribution(
            ("spawn_agent", "wait_agent"),
            expected_revision=0,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        tuple(pool.map(lambda action: action(), (publish_base, publish_multiagent)))

    assert assembler.snapshot().static_default_names == (
        "read",
        "bash",
        "spawn_agent",
        "wait_agent",
    )

    base.withdraw_contribution(expected_revision=1)

    assert assembler.snapshot().static_default_names == (
        "spawn_agent",
        "wait_agent",
    )


def test_product_profile_composition_does_not_fabricate_explicit_enable() -> None:
    assembler = DefaultToolProfileAssembler(
        profile_id="coding.tools.default",
        namespace_order=("base", "multiagent"),
        automatic_selection_policy_fingerprint="coding.tools.auto.v1",
        automatic_selection_enabled=True,
    )
    base_change = assembler.contributor(
        namespace="base",
        contributor_id="coding.base",
    ).replace_contribution(("read",), expected_revision=0)
    multiagent_change = assembler.contributor(
        namespace="multiagent",
        contributor_id="coding.multiagent",
    ).replace_contribution(("spawn_agent",), expected_revision=0)
    coordinator = GovernedToolIntentCoordinator(
        session_id="session-1",
        bound_profile=_profile(revision=0),
    )

    coordinator.profile_publisher(assembler).publish_profile(
        base_change,
        expected_profile_revision=0,
        expected_intent_revision=0,
    )
    coordinator.profile_publisher(assembler).publish_profile(
        multiagent_change,
        expected_profile_revision=1,
        expected_intent_revision=1,
    )

    assert coordinator.resolve_intent().requested_names == ("read", "spawn_agent")
    assert coordinator.snapshot().explicit_enabled == ()


def test_profile_publisher_rejects_a_change_from_another_assembler() -> None:
    expected = DefaultToolProfileAssembler(
        profile_id="coding.tools.default",
        namespace_order=("base",),
        automatic_selection_policy_fingerprint="coding.tools.auto.v1",
        automatic_selection_enabled=True,
    )
    foreign = DefaultToolProfileAssembler(
        profile_id="coding.tools.default",
        namespace_order=("base",),
        automatic_selection_policy_fingerprint="coding.tools.auto.v1",
        automatic_selection_enabled=True,
    )
    foreign_change = foreign.contributor(
        namespace="base",
        contributor_id="coding.base",
    ).replace_contribution(("read",), expected_revision=0)
    coordinator = GovernedToolIntentCoordinator(
        session_id="session-1",
        bound_profile=expected.snapshot(),
    )

    with pytest.raises(PermissionError, match="not issued by this assembler"):
        coordinator.profile_publisher(expected).publish_profile(
            foreign_change,
            expected_profile_revision=0,
            expected_intent_revision=0,
        )

    assert coordinator.snapshot().bound_profile.profile_revision == 0


def test_profile_publisher_rejects_tampered_assembler_receipt() -> None:
    assembler = DefaultToolProfileAssembler(
        profile_id="coding.tools.default",
        namespace_order=("base",),
        automatic_selection_policy_fingerprint="coding.tools.auto.v1",
        automatic_selection_enabled=True,
    )
    change = assembler.contributor(
        namespace="base",
        contributor_id="coding.base",
    ).replace_contribution(("read",), expected_revision=0)
    forged = replace(
        change,
        current=replace(
            change.current,
            static_default_names=("evil",),
            automatic_selection_policy_fingerprint="evil-policy",
        ),
    )
    coordinator = GovernedToolIntentCoordinator(
        session_id="session-1",
        bound_profile=change.previous,
    )

    with pytest.raises(PermissionError, match="not issued by this assembler"):
        coordinator.profile_publisher(assembler).publish_profile(
            forged,
            expected_profile_revision=0,
            expected_intent_revision=0,
        )

    assert coordinator.snapshot().bound_profile == change.previous


def test_profile_receipt_registry_does_not_retain_dead_publications() -> None:
    assembler = DefaultToolProfileAssembler(
        profile_id="coding.tools.default",
        namespace_order=("base",),
        automatic_selection_policy_fingerprint="coding.tools.auto.v1",
        automatic_selection_enabled=True,
    )
    contributor = assembler.contributor(
        namespace="base",
        contributor_id="coding.base",
    )
    publication = contributor.replace_contribution(("read",), expected_revision=0)
    receipt_ref = ref(publication._receipt_token)

    del publication
    gc.collect()

    assert receipt_ref() is None


def test_profile_receipt_payload_rejects_reflective_snapshot_mutation() -> None:
    assembler = DefaultToolProfileAssembler(
        profile_id="coding.tools.default",
        namespace_order=("base",),
        automatic_selection_policy_fingerprint="coding.tools.auto.v1",
        automatic_selection_enabled=True,
    )
    publication = assembler.contributor(
        namespace="base",
        contributor_id="coding.base",
    ).replace_contribution(("read",), expected_revision=0)
    coordinator = GovernedToolIntentCoordinator(
        session_id="session-1",
        bound_profile=publication.previous,
    )
    object.__setattr__(publication.current, "static_default_names", ("evil",))

    with pytest.raises(PermissionError, match="not issued by this assembler"):
        coordinator.profile_publisher(assembler).publish_profile(
            publication,
            expected_profile_revision=0,
            expected_intent_revision=0,
        )


def test_reconciler_retries_after_concurrent_intent_mutation() -> None:
    coordinator = GovernedToolIntentCoordinator(
        session_id="session-1",
        bound_profile=_profile(),
    )
    first_attempt = True

    def select(_profile: DefaultToolProfileSnapshot, _candidate: ToolCatalogCandidate) -> bool:
        nonlocal first_attempt
        if first_attempt:
            first_attempt = False
            coordinator.user_editor().deactivate_tool_names(("other",))
        return True

    reconciler = DefaultSelectionReconciler(
        coordinator,
        should_select=select,
        max_attempts=3,
    )

    reconciler.reconcile(_catalog(1, _candidate("plugin")))

    assert coordinator.resolve_intent().requested_names == ("plugin",)
    assert tuple(
        item.tool_name for item in coordinator.snapshot().explicit_disabled
    ) == ("other",)


def test_equal_catalog_cursor_rejects_different_observation_content() -> None:
    coordinator = GovernedToolIntentCoordinator(
        session_id="session-1",
        bound_profile=_profile(),
    )
    reconciler = DefaultSelectionReconciler(
        coordinator,
        should_select=lambda _profile, _candidate: True,
    )
    reconciler.reconcile(_catalog(1, _candidate("first")))

    with pytest.raises(StaleToolCatalogObservationError):
        reconciler.reconcile(_catalog(1, _candidate("second")))

    assert coordinator.resolve_intent().requested_names == ("first",)


def test_rehydrated_snapshot_retains_monotonic_catalog_epoch_fence() -> None:
    original = GovernedToolIntentCoordinator(
        session_id="session-1",
        bound_profile=_profile(),
    )
    reconciler = DefaultSelectionReconciler(
        original,
        should_select=lambda _profile, _candidate: False,
    )
    reconciler.reconcile(_catalog(1, epoch="catalog:old", epoch_generation=1))
    reconciler.reconcile(_catalog(0, epoch="catalog:new", epoch_generation=2))
    restored = GovernedToolIntentCoordinator.from_snapshot(original.snapshot())

    with pytest.raises(StaleToolCatalogObservationError):
        DefaultSelectionReconciler(
            restored,
            should_select=lambda _profile, _candidate: True,
        ).reconcile(
            _catalog(
                2,
                _candidate("stale"),
                epoch="catalog:old",
                epoch_generation=1,
            )
        )

    assert restored.resolve_intent().requested_names == ()


def test_exact_replacement_reports_changed_automatic_decision_content() -> None:
    coordinator = GovernedToolIntentCoordinator(
        session_id="session-1",
        bound_profile=_profile(),
    )
    DefaultSelectionReconciler(
        coordinator,
        should_select=lambda _profile, _candidate: True,
    ).reconcile(_catalog(1, _candidate("plugin")))
    previous = coordinator.snapshot()
    decision = previous.automatic_decisions[0]
    replacement = replace(
        previous,
        automatic_decisions=(replace(decision, selected_by_default=False),),
    )

    change = coordinator.restorer().replace_tool_intent(
        replacement,
        expected_revision=previous.intent_revision,
    )

    assert change.diff.automatic_decisions_replaced == ("plugin",)
    assert change.diff.changed is True
    assert coordinator.resolve_intent().requested_names == ()


def test_live_exact_replacement_cannot_move_catalog_fence_backwards() -> None:
    coordinator = GovernedToolIntentCoordinator(
        session_id="session-1",
        bound_profile=_profile(),
    )
    reconciler = DefaultSelectionReconciler(
        coordinator,
        should_select=lambda _profile, _candidate: False,
    )
    reconciler.reconcile(_catalog(1, epoch="catalog:old", epoch_generation=1))
    old = coordinator.snapshot()
    reconciler.reconcile(_catalog(0, epoch="catalog:new", epoch_generation=2))
    current = coordinator.snapshot()

    with pytest.raises(StaleToolCatalogObservationError):
        coordinator.restorer().replace_tool_intent(
            old,
            expected_revision=current.intent_revision,
        )

    assert coordinator.snapshot() is current


def test_restorable_snapshot_rejects_noncanonical_or_duplicate_sequences() -> None:
    current = GovernedToolIntentCoordinator.from_legacy_positive(
        session_id="session-1",
        bound_profile=_profile(),
        requested_names=("first", "second"),
    ).snapshot()

    with pytest.raises(ValueError, match="strictly increasing"):
        ToolIntentSnapshot(
            session_id=current.session_id,
            intent_revision=current.intent_revision,
            bound_profile=current.bound_profile,
            selection_mode=current.selection_mode,
            explicit_enabled=tuple(reversed(current.explicit_enabled)),
        )


def test_forged_profile_contributor_handle_cannot_mutate_assembler() -> None:
    assembler = DefaultToolProfileAssembler(
        profile_id="coding.tools.default",
        namespace_order=("base",),
        automatic_selection_policy_fingerprint="coding.tools.auto.v1",
        automatic_selection_enabled=True,
    )
    forged = ToolDefaultProfileContributorHandle(
        assembler,
        ("evil", "intruder"),
        object(),
    )

    with pytest.raises(PermissionError, match="invalid default-profile"):
        forged.replace_contribution(("read",), expected_revision=0)

    assert assembler.snapshot().profile_revision == 0
    assert assembler.snapshot().static_default_names == ()
