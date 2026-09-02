from __future__ import annotations

from dataclasses import dataclass

import pytest

from loushang.harness.capabilities.tools import (
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


def test_refresh_auto_activates_new_tools_in_available_order() -> None:
    coordinator = ToolActivationCoordinator(
        available=(Tool("read"),),
        requested_names=("read",),
        should_activate_new=lambda name, tool: (
            name.startswith("plugin_") and tool.version > 0
        ),
    )

    change = coordinator.refresh(
        (Tool("read"), Tool("plugin_z"), Tool("bash"), Tool("plugin_a"))
    )

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
