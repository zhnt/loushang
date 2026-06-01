from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

from loushang.ai.types import ImagePart
from loushang.coding.platform.clipboard_image import (
    ClipboardImage,
    extension_for_image_mime_type,
    read_clipboard_image,
)
from loushang.coding.ui.native_app import NativeCodingTuiApp
from loushang.tui.input import InputEvent, InputIntent, route_composer_editing_key
from loushang.tui.keybindings import KeybindingConfig, KeybindingManager

RunningSubmitMode = Literal["steer", "follow_up"]
ClipboardImageReader = Callable[[], ClipboardImage | None]
ClipboardImageNameFactory = Callable[[], str]


@dataclass(frozen=True, slots=True)
class _PendingClipboardImage:
    marker: str
    image: ImagePart


@dataclass(frozen=True, slots=True)
class NativeInputResult:
    prompt_text: str | None = None
    prompt_images: tuple[ImagePart, ...] | None = None
    local_text: str | None = None
    steer_text: str | None = None
    steer_images: tuple[ImagePart, ...] | None = None
    followup_text: str | None = None
    followup_images: tuple[ImagePart, ...] | None = None
    surface_intent: InputIntent | None = None
    abort_requested: bool = False
    exit_code: int | None = None
    render_requested: bool = True


@dataclass(slots=True)
class NativeInputRouter:
    app: NativeCodingTuiApp
    should_exit: Callable[[str], bool]
    is_local_command: Callable[[str], bool] = lambda _text: False
    keybindings: KeybindingManager | KeybindingConfig | None = None
    running_submit_mode: RunningSubmitMode = "steer"
    follow_up_keys: tuple[str, ...] = ("alt+enter",)
    width: int = 80
    clipboard_image_reader: ClipboardImageReader = read_clipboard_image
    clipboard_image_dir: Path | str | None = None
    clipboard_image_name_factory: ClipboardImageNameFactory = field(default_factory=lambda: lambda: uuid.uuid4().hex)
    _jump_mode: Literal["forward", "backward"] | None = None
    _pending_clipboard_images: list[_PendingClipboardImage] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.keybindings, KeybindingManager):
            self.keybindings = KeybindingManager(self.keybindings)

    def handle(self, event: InputEvent) -> NativeInputResult:
        if self._runtime_surface_active():
            return self._route_runtime_surface(event)
        if self.app.active_surface is not None:
            return self._route_active_surface(event)
        if event.kind == "text":
            if self._jump_mode is not None:
                self.app.composer.jump_to_char(event.text, direction=self._jump_mode)
                self._jump_mode = None
                return NativeInputResult()
            self.app.composer.insert_text(event.text)
            return NativeInputResult()
        if event.kind == "paste":
            self._jump_mode = None
            self.app.composer.paste(event.text)
            return NativeInputResult()
        if event.kind == "resize":
            if event.columns:
                self.width = event.columns
            return NativeInputResult()
        if event.kind != "key" or event.event_type == "release":
            return NativeInputResult(render_requested=False)

        keybindings = self._keybindings()
        if self._jump_mode is not None:
            if keybindings.matches(event.key, "tui.editor.jumpForward") or keybindings.matches(
                event.key,
                "tui.editor.jumpBackward",
            ):
                self._jump_mode = None
                return NativeInputResult()
            self._jump_mode = None
        if keybindings.matches(event.key, "tui.queue.editLast"):
            self._restore_queued_messages()
            return NativeInputResult()
        if self.app.composer.has_completions and keybindings.matches(event.key, "tui.input.submit"):
            return self._submit_selected_completion()
        if self.app.composer.has_completions and self._route_completion_key(event, keybindings):
            return NativeInputResult()
        if keybindings.matches(event.key, "tui.select.cancel"):
            return self._abort_or_clear()
        if keybindings.matches(event.key, "tui.input.tab"):
            self.app.composer.refresh_completions(force=True, explicit=True)
            if self.app.composer.has_completions:
                self.app.composer.apply_selected_completion()
            return NativeInputResult()
        if keybindings.matches(event.key, "app.clipboard.pasteImage"):
            return self._paste_clipboard_image()
        if keybindings.matches(event.key, "tui.editor.jumpForward"):
            self._jump_mode = "forward"
            return NativeInputResult()
        if keybindings.matches(event.key, "tui.editor.jumpBackward"):
            self._jump_mode = "backward"
            return NativeInputResult()
        if keybindings.matches(event.key, "tui.editor.cursorUp"):
            if self.app.composer.browsing_history:
                self.app.composer.history_previous()
            elif not self.app.composer.value or not self.app.composer.move_visual_up(width=self.width):
                self.app.composer.history_previous()
            return NativeInputResult()
        if keybindings.matches(event.key, "tui.editor.cursorDown"):
            if self.app.composer.browsing_history:
                self.app.composer.history_next()
            elif not self.app.composer.value or not self.app.composer.move_visual_down(width=self.width):
                self.app.composer.history_next()
            return NativeInputResult()
        if self.app.state.running and event.key in self.follow_up_keys:
            return self._submit_running(mode="follow_up")
        if keybindings.matches(event.key, "tui.input.newLine"):
            self.app.composer.insert_newline()
            return NativeInputResult()
        if keybindings.matches(event.key, "tui.input.submit"):
            return self._submit()
        if route_composer_editing_key(self.app.composer, event.key, keybindings=keybindings):
            return NativeInputResult()
        return NativeInputResult(render_requested=False)

    def _route_completion_key(self, event: InputEvent, keybindings: KeybindingManager) -> bool:
        if keybindings.matches(event.key, "tui.select.up"):
            self.app.composer.select_previous_completion()
            return True
        if keybindings.matches(event.key, "tui.select.down"):
            self.app.composer.select_next_completion()
            return True
        if keybindings.matches(event.key, "tui.input.tab"):
            self.app.composer.apply_selected_completion()
            return True
        if keybindings.matches(event.key, "tui.select.cancel"):
            self.app.composer.clear_completion_items()
            return True
        return False

    def _submit_selected_completion(self) -> NativeInputResult:
        should_submit_after_completion = self.app.composer.value.lstrip().startswith("/")
        self.app.composer.apply_selected_completion()
        if should_submit_after_completion:
            return self._submit()
        return NativeInputResult()

    def _abort_or_clear(self) -> NativeInputResult:
        if self.app.state.running:
            return NativeInputResult(abort_requested=True)
        if self.app.state.pending_steers:
            pending_steer = self.app.state.pending_steers.pop(0)
            return NativeInputResult(steer_text=pending_steer)
        if self.app.composer.value:
            self.app.composer.clear()
            self._clear_prompt_attachments()
            return NativeInputResult()
        return NativeInputResult(render_requested=False)

    def _restore_queued_messages(self) -> None:
        text = self.app.state.restore_queued_to_text()
        if text:
            self.app.composer.set_text(text)

    def _submit(self) -> NativeInputResult:
        text = self.app.composer.value
        if not text.strip():
            return NativeInputResult(render_requested=False)
        if self.should_exit(text.strip()):
            self.app.composer.clear()
            self._clear_prompt_attachments()
            return NativeInputResult(exit_code=0)
        if self.app.state.running:
            return self._submit_running(mode=self.running_submit_mode)
        if self.is_local_command(text.strip()):
            self.app.composer.clear()
            self._clear_prompt_attachments()
            return NativeInputResult(local_text=text.strip())
        images = self._prompt_images_for_text(text)
        self.app.start_prompt(text)
        self._clear_prompt_attachments()
        return NativeInputResult(prompt_text=text, prompt_images=images)

    def _submit_running(self, *, mode: RunningSubmitMode) -> NativeInputResult:
        text = self.app.composer.value
        if not text.strip():
            return NativeInputResult(render_requested=False)
        images = self._prompt_images_for_text(text)
        self.app.composer.add_history(text)
        self.app.composer.clear()
        self._clear_prompt_attachments()
        if mode == "follow_up":
            self.app.queue_followup(text)
            return NativeInputResult(followup_text=text, followup_images=images)
        self.app.queue_steer(text)
        return NativeInputResult(steer_text=text, steer_images=images)

    def _keybindings(self) -> KeybindingManager:
        return self.keybindings if isinstance(self.keybindings, KeybindingManager) else KeybindingManager(self.keybindings)

    def _route_active_surface(self, event: InputEvent) -> NativeInputResult:
        handler = getattr(self.app.active_surface, "handle_input", None)
        if not callable(handler):
            return NativeInputResult(render_requested=False)
        intent = handler(event)
        if isinstance(intent, InputIntent):
            return NativeInputResult(surface_intent=intent)
        return NativeInputResult()

    def _runtime_surface_active(self) -> bool:
        surface_host = self.app.surface_host
        return surface_host is not None and bool(surface_host.entries)

    def _route_runtime_surface(self, event: InputEvent) -> NativeInputResult:
        surface_host = self.app.surface_host
        if surface_host is None:
            return NativeInputResult(render_requested=False)
        intents = surface_host.route_input(event, close_on_intents=("surface_close", "dialog_cancel"))
        for intent in intents:
            if isinstance(intent, InputIntent):
                return NativeInputResult(surface_intent=intent)
        return NativeInputResult()

    def _paste_clipboard_image(self) -> NativeInputResult:
        try:
            image = self.clipboard_image_reader()
        except Exception as error:  # noqa: BLE001 - platform clipboard commands can fail in many ways.
            self.app.set_status(f"Unable to read clipboard image: {_exception_message(error)}")
            return NativeInputResult()
        if image is None:
            self.app.set_status("No clipboard image found.")
            return NativeInputResult()
        extension = extension_for_image_mime_type(image.mime_type)
        if extension is None:
            self.app.set_status(f"Unsupported clipboard image type: {image.mime_type or 'unknown'}")
            return NativeInputResult()
        try:
            path = self._write_clipboard_image(image, extension=extension)
        except OSError as error:
            self.app.set_status(f"Unable to attach clipboard image: {error}")
            return NativeInputResult()
        marker_path = _display_path(path, cwd=Path(self.app.cwd))
        marker = f"@{marker_path}"
        self.app.composer.paste(f"{marker} ")
        self._pending_clipboard_images.append(
            _PendingClipboardImage(
                marker=marker,
                image=ImagePart(
                    type="image",
                    data=base64.b64encode(image.bytes).decode("ascii"),
                    mime_type=_base_mime_type(image.mime_type),
                ),
            )
        )
        self.app.set_status(f"Attached clipboard image: {marker_path}")
        return NativeInputResult()

    def _write_clipboard_image(self, image: ClipboardImage, *, extension: str) -> Path:
        directory = Path(self.clipboard_image_dir) if self.clipboard_image_dir is not None else Path(self.app.cwd) / ".loushang" / "clipboard"
        directory.mkdir(parents=True, exist_ok=True)
        token = _safe_filename_token(self.clipboard_image_name_factory())
        path = directory / f"clipboard-{token}.{extension}"
        path.write_bytes(image.bytes)
        return path

    def _prompt_images_for_text(self, text: str) -> tuple[ImagePart, ...] | None:
        present = [
            (position, pending.image)
            for pending in self._pending_clipboard_images
            if (position := text.find(pending.marker)) >= 0
        ]
        images = tuple(image for _position, image in sorted(present, key=lambda item: item[0]))
        return images or None

    def _clear_prompt_attachments(self) -> None:
        self._pending_clipboard_images.clear()


def _display_path(path: Path, *, cwd: Path) -> str:
    try:
        return path.relative_to(cwd).as_posix()
    except ValueError:
        return path.as_posix()


def _safe_filename_token(value: str) -> str:
    token = value.strip() or uuid.uuid4().hex
    safe = "".join(character if _is_safe_filename_character(character) else "_" for character in token)
    safe = safe.strip("._")
    return safe or uuid.uuid4().hex


def _is_safe_filename_character(character: str) -> bool:
    return character.isascii() and (character.isalnum() or character in {"-", "_", "."})


def _exception_message(error: BaseException) -> str:
    return str(error) or error.__class__.__name__


def _base_mime_type(mime_type: str) -> str:
    return mime_type.split(";", 1)[0].strip().lower()


__all__ = ["NativeInputResult", "NativeInputRouter", "RunningSubmitMode"]
