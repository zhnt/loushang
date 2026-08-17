from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from loushang.agent.types import AgentToolResult, ImagePart, TextPart
from loushang.harness.tools.authoring import (
    FilesystemActionAdapter,
    ToolContext,
    authorized_tool,
    tool,
)
from loushang.harness.workspace.operations import ReadOperations, resolve_operation

from .builtin_renderers import render_read_call, render_read_result
from .image_payload import (
    PillowReadImageResizer,
    ReadImageResizer,
    detect_supported_image_mime_type,
    prepare_image_payload,
)
from .image_payload import (
    ReadImageResizeResult as ReadImageResizeResult,
)
from .image_payload import (
    detect_image_dimensions as detect_image_dimensions,
)
from .image_payload import (
    format_image_dimension_note as format_image_dimension_note,
)
from .image_payload import (
    image_exceeds_inline_limits as image_exceeds_inline_limits,
)
from .operations import (
    normalize_read_operations,
    raise_if_operation_aborted,
)
from .path_utils import resolve_tool_path
from .runtime import (
    coerce_int_parameter,
    pi_truncation_details,
    prepare_tool_arguments,
)
from .truncate import DEFAULT_MAX_BYTES, format_size, truncate_head, truncation_details
from .types import PiTruncationDetails, ToolDefinition


class ReadToolInput(TypedDict):
    path: str
    file_path: NotRequired[str]
    offset: NotRequired[int]
    limit: NotRequired[int]


class ReadToolDetails(TypedDict, total=False):
    path: str
    is_image: bool
    start_line: int
    end_line: int
    total_lines: int
    output_lines: int
    total_bytes: int
    output_bytes: int
    max_lines: int
    max_bytes: int
    truncated: bool
    truncated_by: str | None
    first_line_exceeds_limit: bool
    last_line_partial: bool
    truncation: PiTruncationDetails | None
    mime_type: str
    bytes_read: int
    base64_bytes: int
    image_omitted: bool
    image_resized: bool
    omit_reason: str
    width: int | None
    height: int | None
    original_width: int | None
    original_height: int | None
    resize_note: str | None
    resize_unavailable: bool
    resize_reason: str | None
    model_supports_image_input: bool | None


@dataclass(frozen=True)
class ReadToolOptions:
    operations: ReadOperations | None = None
    auto_resize_images: bool = True
    autoResizeImages: bool | None = None
    image_resizer: ReadImageResizer | None = None


