"""Product-neutral `/permissions` center."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from loushang.harness.approval import ApprovalPermissionsSnapshot
from loushang.harness.permissions import (
    PermissionProfileScope,
    PermissionProfileSnapshot,
    permission_profile_snapshot,
)
from loushang.harnesstui.surface.view import ScreenSurfaceView
from loushang.tui import (
    InputEvent,
    InputIntent,
    RenderConstraints,
    RenderLine,
    RenderResult,
    SelectionSurface,
    SelectItem,
    ThemeResolver,
)
from loushang.tui.cell_width import autowrap_safe_width, truncate_to_width
from loushang.tui.theme import apply_theme_style

PermissionsTab = Literal["mode", "retained"]

_PERMISSIONS_THEME = ThemeResolver(
    defaults={
        "permissions.heading": {"bold": True},
        "permissions.tab": {"color": "bright_black", "dim": True},
        "permissions.tab.selected": {"color": "cyan", "bold": True},
        "permissions.scope": {"color": "bright_black"},
        "permissions.scope.selected": {"color": "cyan", "bold": True},
        "permissions.mode": {"color": "default"},
        "permissions.mode.selected": {"color": "cyan", "bold": True},
        "permissions.mode.current": {"color": "green", "bold": True},
        "permissions.mode.full_access": {"color": "red", "bold": True},
        "permissions.description": {"color": "bright_black", "dim": True},
        "permissions.disabled": {"color": "bright_black", "dim": True},
        "permissions.warning": {"color": "red", "bold": True},
        "permissions.counts": {"color": "bright_black", "dim": True},
        "permissions.empty": {"color": "bright_black", "dim": True},
    }
)


@dataclass(slots=True)
class PermissionsCenterSurface:
    profile_snapshot: PermissionProfileSnapshot
    approval_snapshot: ApprovalPermissionsSnapshot
    selected_tab: PermissionsTab = "mode"
    selected_scope: PermissionProfileScope = "session"
    selected_mode_index: int = 0
    focused: bool = False
    _confirm_full_access: bool = field(default=False, init=False, repr=False)
    _retained_items: tuple[SelectItem, ...] = field(init=False, repr=False)
    _retained: SelectionSurface = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.selected_mode_index = next(
            (
                index
                for index, option in enumerate(self.profile_snapshot.options)
                if option.current
            ),
            0,
        )
        self._retained_items = _retained_permission_items(self.approval_snapshot)
        self._retained = SelectionSurface(
            items=self._retained_items,
            max_visible=10,
            empty_text="No retained permissions",
            show_scroll_info=True,
            selected_style={"color": "cyan", "bold": True},
        )

    def focus(self) -> None:
        self.focused = True
        if self.selected_tab == "retained":
            self._retained.focus()

    @property
    def items(self) -> tuple[SelectItem, ...]:
        """Retained items kept visible for structural Product adapters."""

        return self._retained_items

    def blur(self) -> None:
        self.focused = False
        self._retained.blur()

    def handle_input(self, event: InputEvent) -> InputIntent | bool | None:
        value = _event_value(event)
        if value is None:
            return None
        if self._confirm_full_access:
            if value in {"esc", "escape", "n"}:
                self._confirm_full_access = False
                return InputIntent(kind="consumed", note="permission_confirmation")
            if value in {"enter", "y"}:
                return self._profile_action("full_access")
            return True
        if value == "tab":
            self.selected_tab = (
                "retained" if self.selected_tab == "mode" else "mode"
            )
            if self.selected_tab == "retained":
                self._retained.focus()
            else:
                self._retained.blur()
            return InputIntent(kind="consumed", note="permissions_tab")
        if value in {"esc", "escape"}:
            return InputIntent(kind="surface_close")
        if self.selected_tab == "retained":
            return self._retained.handle_input(event)
        if value in {"s", "p", "u"}:
            self.selected_scope = {
                "s": "session",
                "p": "project",
                "u": "user",
            }[value]  # type: ignore[assignment]
            return InputIntent(kind="consumed", note="permission_scope")
        if value in {"up", "down"}:
            self._move_mode(-1 if value == "up" else 1)
            return InputIntent(kind="consumed", note="permission_mode")
        if value in {"home", "end"}:
            self.selected_mode_index = (
                0 if value == "home" else len(self.profile_snapshot.options) - 1
            )
            return InputIntent(kind="consumed", note="permission_mode")
        if value.isdigit():
            index = int(value) - 1
            if 0 <= index < len(self.profile_snapshot.options):
                self.selected_mode_index = index
                return InputIntent(kind="consumed", note="permission_mode")
            return True
        if value == "enter":
            option = self.profile_snapshot.options[self.selected_mode_index]
            if not option.enabled:
                return InputIntent(kind="consumed", note="permission_mode_disabled")
            if (
                option.profile.profile_id == "full_access"
                and not option.current
            ):
                self._confirm_full_access = True
                return InputIntent(kind="consumed", note="permission_confirmation")
            return self._profile_action(option.profile.profile_id)
        return None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        width = autowrap_safe_width(constraints.width)
        lines = self._confirmation_lines(width) if self._confirm_full_access else (
            self._mode_lines(width)
            if self.selected_tab == "mode"
            else self._retained_lines(constraints)
        )
        return RenderResult.from_lines(
            lines[: constraints.max_height],
            constraints=constraints,
        )

    def _mode_lines(self, width: int) -> list[RenderLine]:
        lines = [
            RenderLine(self._tab_line()),
            RenderLine(
                self._styled(
                    "Control how tools, files, network, and approvals are handled.",
                    "permissions.description",
                )
            ),
            RenderLine(""),
            RenderLine(self._scope_line()),
            RenderLine(""),
        ]
        for index, option in enumerate(self.profile_snapshot.options, start=1):
            selected = index - 1 == self.selected_mode_index
            marker = "›" if selected else " "
            current = " (current)" if option.current else ""
            label = f"{marker} {index}. {option.profile.label}{current}"
            token = (
                "permissions.disabled"
                if not option.enabled
                else "permissions.mode.full_access"
                if option.profile.profile_id == "full_access"
                else "permissions.mode.selected"
                if selected
                else "permissions.mode.current"
                if option.current
                else "permissions.mode"
            )
            lines.append(RenderLine(self._styled(label, token)))
            description = option.disabled_reason or option.profile.description
            lines.append(
                RenderLine(
                    self._styled(
                        "     "
                        + truncate_to_width(
                            description,
                            max_width=max(1, width - 5),
                        ),
                        (
                            "permissions.disabled"
                            if not option.enabled
                            else "permissions.description"
                        ),
                    )
                )
            )
        lines.extend(
            (
                RenderLine(""),
                RenderLine(
                    self._styled(
                        f"Retained permissions  {_permission_count(self.approval_snapshot)}",
                        "permissions.counts",
                    )
                ),
            )
        )
        return lines

    def _retained_lines(self, constraints: RenderConstraints) -> list[RenderLine]:
        counts = self.approval_snapshot
        lines = [
            RenderLine(self._tab_line()),
            RenderLine(
                self._styled(
                    f"{len(counts.pending)} pending · "
                    f"{len(counts.grants)} session · "
                    f"{len(counts.project_rules)} project · "
                    f"{len(counts.user_rules)} user",
                    "permissions.counts",
                )
            ),
            RenderLine(""),
        ]
        if not self._retained_items:
            lines.extend(
                (
                    RenderLine(
                        self._styled(
                            "No retained permissions.",
                            "permissions.empty",
                        )
                    ),
                    RenderLine(
                        self._styled(
                            "Actions are still governed by the active permission mode.",
                            "permissions.description",
                        )
                    ),
                )
            )
            return lines
        remaining = max(1, constraints.max_height - len(lines))
        rendered = self._retained.render(
            RenderConstraints(
                width=constraints.width,
                max_height=remaining,
                visible_height=constraints.visible_height,
            )
        )
        lines.extend(rendered.lines)
        return lines

    def _confirmation_lines(self, width: int) -> list[RenderLine]:
        option = next(
            option
            for option in self.profile_snapshot.options
            if option.profile.profile_id == "full_access"
        )
        return [
            RenderLine(self._styled("Enable Full Access?", "permissions.warning")),
            RenderLine(""),
            RenderLine(
                self._styled(
                    truncate_to_width(
                        option.profile.description,
                        max_width=width,
                    ),
                    "permissions.description",
                )
            ),
            RenderLine(""),
            RenderLine(
                self._styled(
                    "Managed denies, delegated ceilings, and configured sandbox "
                    "limits will remain enforced.",
                    "permissions.warning",
                )
            ),
            RenderLine(""),
            RenderLine(
                f"Apply to: {self.selected_scope.title()}"
            ),
            RenderLine(""),
            RenderLine("Enter confirm · Esc back"),
        ]

    def _profile_action(self, profile_id: str) -> InputIntent:
        return InputIntent(
            kind="permission_profile_action",
            text=f"set-profile:{self.selected_scope}:{profile_id}",
        )

    def _move_mode(self, delta: int) -> None:
        count = len(self.profile_snapshot.options)
        self.selected_mode_index = (self.selected_mode_index + delta) % count

    def _tab_line(self) -> str:
        return "   ".join(
            self._styled(
                label,
                (
                    "permissions.tab.selected"
                    if tab == self.selected_tab
                    else "permissions.tab"
                ),
            )
            for tab, label in (("mode", "Mode"), ("retained", "Retained"))
        )

    def _scope_line(self) -> str:
        return "Apply to  " + "  ".join(
            self._styled(
                f"[{scope.title()}]"
                if scope == self.selected_scope
                else scope.title(),
                (
                    "permissions.scope.selected"
                    if scope == self.selected_scope
                    else "permissions.scope"
                ),
            )
            for scope in ("session", "project", "user")
        )

    @staticmethod
    def _styled(text: str, token: str) -> str:
        return apply_theme_style(text, _PERMISSIONS_THEME.resolve(token))


def build_permissions_surface_view(
    snapshot: ApprovalPermissionsSnapshot,
    *,
    profile_snapshot: PermissionProfileSnapshot | None = None,
) -> ScreenSurfaceView:
    """Show permission modes and retained grants without raw tool arguments."""

    resolved_profiles = profile_snapshot or permission_profile_snapshot("standard")
    retained_count = _permission_count(snapshot)
    return ScreenSurfaceView(
        title="Permissions",
        subtitle=(
            f"Current: {resolved_profiles.effective_profile.label} · "
            f"{retained_count} retained"
        ),
        purpose="permissions",
        content=PermissionsCenterSurface(
            profile_snapshot=resolved_profiles,
            approval_snapshot=snapshot,
        ),
        footer=(
            "Tab mode/retained · S/P/U scope · Enter select/revoke · Esc close"
        ),
        presentation="page",
    )


def _retained_permission_items(
    snapshot: ApprovalPermissionsSnapshot,
) -> tuple[SelectItem, ...]:
    items = [
        SelectItem(
            label=f"Pending · {permission.capability}",
            value=f"reopen:{permission.permission_id}",
            description=_permission_description(
                actor_id=permission.actor_id,
                summary=permission.summary,
            ),
        )
        for permission in snapshot.pending
    ]
    items.extend(
        SelectItem(
            label=f"Session · {permission.capability}",
            value=f"revoke:{permission.permission_id}",
            description=_permission_description(
                actor_id=permission.actor_id,
                summary=permission.summary,
            ),
        )
        for permission in snapshot.grants
    )
    for label, permissions in (
        ("Project", snapshot.project_rules),
        ("User", snapshot.user_rules),
    ):
        items.extend(
            SelectItem(
                label=f"{label} · {permission.capability}",
                value=f"revoke-policy:{permission.permission_id}",
                description=_permission_description(
                    actor_id=permission.actor_id,
                    summary=permission.summary,
                ),
            )
            for permission in permissions
        )
    return tuple(items)


def _event_value(event: InputEvent) -> str | None:
    if event.kind == "text":
        return event.text.strip().lower()
    if event.kind == "key":
        return event.key.lower()
    return None


def _permission_count(snapshot: ApprovalPermissionsSnapshot) -> int:
    return sum(
        len(values)
        for values in (
            snapshot.pending,
            snapshot.grants,
            snapshot.project_rules,
            snapshot.user_rules,
        )
    )


def _permission_description(*, actor_id: str, summary: str) -> str:
    requester = "Root" if actor_id == "root" else actor_id
    return f"{requester} · {summary}"


__all__ = ["PermissionsCenterSurface", "build_permissions_surface_view"]
