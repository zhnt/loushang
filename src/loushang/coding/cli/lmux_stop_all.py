"""Coding CLI result presentation over the original managed stop owners."""

from __future__ import annotations

from collections.abc import Callable

from loushang.apphost.managed.defaults import ManagedDefaultsV1
from loushang.apphost.managed.discovery import (
    ManagedDiscoverySnapshotV1,
    ManagedServiceObservationV1,
)
from loushang.apphost.managed.namespace_admission import ManagedNamespaceAdmissionV1
from loushang.apphost.managed.stopper import _ManagedServiceStopBatch


class StopAll(_ManagedServiceStopBatch):
    def __init__(self, namespace: ManagedNamespaceAdmissionV1, defaults: ManagedDefaultsV1,
                 snapshot: ManagedDiscoverySnapshotV1, *, deadline: float,
                 emit: Callable[[dict[str, object]], None]) -> None:
        self.emit = emit
        super().__init__(namespace, defaults, snapshot, deadline=deadline)

    def _report(self, observation: ManagedServiceObservationV1, status: str, *,
                reason: str | None = None, code: str | None = None) -> None:
        result: dict[str, object] = {
            "action": "stop_result", "serviceId": observation.service.service_id,
            "instanceId": None if observation.instance is None else observation.instance.instance_id,
            "status": status,
        }
        if reason is not None:
            result["reason"] = reason
        if code is not None:
            result["code"] = code
        self.emit(result)
