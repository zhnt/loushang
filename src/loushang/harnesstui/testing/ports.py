from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol, TypeVar

from loushang.harnesstui.conversation.input import (
    ConversationInputResult,
    ConversationScreenInputPort,
)
from loushang.harnesstui.conversation.screen_runner import (
    LocalCommandPredicate,
    ShouldExit,
)
from loushang.tui.core import RenderConstraints, RenderResult
from loushang.tui.framework import SurfaceHost
from loushang.tui.input import InputEvent
from loushang.tui.keybindings import KeybindingConfig, KeybindingManager

AppT_co = TypeVar("AppT_co", covariant=True)
AppT_contra = TypeVar("AppT_contra", contravariant=True)


class ConversationPlaybackAppPort(ConversationScreenInputPort, Protocol):
    """Minimal renderable conversation application used by input playback."""

    surface_host: SurfaceHost | None

    def render(self, constraints: RenderConstraints) -> RenderResult: ...


class ConversationPlaybackInputRouterPort(Protocol):
    """Product adapter that routes one decoded input event."""

    def handle(self, event: InputEvent) -> ConversationInputResult: ...


class ConversationPlaybackInputRouterFactoryPort(Protocol):
    """Construct a router without fixing a product-specific result type."""

    def __call__(
        self,
        *,
        app: ConversationPlaybackAppPort,
        should_exit: ShouldExit,
        is_local_command: LocalCommandPredicate,
        keybindings: KeybindingManager | KeybindingConfig | None,
        width: int,
        height: int,
    ) -> ConversationPlaybackInputRouterPort: ...


class ConversationStateSnapshotPort(Protocol[AppT_contra]):
    """Capture stable, JSON-compatible state after a playback step."""

    def __call__(self, app: AppT_contra) -> Mapping[str, object]: ...


class ConversationResultPayloadPort(Protocol):
    """Convert a routed input result into an artifact payload."""

    def __call__(
        self,
        result: ConversationInputResult,
    ) -> Mapping[str, object]: ...


class ConversationLoopResultPayloadPort(Protocol[AppT_contra]):
    """Add application-specific, non-policy data to loop artifacts."""

    def __call__(
        self,
        exit_code: int,
        app: AppT_contra,
    ) -> Mapping[str, object]: ...


class ConversationPlaybackAppFactoryPort(Protocol[AppT_co]):
    """Build an application around a controllable playback clock."""

    def __call__(self, *, now: Callable[[], float]) -> AppT_co: ...


__all__ = [
    "ConversationPlaybackAppFactoryPort",
    "ConversationPlaybackAppPort",
    "ConversationPlaybackInputRouterFactoryPort",
    "ConversationPlaybackInputRouterPort",
    "ConversationLoopResultPayloadPort",
    "ConversationResultPayloadPort",
    "ConversationStateSnapshotPort",
]
