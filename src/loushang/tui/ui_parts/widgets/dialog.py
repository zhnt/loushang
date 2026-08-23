from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, TypeGuard

from loushang.tui.cell_width import autowrap_safe_width, truncate_to_width
from loushang.tui.core import RenderConstraints, RenderLine, RenderResult
from loushang.tui.theme import ThemeResolver
from loushang.tui.ui_parts.widgets._utils import style_text


class _FocusableBody(Protocol):
    def focus(self) -> None: ...

    def blur(self) -> None: ...


@dataclass(frozen=True, slots=True)
class DialogAction:
    label: str
    intent: object
    kind: str = "default"


@dataclass(slots=True)
class Dialog:
    title: str
    body: object | str | None = None
    actions: list[DialogAction] | tuple[DialogAction, ...] = ()
    focused: bool = False
    theme: ThemeResolver | None = field(default=None, kw_only=True)
    _focus_slot: str = field(default="body", init=False, repr=False)

    def focus(self) -> None:
        self.focused = True
        if _is_focusable(self.body):
            self._focus_slot = "body"
            self.body.focus()
        else:
            self._focus_slot = "action"

    def blur(self) -> None:
        self.focused = False
        if _is_focusable(self.body):
            self.body.blur()

    def handle_input(self, event: object) -> object:
        if getattr(event, "kind", "") != "key":
            return None
        key = getattr(event, "key", "")
        if key in {"esc", "escape", "ctrl+c"}:
            return _input_intent("dialog_cancel")
        if key == "tab":
            return self._focus_next()
        if key == "shift+tab":
            return self._focus_previous()
        if self._focus_slot == "body":
            return _delegate_input(self.body, event)
        if key == "enter" and self.actions:
            return self.actions[0].intent
        return None

    def editor_input_target(self) -> object | None:
        if self._focus_slot != "body":
            return None
        return _editor_input_target(self.body)

    def _focus_next(self) -> bool:
        if self._focus_slot == "body" and _form_focus_next(self.body):
            return True
        if _is_focusable(self.body):
            self.body.blur()
        self._focus_slot = "action"
        return True

    def _focus_previous(self) -> bool:
        if self._focus_slot == "body" and _form_focus_previous(self.body):
            return True
        if self._focus_slot == "action" and _is_focusable(self.body):
            self._focus_slot = "body"
            self.body.focus()
            return True
        return False

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return _dialog_result(
            title=self.title,
            body=self.body,
            action_labels=tuple(action.label for action in self.actions),
            constraints=constraints,
            theme=self.theme,
        )


@dataclass(slots=True)
class ConfirmDialog(Dialog):
    confirm_label: str = "Confirm"
    cancel_label: str = "Cancel"
    close_on_confirm: bool = True

    def handle_input(self, event: object) -> object:
        if getattr(event, "kind", "") != "key":
            return None
        key = getattr(event, "key", "")
        if key in {"esc", "escape", "ctrl+c"}:
            return _input_intent("dialog_cancel")
        if key == "tab":
            return self._focus_next()
        if key == "shift+tab":
            return self._focus_previous()
        if self._focus_slot == "body":
            result = _delegate_input(self.body, event)
            if result is not None:
                return result
        if key == "enter":
            confirm = _input_intent("dialog_confirm")
            if not self.close_on_confirm:
                return confirm
            return (confirm, _input_intent("surface_close"))
        return None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        return _dialog_result(
            title=self.title,
            body=self.body,
            action_labels=(self.confirm_label, self.cancel_label),
            constraints=constraints,
            theme=self.theme,
        )


def _input_intent(kind: str) -> object:
    from loushang.tui.input import InputIntent

    return InputIntent(kind=kind)


def _dialog_result(
    *,
    title: str,
    body: object | str | None,
    action_labels: tuple[str, ...],
    constraints: RenderConstraints,
    theme: ThemeResolver | None = None,
) -> RenderResult:
    target_width = autowrap_safe_width(constraints.width)
    title_line = truncate_to_width(title, max_width=target_width, ellipsis="")
    lines = [RenderLine(style_text(title_line, theme, "widget.dialog.title"))]
    if isinstance(body, str) and body:
        lines.append(RenderLine(truncate_to_width(body, max_width=target_width, ellipsis="")))
    elif body is not None:
        render = getattr(body, "render", None)
        if callable(render) and len(lines) < constraints.max_height:
            body_result = render(RenderConstraints(width=constraints.width, max_height=constraints.max_height - len(lines)))
            lines.extend(body_result.lines[: constraints.max_height - len(lines)])
    if action_labels:
        action_line = "  ".join(f"[{label}]" for label in action_labels)
        action_line = truncate_to_width(action_line, max_width=target_width, ellipsis="")
        lines.append(RenderLine(style_text(action_line, theme, "widget.dialog.action")))
    return RenderResult.from_lines(lines[: constraints.max_height], constraints=constraints)


def _is_focusable(value: object) -> TypeGuard[_FocusableBody]:
    return all(callable(getattr(value, name, None)) for name in ("focus", "blur"))


def _delegate_input(value: object, event: object) -> object:
    handler = getattr(value, "handle_input", None)
    if callable(handler):
        return handler(event)
    return None


def _form_focus_next(value: object) -> bool:
    focus_next = getattr(value, "focus_next", None)
    if callable(focus_next):
        return bool(focus_next(wrap=False))
    return False


def _form_focus_previous(value: object) -> bool:
    focus_previous = getattr(value, "focus_previous", None)
    if callable(focus_previous):
        return bool(focus_previous(wrap=False))
    return False


def _editor_input_target(value: object) -> object | None:
    from loushang.tui.framework import EditorInputTargetProvider

    if isinstance(value, EditorInputTargetProvider):
        return value.editor_input_target()
    return None
