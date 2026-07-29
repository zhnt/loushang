import base64
import math
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path
from typing import Any, NotRequired, Protocol, TypedDict

from loushang.agent.types import AgentToolResult, ImagePart, TextPart
from loushang.harness.tools.authoring import (
    FilesystemActionAdapter,
    ToolContext,
    authorized_tool,
    tool,
)
from loushang.harness.workspace.operations import ReadOperations, resolve_operation

from .builtin_renderers import render_read_call, render_read_result
from .operations import (
    normalize_read_operations,
    raise_if_operation_aborted,
)
from .path_utils import resolve_tool_path
from .runtime import (
    MaybeAwaitable,
    coerce_int_parameter,
    pi_truncation_details,
    prepare_tool_arguments,
    resolve_maybe_awaitable,
)
from .truncate import DEFAULT_MAX_BYTES, format_size, truncate_head, truncation_details
from .types import PiTruncationDetails, ToolDefinition

MAX_INLINE_IMAGE_BASE64_BYTES = int(4.5 * 1024 * 1024)
MAX_INLINE_IMAGE_DIMENSION = 2000
DEFAULT_RESIZED_IMAGE_JPEG_QUALITIES = (80, 85, 70, 55, 40)


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
class ReadImageResizeResult:
    payload: bytes
    mime_type: str
    original_dimensions: tuple[int, int] | None
    dimensions: tuple[int, int] | None
    was_resized: bool


class ReadImageResizer(Protocol):
    def resize_image(
        self,
        payload: bytes,
        *,
        mime_type: str,
        dimensions: tuple[int, int] | None,
    ) -> MaybeAwaitable[ReadImageResizeResult | None]: ...


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
            dimensions = _detect_image_dimensions(mime_type, payload)
            original_dimensions = dimensions
            encoded = base64.b64encode(payload)
            model_supports_image_input = _model_supports_image_input(ctx.model)
            text_note = f"Read image file [{mime_type}]"
            exceeds_inline_limits = _image_exceeds_inline_limits(encoded, dimensions)
            omit_for_model = model_supports_image_input is False
            image_resized = False
            resize_note: str | None = None
            resize_unavailable = False
            resize_reason: str | None = None
            if exceeds_inline_limits and not omit_for_model and auto_resize_images:
                resize_unavailable = _image_resize_unavailable(image_resizer)
                resize_reason = "unavailable" if resize_unavailable else None
                resize_result = (
                    None
                    if resize_unavailable
                    else await _resize_image_payload(
                        image_resizer,
                        payload,
                        mime_type=mime_type,
                        dimensions=dimensions,
                    )
                )
                if resize_result is not None:
                    payload = resize_result.payload
                    mime_type = resize_result.mime_type
                    dimensions = resize_result.dimensions or _detect_image_dimensions(
                        mime_type, payload
                    )
                    original_dimensions = (
                        resize_result.original_dimensions or original_dimensions
                    )
                    encoded = base64.b64encode(payload)
                    image_resized = resize_result.was_resized
                    resize_note = _format_dimension_note(
                        original_dimensions=original_dimensions,
                        dimensions=dimensions,
                        was_resized=image_resized,
                    )
                    exceeds_inline_limits = _image_exceeds_inline_limits(
                        encoded, dimensions
                    )
                    text_note = f"Read image file [{mime_type}]"

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


def _image_resize_unavailable(image_resizer: ReadImageResizer) -> bool:
    is_available = getattr(image_resizer, "is_available", None)
    return bool(callable(is_available) and not is_available())


async def _resize_image_payload(
    image_resizer: ReadImageResizer,
    payload: bytes,
    *,
    mime_type: str,
    dimensions: tuple[int, int] | None,
) -> ReadImageResizeResult | None:
    return await resolve_maybe_awaitable(
        image_resizer.resize_image(payload, mime_type=mime_type, dimensions=dimensions)
    )


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
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"} and payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if suffix == ".png" and payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if suffix == ".gif" and (
        payload.startswith(b"GIF87a") or payload.startswith(b"GIF89a")
    ):
        return "image/gif"
    if suffix == ".webp" and _is_webp_payload(payload):
        return "image/webp"
    return None


def _is_webp_payload(payload: bytes) -> bool:
    header = payload[:12]
    return len(header) == 12 and header[:4] == b"RIFF" and header[8:] == b"WEBP"


def _detect_image_dimensions(mime_type: str, payload: bytes) -> tuple[int, int] | None:
    if mime_type == "image/png":
        return _detect_png_dimensions(payload)
    if mime_type == "image/gif":
        return _detect_gif_dimensions(payload)
    if mime_type == "image/jpeg":
        return _detect_jpeg_dimensions(payload)
    if mime_type == "image/webp":
        return _detect_webp_dimensions(payload)
    return None


