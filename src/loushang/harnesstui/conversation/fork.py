"""Full-screen prompt picker for branching an Agent conversation."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from loushang.harnesstui.surface.view import ScreenSurfaceView
from loushang.tui import (
    InputEvent,
    InputIntent,
    RenderConstraints,
    RenderLine,
    RenderResult,
    SelectionSurface,
    SelectItem,
)
from loushang.tui.cell_width import truncate_to_width, wrap_cells
from loushang.tui.theme import ThemeResolver, apply_theme_style

FORK_PROMPT_PAGE_THEME = ThemeResolver(
    defaults={
        "surface.title": {"bold": True, "color": "cyan"},
        "surface.subtitle": {"color": "bright_black"},
        "surface.footer": {"color": "bright_black", "dim": True},
        "selection.selected": {"bold": True, "color": "cyan"},
        "fork.state": {"color": "bright_black", "dim": True, "italic": True},
        "fork.preview.label": {"bold": True, "color": "cyan"},
        "fork.error": {"color": "red"},
    }
)


@dataclass(frozen=True, slots=True)
class ForkPromptCandidate:
    """One user-visible prompt paired with its opaque transcript identity."""

    entry_id: str
    text: str


class ForkPromptSurface:
    """Select one previous user prompt without exposing transcript IDs."""

    def __init__(
        self,
        *,
        candidates: Sequence[ForkPromptCandidate],
        request_render: Callable[[], None],
        theme: ThemeResolver | None = None,
    ) -> None:
        self._candidates = tuple(candidates)
        self._request_render = request_render
        self._theme = theme if theme is not None else FORK_PROMPT_PAGE_THEME
        self._candidate_by_id = {
            candidate.entry_id: candidate for candidate in self._candidates
        }
        self._ordinal_by_id = {
            candidate.entry_id: ordinal
            for ordinal, candidate in enumerate(self._candidates, start=1)
        }
        self._selection = SelectionSurface(
            items=[
                SelectItem(
                    label=_prompt_label(candidate.text),
                    value=candidate.entry_id,
                    description=f"Prompt {self._ordinal_by_id[candidate.entry_id]}",
                )
                for candidate in reversed(self._candidates)
            ],
            max_visible=20,
            empty_text=self._styled("No prompts to fork yet", "fork.state"),
            wrap_navigation=False,
            enable_search=True,
            search_prompt="Search: ",
            search_placeholder=self._styled("Type to search", "fork.state"),
            search_gap_lines=1,
            filter_mode="fuzzy",
            preserve_description_spacing=True,
            theme=self._theme,
        )
        self._preview_visible = False
        self._preview_offset = 0
        self._last_preview_height = 1
        self._max_preview_offset = 0
        self._activating = False
        self._error: str | None = None

    @property
    def selected_entry_id(self) -> str | None:
        selected = self._selection.selected_item()
        return selected.selected_value if selected is not None else None

    @property
    def footer_help(self) -> str:
        if self._activating:
            return ""
        if self._preview_visible:
            return (
                "Enter fork and edit · Space/Esc back · "
                "↑/↓ scroll · PgUp/PgDn page"
            )
        return "Enter fork and edit · Space preview · Esc cancel · ↑/↓ browse"

    def begin_activation(self) -> bool:
        if self._activating or self.selected_entry_id is None:
            return False
        self._activating = True
        self._error = None
        self._request_render()
        return True

    def fail_activation(self, error: BaseException) -> None:
        self._activating = False
        self._error = str(error).strip() or error.__class__.__name__
        self._request_render()

    def handle_input(self, event: InputEvent) -> InputIntent | bool | None:
        if self._activating:
            return InputIntent(kind="consumed", note="fork_activating")
        if self._preview_visible:
            return self._handle_preview_input(event)
        if event.kind == "key" and event.key == "space":
            if self.selected_entry_id is None:
                return InputIntent(kind="consumed", note="fork_preview_unavailable")
            self._preview_visible = True
            self._preview_offset = 0
            self._request_render()
            return InputIntent(kind="consumed", note="fork_preview")
        return self._selection.handle_input(event)

    def render(self, constraints: RenderConstraints) -> RenderResult:
        state_lines = self._state_lines(width=constraints.width)
        body_height = max(1, constraints.max_height - len(state_lines))
        if self._preview_visible:
            body = self._render_preview(
                RenderConstraints(
                    width=constraints.width,
                    max_height=body_height,
                    visible_height=constraints.visible_height,
                )
            )
        else:
            self._selection.max_visible = min(20, max(1, body_height))
            self._selection.primary_column_width = max(
                16,
                min(72, constraints.width - 14),
            )
            body = self._selection.render(
                RenderConstraints(
                    width=constraints.width,
                    max_height=body_height,
                    visible_height=constraints.visible_height,
                )
            )
        return RenderResult.from_lines(
            [*body.lines, *state_lines],
            constraints=constraints,
            cursor=body.cursor,
        )

    def _handle_preview_input(self, event: InputEvent) -> InputIntent | bool | None:
        if event.kind == "text":
            return InputIntent(kind="consumed", note="fork_preview")
        if event.kind != "key":
            return InputIntent(kind="consumed", note="fork_preview")
        if event.key in {"esc", "escape", "space"}:
            self._preview_visible = False
            self._request_render()
            return InputIntent(kind="consumed", note="fork_preview_close")
        if event.key == "enter":
            selected = self.selected_entry_id
            if selected is None:
                return InputIntent(kind="consumed", note="fork_preview_unavailable")
            return InputIntent(kind="select", text=selected)
        if event.key == "up":
            self._scroll_preview(-1)
        elif event.key == "down":
            self._scroll_preview(1)
        elif event.key == "pageUp":
            self._scroll_preview(-self._last_preview_height)
        elif event.key == "pageDown":
            self._scroll_preview(self._last_preview_height)
        elif event.key == "home":
            self._set_preview_offset(0)
        elif event.key == "end":
            self._set_preview_offset(self._max_preview_offset)
        return InputIntent(kind="consumed", note="fork_preview")

    def _render_preview(self, constraints: RenderConstraints) -> RenderResult:
        candidate = self._selected_candidate()
        if candidate is None:
            return RenderResult.from_lines(
                [RenderLine(self._styled("No prompt selected", "fork.state"))],
                constraints=constraints,
            )
        ordinal = self._ordinal_by_id[candidate.entry_id]
        lines = [
            RenderLine(
                self._styled(
                    f"Prompt {ordinal} of {len(self._candidates)}",
                    "fork.preview.label",
                )
            ),
            RenderLine(""),
            *(
                RenderLine(line)
                for line in (
                    wrap_cells(candidate.text, width=max(1, constraints.width)) or [""]
                )
            ),
        ]
        self._last_preview_height = max(1, constraints.max_height)
        self._max_preview_offset = max(0, len(lines) - constraints.max_height)
        self._preview_offset = max(
            0,
            min(self._preview_offset, self._max_preview_offset),
        )
        return RenderResult.from_lines(
            lines[
                self._preview_offset : self._preview_offset
                + constraints.max_height
            ],
            constraints=constraints,
        )

    def _selected_candidate(self) -> ForkPromptCandidate | None:
        entry_id = self.selected_entry_id
        return self._candidate_by_id.get(entry_id) if entry_id is not None else None

    def _scroll_preview(self, delta: int) -> None:
        self._set_preview_offset(self._preview_offset + delta)

    def _set_preview_offset(self, offset: int) -> None:
        next_offset = max(0, min(offset, self._max_preview_offset))
        if next_offset != self._preview_offset:
            self._preview_offset = next_offset
            self._request_render()

    def _state_lines(self, *, width: int) -> list[RenderLine]:
        if self._activating:
            return [RenderLine(""), RenderLine("Forking selected prompt…")]
        if self._error is not None:
            return [
                RenderLine(""),
                RenderLine(
                    self._styled(
                        truncate_to_width(
                            f"Error: {self._error}",
                            max_width=width,
                        ),
                        "fork.error",
                    )
                ),
            ]
        return []

    def _styled(self, text: str, token: str) -> str:
        return apply_theme_style(text, self._theme.resolve(token))


def build_fork_prompt_surface_view(
    *,
    candidates: Sequence[ForkPromptCandidate],
    request_render: Callable[[], None],
    theme: ThemeResolver | None = None,
) -> ScreenSurfaceView:
    resolved_theme = theme if theme is not None else FORK_PROMPT_PAGE_THEME
    content = ForkPromptSurface(
        candidates=candidates,
        request_render=request_render,
        theme=resolved_theme,
    )
    return ScreenSurfaceView(
        title="Fork from a previous prompt",
        subtitle="Choose a prompt to edit in a new session",
        purpose="fork",
        content=content,
        footer=content.footer_help,
        presentation="page",
        theme=resolved_theme,
    )


def _prompt_label(text: str) -> str:
    return " ".join(text.split())


__all__ = [
    "FORK_PROMPT_PAGE_THEME",
    "ForkPromptCandidate",
    "ForkPromptSurface",
    "build_fork_prompt_surface_view",
]
