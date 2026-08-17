from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

HostStatus: TypeAlias = Literal[
    "idle",
    "running",
    "aborting",
    "disposing",
    "disposed",
]
HostLifecycleEventKind: TypeAlias = Literal[
    "run_started",
    "abort_requested",
    "run_completed",
    "run_failed",
    "run_aborted",
    "host_disposing",
    "host_disposed",
]


@dataclass(frozen=True)
class HostLifecycleEvent:
    kind: HostLifecycleEventKind
    status: HostStatus
    run_id: str | None = None
    error: str | None = None


__all__ = [
    "HostLifecycleEvent",
    "HostLifecycleEventKind",
    "HostStatus",
]
