from __future__ import annotations

import asyncio
import base64
import sys
import tomllib
from pathlib import Path
from types import ModuleType

from loushang.harness.tools.workspace.image_payload import (
    PillowReadImageResizer,
    ReadImageResizeResult,
    detect_image_dimensions,
    detect_supported_image_mime_type,
    format_image_dimension_note,
    image_exceeds_inline_limits,
    prepare_image_payload,
    prepare_image_payload_sync,
)


def _png_header(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
    )


class _FakeImage:
    mode = "RGB"

    def __init__(self, width: int, height: int, *, byte_scale: int = 1) -> None:
        self.width = width
        self.height = height
        self.byte_scale = byte_scale
        self.closed = False

    def __enter__(self) -> "_FakeImage":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def close(self) -> None:
        self.closed = True

    def copy(self) -> "_FakeImage":
        return _FakeImage(self.width, self.height, byte_scale=self.byte_scale)

    def convert(self, mode: str) -> "_FakeImage":
        converted = self.copy()
        converted.mode = mode
        return converted

    def thumbnail(self, size: tuple[int, int], resample: object = None) -> None:
        del resample
        max_width, max_height = size
        scale = min(max_width / self.width, max_height / self.height, 1)
        self.width = max(1, round(self.width * scale))
        self.height = max(1, round(self.height * scale))

    def save(
        self, buffer, *, format: str, quality: int | None = None, optimize: bool = False
    ) -> None:
        del format, quality, optimize
        buffer.write(b"x" * (self.width * self.height * self.byte_scale))


def _install_fake_pillow(
    monkeypatch, image: _FakeImage, *, transpose_to: _FakeImage | None = None
) -> list[_FakeImage]:
    opened_images: list[_FakeImage] = []
    pil_module = ModuleType("PIL")
    image_module = ModuleType("PIL.Image")
    image_ops_module = ModuleType("PIL.ImageOps")

    class Resampling:
        LANCZOS = object()

    def open_image(_payload) -> _FakeImage:
        opened_images.append(image)
        return image

    def exif_transpose(opened: _FakeImage) -> _FakeImage:
        return transpose_to if transpose_to is not None else opened

    image_module.open = open_image  # type: ignore[attr-defined]
    image_module.Resampling = Resampling  # type: ignore[attr-defined]
    image_ops_module.exif_transpose = exif_transpose  # type: ignore[attr-defined]
    pil_module.Image = image_module  # type: ignore[attr-defined]
    pil_module.ImageOps = image_ops_module  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "PIL", pil_module)
    monkeypatch.setitem(sys.modules, "PIL.Image", image_module)
    monkeypatch.setitem(sys.modules, "PIL.ImageOps", image_ops_module)
    return opened_images


def test_detect_supported_image_mime_type_requires_matching_suffix_and_magic() -> None:
    cases = (
        (Path("photo.jpg"), b"\xff\xd8\xffpayload", "image/jpeg"),
        (Path("photo.png"), b"\x89PNG\r\n\x1a\npayload", "image/png"),
        (Path("photo.gif"), b"GIF89apayload", "image/gif"),
        (Path("photo.webp"), b"RIFF\x00\x00\x00\x00WEBP", "image/webp"),
    )

    for path, payload, expected in cases:
        assert detect_supported_image_mime_type(path, payload) == expected
    assert (
        detect_supported_image_mime_type(Path("mislabeled.png"), b"\xff\xd8\xffpayload")
        is None
    )


def test_detect_image_dimensions_and_inline_limit_share_one_policy() -> None:
    png_payload = _png_header(3, 5)

    assert detect_image_dimensions("image/png", png_payload) == (3, 5)
    assert image_exceeds_inline_limits(b"encoded", (2000, 1)) is False
    assert image_exceeds_inline_limits(b"encoded", (2001, 1)) is True


