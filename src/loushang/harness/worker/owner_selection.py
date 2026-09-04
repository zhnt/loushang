"""Explicit default-dark selection of the owner for future Worker sessions."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Literal

from .contracts import ManagedWorkerLaunchRequestV1
from .session import ManagedWorkerSession, ManagedWorkerSessionLaunchPort

WORKER_HOSTING_ACTIVATION_VERSION = 1
WORKER_HOSTING_SELECTION_VERSION = 1

WorkerSessionOwner = Literal["current", "hosting"]
WorkerHostingDiagnosticCode = Literal[
    "worker_hosting_current_default",
    "worker_hosting_selected",
    "worker_hosting_rollback_latched",
]


class WorkerHostingActivationError(RuntimeError):
    """Stable refusal at the explicit Current-versus-Hosting owner gate."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class WorkerHostingActivationV1:
    """Trusted-composition input; omission always means the Current owner."""

    owner: WorkerSessionOwner = "current"
    activation_version: int = WORKER_HOSTING_ACTIVATION_VERSION

    def __post_init__(self) -> None:
        _require_owner(self.owner)
        if (
            type(self.activation_version) is not int
            or self.activation_version != WORKER_HOSTING_ACTIVATION_VERSION
        ):
            raise ValueError("Unsupported Worker Hosting activation version")


@dataclass(frozen=True, slots=True)
class WorkerHostingSelectionV1:
    """Pathless diagnostic snapshot of the owner selected for future attempts."""

    requested_owner: WorkerSessionOwner
    effective_owner: WorkerSessionOwner
    hosting_available: bool
    rollback_latched: bool
    generation: int
    code: WorkerHostingDiagnosticCode
    selection_version: int = WORKER_HOSTING_SELECTION_VERSION

    def __post_init__(self) -> None:
        _require_owner(self.requested_owner)
        _require_owner(self.effective_owner)
        if type(self.hosting_available) is not bool:
            raise TypeError("Worker Hosting availability must be a boolean")
        if type(self.rollback_latched) is not bool:
            raise TypeError("Worker Hosting rollback state must be a boolean")
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError("Worker Hosting selection generation must be positive")
        if self.code not in {
            "worker_hosting_current_default",
            "worker_hosting_selected",
            "worker_hosting_rollback_latched",
        }:
            raise ValueError("Worker Hosting diagnostic code is unsupported")
        if self.effective_owner == "hosting" and (
            not self.hosting_available or self.rollback_latched
        ):
            raise ValueError("Worker Hosting selection is internally inconsistent")
        if self.requested_owner == "hosting" and not self.hosting_available:
            raise ValueError("Requested Worker Hosting owner must be available")
        if self.rollback_latched and (
            self.effective_owner != "current" or self.generation < 2
        ):
            raise ValueError("Worker Hosting rollback diagnostic is inconsistent")
        expected_code: WorkerHostingDiagnosticCode
        if self.rollback_latched:
            expected_code = "worker_hosting_rollback_latched"
        elif self.effective_owner == "hosting":
            expected_code = "worker_hosting_selected"
        else:
            expected_code = "worker_hosting_current_default"
        if self.code != expected_code:
            raise ValueError("Worker Hosting diagnostic code is inconsistent")
        if (
            type(self.selection_version) is not int
            or self.selection_version != WORKER_HOSTING_SELECTION_VERSION
        ):
            raise ValueError("Unsupported Worker Hosting selection version")

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "effectiveOwner": self.effective_owner,
            "generation": self.generation,
            "hostingAvailable": self.hosting_available,
            "requestedOwner": self.requested_owner,
            "rollbackLatched": self.rollback_latched,
            "selectionVersion": self.selection_version,
        }


class WorkerSessionOwnerRouter(ManagedWorkerSessionLaunchPort):
    """Explicit, no-fallback owner selector with a sticky rapid-rollback latch."""

    def __init__(
        self,
        *,
        current: ManagedWorkerSessionLaunchPort,
        hosting: ManagedWorkerSessionLaunchPort | None = None,
        activation: WorkerHostingActivationV1 | None = None,
    ) -> None:
        if not callable(getattr(current, "start", None)):
            raise TypeError("Worker session router requires the Current owner")
        if hosting is not None and not callable(getattr(hosting, "start", None)):
            raise TypeError("Worker session router received an invalid Hosting owner")
        if activation is None:
            activation = WorkerHostingActivationV1()
        elif not isinstance(activation, WorkerHostingActivationV1):
            raise TypeError("Worker session router requires typed activation")
        if activation.owner == "hosting" and hosting is None:
            raise WorkerHostingActivationError(
                "Worker Hosting was requested without a compatible session owner",
                code="worker_hosting_owner_unavailable",
            )
        self._current = current
        self._hosting = hosting
        self._requested_owner = activation.owner
        self._effective_owner = activation.owner
        self._rollback_latched = False
        self._generation = 1
        self._lock = threading.Lock()

    @property
    def selection(self) -> WorkerHostingSelectionV1:
        with self._lock:
            return self._selection_locked()

    def rollback_to_current(self) -> WorkerHostingSelectionV1:
        """Latch future attempts to Current; an already selected start is untouched."""

        with self._lock:
            if not self._rollback_latched:
                self._rollback_latched = True
                self._effective_owner = "current"
                self._generation += 1
            return self._selection_locked()

    async def start(
        self,
        request: ManagedWorkerLaunchRequestV1,
        *,
        correlation_id: str,
        signal: object | None = None,
    ) -> ManagedWorkerSession:
        with self._lock:
            owner = self._effective_owner
            port = self._hosting if owner == "hosting" else self._current
        if port is None:
            # Construction and the rollback latch make this unreachable. Keep the
            # execution boundary fail closed if internal state is corrupted.
            raise WorkerHostingActivationError(
                "Selected Worker Hosting owner is unavailable",
                code="worker_hosting_owner_unavailable",
            )
        # Never retry against the other owner after a partial or failed start.
        return await port.start(
            request,
            correlation_id=correlation_id,
            signal=signal,
        )

    def _selection_locked(self) -> WorkerHostingSelectionV1:
        if self._rollback_latched:
            code: WorkerHostingDiagnosticCode = "worker_hosting_rollback_latched"
        elif self._effective_owner == "hosting":
            code = "worker_hosting_selected"
        else:
            code = "worker_hosting_current_default"
        return WorkerHostingSelectionV1(
            requested_owner=self._requested_owner,
            effective_owner=self._effective_owner,
            hosting_available=self._hosting is not None,
            rollback_latched=self._rollback_latched,
            generation=self._generation,
            code=code,
        )


def _require_owner(owner: object) -> None:
    if type(owner) is not str or owner not in {"current", "hosting"}:
        raise ValueError("Worker session owner must be current or hosting")


__all__ = [
    "WORKER_HOSTING_ACTIVATION_VERSION",
    "WORKER_HOSTING_SELECTION_VERSION",
    "WorkerHostingActivationError",
    "WorkerHostingActivationV1",
    "WorkerHostingSelectionV1",
    "WorkerSessionOwner",
    "WorkerSessionOwnerRouter",
]
