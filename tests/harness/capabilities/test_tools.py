from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Thread

import pytest

from loushang.harness.capabilities.tools import (
    StaleToolActivationCheckpointError,
    StaleToolActivationPublicationError,
    ToolActivationChange,
    ToolActivationCoordinator,
)


@dataclass(frozen=True)
class Tool:
    name: str
    version: int = 1


def test_tool_activation_tracks_allowed_requested_active_and_missing() -> None:
    coordinator = ToolActivationCoordinator(
        available=(Tool("read"), Tool("bash")),
        requested_names=("missing", "bash", "read", "bash"),
        allowed_names=("read", "missing"),
    )

    snapshot = coordinator.snapshot()

    assert snapshot.available_names == ("read",)
    assert snapshot.requested_names == ("missing", "read")
    assert snapshot.active_names == ("read",)
    assert snapshot.missing_requested_names == ("missing",)
    assert coordinator.resolve(("bash", "read", "missing")).names == ("read",)
    assert coordinator.resolve(("bash", "read", "missing")).missing_names == (
        "missing",
    )


def test_requested_missing_tool_reactivates_after_deterministic_refresh() -> None:
    rebound: list[ToolActivationChange[Tool]] = []
    coordinator = ToolActivationCoordinator(
        available=(Tool("read"), Tool("report")),
        requested_names=("read", "late"),
        rebind=rebound.append,
    )

    removed = coordinator.refresh((Tool("report"),), activate_new=False)
    restored = coordinator.refresh(
        (Tool("report"), Tool("read", 2), Tool("late")),
        activate_new=False,
    )

    assert removed.current.requested_names == ("read", "late")
    assert removed.current.active_names == ()
    assert removed.diff.deactivated == ("read",)
    assert restored.current.active_names == ("read", "late")
    assert restored.diff.activated == ("read", "late")
    assert [tool.name for tool in restored.active_items] == ["read", "late"]
    assert rebound == [removed, restored]


def test_activate_adds_names_without_dropping_missing_requests() -> None:
    coordinator = ToolActivationCoordinator(
        available=(Tool("spawn_agent"),),
        requested_names=("read", "bash"),
    )

    activated = coordinator.activate(("spawn_agent", "spawn_agent"))

    assert activated.current.requested_names == ("read", "bash", "spawn_agent")
    assert activated.current.active_names == ("spawn_agent",)
    assert activated.diff.requested_added == ("spawn_agent",)
    assert activated.diff.activated == ("spawn_agent",)

    published = coordinator.refresh(
        (Tool("spawn_agent"), Tool("read"), Tool("bash")),
        activate_new=False,
    )

    assert published.current.requested_names == ("read", "bash", "spawn_agent")
    assert published.current.active_names == ("read", "bash", "spawn_agent")


def test_activate_does_not_restore_names_removed_by_exact_request() -> None:
    coordinator = ToolActivationCoordinator(
        available=(Tool("read"), Tool("spawn_agent")),
        requested_names=("read",),
    )
    coordinator.request(())

    change = coordinator.activate(("spawn_agent",))

    assert change.current.requested_names == ("spawn_agent",)
    assert change.current.active_names == ("spawn_agent",)


def test_activate_respects_allowed_names() -> None:
    coordinator = ToolActivationCoordinator(
        available=(Tool("read"), Tool("spawn_agent")),
        requested_names=("read",),
        allowed_names=("read",),
    )

    change = coordinator.activate(("spawn_agent",))

    assert change.current.requested_names == ("read",)
    assert change.current.active_names == ("read",)


def test_refresh_and_default_reconciliation_are_separate_transitions() -> None:
    coordinator = ToolActivationCoordinator(
        available=(Tool("read"),),
        requested_names=("read",),
        should_activate_new=lambda name, tool: (
            name.startswith("plugin_") and tool.version > 0
        ),
    )

    publication = coordinator.refresh(
        (Tool("read"), Tool("plugin_z"), Tool("bash"), Tool("plugin_a"))
    )
    assert publication.current.requested_names == ("read",)

    change = coordinator.reconcile_default_selection(publication)

    assert change.current.requested_names == (
        "read",
        "plugin_z",
        "plugin_a",
    )
    assert change.current.active_names == (
        "read",
        "plugin_z",
        "plugin_a",
    )
    assert change.diff.requested_added == ("plugin_z", "plugin_a")
    assert change.diff.activated == ("plugin_z", "plugin_a")