def test_detect_image_dimensions_supports_all_owned_header_formats() -> None:
    jpeg_payload = (
        b"\xff\xd8\xff\xc0\x00\x07\x08"
        + (11).to_bytes(2, "big")
        + (13).to_bytes(2, "big")
    )
    gif_payload = b"GIF89a" + (17).to_bytes(2, "little") + (19).to_bytes(2, "little")
    webp_payload = (
        b"RIFF\x00\x00\x00\x00WEBPVP8X"
        + (b"\x00" * 8)
        + (22).to_bytes(3, "little")
        + (28).to_bytes(3, "little")
    )

    assert detect_image_dimensions("image/jpeg", jpeg_payload) == (13, 11)
    assert detect_image_dimensions("image/gif", gif_payload) == (17, 19)
    assert detect_image_dimensions("image/webp", webp_payload) == (23, 29)


def test_prepare_image_payload_sync_owns_inspection_and_encoding() -> None:
    payload = _png_header(3, 5)

    class FailingIfCalledResizer:
        def resize_image(self, *args, **kwargs):
            raise AssertionError("in-limit image must not be resized")

    prepared = prepare_image_payload_sync(
        payload,
        mime_type="image/png",
        image_resizer=FailingIfCalledResizer(),
        resize_if_needed=True,
    )

    assert prepared.payload == payload
    assert prepared.base64_payload == base64.b64encode(payload)
    assert prepared.mime_type == "image/png"
    assert prepared.original_dimensions == (3, 5)
    assert prepared.dimensions == (3, 5)
    assert prepared.exceeds_inline_limits is False
    assert prepared.resize_attempted is False
    assert prepared.resize_succeeded is False
    assert prepared.resize_unavailable is False
    assert prepared.was_resized is False
    assert prepared.dimension_note is None


def test_prepare_image_payload_sync_recomputes_resized_payload_state() -> None:
    payload = _png_header(3001, 10)
    resized_payload = _png_header(2000, 7)

    class SyncResizer:
        def resize_image(
            self,
            source: bytes,
            *,
            mime_type: str,
            dimensions: tuple[int, int] | None,
        ) -> ReadImageResizeResult:
            assert (source, mime_type, dimensions) == (
                payload,
                "image/png",
                (3001, 10),
            )
            return ReadImageResizeResult(
                payload=resized_payload,
                mime_type="image/png",
                original_dimensions=(3001, 10),
                dimensions=(2000, 7),
                was_resized=True,
            )

    prepared = prepare_image_payload_sync(
        payload,
        mime_type="image/png",
        image_resizer=SyncResizer(),
        resize_if_needed=True,
    )

    assert prepared.payload == resized_payload
    assert prepared.base64_payload == base64.b64encode(resized_payload)
    assert prepared.original_dimensions == (3001, 10)
    assert prepared.dimensions == (2000, 7)
    assert prepared.exceeds_inline_limits is False
    assert prepared.resize_attempted is True
    assert prepared.resize_succeeded is True
    assert prepared.resize_unavailable is False
    assert prepared.was_resized is True
    assert prepared.dimension_note == (
        "[Image: original 3001x10, displayed at 2000x7. "
        "Multiply coordinates by 1.50 to map to original image.]"
    )


def test_prepare_image_payload_sync_reports_unavailable_resizer() -> None:
    payload = _png_header(3001, 10)

    class UnavailableResizer:
        def is_available(self) -> bool:
            return False

        def resize_image(self, *args, **kwargs):
            raise AssertionError("unavailable resizer must not be called")

    prepared = prepare_image_payload_sync(
        payload,
        mime_type="image/png",
        image_resizer=UnavailableResizer(),
        resize_if_needed=True,
    )

    assert prepared.payload == payload
    assert prepared.exceeds_inline_limits is True
    assert prepared.resize_attempted is True
    assert prepared.resize_succeeded is False
    assert prepared.resize_unavailable is True


def test_prepare_image_payload_sync_reports_failed_resize() -> None:
    payload = _png_header(3001, 10)

    class FailingResizer:
        def resize_image(
            self,
            source: bytes,
            *,
            mime_type: str,
            dimensions: tuple[int, int] | None,
        ) -> None:
            assert (source, mime_type, dimensions) == (
                payload,
                "image/png",
                (3001, 10),
            )
            return None

    prepared = prepare_image_payload_sync(
        payload,
        mime_type="image/png",
        image_resizer=FailingResizer(),
        resize_if_needed=True,
    )

    assert prepared.payload == payload
    assert prepared.exceeds_inline_limits is True
    assert prepared.resize_attempted is True
    assert prepared.resize_succeeded is False
    assert prepared.resize_unavailable is False


