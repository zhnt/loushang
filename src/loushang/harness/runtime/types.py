from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from loushang.harness.events.host import HostStatus

QueueMode: TypeAlias = Literal["all", "one-at-a-time"]


@dataclass(frozen=True)
class RunState:
    status: Literal["idle", "running"]


@dataclass(frozen=True)
class HostSnapshot:
    status: HostStatus
    active_run_id: str | None = None


__all__ = [
    "HostSnapshot",
    "QueueMode",
    "RunState",
]