def create_read_tool_definition(
    *,
    operations: ReadOperations | None = None,
    options: ReadToolOptions | None = None,
) -> ToolDefinition:
    ops = normalize_read_operations(
        operations or (options.operations if options is not None else None)
    )
    auto_resize_images = _resolve_auto_resize_images(options)
    image_resizer = _resolve_image_resizer(options)

    @tool(
        name="read",
        label="Read",
        description=(
            "Read text files and images from the workspace. "
            "For large text files, use offset and limit to continue reading."
        ),
        prompt_snippet="- read: Read text files and images from the workspace.",
    )
    async def read(
        path: str,
        offset: int | None = None,
        limit: int | None = None,
        *,
        ctx: ToolContext,
    ) -> AgentToolResult[dict[str, Any]]:
        raise_if_operation_aborted(ctx.signal)
        resolved = resolve_tool_path(path, cwd=ctx.cwd)
        payload = await _read_file_payload(resolved, operations=ops)
        raise_if_operation_aborted(ctx.signal)
        mime_type = await _detect_supported_image_mime_type(
            resolved, payload, operations=ops
        )
        if mime_type is not None:
            model_supports_image_input = _model_supports_image_input(ctx.model)
            omit_for_model = model_supports_image_input is False
            prepared = await prepare_image_payload(
                payload,
                mime_type=mime_type,
                image_resizer=image_resizer,
                resize_if_needed=auto_resize_images and not omit_for_model,
            )
            payload = prepared.payload
            mime_type = prepared.mime_type
            encoded = prepared.base64_payload
            dimensions = prepared.dimensions
            original_dimensions = prepared.original_dimensions
            text_note = f"Read image file [{mime_type}]"
            exceeds_inline_limits = prepared.exceeds_inline_limits
            image_resized = prepared.was_resized
            resize_note = prepared.dimension_note
            resize_unavailable = prepared.resize_unavailable
            resize_reason = "unavailable" if resize_unavailable else None

            if exceeds_inline_limits or omit_for_model:
                omit_reasons = []
                if exceeds_inline_limits:
                    omit_reasons.append("inline_image_limit")
                    text_note = _append_image_omit_note(
                        text_note,
                        auto_resize_images=auto_resize_images,
                        image_resized=image_resized,
                        resize_unavailable=resize_unavailable,
                    )
                if omit_for_model:
                    omit_reasons.append("non_vision_model")
                text_note = _append_non_vision_image_note(
                    text_note, model_supports_image_input
                )
                return AgentToolResult(
                    content=[TextPart(type="text", text=text_note)],
                    details={
                        "path": str(resolved),
                        "is_image": True,
                        "mime_type": mime_type,
                        "bytes_read": len(payload),
                        "base64_bytes": len(encoded),
                        "image_omitted": True,
                        "image_resized": image_resized,
                        "omit_reason": "+".join(omit_reasons),
                        "width": dimensions[0] if dimensions is not None else None,
                        "height": dimensions[1] if dimensions is not None else None,
                        "original_width": original_dimensions[0]
                        if original_dimensions is not None
                        else None,
                        "original_height": original_dimensions[1]
                        if original_dimensions is not None
                        else None,
                        "resize_note": resize_note,
                        "resize_unavailable": resize_unavailable,
                        "resize_reason": resize_reason,
                        "model_supports_image_input": model_supports_image_input,
                    },
                )
            if resize_note:
                text_note = f"{text_note}\n{resize_note}"
            text_note = _append_non_vision_image_note(
                text_note, model_supports_image_input
            )
            return AgentToolResult(
                content=[
                    TextPart(type="text", text=text_note),
                    ImagePart(
                        type="image", data=encoded.decode("ascii"), mime_type=mime_type
                    ),
                ],
                details={
                    "path": str(resolved),
                    "is_image": True,
                    "mime_type": mime_type,
                    "bytes_read": len(payload),
                    "base64_bytes": len(encoded),
                    "image_omitted": False,
                    "image_resized": image_resized,
                    "width": dimensions[0] if dimensions is not None else None,
                    "height": dimensions[1] if dimensions is not None else None,
                    "original_width": original_dimensions[0]
                    if original_dimensions is not None
                    else None,
                    "original_height": original_dimensions[1]
                    if original_dimensions is not None
                    else None,
                    "resize_note": resize_note,
                    "resize_unavailable": resize_unavailable,
                    "resize_reason": resize_reason,
                    "model_supports_image_input": model_supports_image_input,
                },
            )
        text = _decode_text_payload(resolved, payload)
        (
            sliced_text,
            start_line,
            end_line,
            truncated,
            total_lines,
            user_limit_remaining,
        ) = _slice_text(
            text,
            offset=offset,
            limit=limit,
        )
        truncation = truncate_head(sliced_text)
        if truncation.first_line_exceeds_limit:
            first_line_notice = _first_line_too_large_notice(
                sliced_text,
                start_line=start_line,
                path=path,
            )
            assert first_line_notice is not None
            return AgentToolResult(
                content=[TextPart(type="text", text=first_line_notice)],
                details={
                    "path": str(resolved),
                    "is_image": False,
                    "start_line": start_line,
                    "end_line": start_line - 1,
                    **truncation_details(truncation),
                    "truncation": pi_truncation_details(truncation)
                    if truncation.truncated
                    else None,
                },
            )

        start_line, end_line = _align_rendered_line_range(
            sliced_text=sliced_text,
            rendered_text=truncation.content,
            start_line=start_line,
            end_line=end_line,
        )
        rendered_text = _append_read_notice(
            truncation.content,
            start_line=start_line,
            end_line=end_line,
            total_lines=total_lines,
            user_limit_remaining=user_limit_remaining,
            truncated_by=truncation.truncated_by,
        )
        return AgentToolResult(
            content=[TextPart(type="text", text=rendered_text)],
            details={
                "path": str(resolved),
                "is_image": False,
                "start_line": start_line,
                "end_line": end_line,
                **truncation_details(truncation),
                "truncated": truncated or truncation.truncated,
                "truncation": pi_truncation_details(truncation)
                if truncation.truncated
                else None,
            },
        )

    return replace(
        authorized_tool(
            read,
            action=FilesystemActionAdapter("read"),
        ),
        prepare_arguments=lambda value: prepare_tool_arguments(
            value, aliases=(("file_path", "path"),)
        ),
        render_call=render_read_call,
        render_result=render_read_result,
    )


def _resolve_auto_resize_images(options: ReadToolOptions | None) -> bool:
    if options is None:
        return True
    if options.autoResizeImages is not None:
        return bool(options.autoResizeImages)
    return bool(options.auto_resize_images)


def _resolve_image_resizer(options: ReadToolOptions | None) -> ReadImageResizer:
    if options is not None and options.image_resizer is not None:
        return options.image_resizer
    return PillowReadImageResizer()


async def _read_file_payload(
    resolved: Path,
    *,
    operations: ReadOperations,
) -> bytes:
    if not await resolve_operation(operations.exists(resolved)):
        raise FileNotFoundError(str(resolved))
    if not await resolve_operation(operations.is_file(resolved)):
        raise IsADirectoryError(str(resolved))
    return await resolve_operation(operations.read_bytes(resolved))


def _decode_text_payload(path: Path, payload: bytes) -> str:
    if b"\x00" in payload:
        raise ValueError(f"binary file payloads are not supported: {path}")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"binary file payloads are not supported: {path}") from exc


