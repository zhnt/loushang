"""Product-neutral prompt input assembly for Agent-facing hosts.

This module owns the reusable ``stdin``/``@file``/image input mechanics.  A
Product supplies its argument grammar and can keep its own prompt wording;
the input protocol and image payload construction remain shared.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from loushang.ai.types import ImagePart
from loushang.harness.tools.workspace.image_payload import (
    PillowReadImageResizer,
    detect_supported_image_mime_type,
    prepare_image_payload_sync,
)
from loushang.harness.tools.workspace.path_utils import resolve_tool_path


@dataclass(frozen=True)
class PromptInputPlan:
    """Prompt text, initial images, and messages for the next turn."""

    user_input: str | None
    images: list[ImagePart] | None
    follow_up_messages: tuple[str, ...]


def resolve_prompt_input(
    *,
    prompt: str | None,
    messages: tuple[str, ...],
    message_prompts: tuple[str, ...],
    file_args: tuple[str, ...],
    stdin: TextIO,
    cwd: Path,
    auto_resize_images: bool = True,
) -> PromptInputPlan:
    """Assemble one prompt from injected streams and file arguments."""

    file_text, images = _process_file_args(
        file_args,
        cwd,
        auto_resize_images=auto_resize_images,
    )
    parts: list[str] = []
    stdin_content = _read_stdin_prompt(stdin)
    if stdin_content is not None:
        parts.append(stdin_content)
    if file_text:
        parts.append(file_text)
    if prompt is not None:
        parts.append(prompt.strip())
    if messages:
        parts.append(" ".join(messages).strip())

    user_input = "".join(parts).strip() or None
    follow_up_messages = message_prompts
    if user_input is None and follow_up_messages:
        user_input = follow_up_messages[0]
        follow_up_messages = follow_up_messages[1:]
    return PromptInputPlan(
        user_input=user_input,
        images=images or None,
        follow_up_messages=follow_up_messages,
    )


def _process_file_args(
    file_args: tuple[str, ...],
    cwd: Path,
    *,
    auto_resize_images: bool = True,
) -> tuple[str, list[ImagePart]]:
    text_parts: list[str] = []
    images: list[ImagePart] = []
    for file_arg in file_args:
        path = resolve_tool_path(file_arg, cwd=str(cwd))
        payload = path.read_bytes()
        if not payload:
            continue
        mime_type = detect_supported_image_mime_type(path, payload)
        if mime_type is not None:
            prepared = prepare_image_payload_sync(
                payload,
                mime_type=mime_type,
                image_resizer=PillowReadImageResizer(),
                resize_if_needed=auto_resize_images,
            )
            if prepared.resize_attempted and not prepared.resize_succeeded:
                text_parts.append(
                    f'<file name="{path}">'
                    "[Image omitted: could not be resized below the inline image size limit.]"
                    "</file>\n"
                )
                continue
            images.append(
                ImagePart(
                    type="image",
                    data=prepared.base64_payload.decode("ascii"),
                    mime_type=prepared.mime_type,
                )
            )
            text_parts.append(
                f'<file name="{path}">{prepared.dimension_note or ""}</file>\n'
            )
            continue
        try:
            content = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RuntimeError(f"Could not read file {path}: {error}") from error
        text_parts.append(f'<file name="{path}">\n{content}\n</file>\n')
    return "".join(text_parts), images


def _read_stdin_prompt(stdin: TextIO) -> str | None:
    isatty = getattr(stdin, "isatty", None)
    if callable(isatty):
        try:
            if isatty():
                return None
        except OSError:
            pass
    content = stdin.read()
    if not isinstance(content, str):
        return None
    stripped = content.strip()
    return stripped or None


__all__ = ["PromptInputPlan", "resolve_prompt_input"]
