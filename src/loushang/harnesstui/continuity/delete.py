"""Confirmation surface for deleting one selected continuity item."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.continuity import ContinuityTarget
from loushang.harnesstui.surface.view import ScreenSurfaceView
from loushang.tui import InputEvent, InputIntent, RenderConstraints, RenderResult
from loushang.tui.cell_width import truncate_to_width, wrap_cells
from loushang.tui.theme import ThemeResolver, apply_theme_style

DELETE_CONTINUITY_CONFIRMATION_THEME = ThemeResolver(
    defaults={
        "surface.title": {"bold": True, "color": "red"},
        "surface.subtitle": {"color": "yellow"},
        "delete.session": {"bold": True, "color": "bright_red"},
        "delete.warning": {"color": "yellow"},
        "delete.action": {"bold": True, "color": "red"},
        "delete.cancel": {"color": "bright_black", "dim": True},
    }
)


@dataclass(frozen=True, slots=True)
class DeleteContinuityConfirmation:
    """Explicit, irreversible confirmation for a selected continuity target."""

    target: ContinuityTarget
    title: str

    def handle_input(self, event: InputEvent) -> InputIntent[str] | None:
        if event.kind != "key":
            return None
        if event.key == "enter":
            return InputIntent(kind="dialog_confirm")
        if event.key in {"esc", "escape"}:
            return InputIntent(kind="dialog_cancel")
        return None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        lines = [
            _styled("Session", "delete.warning"),
            *(
                _styled(line, "delete.session")
                for line in wrap_cells(self.title, width=constraints.width)
            ),
            "",
            *(
                _styled(line, "delete.warning")
                for line in wrap_cells(
                    "This permanently deletes its saved transcript. It cannot be undone.",
                    width=constraints.width,
                )
            ),
            *(
                line
                for line in wrap_cells(
                    (
                        f"{_styled('Enter delete permanently', 'delete.action')} · "
                        f"{_styled('Esc cancel', 'delete.cancel')}"
                    ),
                    width=constraints.width,
                )
            ),
        ]
        return RenderResult.from_text(
            "\n".join(
                truncate_to_width(line, max_width=constraints.width)
                for line in lines[: constraints.max_height]
            ),
            constraints=constraints,
        )


def build_delete_continuity_confirmation_surface(
    *,
    target: ContinuityTarget,
    title: str,
) -> ScreenSurfaceView:
    return ScreenSurfaceView(
        title="Delete session",
        subtitle="Permanently delete the selected session",
        purpose="delete",
        content=DeleteContinuityConfirmation(target=target, title=title),
        footer="",
        presentation="page",
        theme=DELETE_CONTINUITY_CONFIRMATION_THEME,
    )


def _styled(text: str, token: str) -> str:
    return apply_theme_style(
        text,
        DELETE_CONTINUITY_CONFIRMATION_THEME.resolve(token),
    )


__all__ = [
    "DeleteContinuityConfirmation",
    "DELETE_CONTINUITY_CONFIRMATION_THEME",
    "build_delete_continuity_confirmation_surface",
]