async def _detect_supported_image_mime_type(
    path: Path, payload: bytes, *, operations: ReadOperations
) -> str | None:
    detector = getattr(operations, "detect_image_mime_type", None)
    if callable(detector):
        detected = await resolve_operation(detector(path))
        if isinstance(detected, str) and detected:
            return detected
    return detect_supported_image_mime_type(path, payload)


def _append_image_omit_note(
    text: str,
    *,
    auto_resize_images: bool,
    image_resized: bool,
    resize_unavailable: bool,
) -> str:
    if not auto_resize_images:
        reason = "auto-resize is disabled"
    elif resize_unavailable:
        reason = "auto-resize backend is unavailable"
    elif image_resized:
        reason = "resized image still exceeds inline image safety limits"
    else:
        reason = "auto-resize is unavailable or failed"
    return f"{text}\n[Image omitted: exceeds inline image safety limits and {reason}.]"


def _model_supports_image_input(model: object | None) -> bool | None:
    if model is None:
        return None
    supports_image_input = getattr(model, "supports_image_input", None)
    if supports_image_input is not None:
        return bool(supports_image_input)
    model_input = getattr(model, "input", None)
    if model_input is None:
        return None
    try:
        return "image" in model_input
    except TypeError:
        return None


def _append_non_vision_image_note(
    text: str, model_supports_image_input: bool | None
) -> str:
    if model_supports_image_input is not False:
        return text
    return f"{text}\n[Current model does not support images. The image will be omitted from this request.]"


def _slice_text(
    text: str,
    *,
    offset: int | None,
    limit: int | None,
) -> tuple[str, int, int, bool, int, int]:
    offset = coerce_int_parameter(offset, field_name="offset", minimum=1)
    limit = coerce_int_parameter(limit, field_name="limit", minimum=1)

    lines = text.splitlines(keepends=True)
    total_lines = len(lines)
    start_index = (offset - 1) if offset is not None else 0
    if (
        start_index >= total_lines
        and offset is not None
        and not (total_lines == 0 and start_index == 0)
    ):
        raise ValueError(
            f"Offset {offset} is beyond end of file ({total_lines} lines total)"
        )
    end_index = (start_index + limit) if limit is not None else len(lines)
    sliced = lines[start_index:end_index]
    truncated = start_index > 0 or end_index < len(lines)
    user_limit_remaining = max(0, len(lines) - end_index) if limit is not None else 0

    if sliced:
        start_line = start_index + 1
        end_line = start_index + len(sliced)
    else:
        start_line = 1 if not lines else min(start_index + 1, len(lines) + 1)
        end_line = start_index

    return (
        "".join(sliced),
        start_line,
        end_line,
        truncated,
        total_lines,
        user_limit_remaining,
    )


def _first_line_too_large_notice(
    text: str, *, start_line: int, path: str
) -> str | None:
    if not text:
        return None
    first_line = text.splitlines()[0] if text.splitlines() else text
    first_line_size = len(first_line.encode("utf-8"))
    if first_line_size <= DEFAULT_MAX_BYTES:
        return None
    return (
        f"[Line {start_line} is {format_size(first_line_size)}, exceeds {format_size(DEFAULT_MAX_BYTES)} limit. "
        f"Use bash: sed -n '{start_line}p' {path} | head -c {DEFAULT_MAX_BYTES}]"
    )


def _append_read_notice(
    content: str,
    *,
    start_line: int,
    end_line: int,
    total_lines: int,
    user_limit_remaining: int,
    truncated_by: str | None,
) -> str:
    if not content:
        return content
    if truncated_by == "lines":
        return (
            f"{content}\n[Showing lines {start_line}-{end_line} of {total_lines}. "
            f"Use offset={end_line + 1} to continue.]"
        )
    if truncated_by is None and user_limit_remaining > 0:
        return f"{content}\n[{user_limit_remaining} more lines in file. Use offset={end_line + 1} to continue.]"
    if truncated_by is None:
        return content
    return (
        f"{content}\n[Showing lines {start_line}-{end_line} of {total_lines} "
        f"({format_size(DEFAULT_MAX_BYTES)} limit). Use offset={end_line + 1} to continue.]"
    )


def _align_rendered_line_range(
    *,
    sliced_text: str,
    rendered_text: str,
    start_line: int,
    end_line: int,
) -> tuple[int, int]:
    if not sliced_text or rendered_text == sliced_text:
        return start_line, end_line

    visible_lines = _count_visible_rendered_lines(
        sliced_text=sliced_text, rendered_text=rendered_text
    )
    if visible_lines == 0:
        return start_line, start_line - 1
    return start_line, start_line + visible_lines - 1


def _count_visible_rendered_lines(*, sliced_text: str, rendered_text: str) -> int:
    consumed = 0
    visible_lines = 0
    for line in sliced_text.splitlines(keepends=True):
        if consumed >= len(rendered_text):
            break
        visible_lines += 1
        consumed += len(line)
    return visible_lines
