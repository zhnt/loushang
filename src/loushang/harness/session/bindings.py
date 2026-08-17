"""Reusable bindings for the standard Product session facade.

These adapters keep the common session surface in Harness while allowing a
Product to inject model, identity, maintenance, and extension policies.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from loushang.agent.types import ThinkingLevel
from loushang.ai.model import ModelSelection


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


@dataclass
class SessionIdentityBinding:
    """Bind stable session identity and display metadata."""

    get_session_id: Callable[[], str]
    get_session_name: Callable[[], str | None]
    set_session_name_callback: Callable[[str | None], Awaitable[None]]

    @property
    def session_id(self) -> str:
        return self.get_session_id()

    @property
    def session_name(self) -> str | None:
        return self.get_session_name()

    async def set_session_name(self, name: str | None) -> None:
        await self.set_session_name_callback(name)


@dataclass
class SessionMaintenanceBinding:
    """Bind retry and transcript-maintenance policy selected by a Product."""

    is_compacting_callback: Callable[[], bool]
    auto_retry_enabled_callback: Callable[[], bool]
    auto_compaction_enabled_callback: Callable[[], bool]
    set_auto_retry_enabled_callback: Callable[[bool], None]
    set_auto_compaction_enabled_callback: Callable[[bool], None]
    compact_callback: Callable[[str | None], Awaitable[object]]
    abort_compaction_callback: Callable[[], None]

    @property
    def is_compacting(self) -> bool:
        return self.is_compacting_callback()

    @property
    def auto_retry_enabled(self) -> bool:
        return self.auto_retry_enabled_callback()

    @property
    def auto_compaction_enabled(self) -> bool:
        return self.auto_compaction_enabled_callback()

    def set_auto_retry_enabled(self, enabled: bool) -> None:
        self.set_auto_retry_enabled_callback(enabled)

    def set_auto_compaction_enabled(self, enabled: bool) -> None:
        self.set_auto_compaction_enabled_callback(enabled)

    async def compact(self, custom_instructions: str | None = None) -> object:
        return await self.compact_callback(custom_instructions)

    def abort_compaction(self) -> None:
        self.abort_compaction_callback()


@dataclass
class SessionModelBinding:
    """Bind model and thinking selection without choosing Product defaults."""

    get_model_selection_callback: Callable[[], ModelSelection | None]
    set_model_callback: Callable[[object], Awaitable[None]]
    cycle_model_selection_callback: Callable[
        [str], ModelSelection | None | Awaitable[ModelSelection | None]
    ]
    set_thinking_level_callback: Callable[[ThinkingLevel], Awaitable[None]]
    cycle_thinking_level_callback: Callable[[], Awaitable[ThinkingLevel | None]]
    supports_thinking_callback: Callable[[], bool]
    available_thinking_levels_callback: Callable[[], list[ThinkingLevel]]
    available_models_callback: Callable[[], list[ModelSelection]]
    available_model_details_callback: Callable[[], list[object]]
    get_scoped_models_callback: Callable[[], list[dict[str, object]]]
    set_scoped_models_callback: Callable[[list[dict[str, object]]], None]
    apply_cycled_model_callback: Callable[[ModelSelection], Awaitable[None]] | None = None
    cycle_scoped_selection_callback: (
        Callable[[str], tuple[ModelSelection, ThinkingLevel | None] | None] | None
    ) = None

    def get_model_selection(self) -> ModelSelection | None:
        return self.get_model_selection_callback()

    async def set_model(self, model: object) -> None:
        await self.set_model_callback(model)

    async def cycle_model(self, direction: str = "forward") -> ModelSelection | None:
        if self.cycle_scoped_selection_callback is not None:
            scoped = self.cycle_scoped_selection_callback(direction)
            if scoped is not None:
                selection, thinking_level = scoped
                await self._apply_cycled_model(selection)
                if thinking_level is not None:
                    await self.set_thinking_level(thinking_level)
                return selection
        selection = await _maybe_await(self.cycle_model_selection_callback(direction))
        if selection is not None:
            await self._apply_cycled_model(selection)
        return selection

    async def _apply_cycled_model(self, selection: ModelSelection) -> None:
        callback = self.apply_cycled_model_callback
        if callback is None:
            await self.set_model(selection)
            return
        await callback(selection)

    async def set_thinking_level(self, level: ThinkingLevel) -> None:
        await self.set_thinking_level_callback(level)

    async def cycle_thinking_level(self) -> ThinkingLevel | None:
        return await self.cycle_thinking_level_callback()

    def supports_thinking(self) -> bool:
        return self.supports_thinking_callback()

    def get_available_thinking_levels(self) -> list[ThinkingLevel]:
        return self.available_thinking_levels_callback()

    def get_available_models(self) -> list[ModelSelection]:
        return self.available_models_callback()

    def get_available_model_details(self) -> list[object]:
        return self.available_model_details_callback()

    def get_scoped_models(self) -> list[dict[str, object]]:
        return self.get_scoped_models_callback()

    def set_scoped_models(self, scoped_models: list[dict[str, object]]) -> None:
        self.set_scoped_models_callback(scoped_models)


@dataclass
class SessionExtensionBinding:
    """Bind extension/resource lifecycle operations for a Product session."""

    start_runtime_callback: Callable[[str], Awaitable[None]]
    reload_runtime_callback: Callable[[], Awaitable[None]]
    poll_resource_changes_callback: Callable[[], Awaitable[bool]]
    start_resource_watcher_callback: Callable[[float], None]
    stop_resource_watcher_callback: Callable[[], Awaitable[None]]
    set_ui_context_callback: Callable[[object | None], None]
    set_runtime_host_callback: Callable[[object | None], None]
    list_extensions_callback: Callable[[], list[dict[str, object]]]

    async def start_extension_runtime(self, *, reason: str = "startup") -> None:
        await self.start_runtime_callback(reason)

    async def reload_extension_runtime(self) -> None:
        await self.reload_runtime_callback()

    async def poll_resource_changes(self) -> bool:
        return await self.poll_resource_changes_callback()

    def start_resource_watcher(self, *, interval_seconds: float = 1.0) -> None:
        self.start_resource_watcher_callback(interval_seconds)

    async def stop_resource_watcher(self) -> None:
        await self.stop_resource_watcher_callback()

    def set_extension_ui_context(self, ui_context: object | None) -> None:
        self.set_ui_context_callback(ui_context)

    def set_extension_runtime_host(self, runtime_host: object | None) -> None:
        self.set_runtime_host_callback(runtime_host)

    def list_extensions(self) -> list[dict[str, object]]:
        return self.list_extensions_callback()


__all__ = [
    "SessionExtensionBinding",
    "SessionIdentityBinding",
    "SessionMaintenanceBinding",
    "SessionModelBinding",
]