def test_failed_legacy_predicate_does_not_consume_first_seen_decision() -> None:
    attempts = 0

    def select(_name: str, _tool: Tool) -> bool:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("selector failed")
        return True

    coordinator = ToolActivationCoordinator(
        should_activate_new=select,
    )
    publication = coordinator.refresh((Tool("plugin"),), rebind=False)

    with pytest.raises(RuntimeError, match="selector failed"):
        coordinator.reconcile_default_selection(publication, rebind=False)

    change = coordinator.reconcile_default_selection(publication, rebind=False)
    assert change.current.requested_names == ("plugin",)
    assert attempts == 2


def test_stale_legacy_publication_cannot_consume_republished_first_seen() -> None:
    coordinator = ToolActivationCoordinator(
        should_activate_new=lambda _name, _tool: True,
    )
    stale = coordinator.refresh((Tool("plugin"),), rebind=False)
    coordinator.refresh((), rebind=False)

    with pytest.raises(StaleToolActivationPublicationError):
        coordinator.reconcile_default_selection(stale, rebind=False)

    change = coordinator.refresh_and_reconcile_default_selection(
        (Tool("plugin"),),
        rebind=False,
    )
    assert change.current.requested_names == ("plugin",)


def test_legacy_checkpoint_cannot_overwrite_a_newer_mutation() -> None:
    coordinator = ToolActivationCoordinator(
        available=(Tool("read"), Tool("manual")),
        requested_names=("read",),
    )
    checkpoint = coordinator.checkpoint()
    activation = coordinator.activate(("manual",), rebind=False)
    coordinator.request(("manual",), rebind=False)

    with pytest.raises(StaleToolActivationCheckpointError):
        coordinator.restore_checkpoint(
            checkpoint,
            expected_previous_revision=checkpoint.revision,
            expected_revision=activation.current.revision,
            rebind=False,
        )

    assert coordinator.snapshot().requested_names == ("manual",)


def test_legacy_checkpoint_rollback_keeps_revision_monotonic() -> None:
    coordinator = ToolActivationCoordinator(
        available=(Tool("read"), Tool("manual")),
        requested_names=("read",),
    )
    checkpoint = coordinator.checkpoint()
    activation = coordinator.activate(("manual",), rebind=False)

    coordinator.restore_checkpoint(
        checkpoint,
        expected_previous_revision=checkpoint.revision,
        expected_revision=activation.current.revision,
        rebind=False,
    )

    restored = coordinator.snapshot()
    assert restored.revision > activation.current.revision
    assert restored.requested_names == ("read",)


def test_failed_publication_compensation_preserves_intervening_user_intent() -> (
    None
):
    coordinator = ToolActivationCoordinator(
        should_activate_new=lambda _name, _tool: True,
    )
    checkpoint = coordinator.checkpoint()
    coordinator.activate(("manual",), rebind=False)
    publication = coordinator.refresh_and_reconcile_default_selection(
        (Tool("plugin"),),
        rebind=False,
    )

    with pytest.raises(StaleToolActivationCheckpointError):
        coordinator.restore_checkpoint(
            checkpoint,
            expected_previous_revision=publication.previous.revision,
            expected_revision=publication.current.revision,
            rebind=False,
        )

    coordinator.compensate_failed_publication(
        checkpoint,
        publication_revision=publication.current.revision,
        rebind=False,
    )
    coordinator.refresh_and_reconcile_default_selection(
        (),
        enabled=False,
        rebind=False,
    )
    republished = coordinator.refresh_and_reconcile_default_selection(
        (Tool("plugin"),),
        enabled=False,
        rebind=False,
    )

    assert republished.current.requested_names == ("manual",)
    assert republished.current.active_names == ()