def detect_image_dimensions(mime_type: str, payload: bytes) -> tuple[int, int] | None:
    return _detect_image_dimensions(mime_type, payload)


def _detect_png_dimensions(payload: bytes) -> tuple[int, int] | None:
    if (
        len(payload) < 24
        or not payload.startswith(b"\x89PNG\r\n\x1a\n")
        or payload[12:16] != b"IHDR"
    ):
        return None
    width = int.from_bytes(payload[16:20], "big")
    height = int.from_bytes(payload[20:24], "big")
    return (width, height) if width > 0 and height > 0 else None


def _detect_gif_dimensions(payload: bytes) -> tuple[int, int] | None:
    if len(payload) < 10 or not (
        payload.startswith(b"GIF87a") or payload.startswith(b"GIF89a")
    ):
        return None
    width = int.from_bytes(payload[6:8], "little")
    height = int.from_bytes(payload[8:10], "little")
    return (width, height) if width > 0 and height > 0 else None


def _detect_jpeg_dimensions(payload: bytes) -> tuple[int, int] | None:
    if len(payload) < 4 or not payload.startswith(b"\xff\xd8"):
        return None
    cursor = 2
    while cursor + 3 < len(payload):
        if payload[cursor] != 0xFF:
            cursor += 1
            continue
        while cursor < len(payload) and payload[cursor] == 0xFF:
            cursor += 1
        if cursor >= len(payload):
            return None
        marker = payload[cursor]
        cursor += 1
        if marker in {0x01, *range(0xD0, 0xD8), 0xD9}:
            continue
        if cursor + 2 > len(payload):
            return None
        segment_length = int.from_bytes(payload[cursor : cursor + 2], "big")
        if segment_length < 2 or cursor + segment_length > len(payload):
            return None
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            if segment_length < 7:
                return None
            height = int.from_bytes(payload[cursor + 3 : cursor + 5], "big")
            width = int.from_bytes(payload[cursor + 5 : cursor + 7], "big")
            return (width, height) if width > 0 and height > 0 else None
        cursor += segment_length
    return None


def _detect_webp_dimensions(payload: bytes) -> tuple[int, int] | None:
    if len(payload) < 16 or not _is_webp_payload(payload):
        return None
    chunk = payload[12:16]
    if chunk == b"VP8X" and len(payload) >= 30:
        width = int.from_bytes(payload[24:27], "little") + 1
        height = int.from_bytes(payload[27:30], "little") + 1
        return (width, height) if width > 0 and height > 0 else None
    if chunk == b"VP8 " and len(payload) >= 30:
        width = int.from_bytes(payload[26:28], "little") & 0x3FFF
        height = int.from_bytes(payload[28:30], "little") & 0x3FFF
        return (width, height) if width > 0 and height > 0 else None
    if chunk == b"VP8L" and len(payload) >= 25:
        packed = int.from_bytes(payload[21:25], "little")
        width = (packed & 0x3FFF) + 1
        height = ((packed >> 14) & 0x3FFF) + 1
        return (width, height) if width > 0 and height > 0 else None
    return None


def _image_exceeds_inline_limits(
    encoded: bytes, dimensions: tuple[int, int] | None
) -> bool:
    if len(encoded) >= MAX_INLINE_IMAGE_BASE64_BYTES:
        return True
    if dimensions is None:
        return False
    return max(dimensions) > MAX_INLINE_IMAGE_DIMENSION


def image_exceeds_inline_limits(
    encoded: bytes, dimensions: tuple[int, int] | None
) -> bool:
    return _image_exceeds_inline_limits(encoded, dimensions)


@dataclass(frozen=True)
class PillowReadImageResizer:
    max_width: int = MAX_INLINE_IMAGE_DIMENSION
    max_height: int = MAX_INLINE_IMAGE_DIMENSION
    max_base64_bytes: int = MAX_INLINE_IMAGE_BASE64_BYTES
    jpeg_qualities: tuple[int, ...] = DEFAULT_RESIZED_IMAGE_JPEG_QUALITIES

    def is_available(self) -> bool:
        try:
            from PIL import Image  # noqa: F401
        except ImportError:
            return False
        return True

    def resize_image(
        self,
        payload: bytes,
        *,
        mime_type: str,
        dimensions: tuple[int, int] | None,
    ) -> ReadImageResizeResult | None:
        try:
            from PIL import Image
        except ImportError:
            return None

        try:
            from PIL import ImageOps
        except ImportError:
            ImageOps = None

        try:
            with Image.open(BytesIO(payload)) as opened_image:
                image = _apply_exif_transpose(opened_image, image_ops=ImageOps)
                original_dimensions = (image.width, image.height)
                try:
                    for target_dimensions in _iter_resize_dimensions(
                        original_dimensions,
                        max_width=self.max_width,
                        max_height=self.max_height,
                    ):
                        resized_image = image.copy()
                        try:
                            resized_image.thumbnail(
                                target_dimensions, _pillow_lanczos_filter(Image)
                            )
                            resized_dimensions = (
                                resized_image.width,
                                resized_image.height,
                            )
                            candidates = _encode_resized_image_candidates(
                                resized_image,
                                jpeg_qualities=self.jpeg_qualities,
                            )
                            fitting_candidate = _first_fitting_encoded_candidate(
                                candidates,
                                max_base64_bytes=self.max_base64_bytes,
                            )
                            if fitting_candidate is None:
                                continue
                            candidate_mime_type, candidate_payload = fitting_candidate
                            return ReadImageResizeResult(
                                payload=candidate_payload,
                                mime_type=candidate_mime_type,
                                original_dimensions=original_dimensions,
                                dimensions=resized_dimensions,
                                was_resized=(
                                    resized_dimensions != original_dimensions
                                    or candidate_mime_type != mime_type
                                    or candidate_payload != payload
                                ),
                            )
                        finally:
                            _close_image(resized_image)
                finally:
                    if image is not opened_image:
                        _close_image(image)
        except Exception:
            return None
        return None


