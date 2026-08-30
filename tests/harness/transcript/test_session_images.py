from __future__ import annotations

import base64
from dataclasses import replace

import pytest

from loushang.ai.json_codec import serialize_message
from loushang.ai.types import (
    AssistantMessage,
    ImagePart,
    TextPart,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from loushang.harness.artifacts import SessionBlobStore
from loushang.harness.transcript import ApplicationMessage, SessionImagePart
from loushang.harness.transcript.model_input_blobs import (
    ModelInputBinaryProjectionError,
    SessionModelInputBlobCodec,
)
from loushang.harness.transcript.session_images import (
    SessionImageHydrationContext,
    externalize_session_message_images,
    hydrate_session_message_images,
)


def test_externalize_and_hydrate_session_image_round_trip(tmp_path) -> None:
    store = SessionBlobStore(tmp_path / "data", "image-session")
    payload = b"portable image bytes"
    message = UserMessage(
        role="user",
        content=[
            TextPart(type="text", text="inspect"),
            ImagePart(
                type="image",
                data=base64.b64encode(payload).decode("ascii"),
                mime_type="image/png",
            ),
        ],
        timestamp=1.0,
    )

    externalized = externalize_session_message_images(message, store, now=2.0)

    image = externalized.message.content[1]
    assert isinstance(image, SessionImagePart)
    assert image.blob.session_id == "image-session"
    assert store.read_bytes(image.blob) == payload
    hydrated = hydrate_session_message_images(externalized.message, store)
    assert isinstance(hydrated, UserMessage)
    restored = hydrated.content[1]
    assert isinstance(restored, ImagePart)
    assert base64.b64decode(restored.data) == payload


def test_durable_image_placeholder_cannot_cross_the_ai_wire_boundary(tmp_path) -> None:
    store = SessionBlobStore(tmp_path / "data", "image-session")
    reference = store.put_bytes(
        b"image",
        logical_name="images/user.png",
        kind="image",
        media_type="image/png",
    )
    message = UserMessage(
        role="user",
        content=[SessionImagePart(type="image", blob=reference)],  # type: ignore[list-item]
        timestamp=1.0,
    )

    with pytest.raises(ValueError, match="Unsupported content part"):
        serialize_message(message)


def test_externalize_images_is_atomic_when_a_later_image_is_invalid(tmp_path) -> None:
    store = SessionBlobStore(tmp_path / "data", "image-session")
    message = UserMessage(
        role="user",
        content=[
            ImagePart(type="image", data="aGVsbG8=", mime_type="image/png"),
            ImagePart(type="image", data="not base64", mime_type="image/png"),
        ],
        timestamp=1.0,
    )

    with pytest.raises(ValueError, match="canonical base64"):
        externalize_session_message_images(message, store)

    assert not store.root.exists()


def test_model_input_blob_projection_escapes_reserved_literal_shape(tmp_path) -> None:
    store = SessionBlobStore(tmp_path / "data", "image-session")
    payload = b"hello"
    encoded = base64.b64encode(payload).decode("ascii")
    store.put_bytes(
        payload,
        logical_name="images/user.png",
        kind="image",
        media_type="image/png",
    )
    original = {
        "image": encoded,
        "literal": {
            "$loushang.sessionBlob": {
                "version": 1,
                "blobId": "not-a-real-reference",
                "encoding": "base64",
                "prefix": "",
            }
        },
    }
    codec = SessionModelInputBlobCodec(store)

    projected = codec.externalize_mapping(original)

    # Arbitrary base64-looking strings are not images. Only the explicit
    # logical image shape (or AI-prepared binary metadata) can externalize one.
    assert projected.replacement_count == 1
    assert codec.hydrate_mapping(projected.value) == original


def test_model_input_blob_projection_versions_reserved_literal_without_images(
    tmp_path,
) -> None:
    store = SessionBlobStore(tmp_path / "data", "image-session")
    original = {"$loushang.sessionBlob": {"literal": True}}

    projected = SessionModelInputBlobCodec(store).externalize_mapping(original)

    assert projected.replacement_count == 1
    assert (
        SessionModelInputBlobCodec(store).hydrate_mapping(projected.value) == original
    )


def test_model_input_projection_uses_manifest_digest_when_object_is_missing(
    tmp_path,
) -> None:
    store = SessionBlobStore(tmp_path / "data", "image-session")
    reference = store.put_bytes(
        b"hello",
        logical_name="images/user.png",
        kind="image",
        media_type="image/png",
    )
    (store.objects_root / reference.blob_id).unlink()
    codec = SessionModelInputBlobCodec(store)

    projected = codec.externalize_mapping(
        {
            "part": {
                "type": "image",
                "data": "aGVsbG8=",
                "mimeType": "image/png",
            }
        }
    )

    assert projected.replacement_count == 1
    with pytest.raises(ModelInputBinaryProjectionError, match="integrity"):
        codec.hydrate_mapping(projected.value)


def test_model_input_projection_rejects_unowned_inline_image(tmp_path) -> None:
    codec = SessionModelInputBlobCodec(
        SessionBlobStore(tmp_path / "data", "image-session")
    )

    with pytest.raises(ModelInputBinaryProjectionError, match="not owned"):
        codec.externalize_mapping(
            {
                "part": {
                    "type": "image",
                    "data": "aGVsbG8=",
                    "mimeType": "image/png",
                }
            }
        )


def test_existing_session_image_must_be_owned_and_available(tmp_path) -> None:
    current = SessionBlobStore(tmp_path / "data", "current")
    foreign = SessionBlobStore(tmp_path / "data", "foreign").put_bytes(
        b"foreign",
        logical_name="images/foreign.png",
        kind="image",
        media_type="image/png",
    )
    message = UserMessage(
        role="user",
        content=[SessionImagePart(type="image", blob=foreign)],
        timestamp=1.0,
    )

    with pytest.raises(ValueError, match="another Session authority"):
        externalize_session_message_images(message, current)

    local = current.put_bytes(
        b"local",
        logical_name="images/local.png",
        kind="image",
        media_type="image/png",
    )
    (current.objects_root / local.blob_id).unlink()
    with pytest.raises((OSError, ValueError)):
        externalize_session_message_images(
            replace(message, content=[SessionImagePart(type="image", blob=local)]),
            current,
        )


def test_image_base64_requires_canonical_pad_bits(tmp_path) -> None:
    store = SessionBlobStore(tmp_path / "data", "image-session")
    message = UserMessage(
        role="user",
        content=[ImagePart(type="image", data="AB==", mime_type="image/png")],
        timestamp=1.0,
    )

    with pytest.raises(ValueError, match="canonical base64"):
        externalize_session_message_images(message, store)


def test_hydration_deduplicates_content_and_enforces_one_context_budget(
    tmp_path,
) -> None:
    store = SessionBlobStore(tmp_path / "data", "image-session")
    first = store.put_bytes(
        b"same",
        logical_name="images/first.png",
        kind="image",
        media_type="image/png",
    )
    duplicate = store.put_bytes(
        b"same",
        logical_name="images/second.png",
        kind="image",
        media_type="image/png",
    )
    other = store.put_bytes(
        b"next",
        logical_name="images/third.png",
        kind="image",
        media_type="image/png",
    )
    hydration = SessionImageHydrationContext(max_total_bytes=4)
    message = UserMessage(
        role="user",
        content=[
            SessionImagePart(type="image", blob=first),
            SessionImagePart(type="image", blob=duplicate),
            SessionImagePart(type="image", blob=other),
        ],
        timestamp=1.0,
    )

    hydrated = hydrate_session_message_images(message, store, hydration=hydration)

    assert hydration.total_bytes == 4
    assert isinstance(hydrated, UserMessage)
    assert isinstance(hydrated.content[0], ImagePart)
    assert isinstance(hydrated.content[1], ImagePart)
    assert isinstance(hydrated.content[2], TextPart)
    assert "context budget exceeded" in hydrated.content[2].text


def test_application_message_images_use_the_same_durable_boundary(tmp_path) -> None:
    store = SessionBlobStore(tmp_path / "data", "application-session")
    message = ApplicationMessage(
        application_message_id="application-1",
        custom_type="clipboard",
        content=[ImagePart(type="image", data="aGVsbG8=", mime_type="image/png")],
        timestamp=1.0,
    )

    externalized = externalize_session_message_images(message, store)

    assert isinstance(externalized.message, ApplicationMessage)
    assert isinstance(externalized.message.content[0], SessionImagePart)
    hydrated = hydrate_session_message_images(externalized.message, store)
    assert isinstance(hydrated, ApplicationMessage)
    assert isinstance(hydrated.content[0], ImagePart)
    assert hydrated.content[0].data == "aGVsbG8="


def test_hydrate_missing_image_degrades_to_portable_marker(tmp_path) -> None:
    store = SessionBlobStore(tmp_path / "data", "image-session")
    externalized = externalize_session_message_images(
        UserMessage(
            role="user",
            content=[ImagePart(type="image", data="aGVsbG8=", mime_type="image/png")],
            timestamp=1.0,
        ),
        store,
    )
    image = externalized.message.content[0]
    assert isinstance(image, SessionImagePart)
    (store.objects_root / image.blob.blob_id).unlink()

    hydrated = hydrate_session_message_images(externalized.message, store)

    assert isinstance(hydrated, UserMessage)
    marker = hydrated.content[0]
    assert isinstance(marker, TextPart)
    assert marker.text == f"[Image unavailable: {image.blob.logical_name}]"


@pytest.mark.parametrize(
    "message,source",
    [
        (
            ToolResultMessage(
                role="toolResult",
                tool_call_id="screenshot-1",
                tool_name="screenshot",
                content=[
                    ImagePart(type="image", data="aGVsbG8=", mime_type="image/png")
                ],
                is_error=False,
                timestamp=1.0,
            ),
            "transcript-image:tool-result",
        ),
        (
            AssistantMessage(
                role="assistant",
                content=[
                    ImagePart(type="image", data="aGVsbG8=", mime_type="image/png")
                ],
                api="responses",
                provider="faux",
                endpoint="responses",
                model="image-model",
                response_id="response-1",
                usage=Usage(0, 0, 0, 0, 0, None),
                stop_reason="stop",
                error_message=None,
                timestamp=1.0,
            ),
            "transcript-image:assistant",
        ),
    ],
)
def test_screenshot_and_generated_images_use_the_same_session_boundary(
    tmp_path,
    message,
    source,
) -> None:
    store = SessionBlobStore(tmp_path / "data", "image-session")

    externalized = externalize_session_message_images(message, store)

    image = externalized.message.content[0]
    assert isinstance(image, SessionImagePart)
    assert image.blob.source == source
    assert store.read_bytes(image.blob) == b"hello"
