"""Shared image payload inspection and resizing.

This module owns image-format validation, dimension inspection, encoding,
inline payload limits, resize preparation, and the default Pillow resize
policy. Workspace consumers such as the read tool and prompt-input assembly
depend on this owner instead of depending on one another.
"""

from __future__ import annotations

import base64
import inspect
import math
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol, TypeVar, cast

from .runtime import MaybeAwaitable, resolve_maybe_awaitable

MAX_INLINE_IMAGE_BASE64_BYTES = int(4.5 * 1024 * 1024)
MAX_INLINE_IMAGE_DIMENSION = 2000
DEFAULT_RESIZED_IMAGE_JPEG_QUALITIES = (80, 85, 70, 55, 40)
ImageT = TypeVar("ImageT")


@dataclass(frozen=True)
class ReadImageResizeResult:
    payload: bytes
    mime_type: str
    original_dimensions: tuple[int, int] | None
    dimensions: tuple[int, int] | None
    was_resized: bool


@dataclass(frozen=True)
class PreparedImagePayload:
    """Inspected and optionally resized payload ready for consumer projection."""

    payload: bytes
    mime_type: str
    base64_payload: bytes
    original_dimensions: tuple[int, int] | None
    dimensions: tuple[int, int] | None
    exceeds_inline_limits: bool
    resize_attempted: bool
    resize_succeeded: bool
    resize_unavailable: bool
    was_resized: bool
    dimension_note: str | None


class ReadImageResizer(Protocol):
    def resize_image(
        self,
        payload: bytes,
        *,
        mime_type: str,
        dimensions: tuple[int, int] | None,
    ) -> MaybeAwaitable[ReadImageResizeResult | None]: ...


def detect_supported_image_mime_type(path: Path, payload: bytes) -> str | None:
    """Return a supported MIME type when both suffix and payload agree."""

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


def detect_image_dimensions(mime_type: str, payload: bytes) -> tuple[int, int] | None:
    """Inspect supported image headers without decoding the full payload."""

    if mime_type == "image/png":
        return _detect_png_dimensions(payload)
    if mime_type == "image/gif":
        return _detect_gif_dimensions(payload)
    if mime_type == "image/jpeg":
        return _detect_jpeg_dimensions(payload)
    if mime_type == "image/webp":
        return _detect_webp_dimensions(payload)
    return None


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


def image_exceeds_inline_limits(
    encoded: bytes, dimensions: tuple[int, int] | None
) -> bool:
    """Return whether an encoded image exceeds the shared inline policy."""

    if len(encoded) >= MAX_INLINE_IMAGE_BASE64_BYTES:
        return True
    if dimensions is None:
        return False
    return max(dimensions) > MAX_INLINE_IMAGE_DIMENSION


async def prepare_image_payload(
    payload: bytes,
    *,
    mime_type: str,
    image_resizer: ReadImageResizer,
    resize_if_needed: bool,
) -> PreparedImagePayload:
    """Inspect, encode, and optionally resize an image payload asynchronously."""

    prepared = _inspect_image_payload(payload, mime_type=mime_type)
    if not resize_if_needed or not prepared.exceeds_inline_limits:
        return prepared
    if _image_resizer_is_unavailable(image_resizer):
        return replace(
            prepared,
            resize_attempted=True,
            resize_unavailable=True,
        )
    resize_result = await resolve_maybe_awaitable(
        image_resizer.resize_image(
            payload,
            mime_type=mime_type,
            dimensions=prepared.dimensions,
        )
    )
    return _apply_resize_result(prepared, resize_result)


def prepare_image_payload_sync(
    payload: bytes,
    *,
    mime_type: str,
    image_resizer: ReadImageResizer,
    resize_if_needed: bool,
) -> PreparedImagePayload:
    """Inspect, encode, and optionally resize with a synchronous resizer."""

    prepared = _inspect_image_payload(payload, mime_type=mime_type)
    if not resize_if_needed or not prepared.exceeds_inline_limits:
        return prepared
    if _image_resizer_is_unavailable(image_resizer):
        return replace(
            prepared,
            resize_attempted=True,
            resize_unavailable=True,
        )
    resize_result = image_resizer.resize_image(
        payload,
        mime_type=mime_type,
        dimensions=prepared.dimensions,
    )
    if inspect.isawaitable(resize_result):
        close = getattr(resize_result, "close", None)
        if callable(close):
            close()
        raise TypeError("synchronous image preparation requires a synchronous resizer")
    return _apply_resize_result(prepared, resize_result)


