from __future__ import annotations

from dataclasses import dataclass, field

from loushang.harnesstui.selection.catalog import ModelChoice, model_search_items
from loushang.harnesstui.settings.dashboard import StaticLinesPage
from loushang.tui import (
    InputIntent,
    RenderConstraints,
    RenderResult,
    SearchableList,
    SearchableListSelect,
)
from loushang.tui.settings import (
    SETTINGS_PAGE_THEME,
    SETTINGS_VALUE_COLUMN,
    is_space_event,
    is_tab_fallback_key,
)


@dataclass(slots=True)
class ModelPage:
    """Model-selection page over choices prepared by a product adapter."""

    choices: tuple[ModelChoice, ...]
    current_value: str | None = None
    error: str = ""
    focused: bool = False
    models: SearchableList = field(init=False)

    def __post_init__(self) -> None:
        self.models = self._make_list(focused=False)

    @property
    def unavailable(self) -> bool:
        return bool(self.error) or not self.choices

    def focus(self) -> None:
        self.focused = True
        self.models.focus()

    def blur(self) -> None:
        self.focused = False
        self.models.blur()

    def editor_input_target(self) -> object | None:
        if self.unavailable:
            return None
        return self.models.editor_input_target()

    def set_choices(
        self,
        choices: tuple[ModelChoice, ...],
        *,
        current_value: str | None,
        error: str = "",
    ) -> None:
        self.choices = choices
        self.current_value = current_value
        self.error = error
        self.models.set_items(
            model_search_items(choices, current_value=current_value),
            preserve_active_key=current_value or "",
        )

    def handle_input(self, event: object) -> object:
        if self.unavailable:
            return True if is_tab_fallback_key(event) else None
        result = self.models.handle_input(event)
        if isinstance(result, SearchableListSelect):
            return InputIntent(kind="setting", text="model.current", note=result.key)
        if result is not None:
            return result
        if self.models.focus_region == "list" and is_space_event(event):
            item = self.models.active_item
            if item is not None:
                return InputIntent(
                    kind="setting",
                    text="model.current",
                    note=item.key,
                )
        if is_tab_fallback_key(event):
            return True
        return None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        if self.unavailable:
            lines = ("Model selection unavailable", self.error or "No models available.")
            return StaticLinesPage(lines).render(constraints)
        return self.models.render(constraints)

    def _make_list(self, *, focused: bool) -> SearchableList:
        return SearchableList(
            model_search_items(self.choices, current_value=self.current_value),
            placeholder="Search models...",
            empty_text="No matching models",
            focused=focused,
            search_box=True,
            detail_column=SETTINGS_VALUE_COLUMN,
            theme=SETTINGS_PAGE_THEME,
        )


__all__ = ["ModelPage"]
