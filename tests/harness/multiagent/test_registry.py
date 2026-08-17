from __future__ import annotations

from datetime import UTC, datetime

import pytest

from loushang.harness.multiagent import (
    AgentPath,
    AgentRegistry,
    MultiAgentError,
)

NOW = datetime(2026, 7, 26, tzinfo=UTC)


def _registry() -> AgentRegistry:
    return AgentRegistry(clock=lambda: NOW)


def test_agent_path_is_canonical_and_round_trips() -> None:
    path = AgentPath.root().child("reviewer-1").child("security_check")

    assert str(path) == "/root/reviewer-1/security_check"
    assert AgentPath.parse(str(path)) == path
    assert path.depth == 2
    assert path.parent == AgentPath.parse("/root/reviewer-1")


@pytest.mark.parametrize(
    "value",
    [
        "root",
        "/other",
        "/root/Upper",
        "/root/has space",
        "/root/a.b",
        "/root/",
        "/root//child",
    ],
)
def test_agent_path_rejects_noncanonical_values(value: str) -> None:
    with pytest.raises(ValueError):
        AgentPath.parse(value)


def test_pending_reservation_is_hidden_and_rollback_releases_the_name() -> None:
    registry = _registry()
    reservation = registry.reserve(
        parent_ref=registry.root_ref,
        name="reviewer",
        agent_type="reviewer",
    )

    assert registry.current(reservation.ref.path) is None
    assert registry.reserved_count == 1

    reservation.rollback()
    replacement = registry.reserve(
        parent_ref=registry.root_ref,
        name="reviewer",
        agent_type="reviewer",
    )

    assert replacement.ref.incarnation > reservation.ref.incarnation


def test_open_name_conflicts_but_close_allows_a_new_incarnation() -> None:
    registry = _registry()
    first = registry.reserve(
        parent_ref=registry.root_ref,
        name="reviewer",
        agent_type="reviewer",
    ).commit()

    with pytest.raises(MultiAgentError, match="already uses") as error:
        registry.reserve(
            parent_ref=registry.root_ref,
            name="reviewer",
            agent_type="reviewer",
        )
    assert error.value.code == "agent_name_conflict"

    registry.close(first.ref)
    second = registry.reserve(
        parent_ref=registry.root_ref,
        name="reviewer",
        agent_type="reviewer",
    ).commit()

    assert second.path == first.path
    assert second.ref.incarnation == first.ref.incarnation + 1
    assert registry.get(first.ref, include_closed=True) is None


def test_relative_resolution_reports_ambiguous_descendant_names() -> None:
    registry = _registry()
    left = registry.reserve(
        parent_ref=registry.root_ref,
        name="left",
        agent_type="coordinator",
    ).commit()
    right = registry.reserve(
        parent_ref=registry.root_ref,
        name="right",
        agent_type="coordinator",
    ).commit()
    registry.reserve(
        parent_ref=left.ref,
        name="reviewer",
        agent_type="reviewer",
    ).commit()
    registry.reserve(
        parent_ref=right.ref,
        name="reviewer",
        agent_type="reviewer",
    ).commit()

    with pytest.raises(MultiAgentError) as error:
        registry.resolve(caller_ref=registry.root_ref, target="reviewer")

    assert error.value.code == "agent_reference_ambiguous"
    assert error.value.details["candidates"] == (
        "/root/left/reviewer",
        "/root/right/reviewer",
    )


def test_commit_fails_if_parent_closes_during_the_reservation_window() -> None:
    registry = _registry()
    parent = registry.reserve(
        parent_ref=registry.root_ref,
        name="parent",
        agent_type="coordinator",
    ).commit()
    child = registry.reserve(
        parent_ref=parent.ref,
        name="child",
        agent_type="reviewer",
    )
    registry.close(parent.ref)

    with pytest.raises(MultiAgentError) as error:
        child.commit()

    assert error.value.code == "parent_not_open"
    assert registry.reserved_count == 0