def _inspect_image_payload(
    payload: bytes,
    *,
    mime_type: str,
) -> PreparedImagePayload:
    dimensions = detect_image_dimensions(mime_type, payload)
    encoded = base64.b64encode(payload)
    return PreparedImagePayload(
        payload=payload,
        mime_type=mime_type,
        base64_payload=encoded,
        original_dimensions=dimensions,
        dimensions=dimensions,
        exceeds_inline_limits=image_exceeds_inline_limits(encoded, dimensions),
        resize_attempted=False,
        resize_succeeded=False,
        resize_unavailable=False,
        was_resized=False,
        dimension_note=None,
    )


def _image_resizer_is_unavailable(image_resizer: ReadImageResizer) -> bool:
    is_available = getattr(image_resizer, "is_available", None)
    return bool(callable(is_available) and not is_available())


def _apply_resize_result(
    prepared: PreparedImagePayload,
    resize_result: ReadImageResizeResult | None,
) -> PreparedImagePayload:
    if resize_result is None:
        return replace(prepared, resize_attempted=True)
    payload = resize_result.payload
    mime_type = resize_result.mime_type
    dimensions = resize_result.dimensions or detect_image_dimensions(mime_type, payload)
    original_dimensions = (
        resize_result.original_dimensions or prepared.original_dimensions
    )
    encoded = base64.b64encode(payload)
    return PreparedImagePayload(
        payload=payload,
        mime_type=mime_type,
        base64_payload=encoded,
        original_dimensions=original_dimensions,
        dimensions=dimensions,
        exceeds_inline_limits=image_exceeds_inline_limits(encoded, dimensions),
        resize_attempted=True,
        resize_succeeded=True,
        resize_unavailable=False,
        was_resized=resize_result.was_resized,
        dimension_note=format_image_dimension_note(
            original_dimensions=original_dimensions,
            dimensions=dimensions,
            was_resized=resize_result.was_resized,
        ),
    )


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

        image_ops: object | None
        try:
            from PIL import ImageOps as pillow_image_ops
        except ImportError:
            image_ops = None
        else:
            image_ops = pillow_image_ops

        try:
            with Image.open(BytesIO(payload)) as opened_image:
                image = _apply_exif_transpose(
                    opened_image,
                    image_ops=image_ops,
                )
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


def _apply_exif_transpose(
    image: ImageT,
    *,
    image_ops: object | None,
) -> ImageT:
    if image_ops is None:
        return image
    exif_transpose = getattr(image_ops, "exif_transpose", None)
    if not callable(exif_transpose):
        return image
    return cast(ImageT, exif_transpose(image))


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
        rgb_image.save(  # type: ignore[attr-defined]
            jpeg_buffer,
            format="JPEG",
            quality=quality,
            optimize=True,
        )
        candidates.append(("image/jpeg", jpeg_buffer.getvalue()))
    return candidates


def _pillow_lanczos_filter(image_module: object) -> Any:
    resampling = getattr(image_module, "Resampling", None)
    if resampling is not None:
        return resampling.LANCZOS
    return getattr(image_module, "LANCZOS", 1)


def format_image_dimension_note(
    *,
    original_dimensions: tuple[int, int] | None,
    dimensions: tuple[int, int] | None,
    was_resized: bool,
) -> str | None:
    """Describe resize coordinates for consumers that display image metadata."""

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


__all__ = [
    "DEFAULT_RESIZED_IMAGE_JPEG_QUALITIES",
    "MAX_INLINE_IMAGE_BASE64_BYTES",
    "MAX_INLINE_IMAGE_DIMENSION",
    "PillowReadImageResizer",
    "PreparedImagePayload",
    "ReadImageResizer",
    "ReadImageResizeResult",
    "detect_image_dimensions",
    "detect_supported_image_mime_type",
    "format_image_dimension_note",
    "image_exceeds_inline_limits",
    "prepare_image_payload",
    "prepare_image_payload_sync",
]
