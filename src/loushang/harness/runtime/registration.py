"""Owner-scoped lifecycle primitives for exact live registrations."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol, TypeVar
from uuid import uuid4

RegistrationOwnerKind = Literal[
    "product",
    "oem",
    "extension",
    "capability",
    "session",
    "runtime",
]
RegistrationDisposalState = Literal[
    "removed",
    "already_removed",
    "failed_retryable",
    "failed_terminal",
]
RegistrationLeaseState = Literal[
    "staged",
    "active",
    "disposing",
    "disposed",
    "failed_retryable",
    "failed_terminal",
]
RegistrationScopeState = Literal[
    "open",
    "committed",
    "disposing",
    "disposed",
    "failed_retryable",
    "failed_terminal",
]

_OWNER_KINDS = frozenset(
    {"product", "oem", "extension", "capability", "session", "runtime"}
)
_DISPOSAL_STATES = frozenset(
    {"removed", "already_removed", "failed_retryable", "failed_terminal"}
)


@dataclass(frozen=True)
class RegistrationOwner:
    """Stable, pre-redacted diagnostic owner identity for one runtime generation."""

    owner_kind: RegistrationOwnerKind
    owner_id: str
    runtime_id: str
    generation: int

    def __post_init__(self) -> None:
        if self.owner_kind not in _OWNER_KINDS:
            raise ValueError(f"unsupported registration owner kind: {self.owner_kind}")
        _require_nonempty(self.owner_id, name="registration owner id")
        _require_nonempty(self.runtime_id, name="registration runtime id")
        if isinstance(self.generation, bool) or not isinstance(self.generation, int):
            raise TypeError("registration owner generation must be an integer")
        if self.generation < 0:
            raise ValueError("registration owner generation must not be negative")


@dataclass(frozen=True)
class RegistrationIdentity:
    """Opaque exact identity plus pre-redacted diagnostic surface/key labels."""

    surface: str
    registration_id: str
    public_key: str | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.surface, name="registration surface")
        _require_nonempty(self.registration_id, name="registration id")
        if self.public_key is not None:
            _require_nonempty(self.public_key, name="registration public key")

    @classmethod
    def create(
        cls,
        *,
        surface: str,
        public_key: str | None = None,
    ) -> RegistrationIdentity:
        """Create an opaque identity for one exact live mutation."""

        return cls(
            surface=surface,
            registration_id=uuid4().hex,
            public_key=public_key,
        )


@dataclass(frozen=True)
class RegistrationDisposalResult:
    """Redacted outcome of attempting to remove one exact registration.

    ``diagnostic_code`` is a pre-redacted stable machine identifier, never a
    raw exception message or registered value.
    """

    state: RegistrationDisposalState
    diagnostic_code: str | None = None

    def __post_init__(self) -> None:
        if self.state not in _DISPOSAL_STATES:
            raise ValueError(f"unsupported registration disposal state: {self.state}")
        if self.diagnostic_code is not None:
            _require_nonempty(
                self.diagnostic_code,
                name="registration disposal diagnostic code",
            )


RegistrationDisposer = Callable[
    [],
    None | RegistrationDisposalResult | Awaitable[None | RegistrationDisposalResult],
]
RegistrationActivation = Callable[[], None]
RegistrationRollback = Callable[[], None | RegistrationDisposalResult]


class RegistrationLease:
    """Capability token that removes only the registration that created it."""

    def __init__(
        self,
        *,
        owner: RegistrationOwner,
        identity: RegistrationIdentity,
        dispose: RegistrationDisposer,
        activate: RegistrationActivation | None = None,
        deactivate: RegistrationActivation | None = None,
        rollback: RegistrationRollback | None = None,
    ) -> None:
        if not isinstance(owner, RegistrationOwner):
            raise TypeError("registration owner must be a RegistrationOwner")
        if not isinstance(identity, RegistrationIdentity):
            raise TypeError("registration identity must be a RegistrationIdentity")
        if not callable(dispose):
            raise TypeError("registration disposer must be callable")
        if (activate is None) != (deactivate is None):
            raise ValueError(
                "staged registration requires both activate and deactivate"
            )
        if activate is not None and not callable(activate):
            raise TypeError("registration activator must be callable")
        if deactivate is not None and not callable(deactivate):
            raise TypeError("registration deactivator must be callable")
        if rollback is not None and not callable(rollback):
            raise TypeError("registration rollback must be callable")
        self._owner = owner
        self._identity = identity
        self._dispose: RegistrationDisposer | None = dispose
        self._activate = activate
        self._deactivate = deactivate
        self._rollback = rollback
        self._state: RegistrationLeaseState = (
            "staged" if activate is not None else "active"
        )
        self._last_result: RegistrationDisposalResult | None = None
        self._dispose_task: asyncio.Task[RegistrationDisposalResult] | None = None

    @property
    def owner(self) -> RegistrationOwner:
        return self._owner

    @property
    def identity(self) -> RegistrationIdentity:
        return self._identity

    @property
    def state(self) -> RegistrationLeaseState:
        return self._state

    @property
    def last_result(self) -> RegistrationDisposalResult | None:
        return self._last_result

    @property
    def can_deactivate(self) -> bool:
        return self._deactivate is not None

    def activate(self) -> None:
        """Make a staged registration effective at a synchronous commit point."""

        if self._state == "active":
            return
        if self._state != "staged" or self._activate is None:
            raise RuntimeError("registration lease cannot be activated")
        try:
            self._activate()
        except BaseException as activation_error:
            if self._deactivate is not None:
                try:
                    self._deactivate()
                except BaseException:
                    activation_error.add_note(
                        "staged registration activation rollback failed"
                    )
            raise
        self._state = "active"

    def deactivate(self) -> None:
        """Undo activation while rolling back a failed scope commit."""

        if self._state == "staged":
            return
        if self._state != "active" or self._deactivate is None:
            raise RuntimeError("registration lease cannot be deactivated")
        self._deactivate()
        self._state = "staged"

    def rollback_registration(self) -> RegistrationDisposalResult:
        """Synchronously remove an uncommitted admission mutation exactly once."""

        if self._state == "disposed":
            return RegistrationDisposalResult(state="already_removed")
        if self._state not in {"staged", "active"}:
            raise RuntimeError("registration lease cannot be rolled back")
        rollback = self._rollback
        if rollback is None:
            return RegistrationDisposalResult(
                state="failed_retryable",
                diagnostic_code="registration_rollback_unavailable",
            )
        try:
            result = rollback()
            if result is None:
                result = RegistrationDisposalResult(state="removed")
            elif not isinstance(result, RegistrationDisposalResult):
                raise TypeError(
                    "registration rollback must return a disposal result or None"
                )
        except Exception:
            result = RegistrationDisposalResult(
                state="failed_retryable",
                diagnostic_code="registration_rollback_failed",
            )
        self._last_result = result
        if result.state in {"removed", "already_removed"}:
            self._state = "disposed"
            self._dispose = None
            self._activate = None
            self._deactivate = None
            self._rollback = None
        elif result.state == "failed_retryable":
            self._state = "failed_retryable"
        else:
            self._state = "failed_terminal"
            self._dispose = None
            self._activate = None
            self._deactivate = None
            self._rollback = None
        return result

    async def dispose(self) -> RegistrationDisposalResult:
        """Remove the exact entry once and join cleanup before cancellation wins."""

        if self._state == "disposed":
            return RegistrationDisposalResult(state="already_removed")
        if self._state == "failed_terminal":
            assert self._last_result is not None
            return self._last_result

        task = self._dispose_task
        if task is None:
            self._state = "disposing"
            task = asyncio.create_task(self._dispose_once())
            self._dispose_task = task
        return await _await_cancellation_atomic(task)

    async def _dispose_once(self) -> RegistrationDisposalResult:
        try:
            disposer = self._dispose
            if disposer is None:
                raise RuntimeError("terminal registration lease has no disposer")
            result = disposer()
            if inspect.isawaitable(result):
                result = await result
            # Deliver cancellation requested synchronously by a disposer before
            # publishing a successful terminal result.
            await asyncio.sleep(0)
            if result is None:
                result = RegistrationDisposalResult(state="removed")
            elif not isinstance(result, RegistrationDisposalResult):
                raise TypeError(
                    "registration disposer must return a disposal result or None"
                )
        except asyncio.CancelledError:
            result = RegistrationDisposalResult(
                state="failed_retryable",
                diagnostic_code="registration_disposer_cancelled",
            )
        except Exception:
            result = RegistrationDisposalResult(
                state="failed_retryable",
                diagnostic_code="registration_disposer_failed",
            )

        self._last_result = result
        if result.state in {"removed", "already_removed"}:
            self._state = "disposed"
            self._dispose = None
            self._activate = None
            self._deactivate = None
            self._rollback = None
        elif result.state == "failed_retryable":
            self._state = "failed_retryable"
            self._dispose_task = None
        else:
            self._state = "failed_terminal"
            self._dispose = None
            self._activate = None
            self._deactivate = None
            self._rollback = None
        return result


class RegistrationLeaseCollector(Protocol):
    """Capture exact leases under one already-selected runtime owner."""

    @property
    def owner(self) -> RegistrationOwner: ...

    def capture(self, lease: RegistrationLease) -> RegistrationLease: ...


@dataclass(frozen=True)
class RegistrationDisposalOutcome:
    """One identity-correlated result in a scope disposal report."""

    identity: RegistrationIdentity
    result: RegistrationDisposalResult


@dataclass(frozen=True)
class RegistrationScopeDisposalResult:
    """Ordered, redacted outcomes from one reverse-disposal pass."""

    outcomes: tuple[RegistrationDisposalOutcome, ...]

    @property
    def has_failures(self) -> bool:
        return any(
            outcome.result.state in {"failed_retryable", "failed_terminal"}
            for outcome in self.outcomes
        )


class RegistrationScope:
    """Collect one owner's leases and retire them in strict reverse order."""

    def __init__(self, owner: RegistrationOwner) -> None:
        if not isinstance(owner, RegistrationOwner):
            raise TypeError("registration scope owner must be a RegistrationOwner")
        self._owner = owner
        self._leases: list[RegistrationLease] = []
        self._state: RegistrationScopeState = "open"
        self._last_result: RegistrationScopeDisposalResult | None = None
        self._dispose_task: asyncio.Task[RegistrationScopeDisposalResult] | None = None

    @property
    def owner(self) -> RegistrationOwner:
        return self._owner

    @property
    def state(self) -> RegistrationScopeState:
        return self._state

    @property
    def last_result(self) -> RegistrationScopeDisposalResult | None:
        return self._last_result

    @property
    def inventory(
        self,
    ) -> tuple[
        tuple[RegistrationOwner, RegistrationIdentity, RegistrationLeaseState], ...
    ]:
        """Return read-only ownership facts without exposing lease/disposer handles."""

        return tuple(
            (lease.owner, lease.identity, lease.state) for lease in self._leases
        )

    def add(self, lease: RegistrationLease) -> RegistrationLease:
        if self._state != "open":
            raise RuntimeError("registration scope no longer accepts leases")
        if not isinstance(lease, RegistrationLease):
            raise TypeError("registration scope accepts RegistrationLease values")
        if lease.owner != self._owner:
            raise ValueError("registration lease owner does not match scope owner")
        if lease.state not in {"active", "staged"}:
            raise ValueError("registration scope accepts only live leases")
        if any(
            existing.identity.surface == lease.identity.surface
            and existing.identity.registration_id == lease.identity.registration_id
            for existing in self._leases
        ):
            raise ValueError("registration identity is already owned by this scope")
        self._leases.append(lease)
        return lease

    def commit(self) -> None:
        if self._state != "open":
            raise RuntimeError("registration scope cannot be committed in this state")
        activated: list[RegistrationLease] = []
        try:
            for lease in self._leases:
                if lease.state == "staged":
                    lease.activate()
                    activated.append(lease)
        except BaseException:
            for lease in reversed(activated):
                lease.deactivate()
            raise
        self._state = "committed"

    def rollback_commit(self) -> None:
        """Synchronously hide staged leases after failed publication."""

        if self._state == "open":
            return
        if self._state != "committed":
            raise RuntimeError("registration scope commit cannot be rolled back")
        for lease in reversed(self._leases):
            if lease.state == "active" and lease.can_deactivate:
                lease.deactivate()
        self._state = "open"

    def rollback_admission(self) -> RegistrationScopeDisposalResult:
        """Synchronously discard an open scope before it becomes authoritative."""

        if self._state != "open":
            raise RuntimeError("registration scope admission cannot be rolled back")
        outcomes = tuple(
            RegistrationDisposalOutcome(
                identity=lease.identity,
                result=lease.rollback_registration(),
            )
            for lease in reversed(self._leases)
        )
        report = RegistrationScopeDisposalResult(outcomes=outcomes)
        self._last_result = report
        states = {outcome.result.state for outcome in outcomes}
        if "failed_retryable" in states:
            self._state = "failed_retryable"
        elif "failed_terminal" in states:
            self._state = "failed_terminal"
        else:
            self._state = "disposed"
        return report

    async def dispose(self) -> RegistrationScopeDisposalResult:
        if self._state in {"disposed", "failed_terminal"}:
            assert self._last_result is not None
            return self._last_result

        task = self._dispose_task
        if task is None:
            self._state = "disposing"
            task = asyncio.create_task(self._dispose_all())
            self._dispose_task = task
        return await _await_cancellation_atomic(task)

    async def _dispose_all(self) -> RegistrationScopeDisposalResult:
        outcomes: list[RegistrationDisposalOutcome] = []
        for lease in reversed(self._leases):
            result = await lease.dispose()
            outcomes.append(
                RegistrationDisposalOutcome(identity=lease.identity, result=result)
            )

        report = RegistrationScopeDisposalResult(outcomes=tuple(outcomes))
        self._last_result = report
        states = {outcome.result.state for outcome in outcomes}
        if "failed_retryable" in states:
            self._state = "failed_retryable"
            self._dispose_task = None
        elif "failed_terminal" in states:
            self._state = "failed_terminal"
        else:
            self._state = "disposed"
        return report

    async def __aenter__(self) -> RegistrationScope:
        return self

    async def __aexit__(self, *_args: object) -> None:
        if self._state == "open":
            await self.dispose()


T = TypeVar("T")


async def _await_cancellation_atomic(task: asyncio.Task[T]) -> T:
    """Join an owned cleanup task before propagating caller cancellation."""

    cancellation: asyncio.CancelledError | None = None
    caller = asyncio.current_task()
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            if caller is None or caller.cancelling() == 0:
                return task.result()
            cancellation = exc
    result = task.result()
    if cancellation is not None:
        raise cancellation
    return result


def _require_nonempty(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value


__all__ = [
    "RegistrationDisposalOutcome",
    "RegistrationDisposalResult",
    "RegistrationIdentity",
    "RegistrationLease",
    "RegistrationLeaseCollector",
    "RegistrationOwner",
    "RegistrationScope",
    "RegistrationScopeDisposalResult",
]