def test_failed_publication_never_consumes_first_seen_after_explicit_touch() -> (
    None
):
    calls: list[str] = []
    coordinator = ToolActivationCoordinator(
        should_activate_new=lambda name, _tool: calls.append(name) or True,
    )
    checkpoint = coordinator.checkpoint()
    publication = coordinator.refresh_and_reconcile_default_selection(
        (Tool("plugin"),),
        rebind=False,
    )
    coordinator.activate(("plugin",), rebind=False)

    coordinator.compensate_failed_publication(
        checkpoint,
        publication_revision=publication.current.revision,
        rebind=False,
    )
    coordinator.refresh_and_reconcile_default_selection(
        (),
        enabled=False,
        rebind=False,
    )
    coordinator.request((), rebind=False)
    republished = coordinator.refresh_and_reconcile_default_selection(
        (Tool("plugin"),),
        rebind=False,
    )

    assert calls == ["plugin", "plugin"]
    assert republished.current.requested_names == ("plugin",)


def test_rebind_failure_receipt_keeps_origin_separate_from_chased_revision() -> (
    None
):
    calls: list[int] = []
    coordinator: ToolActivationCoordinator[Tool]

    def rebind(change: ToolActivationChange[Tool]) -> None:
        calls.append(change.current.revision)
        if len(calls) == 1:
            coordinator.activate(("manual",), rebind=False)
            return
        raise RuntimeError("newer rebind failed")

    coordinator = ToolActivationCoordinator(
        available=(Tool("read"), Tool("manual")),
        rebind=rebind,
    )

    with pytest.raises(RuntimeError, match="newer rebind failed") as raised:
        coordinator.request(("read",))

    assert calls == [1, 2]
    assert coordinator.failed_rebind_transition(raised.value) == (0, 1, 2)
    assert coordinator.snapshot().requested_names == ("read", "manual")


def test_legacy_selector_reentrant_mutation_is_preserved_by_retry() -> None:
    first_attempt = True
    coordinator: ToolActivationCoordinator[Tool]

    def select(_name: str, _tool: Tool) -> bool:
        nonlocal first_attempt
        if first_attempt:
            first_attempt = False
            coordinator.activate(("manual",), rebind=False)
        return True

    coordinator = ToolActivationCoordinator(should_activate_new=select)

    change = coordinator.refresh_and_reconcile_default_selection(
        (Tool("plugin"),),
        rebind=False,
    )

    assert change.current.requested_names == ("manual", "plugin")
    assert change.current.active_names == ("plugin",)


def test_legacy_rebind_does_not_hold_the_state_lock() -> None:
    snapshot_completed = Event()
    worker: Thread | None = None
    coordinator: ToolActivationCoordinator[Tool]

    def rebind(_change: ToolActivationChange[Tool]) -> None:
        nonlocal worker

        def observe() -> None:
            coordinator.snapshot()
            snapshot_completed.set()

        worker = Thread(target=observe)
        worker.start()
        assert snapshot_completed.wait(1)

    coordinator = ToolActivationCoordinator(
        available=(Tool("read"),),
        rebind=rebind,
    )

    coordinator.request(("read",))

    assert worker is not None
    worker.join(timeout=1)
    assert not worker.is_alive()


def test_replacement_rebinds_even_when_activation_names_do_not_change() -> None:
    rebound: list[ToolActivationChange[Tool]] = []
    original = Tool("read", 1)
    replacement = Tool("read", 2)
    coordinator = ToolActivationCoordinator(
        available=(original,),
        requested_names=("read",),
        rebind=rebound.append,
    )

    change = coordinator.refresh((replacement,))

    assert change.diff.available_replaced == ("read",)
    assert change.diff.activated == ()
    assert change.current.revision == 1
    assert change.active_items == (replacement,)
    assert rebound == [change]


def test_request_reports_activation_diff_and_rebinds_after_commit() -> None:
    observed_snapshots = []
    coordinator: ToolActivationCoordinator[Tool]

    def rebind(change: ToolActivationChange[Tool]) -> None:
        observed_snapshots.append((coordinator.snapshot(), change))

    coordinator = ToolActivationCoordinator(
        available=(Tool("read"), Tool("bash")),
        requested_names=("read",),
        rebind=rebind,
    )

    change = coordinator.request(("bash", "missing"))

    assert change.diff.activated == ("bash",)
    assert change.diff.deactivated == ("read",)
    assert change.current.missing_requested_names == ("missing",)
    assert observed_snapshots == [(change.current, change)]


def test_duplicate_available_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate available tool name"):
        ToolActivationCoordinator(available=(Tool("read", 1), Tool("read", 2)))