def test_prepare_image_payload_supports_async_resizer() -> None:
    payload = _png_header(3001, 10)
    resized_payload = _png_header(2000, 7)

    class AsyncResizer:
        async def resize_image(
            self,
            source: bytes,
            *,
            mime_type: str,
            dimensions: tuple[int, int] | None,
        ) -> ReadImageResizeResult:
            assert (source, mime_type, dimensions) == (
                payload,
                "image/png",
                (3001, 10),
            )
            return ReadImageResizeResult(
                payload=resized_payload,
                mime_type="image/png",
                original_dimensions=(3001, 10),
                dimensions=(2000, 7),
                was_resized=True,
            )

    prepared = asyncio.run(
        prepare_image_payload(
            payload,
            mime_type="image/png",
            image_resizer=AsyncResizer(),
            resize_if_needed=True,
        )
    )

    assert prepared.payload == resized_payload
    assert prepared.resize_attempted is True
    assert prepared.resize_succeeded is True
    assert prepared.was_resized is True


def test_workspace_facade_and_legacy_read_module_reexport_owner_type() -> None:
    from loushang.harness.tools.workspace import (
        PillowReadImageResizer as facade_resizer,
    )
    from loushang.harness.tools.workspace.read import (
        PillowReadImageResizer as legacy_resizer,
    )
    from loushang.harness.tools.workspace.read import (
        detect_image_dimensions as legacy_detect_dimensions,
    )
    from loushang.harness.tools.workspace.read import (
        format_image_dimension_note as legacy_dimension_note,
    )
    from loushang.harness.tools.workspace.read import (
        image_exceeds_inline_limits as legacy_inline_limits,
    )

    assert facade_resizer is PillowReadImageResizer
    assert legacy_resizer is PillowReadImageResizer
    assert legacy_detect_dimensions is detect_image_dimensions
    assert legacy_dimension_note is format_image_dimension_note
    assert legacy_inline_limits is image_exceeds_inline_limits


def test_pillow_resizer_progressively_reduces_dimensions_until_payload_fits(
    monkeypatch,
) -> None:
    _install_fake_pillow(monkeypatch, _FakeImage(16, 16))
    resizer = PillowReadImageResizer(
        max_width=8,
        max_height=8,
        max_base64_bytes=20,
        jpeg_qualities=(80,),
    )

    result = resizer.resize_image(
        b"payload", mime_type="image/png", dimensions=(16, 16)
    )

    assert result is not None
    assert result.original_dimensions == (16, 16)
    assert result.dimensions == (3, 3)
    assert result.was_resized is True


def test_pillow_resizer_applies_exif_transpose_before_resizing(monkeypatch) -> None:
    opened = _FakeImage(16, 8)
    transposed = _FakeImage(8, 16)
    _install_fake_pillow(monkeypatch, opened, transpose_to=transposed)
    resizer = PillowReadImageResizer(
        max_width=8,
        max_height=8,
        max_base64_bytes=200,
        jpeg_qualities=(80,),
    )

    result = resizer.resize_image(
        b"payload", mime_type="image/jpeg", dimensions=(16, 8)
    )

    assert result is not None
    assert result.original_dimensions == (8, 16)
    assert result.dimensions == (4, 8)
    assert result.was_resized is True


def test_default_pillow_resizer_backend_is_available_from_runtime_dependency() -> None:
    assert PillowReadImageResizer().is_available() is True


def test_pillow_is_declared_as_runtime_dependency() -> None:
    project_root = Path(__file__).resolve().parents[3]
    pyproject = tomllib.loads(
        (project_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    dependencies = pyproject["project"]["dependencies"]

    assert any(dependency.lower().startswith("pillow") for dependency in dependencies)
