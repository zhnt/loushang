"""Handle-free Worker witness across Hosting and Product start-gate owners.

Hosting alone inspects a native ChildSession. Product receives only immutable
identity and pipe facts, then decides whether its private gate may be released.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol

from loushang.hosting.contracts import ChildSessionLease
from loushang.hosting.errors import HostingError
from loushang.hosting.gated_identity import linux_gated_child_session_witness
from loushang.hosting.service import LinuxServiceIdentityV1
from loushang.hosting.service_group import (
    linux_service_group_absent_after_restart,
    linux_service_group_recovery_status,
)

_BOOT_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"
)


@dataclass(frozen=True, slots=True)
class WorkerNativeProcessIdentityV1:
    pid: int
    start_ticks: int
    boot_id: str
    user_id: int
    pid_namespace_device: int
    pid_namespace_inode: int

    def __post_init__(self) -> None:
        if (
            type(self.pid) is not int
            or not 1 <= self.pid < 2**31
            or type(self.boot_id) is not str
            or _BOOT_ID.fullmatch(self.boot_id) is None
            or any(
                type(value) is not int or not 0 <= value < 2**64
                for value in (
                    self.start_ticks,
                    self.user_id,
                    self.pid_namespace_device,
                    self.pid_namespace_inode,
                )
            )
            or self.pid_namespace_inode == 0
        ):
            raise ValueError("Worker native process identity is invalid")

    @classmethod
    def from_hosting(
        cls, identity: LinuxServiceIdentityV1
    ) -> WorkerNativeProcessIdentityV1:
        if type(identity) is not LinuxServiceIdentityV1:
            raise TypeError("Hosting process identity is required")
        return cls(
            pid=identity.pid,
            start_ticks=identity.start_ticks,
            boot_id=identity.boot_id,
            user_id=identity.user_id,
            pid_namespace_device=identity.pid_namespace_device,
            pid_namespace_inode=identity.pid_namespace_inode,
        )

    def to_hosting(self) -> LinuxServiceIdentityV1:
        return LinuxServiceIdentityV1(
            pid=self.pid,
            start_ticks=self.start_ticks,
            boot_id=self.boot_id,
            user_id=self.user_id,
            pid_namespace_device=self.pid_namespace_device,
            pid_namespace_inode=self.pid_namespace_inode,
        )


@dataclass(frozen=True, slots=True)
class WorkerGatedStartWitnessV1:
    native_identity: WorkerNativeProcessIdentityV1
    gate_device: int
    gate_inode: int

    def __post_init__(self) -> None:
        if (
            type(self.native_identity) is not WorkerNativeProcessIdentityV1
            or type(self.gate_device) is not int
            or self.gate_device < 0
            or type(self.gate_inode) is not int
            or self.gate_inode < 1
        ):
            raise ValueError("Worker gated start witness is invalid")


class _ProductGatePort(Protocol):
    def release(self, witness: WorkerGatedStartWitnessV1) -> None: ...

    def close(self) -> None: ...


class _HostingGatedStartRelease:
    def __init__(self, product_gate: _ProductGatePort) -> None:
        self._product_gate = product_gate

    def release(self, lease: ChildSessionLease) -> None:
        native = linux_gated_child_session_witness(lease)
        self._product_gate.release(
            WorkerGatedStartWitnessV1(
                native_identity=WorkerNativeProcessIdentityV1.from_hosting(
                    native.native_identity
                ),
                gate_device=native.gate_device,
                gate_inode=native.gate_inode,
            )
        )

    def close(self) -> None:
        self._product_gate.close()


def bind_worker_gated_start_release(
    product_gate: _ProductGatePort,
) -> _HostingGatedStartRelease:
    if not callable(getattr(product_gate, "release", None)) or not callable(
        getattr(product_gate, "close", None)
    ):
        raise TypeError("Product Worker start gate is invalid")
    return _HostingGatedStartRelease(product_gate)


def worker_native_group_absent_after_restart(
    identity: WorkerNativeProcessIdentityV1,
) -> bool:
    if type(identity) is not WorkerNativeProcessIdentityV1:
        raise TypeError("Worker native process identity is required")
    return linux_service_group_absent_after_restart(identity.to_hosting())


WorkerNativeGroupStatus = Literal[
    "absent", "present", "prior_boot_absent", "context_stale", "unknown"
]


def worker_native_group_status_after_restart(
    identity: WorkerNativeProcessIdentityV1,
) -> WorkerNativeGroupStatus:
    """Report a read-only native fact; stale context is never absence proof."""

    if type(identity) is not WorkerNativeProcessIdentityV1:
        raise TypeError("Worker native process identity is required")
    try:
        return linux_service_group_recovery_status(identity.to_hosting())
    except HostingError:
        return "unknown"


__all__ = [
    "WorkerGatedStartWitnessV1",
    "WorkerNativeProcessIdentityV1",
    "WorkerNativeGroupStatus",
    "bind_worker_gated_start_release",
    "worker_native_group_absent_after_restart",
    "worker_native_group_status_after_restart",
]
