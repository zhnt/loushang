"""Typed, Product-neutral operations over a bound session control surface.

This module is intentionally below any RPC or channel schema.  Products choose
which operation groups to expose, map their own requests to these values, and
project their own responses and errors.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from loushang.ai.types import ImagePart
from loushang.harness.runtime import SessionOperationResult
from loushang.harness.session.facade import (
    SessionControlPort,
    require_active_session_control,
)


class SessionOperationCapability(str, Enum):
    """A coherent group of optional Product session operations."""

    INPUT = "input"
    QUEUE = "queue"
    LIFECYCLE = "lifecycle"
    IDENTITY = "identity"
    RETRY = "retry"
    MAINTENANCE = "maintenance"


class SessionInputCapability(str, Enum):
    """One input-delivery action guaranteed by a bound Harness session."""

    STEER = "steer"
    FOLLOW_UP = "follow_up"


class SessionOperationUnavailableError(RuntimeError):
    """Raised when a Product did not bind an optional operation group."""


@dataclass(frozen=True)
class SessionInputCapabilities:
    """Explicit input-delivery capabilities for one session binding."""

    capabilities: frozenset[SessionInputCapability]

    @classmethod
    def standard(cls) -> "SessionInputCapabilities":
        """Declare the steer and follow-up guarantees of the standard Session."""

        return cls(frozenset(SessionInputCapability))

    @classmethod
    def from_capabilities(
        cls,
        capabilities: Iterable[SessionInputCapability],
    ) -> "SessionInputCapabilities":
        return cls(frozenset(capabilities))

    def supports(self, capability: SessionInputCapability) -> bool:
        return capability in self.capabilities

    def require(self, capability: SessionInputCapability) -> None:
        if not self.supports(capability):
            raise SessionOperationUnavailableError(
                f"Session input capability is unavailable: {capability.value}"
            )


@dataclass(frozen=True)
class SessionOperationAvailability:
    """Explicit capability declaration for one Product session binding."""

    capabilities: frozenset[SessionOperationCapability]

    @classmethod
    def standard(cls) -> "SessionOperationAvailability":
        """Expose every operation supported by ``SessionControlPort``."""

        return cls(frozenset(SessionOperationCapability))

    @classmethod
    def from_capabilities(
        cls,
        capabilities: Iterable[SessionOperationCapability],
    ) -> "SessionOperationAvailability":
        return cls(frozenset(capabilities))

    def supports(self, capability: SessionOperationCapability) -> bool:
        return capability in self.capabilities

    def require(self, capability: SessionOperationCapability) -> None:
        if not self.supports(capability):
            raise SessionOperationUnavailableError(
                f"Session operation capability is unavailable: {capability.value}"
            )


@dataclass(frozen=True)
class SessionPromptRequest:
    """One Product-adapted prompt submission without transport vocabulary."""

    text: str
    images: tuple[ImagePart, ...] = ()
    streaming_behavior: str | None = None
    source: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("Session prompt text must be a non-empty string.")
        if self.streaming_behavior is not None and not isinstance(
            self.streaming_behavior, str
        ):
            raise TypeError("Session prompt streaming behavior must be a string.")
        if self.source is not None and not isinstance(self.source, str):
            raise TypeError("Session prompt source must be a string.")


@dataclass(frozen=True)
class SessionLifecycleOperationPorts:
    """Product callbacks for standard session replacement operations."""

    new_session: Callable[
        [str | None, str | None], Awaitable[SessionOperationResult[Any, Any]]
    ]
    restore_session: Callable[[str | Path], Awaitable[SessionOperationResult[Any, Any]]]
    fork_session: Callable[
        [str | None, str], Awaitable[SessionOperationResult[Any, Any]]
    ]
    clone_session: Callable[[], Awaitable[SessionOperationResult[Any, Any]]] | None = None


class SessionOperationRuntime:
    """Execute admitted session control groups through one explicit port.

    The runtime does not own background task scheduling, request validation,
    error schema, model selection, or output projection. ``prompt`` is the
    settled turn operation: it submits through the bound control and waits for
    the Session to become idle. Hosts must not add a second idle wait after it.
    """

    def __init__(
        self,
        control: SessionControlPort,
        *,
        availability: SessionOperationAvailability | None = None,
        input_capabilities: SessionInputCapabilities | None = None,
        lifecycle: SessionLifecycleOperationPorts | None = None,
    ) -> None:
        self._control = control
        self._availability = (
            SessionOperationAvailability.standard()
            if availability is None
            else availability
        )
        self._input_capabilities = (
            SessionInputCapabilities.standard()
            if input_capabilities is None
            else input_capabilities
        )
        self._lifecycle = lifecycle

    @property
    def availability(self) -> SessionOperationAvailability:
        return self._availability

    @property
    def input_capabilities(self) -> SessionInputCapabilities:
        if not self._availability.supports(SessionOperationCapability.INPUT):
            return SessionInputCapabilities.from_capabilities(())
        return self._input_capabilities

    async def prompt(
        self,
        request: SessionPromptRequest,
        *,
        on_preflight: Callable[[bool], None] | None = None,
    ) -> None:
        self._require(SessionOperationCapability.INPUT)
        images = list(request.images) or None
        if images is not None and on_preflight is not None:
            await self._control.prompt(
                request.text,
                images=images,
                streaming_behavior=request.streaming_behavior,
                source=request.source,
                preflight_result=on_preflight,
            )
        elif images is not None:
            await self._control.prompt(
                request.text,
                images=images,
                streaming_behavior=request.streaming_behavior,
                source=request.source,
            )
        elif on_preflight is not None:
            await self._control.prompt(
                request.text,
                streaming_behavior=request.streaming_behavior,
                source=request.source,
                preflight_result=on_preflight,
            )
        else:
            await self._control.prompt(
                request.text,
                streaming_behavior=request.streaming_behavior,
                source=request.source,
            )
        await self._control.wait_for_idle()

    async def new_session(
        self,
        *,
        cwd: str | None = None,
        parent_session: str | None = None,
    ) -> SessionOperationResult[Any, Any]:
        lifecycle = self._require_lifecycle_port()
        return await lifecycle.new_session(cwd, parent_session)

    async def restore_session(
        self,
        session_ref: str | Path,
    ) -> SessionOperationResult[Any, Any]:
        lifecycle = self._require_lifecycle_port()
        return await lifecycle.restore_session(session_ref)

    async def fork_session(
        self,
        entry_id: str | None,
        *,
        position: str = "at",
    ) -> SessionOperationResult[Any, Any]:
        lifecycle = self._require_lifecycle_port()
        return await lifecycle.fork_session(entry_id, position)

    async def clone_session(self) -> SessionOperationResult[Any, Any]:
        """Create an independent session at the current product position."""
        lifecycle = self._require_lifecycle_port()
        if lifecycle.clone_session is None:
            raise SessionOperationUnavailableError(
                "Session clone operation is unavailable"
            )
        return await lifecycle.clone_session()

    def steer(self, text: str, *, images: Iterable[ImagePart] = ()) -> None:
        self._require(SessionOperationCapability.INPUT)
        self._input_capabilities.require(SessionInputCapability.STEER)
        self._control.steer(text, images=list(images) or None)

    def follow_up(self, text: str, *, images: Iterable[ImagePart] = ()) -> None:
        self._require(SessionOperationCapability.INPUT)
        self._input_capabilities.require(SessionInputCapability.FOLLOW_UP)
        self._control.follow_up(text, images=list(images) or None)

    @property
    def pending_message_count(self) -> int:
        self._require(SessionOperationCapability.QUEUE)
        return self._control.pending_message_count

    def get_steering_messages(self) -> list[str]:
        self._require(SessionOperationCapability.QUEUE)
        return self._control.get_steering_messages()

    def get_follow_up_messages(self) -> list[str]:
        self._require(SessionOperationCapability.QUEUE)
        return self._control.get_follow_up_messages()

    def clear_queue(self) -> dict[str, list[str]]:
        self._require(SessionOperationCapability.QUEUE)
        return self._control.clear_queue()

    async def continue_run(self) -> None:
        self._require(SessionOperationCapability.LIFECYCLE)
        await self._control.continue_run()

    def abort_turn(self) -> bool:
        """Abort only the active Agent turn.

        Queue clearing and command-execution cancellation are host composites,
        not implicit effects of this shared Session primitive.
        """

        self._require(SessionOperationCapability.LIFECYCLE)
        return self._control.abort()

    def abort(self) -> bool:
        """Compatibility alias for the explicitly named turn-only primitive."""

        return self.abort_turn()

    async def wait_for_idle(self) -> None:
        self._require(SessionOperationCapability.LIFECYCLE)
        await self._control.wait_for_idle()

    @property
    def session_id(self) -> str:
        self._require(SessionOperationCapability.IDENTITY)
        return self._control.session_id

    @property
    def session_name(self) -> str | None:
        self._require(SessionOperationCapability.IDENTITY)
        return self._control.session_name

    async def set_session_name(self, name: str | None) -> None:
        self._require(SessionOperationCapability.IDENTITY)
        await self._control.set_session_name(name)

    @property
    def is_retrying(self) -> bool:
        self._require(SessionOperationCapability.RETRY)
        return self._control.is_retrying

    def abort_retry(self) -> None:
        self._require(SessionOperationCapability.RETRY)
        self._control.abort_retry()

    async def wait_for_retry(self) -> None:
        self._require(SessionOperationCapability.RETRY)
        await self._control.wait_for_retry()

    @property
    def is_compacting(self) -> bool:
        self._require(SessionOperationCapability.MAINTENANCE)
        return self._control.is_compacting

    @property
    def auto_retry_enabled(self) -> bool:
        self._require(SessionOperationCapability.MAINTENANCE)
        return self._control.auto_retry_enabled

    @property
    def auto_compaction_enabled(self) -> bool:
        self._require(SessionOperationCapability.MAINTENANCE)
        return self._control.auto_compaction_enabled

    def set_auto_retry_enabled(self, enabled: bool) -> None:
        self._require(SessionOperationCapability.MAINTENANCE)
        self._control.set_auto_retry_enabled(enabled)

    def set_auto_compaction_enabled(self, enabled: bool) -> None:
        self._require(SessionOperationCapability.MAINTENANCE)
        self._control.set_auto_compaction_enabled(enabled)

    async def compact(self, custom_instructions: str | None = None) -> object:
        self._require(SessionOperationCapability.MAINTENANCE)
        return await self._control.compact(custom_instructions)

    def abort_compaction(self) -> None:
        self._require(SessionOperationCapability.MAINTENANCE)
        self._control.abort_compaction()

    def _require(self, capability: SessionOperationCapability) -> None:
        self._availability.require(capability)

    def _require_lifecycle_port(self) -> SessionLifecycleOperationPorts:
        self._require(SessionOperationCapability.LIFECYCLE)
        if self._lifecycle is None:
            raise SessionOperationUnavailableError(
                "Session lifecycle operation ports are not bound"
            )
        return self._lifecycle


@dataclass(frozen=True)
class SessionOperationResolver:
    """Callable binding whose capabilities can be inspected without a Session.

    Resolving operations may require an active Session and must therefore stay
    lazy.  Capability declarations are immutable binding metadata, so Product
    adapters can project them before a Session exists without crossing that
    runtime boundary.
    """

    get_control: Callable[[], SessionControlPort]
    lifecycle: SessionLifecycleOperationPorts | None = None
    availability: SessionOperationAvailability | None = None
    declared_input_capabilities: SessionInputCapabilities | None = None

    @property
    def input_capabilities(self) -> SessionInputCapabilities:
        availability = self.availability or SessionOperationAvailability.standard()
        if not availability.supports(SessionOperationCapability.INPUT):
            return SessionInputCapabilities.from_capabilities(())
        return self.declared_input_capabilities or SessionInputCapabilities.standard()

    def __call__(self) -> SessionOperationRuntime:
        return SessionOperationRuntime(
            self.get_control(),
            availability=self.availability,
            input_capabilities=self.declared_input_capabilities,
            lifecycle=self.lifecycle,
        )


def current_session_operation_resolver(
    runtime: object,
    *,
    lifecycle: SessionLifecycleOperationPorts | None = None,
    availability: SessionOperationAvailability | None = None,
    input_capabilities: SessionInputCapabilities | None = None,
) -> SessionOperationResolver:
    """Build a resolver that never retains a control from a replaced Session."""

    return session_operation_resolver(
        lambda: require_active_session_control(runtime),
        lifecycle=lifecycle,
        availability=availability,
        input_capabilities=input_capabilities,
    )


def session_operation_resolver(
    get_control: Callable[[], SessionControlPort],
    *,
    lifecycle: SessionLifecycleOperationPorts | None = None,
    availability: SessionOperationAvailability | None = None,
    input_capabilities: SessionInputCapabilities | None = None,
) -> SessionOperationResolver:
    """Build a resolver from a Product-owned current-control callback."""

    return SessionOperationResolver(
        get_control=get_control,
        lifecycle=lifecycle,
        availability=availability,
        declared_input_capabilities=input_capabilities,
    )


__all__ = [
    "SessionInputCapabilities",
    "SessionInputCapability",
    "SessionOperationResolver",
    "SessionOperationAvailability",
    "SessionOperationCapability",
    "SessionOperationRuntime",
    "SessionOperationUnavailableError",
    "SessionLifecycleOperationPorts",
    "SessionPromptRequest",
    "current_session_operation_resolver",
    "session_operation_resolver",
]