def _apply_exif_transpose(image: object, *, image_ops: object | None) -> object:
    if image_ops is None:
        return image
    exif_transpose = getattr(image_ops, "exif_transpose", None)
    if not callable(exif_transpose):
        return image
    return exif_transpose(image)


def _initial_resize_dimensions(
    original_dimensions: tuple[int, int],
    *,
    max_width: int,
    max_height: int,
) -> tuple[int, int]:
    width, height = original_dimensions
    target_width = width
    target_height = height

    if target_width > max_width:
        target_height = round((target_height * max_width) / target_width)
        target_width = max_width
    if target_height > max_height:
        target_width = round((target_width * max_height) / target_height)
        target_height = max_height
    return (max(1, target_width), max(1, target_height))


def _iter_resize_dimensions(
    original_dimensions: tuple[int, int],
    *,
    max_width: int,
    max_height: int,
):
    width, height = _initial_resize_dimensions(
        original_dimensions,
        max_width=max_width,
        max_height=max_height,
    )
    while True:
        yield (width, height)
        if width == 1 and height == 1:
            break
        next_width = 1 if width == 1 else max(1, math.floor(width * 0.75))
        next_height = 1 if height == 1 else max(1, math.floor(height * 0.75))
        if next_width == width and next_height == height:
            break
        width = next_width
        height = next_height


def _first_fitting_encoded_candidate(
    candidates: list[tuple[str, bytes]],
    *,
    max_base64_bytes: int,
) -> tuple[str, bytes] | None:
    for candidate_mime_type, candidate_payload in candidates:
        if len(base64.b64encode(candidate_payload)) < max_base64_bytes:
            return (candidate_mime_type, candidate_payload)
    return None


def _close_image(image: object) -> None:
    close = getattr(image, "close", None)
    if callable(close):
        close()


def _encode_resized_image_candidates(
    image: object,
    *,
    jpeg_qualities: tuple[int, ...],
) -> list[tuple[str, bytes]]:
    candidates: list[tuple[str, bytes]] = []
    png_buffer = BytesIO()
    image.save(png_buffer, format="PNG")  # type: ignore[attr-defined]
    candidates.append(("image/png", png_buffer.getvalue()))

    rgb_image = image
    if getattr(image, "mode", None) not in {"RGB", "L"}:
        rgb_image = image.convert("RGB")  # type: ignore[attr-defined]
    for quality in jpeg_qualities:
        jpeg_buffer = BytesIO()
        rgb_image.save(jpeg_buffer, format="JPEG", quality=quality, optimize=True)  # type: ignore[attr-defined]
        candidates.append(("image/jpeg", jpeg_buffer.getvalue()))
    return candidates


def _pillow_lanczos_filter(image_module: object) -> object:
    resampling = getattr(image_module, "Resampling", None)
    if resampling is not None:
        return resampling.LANCZOS
    return getattr(image_module, "LANCZOS", 1)


def _format_dimension_note(
    *,
    original_dimensions: tuple[int, int] | None,
    dimensions: tuple[int, int] | None,
    was_resized: bool,
) -> str | None:
    if not was_resized or original_dimensions is None or dimensions is None:
        return None
    original_width, original_height = original_dimensions
    width, height = dimensions
    if width <= 0 or height <= 0:
        return None
    scale = original_width / width
    return (
        f"[Image: original {original_width}x{original_height}, displayed at {width}x{height}. "
        f"Multiply coordinates by {scale:.2f} to map to original image.]"
    )


def format_image_dimension_note(
    *,
    original_dimensions: tuple[int, int] | None,
    dimensions: tuple[int, int] | None,
    was_resized: bool,
) -> str | None:
    return _format_dimension_note(
        original_dimensions=original_dimensions,
        dimensions=dimensions,
        was_resized=was_resized,
    )


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
