from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from loushang.tui.core import RenderConstraints, RenderLine, RenderResult
from loushang.tui.framework import Renderable, Surface, SurfaceHandle, SurfaceHost
from loushang.tui.input import InputEvent, InputIntent
from loushang.tui.ui_parts import StatusField

WidgetPlacement = Literal["above_composer", "below_composer"]
RenderFactory = Callable[[RenderConstraints], RenderResult | list[str] | tuple[str, ...]]
InputFactory = Callable[[InputEvent], InputIntent[str] | None]


@dataclass(slots=True)
class ExtensionHandle:
    _dispose: Callable[[], None]
    disposed: bool = False

    def dispose(self) -> None:
        if self.disposed:
            return
        self._dispose()
        self.disposed = True


@dataclass(slots=True)
class _WidgetEntry:
    extension_id: str
    widget_id: str
    placement: WidgetPlacement
    renderable: Renderable


@dataclass(slots=True)
class _StatusEntry:
    extension_id: str
    field_id: str
    field: StatusField


@dataclass(slots=True)
class _SurfaceEntry:
    extension_id: str
    surface_id: str
    handle: SurfaceHandle


@dataclass(slots=True)
class _FooterEntry:
    extension_id: str
    renderable: Renderable


@dataclass(slots=True)
class ExtensionHost:
    _widgets: dict[tuple[str, str], _WidgetEntry] = field(default_factory=dict)
    _status_fields: dict[tuple[str, str], _StatusEntry] = field(default_factory=dict)
    _surfaces: dict[tuple[str, str], _SurfaceEntry] = field(default_factory=dict)
    _footers: dict[str, _FooterEntry] = field(default_factory=dict)

    def set_widget(
        self,
        extension_id: str,
        widget_id: str,
        renderable: Renderable,
        *,
        placement: WidgetPlacement,
    ) -> ExtensionHandle:
        key = (extension_id, widget_id)
        self._widgets[key] = _WidgetEntry(
            extension_id=extension_id,
            widget_id=widget_id,
            placement=placement,
            renderable=renderable,
        )
        return ExtensionHandle(lambda: self._dispose_widget(key))

    def widgets(self, placement: WidgetPlacement) -> tuple[Renderable, ...]:
        return tuple(entry.renderable for entry in self._widgets.values() if entry.placement == placement)

    def set_status(self, extension_id: str, field_id: str, text: str, *, priority: int = 0) -> ExtensionHandle:
        key = (extension_id, field_id)
        self._status_fields[key] = _StatusEntry(
            extension_id=extension_id,
            field_id=field_id,
            field=StatusField(text, priority=priority),
        )
        return ExtensionHandle(lambda: self._dispose_status(key))

    def status_fields(self) -> tuple[StatusField, ...]:
        fields = [entry.field for entry in self._status_fields.values()]
        return tuple(sorted(fields, key=lambda field: field.priority, reverse=True))

    def set_footer(self, extension_id: str, renderable: Renderable | None) -> ExtensionHandle:
        if renderable is None:
            self._footers.pop(extension_id, None)
            return ExtensionHandle(lambda: None)
        self._footers[extension_id] = _FooterEntry(extension_id=extension_id, renderable=renderable)
        return ExtensionHandle(lambda: self._dispose_footer(extension_id))

    def footer(self) -> Renderable | None:
        if not self._footers:
            return None
        return next(reversed(self._footers.values())).renderable

    def open_surface(
        self,
        extension_id: str,
        surface_id: str,
        surface: Surface,
        *,
        surface_host: SurfaceHost,
    ) -> ExtensionHandle:
        key = (extension_id, surface_id)
        existing = self._surfaces.pop(key, None)
        if existing is not None:
            existing.handle.close("replaced")
        handle = surface_host.open_surface(surface)
        self._surfaces[key] = _SurfaceEntry(extension_id=extension_id, surface_id=surface_id, handle=handle)
        return ExtensionHandle(lambda: self._dispose_surface(key))

    def dispose_extension(self, extension_id: str) -> None:
        for key in [key for key in self._widgets if key[0] == extension_id]:
            self._widgets.pop(key, None)
        for key in [key for key in self._status_fields if key[0] == extension_id]:
            self._status_fields.pop(key, None)
        for key in [key for key in self._surfaces if key[0] == extension_id]:
            self._dispose_surface(key)
        self._footers.pop(extension_id, None)

    def _dispose_surface(self, key: tuple[str, str]) -> None:
        entry = self._surfaces.pop(key, None)
        if entry is not None:
            entry.handle.close("disposed")

    def _dispose_widget(self, key: tuple[str, str]) -> None:
        self._widgets.pop(key, None)

    def _dispose_status(self, key: tuple[str, str]) -> None:
        self._status_fields.pop(key, None)

    def _dispose_footer(self, extension_id: str) -> None:
        self._footers.pop(extension_id, None)


@dataclass(slots=True)
class PublicTuiApi:
    extension_id: str
    host: ExtensionHost
    surface_host: SurfaceHost | None = None

    def set_widget(
        self,
        widget_id: str,
        renderable: Renderable,
        *,
        placement: WidgetPlacement,
    ) -> ExtensionHandle:
        return self.host.set_widget(self.extension_id, widget_id, renderable, placement=placement)

    def set_status(self, field_id: str, text: str, *, priority: int = 0) -> ExtensionHandle:
        return self.host.set_status(self.extension_id, field_id, text, priority=priority)

    def set_footer(self, renderable: Renderable | None) -> ExtensionHandle:
        return self.host.set_footer(self.extension_id, renderable)

    def open_surface(self, surface_id: str, surface: Surface) -> ExtensionHandle:
        if self.surface_host is None:
            raise RuntimeError("surface_host is required to open extension surfaces")
        return self.host.open_surface(self.extension_id, surface_id, surface, surface_host=self.surface_host)

    def adapt_renderable(
        self,
        render: RenderFactory,
        *,
        on_input: InputFactory | None = None,
    ) -> RenderableAdapter:
        return RenderableAdapter(_render=render, on_input=on_input)


@dataclass(slots=True)
class RenderableAdapter:
    _render: RenderFactory
    on_input: InputFactory | None = None
    focused: bool = False

    def focus(self) -> None:
        self.focused = True

    def blur(self) -> None:
        self.focused = False

    def handle_input(self, event: InputEvent) -> InputIntent[str] | None:
        if self.on_input is None:
            return None
        return self.on_input(event)

    def render_result(self, constraints: RenderConstraints) -> RenderResult:
        return _coerce_render_result(self._render(constraints), constraints)

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return _coerce_render_result(self._render(constraints), constraints)


def _coerce_render_result(value: RenderResult | list[str] | tuple[str, ...], constraints: RenderConstraints) -> RenderResult:
    if isinstance(value, RenderResult):
        return value
    return RenderResult.from_lines([RenderLine(line) for line in value], constraints=constraints)
