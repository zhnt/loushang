from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal, cast

from loushang.tui import (
    InputEvent,
    InputIntent,
    RenderConstraints,
    RenderLine,
    RenderResult,
    SelectionSurface,
    SelectItem,
    ThemeResolver,
    apply_theme_style,
    visible_width,
)
from loushang.tui.input import InputIntentKind

MODEL_SELECTOR_SELECTED_STYLE = {"color": 33, "bold": True}
MODEL_SELECTOR_THEME = ThemeResolver(
    defaults={
        "surface.title": {"bold": True, "color": "cyan"},
        "surface.subtitle": {"color": "bright_black"},
        "surface.footer": {"color": "bright_black", "dim": True},
        "model_selector.error": {"color": "bright_red"},
        "model_selector.recovery": {"color": "yellow"},
        "model_selector.search": {"bold": True, "color": "cyan"},
    }
)


@dataclass(slots=True)
class ModelSelectorSurface:
    all_items: tuple[SelectItem, ...]
    scoped_items: tuple[SelectItem, ...] = ()
    selected_value: str | None = None
    max_visible: int = 10
    theme: ThemeResolver = field(default_factory=lambda: MODEL_SELECTOR_THEME)
    _scope: Literal["all", "scoped"] = field(default="all", init=False)
    _surface: SelectionSurface = field(init=False, repr=False)
    _filter_text: str = field(default="", init=False, repr=False)
    _pending_ordinal: str = field(default="", init=False, repr=False)

    def __post_init__(self) -> None:
        if self.scoped_items:
            self._scope = "scoped"
        self._rebuild_surface()

    def focus(self) -> None:
        self._surface.focus()

    def blur(self) -> None:
        self._surface.blur()

    @property
    def footer_help(self) -> str:
        if self._filter_text:
            return "↑/↓ choose · Enter switch · Esc keep current"
        return (
            "Type to filter · ↑/↓ choose · Enter switch · "
            "1–9 quick select · Esc keep current"
        )

    def handle_input(self, event: InputEvent) -> InputIntent | None:
        if event.kind == "text":
            consumed, quick_select = self._handle_ordinal_text(event.text)
            if consumed:
                return quick_select
        if event.kind == "key" and event.key == "enter" and self._pending_ordinal:
            return self._select_pending_ordinal()
        if event.kind == "key" and event.key == "tab" and self.scoped_items:
            self._set_scope("all" if self._scope == "scoped" else "scoped")
            return None
        if event.kind == "key" and event.key == "right" and self.scoped_items:
            self._set_scope("all")
            return None
        if event.kind == "key" and event.key == "left" and self.scoped_items:
            self._set_scope("scoped")
            return None
        if event.kind != "text":
            self._pending_ordinal = ""
        intent = self._surface.handle_input(event)
        self._filter_text = self._surface.filter_text
        return _screen_input_intent_or_none(intent)

    def render(self, constraints: RenderConstraints) -> RenderResult:
        if not self.scoped_items:
            return self._surface.render(constraints)
        header = [RenderLine(self._scope_line()), RenderLine("")]
        body_height = constraints.max_height - len(header)
        if body_height <= 0:
            return RenderResult.from_lines(
                header[: constraints.max_height], constraints=constraints
            )
        body = self._surface.render(
            RenderConstraints(
                width=constraints.width,
                max_height=body_height,
                visible_height=constraints.visible_height,
            )
        )
        cursor = (
            replace(body.cursor, row=body.cursor.row + len(header))
            if body.cursor is not None
            else None
        )
        return RenderResult.from_lines(
            [*header, *body.lines], constraints=constraints, cursor=cursor
        )

    def _rebuild_surface(self) -> None:
        items = self.scoped_items if self._scope == "scoped" else self.all_items
        selected_index = _selected_model_item_index(items, self.selected_value)
        self._surface = SelectionSurface(
            items,
            max_visible=self.max_visible,
            select_kind="select",
            selected_index=selected_index,
            empty_text="No matching models",
            show_scroll_info=False,
            selected_style=MODEL_SELECTOR_SELECTED_STYLE,
            theme=self.theme,
            search_prompt=apply_theme_style(
                "Search: ", self.theme.resolve("model_selector.search")
            ),
            enable_search=True,
            show_search_when_empty=False,
            filter_mode="contains",
            primary_column_width=_model_primary_column_width(items),
        )
        if self._filter_text:
            self._surface.set_filter(self._filter_text)

    def _set_scope(self, scope: Literal["all", "scoped"]) -> None:
        if not self.scoped_items:
            return
        self._pending_ordinal = ""
        self._filter_text = self._surface.filter_text
        self._scope = scope
        self._rebuild_surface()

    def _scope_line(self) -> str:
        if self._scope == "scoped":
            scoped = apply_theme_style("scoped", MODEL_SELECTOR_SELECTED_STYLE)
            return f"Scope: {scoped} | all"
        all_models = apply_theme_style("all", MODEL_SELECTOR_SELECTED_STYLE)
        return f"Scope: {all_models} | scoped"

    def _handle_ordinal_text(self, text: str) -> tuple[bool, InputIntent | None]:
        if (
            self._surface.filter_text
            or not text
            or any(digit not in "0123456789" for digit in text)
        ):
            self._pending_ordinal = ""
            return False, None
        consumed = False
        for digit in text:
            digit_consumed, intent = self._handle_ordinal_digit(digit)
            if not digit_consumed:
                return consumed, None
            consumed = True
            if intent is not None:
                return True, intent
        return consumed, None

    def _handle_ordinal_digit(self, digit: str) -> tuple[bool, InputIntent | None]:
        items = self._current_items()
        if not items:
            self._pending_ordinal = ""
            return False, None
        if not self._pending_ordinal and digit == "0":
            intent = self._select_ordinal(10)
            return intent is not None, intent

        candidate = f"{self._pending_ordinal}{digit}"
        if not self._ordinal_is_possible(candidate, len(items)):
            consumed = bool(self._pending_ordinal)
            self._pending_ordinal = ""
            return consumed, None

        ordinal = int(candidate)
        if 1 <= ordinal <= len(items) and not self._has_longer_ordinal_match(
            candidate, len(items)
        ):
            self._pending_ordinal = ""
            return True, self._select_ordinal(ordinal)

        self._pending_ordinal = candidate
        return True, None

    def _select_pending_ordinal(self) -> InputIntent | None:
        if not self._pending_ordinal:
            return None
        pending = self._pending_ordinal
        self._pending_ordinal = ""
        if not self._ordinal_is_possible(pending, len(self._current_items())):
            return None
        return self._select_ordinal(int(pending))

    def _select_ordinal(self, ordinal: int) -> InputIntent | None:
        index = ordinal - 1
        items = self._current_items()
        if index < 0 or index >= len(items):
            return None
        return InputIntent(kind="select", text=items[index].selected_value)

    def _current_items(self) -> tuple[SelectItem, ...]:
        return self.scoped_items if self._scope == "scoped" else self.all_items

    @staticmethod
    def _ordinal_is_possible(prefix: str, item_count: int) -> bool:
        if not prefix:
            return False
        ordinal = int(prefix)
        return (
            1 <= ordinal <= item_count
            or ModelSelectorSurface._has_longer_ordinal_match(prefix, item_count)
        )

    @staticmethod
    def _has_longer_ordinal_match(prefix: str, item_count: int) -> bool:
        if not prefix or prefix.startswith("0"):
            return False
        prefix_length = len(prefix)
        max_length = len(str(item_count))
        for length in range(prefix_length + 1, max_length + 1):
            lower = int(f"{prefix}{'0' * (length - prefix_length)}")
            if lower <= item_count:
                return True
        return False


def _selected_model_item_index(
    items: tuple[SelectItem, ...], selected_value: str | None
) -> int:
    if selected_value is None:
        return 0
    for index, item in enumerate(items):
        if item.selected_value == selected_value:
            return index
    return 0


def _model_primary_column_width(items: tuple[SelectItem, ...]) -> int | None:
    """Reserve enough room to distinguish complete model identities when possible."""

    if not items:
        return None
    return max(visible_width(item.label or item.selected_value) + 2 for item in items)


def _screen_input_intent_or_none(result: object) -> InputIntent | None:
    if isinstance(result, InputIntent):
        return result
    kind = getattr(result, "kind", None)
    if not isinstance(kind, str):
        return None
    return InputIntent(
        kind=cast(InputIntentKind, kind),
        text=str(getattr(result, "text", "")),
        note=str(getattr(result, "note", "")),
    )


__all__ = [
    "MODEL_SELECTOR_SELECTED_STYLE",
    "MODEL_SELECTOR_THEME",
    "ModelSelectorSurface",
]
