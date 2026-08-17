from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from loushang.harness.events.host import HostLifecycleEvent
from loushang.harness.events.session import (
    QueuedMessageSnapshot,
    QueueSnapshot,
)
from loushang.harness.runtime.types import HostSnapshot, RunState


def test_host_records_are_frozen_and_preserve_neutral_values() -> None:
    queued = QueuedMessageSnapshot(id="q1", kind="steering", text="inspect")
    snapshot = QueueSnapshot(steering=(queued,))
    host = HostSnapshot(status="running", active_run_id="reference-run")
    event = HostLifecycleEvent(
        kind="run_started",
        status="running",
        run_id="reference-run",
    )

    assert snapshot.steering == (queued,)
    assert snapshot.follow_up == ()
    assert host.active_run_id == "reference-run"
    assert event.kind == "run_started"
    assert RunState(status="idle").status == "idle"
    with pytest.raises(FrozenInstanceError):
        host.status = "idle"  # type: ignore[misc]
