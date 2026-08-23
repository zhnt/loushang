from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal, TypedDict, Unpack, cast, overload

from loushang.tui.cell_width import autowrap_safe_width, truncate_to_width
from loushang.tui.core import RenderConstraints, RenderLine, RenderResult
from loushang.tui.theme import ThemeResolver
from loushang.tui.ui_parts.widgets._utils import style_text

ToastKind = Literal["info", "success", "warning", "danger"]
_NowMs = Callable[[], int]
_VALID_KINDS = frozenset({"info", "success", "warning", "danger"})

__all__ = ["Toast", "ToastKind", "ToastStack"]


class _ToastOptions(TypedDict, total=False):
    title: str
    kind: ToastKind
    value: str
    duration_ms: int | None
    created_at_ms: int | None
    dismissible: bool


class _ToastOverrides(_ToastOptions, total=False):
    message: str


def _monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


def _single_line_text(text: str) -> str:
    return text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")


@dataclass(frozen=True, slots=True)
class Toast:
    message: str
    title: str = ""
    kind: ToastKind = "info"
    value: str = ""
    duration_ms: int | None = 4000
    created_at_ms: int | None = None
    dismissible: bool = True


@dataclass(slots=True)
class ToastStack:
    toasts: Sequence[Toast] = ()
    max_visible: int = 3
    newest_on_top: bool = True
    empty_height: int = 0
    theme: ThemeResolver | None = None
    now_ms: _NowMs = _monotonic_ms
    _next_generated_index: int = field(default=1, init=False, repr=False)

    def __post_init__(self) -> None:
        self.empty_height = max(0, self.empty_height)
        self.toasts = self._normalize_batch(tuple(self.toasts))

    def _normalize_batch(self, toasts: tuple[Toast, ...]) -> tuple[Toast, ...]:
        now_ms = self.now_ms() if any(toast.created_at_ms is None for toast in toasts) else None
        existing: set[str] = set()
        normalized: list[Toast] = []
        for toast in toasts:
            normalized.append(self._normalize_toast(toast, now_ms=now_ms, existing_values=existing))
        return tuple(normalized)

    def _normalize_toast(self, toast: Toast, *, now_ms: int | None, existing_values: set[str]) -> Toast:
        self._validate_toast(toast)
        value = toast.value or self._next_generated_value(existing_values)
        if value in existing_values:
            raise ValueError(f"duplicate Toast value: {value!r}")
        existing_values.add(value)
        if toast.created_at_ms is None:
            if now_ms is None:
                raise AssertionError("now_ms is required for Toast without created_at_ms")
            created_at_ms = now_ms
        else:
            created_at_ms = toast.created_at_ms
        return replace(toast, value=value, created_at_ms=created_at_ms)

    def _next_generated_value(self, existing_values: set[str]) -> str:
        stored_values = {toast.value for toast in self.toasts}
        while True:
            value = f"toast-{self._next_generated_index}"
            self._next_generated_index += 1
            if value not in existing_values and value not in stored_values:
                return value

    def _validate_toast(self, toast: Toast) -> None:
        if toast.kind not in _VALID_KINDS:
            raise ValueError(f"unknown Toast kind: {toast.kind!r}")
        if toast.duration_ms is not None and toast.duration_ms < 0:
            raise ValueError("Toast duration_ms must be non-negative or None")

    def all_toasts(self) -> tuple[Toast, ...]:
        return tuple(self.toasts)

    def _is_expired(self, toast: Toast, *, now_ms: int) -> bool:
        if toast.duration_ms is None:
            return False
        return now_ms - int(toast.created_at_ms or 0) >= toast.duration_ms

    def _visible_toasts_at(self, now_ms: int) -> tuple[Toast, ...]:
        if self.max_visible <= 0:
            return ()
        visible = tuple(toast for toast in self.toasts if not self._is_expired(toast, now_ms=now_ms))
        if self.newest_on_top:
            visible = tuple(reversed(visible))
        return visible[: self.max_visible]

    @overload
    def push(self, toast: str, **overrides: Unpack[_ToastOptions]) -> str: ...

    @overload
    def push(self, toast: Toast, **overrides: Unpack[_ToastOverrides]) -> str: ...

    def push(self, toast: Toast | str, **overrides: Unpack[_ToastOverrides]) -> str:
        if isinstance(toast, str):
            if "message" in overrides:
                raise TypeError("Toast message cannot be overridden when pushing a string")
            candidate = Toast(toast, **cast(_ToastOptions, overrides))
        elif isinstance(toast, Toast):
            candidate = replace(toast, **overrides) if overrides else toast
        else:
            raise TypeError("push() expects Toast or str")
        existing = {item.value for item in self.toasts}
        now_ms = self.now_ms() if candidate.created_at_ms is None else None
        normalized = self._normalize_toast(candidate, now_ms=now_ms, existing_values=existing)
        self.toasts = (*tuple(self.toasts), normalized)
        return normalized.value

    def visible_toasts(self) -> tuple[Toast, ...]:
        return self._visible_toasts_at(self.now_ms())

    def prune_expired(self) -> int:
        now_ms = self.now_ms()
        kept = tuple(toast for toast in self.toasts if not self._is_expired(toast, now_ms=now_ms))
        removed = len(tuple(self.toasts)) - len(kept)
        self.toasts = kept
        return removed

    def dismiss(self, value: str) -> bool:
        for toast in self.toasts:
            if toast.value == value and toast.dismissible:
                self.toasts = tuple(item for item in self.toasts if item.value != value)
                return True
            if toast.value == value:
                return False
        return False

    def dismiss_oldest(self) -> bool:
        now_ms = self.now_ms()
        visible_values = {toast.value for toast in self._visible_toasts_at(now_ms)}
        for toast in self.toasts:
            if toast.value not in visible_values or not toast.dismissible:
                continue
            self.toasts = tuple(item for item in self.toasts if item.value != toast.value)
            return True
        return False

    def clear(self) -> None:
        self.toasts = ()

    def _toast_line(self, toast: Toast, target_width: int) -> str:
        prefix = style_text(f"[{toast.kind}]", self.theme, f"widget.toast.{toast.kind}")
        title = style_text(_single_line_text(toast.title), self.theme, "widget.toast.title") if toast.title else ""
        message = (
            style_text(_single_line_text(toast.message), self.theme, "widget.toast.message")
            if toast.message
            else ""
        )
        if title and message:
            line = f"{prefix} {title}: {message}"
        elif title:
            line = f"{prefix} {title}"
        elif message:
            line = f"{prefix} {message}"
        else:
            line = prefix
        return truncate_to_width(line, max_width=target_width, ellipsis="")

    def render(self, constraints: RenderConstraints) -> RenderResult:
        target_width = autowrap_safe_width(constraints.width)
        height = max(0, constraints.max_height)
        if height == 0:
            return RenderResult.from_lines([], constraints=constraints)
        visible = self._visible_toasts_at(self.now_ms())
        if not visible:
            empty_count = min(self.empty_height, height)
            return RenderResult.from_lines([RenderLine("") for _ in range(empty_count)], constraints=constraints)
        lines = [RenderLine(self._toast_line(toast, target_width)) for toast in visible[:height]]
        return RenderResult.from_lines(lines, constraints=constraints)
