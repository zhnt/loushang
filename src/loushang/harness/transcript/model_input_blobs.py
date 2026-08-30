"""Pathless Session-blob projection for durable Model Input snapshots."""

from __future__ import annotations

import base64
import binascii
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from loushang.ai.prepared_request import PreparedRequestBinaryField
from loushang.foundation.json import JSONValue, require_json_value
from loushang.harness.artifacts import SessionBlobRef, SessionBlobStore

MODEL_INPUT_BINARY_PROJECTION_VERSION = 1
MODEL_INPUT_BINARY_MAX_BYTES = 64 * 1024 * 1024
_BLOB_MARKER = "$loushang.sessionBlob"
_LITERAL_MARKER = "$loushang.literal"
_RESERVED_MARKERS = frozenset({_BLOB_MARKER, _LITERAL_MARKER})


class ModelInputBinaryProjectionError(ValueError):
    """Raised when a projected Model Input blob marker cannot be restored."""


@dataclass(frozen=True, slots=True)
class ProjectedModelInputMapping:
    value: dict[str, JSONValue]
    replacement_count: int


class SessionModelInputBlobCodec:
    """Replace known image encodings with content-addressed Session markers.

    The codec is deliberately attached at the durable transcript edge. AI and
    provider adapters continue to receive their ordinary inline image shapes;
    physical storage authority never crosses into those layers.
    """

    def __init__(
        self,
        store: SessionBlobStore,
        *,
        references: Sequence[SessionBlobRef] | None = None,
    ) -> None:
        if not isinstance(store, SessionBlobStore):
            raise TypeError("Model Input blob codec requires SessionBlobStore")
        self._store = store
        self._references = tuple(references) if references is not None else None

    def externalize_mapping(
        self,
        value: Mapping[str, JSONValue],
        *,
        binary_fields: Sequence[PreparedRequestBinaryField] | None = None,
    ) -> ProjectedModelInputMapping:
        references = self._image_references()
        prepared_fields = (
            None
            if binary_fields is None
            else _prepared_binary_fields(dict(value), binary_fields)
        )
        projected, count = _externalize_value(
            dict(value),
            references,
            path=(),
            prepared_fields=prepared_fields,
            max_bytes=min(
                self._store.policy.max_blob_bytes,
                MODEL_INPUT_BINARY_MAX_BYTES,
            ),
        )
        if not isinstance(projected, dict):  # pragma: no cover - root is a mapping
            raise AssertionError("projected Model Input root changed shape")
        return ProjectedModelInputMapping(
            cast(dict[str, JSONValue], projected),
            count,
        )

    def hydrate_mapping(
        self,
        value: Mapping[str, JSONValue],
    ) -> dict[str, JSONValue]:
        hydrated = _hydrate_value(dict(value), self._store)
        if not isinstance(hydrated, dict):  # pragma: no cover - root is a mapping
            raise ModelInputBinaryProjectionError(
                "projected Model Input root changed shape"
            )
        return cast(dict[str, JSONValue], hydrated)

    def _image_references(self) -> dict[str, tuple[SessionBlobRef, ...]]:
        """Index image metadata by digest without materializing their bytes."""

        grouped: dict[str, list[SessionBlobRef]] = {}
        selected = self._store.records if self._references is None else self._references
        for reference in selected:
            if reference.kind != "image" or not reference.media_type.startswith(
                "image/"
            ):
                continue
            if reference.session_id != self._store.session_id:
                raise ModelInputBinaryProjectionError(
                    "Model Input image belongs to another Session authority"
                )
            candidates = grouped.setdefault(reference.sha256, [])
            if reference not in candidates:
                candidates.append(reference)
        return {digest: tuple(candidates) for digest, candidates in grouped.items()}


def _externalize_value(
    value: JSONValue,
    references: Mapping[str, tuple[SessionBlobRef, ...]],
    *,
    path: tuple[str | int, ...],
    prepared_fields: Mapping[tuple[str | int, ...], PreparedRequestBinaryField] | None,
    max_bytes: int,
) -> tuple[JSONValue, int]:
    if isinstance(value, str):
        field = prepared_fields.get(path) if prepared_fields is not None else None
        if field is not None:
            encoded, prefix = _prepared_binary_encoding(value, field)
            reference = _reference_for_encoding(
                encoded,
                references,
                max_bytes=max_bytes,
                required=True,
                expected_media_type=field.media_type,
            )
            if reference is None:  # pragma: no cover - required=True
                raise AssertionError("required Model Input image was not resolved")
            return _blob_marker(reference, prefix=prefix), 1
        return value, 0
    if isinstance(value, list):
        result: list[JSONValue] = []
        count = 0
        for index, item in enumerate(value):
            projected_item, item_count = _externalize_value(
                item,
                references,
                path=(*path, index),
                prepared_fields=prepared_fields,
                max_bytes=max_bytes,
            )
            result.append(projected_item)
            count += item_count
        return result, count
    if isinstance(value, dict):
        projected_mapping: dict[str, JSONValue] = {}
        count = 0
        image_data = (
            _logical_image_data_field(value) if prepared_fields is None else None
        )
        for name, item in value.items():
            child: JSONValue
            if image_data is not None and name == image_data[0]:
                if not isinstance(item, str):
                    raise ModelInputBinaryProjectionError(
                        "Model Input image data must be a base64 string"
                    )
                reference = _reference_for_encoding(
                    item,
                    references,
                    max_bytes=max_bytes,
                    required=True,
                    expected_media_type=image_data[1],
                )
                if reference is None:  # pragma: no cover - required=True
                    raise AssertionError("required Model Input image was not resolved")
                child, child_count = _blob_marker(reference, prefix=""), 1
            else:
                child, child_count = _externalize_value(
                    item,
                    references,
                    path=(*path, name),
                    prepared_fields=prepared_fields,
                    max_bytes=max_bytes,
                )
            projected_mapping[name] = child
            count += child_count
        if len(value) == 1 and next(iter(value), None) in _RESERVED_MARKERS:
            return {_LITERAL_MARKER: projected_mapping}, count + 1
        return projected_mapping, count
    return value, 0


def _logical_image_data_field(
    value: Mapping[str, JSONValue],
) -> tuple[str, str] | None:
    data = value.get("data")
    if not isinstance(data, str):
        return None
    media_type = value.get("mimeType")
    if not isinstance(media_type, str) or not media_type.startswith("image/"):
        return None
    if value.get("type") != "image":
        return None
    return "data", media_type


def _prepared_binary_fields(
    value: Mapping[str, JSONValue],
    fields: Sequence[PreparedRequestBinaryField],
) -> dict[tuple[str | int, ...], PreparedRequestBinaryField]:
    selected: dict[tuple[str | int, ...], PreparedRequestBinaryField] = {}
    for field in fields:
        if not isinstance(field, PreparedRequestBinaryField):
            raise TypeError("prepared binary fields must use the AI contract")
        if field.path in selected:
            raise ModelInputBinaryProjectionError(
                "prepared Model Input binary field paths must be unique"
            )
        current: object = value
        for component in field.path:
            if isinstance(component, str) and isinstance(current, Mapping):
                current = current.get(component)
            elif (
                isinstance(component, int)
                and isinstance(current, list)
                and component < len(current)
            ):
                current = current[component]
            else:
                raise ModelInputBinaryProjectionError(
                    "prepared Model Input binary field path is invalid"
                )
        if not isinstance(current, str):
            raise ModelInputBinaryProjectionError(
                "prepared Model Input binary field must resolve to a string"
            )
        selected[field.path] = field
    return selected


def _prepared_binary_encoding(
    value: str,
    field: PreparedRequestBinaryField,
) -> tuple[str, str]:
    if field.encoding == "base64":
        return value, ""
    prefix = f"data:{field.media_type};base64,"
    if not value.startswith(prefix):
        raise ModelInputBinaryProjectionError(
            "prepared Model Input data URL does not match its binary metadata"
        )
    return value.removeprefix(prefix), prefix


def _reference_for_encoding(
    encoded: str,
    references: Mapping[str, tuple[SessionBlobRef, ...]],
    *,
    max_bytes: int,
    required: bool,
    expected_media_type: str | None = None,
) -> SessionBlobRef | None:
    if len(encoded) > ((max_bytes + 2) // 3) * 4 + 4:
        if required:
            raise ModelInputBinaryProjectionError(
                "Model Input image exceeds the Session blob size limit"
            )
        return None
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        if required:
            raise ModelInputBinaryProjectionError(
                "Model Input image data is not canonical base64"
            )
        return None
    if base64.b64encode(payload).decode("ascii") != encoded:
        if required:
            raise ModelInputBinaryProjectionError(
                "Model Input image data is not canonical base64"
            )
        return None
    candidates = references.get(hashlib.sha256(payload).hexdigest(), ())
    reference = next(
        (
            candidate
            for candidate in candidates
            if candidate.size_bytes == len(payload)
            and (
                expected_media_type is None
                or candidate.media_type == expected_media_type
            )
        ),
        None,
    )
    if reference is None:
        if required:
            raise ModelInputBinaryProjectionError(
                "Model Input image is not owned by this Session"
            )
        return None
    return reference


def _blob_marker(reference: SessionBlobRef, *, prefix: str) -> dict[str, JSONValue]:
    return {
        _BLOB_MARKER: {
            "version": MODEL_INPUT_BINARY_PROJECTION_VERSION,
            "blobId": reference.blob_id,
            "encoding": "base64",
            "prefix": prefix,
        }
    }


def _hydrate_value(value: JSONValue, store: SessionBlobStore) -> JSONValue:
    if isinstance(value, list):
        return [_hydrate_value(item, store) for item in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {_LITERAL_MARKER}:
        literal = value[_LITERAL_MARKER]
        if not isinstance(literal, dict):
            raise ModelInputBinaryProjectionError(
                "Model Input literal marker is malformed"
            )
        # Decode children but deliberately do not interpret the restored root.
        return {name: _hydrate_value(item, store) for name, item in literal.items()}
    if set(value) == {_BLOB_MARKER}:
        return _hydrate_blob_marker(value[_BLOB_MARKER], store)
    return {name: _hydrate_value(item, store) for name, item in value.items()}


def _hydrate_blob_marker(value: JSONValue, store: SessionBlobStore) -> str:
    if not isinstance(value, dict) or set(value) != {
        "version",
        "blobId",
        "encoding",
        "prefix",
    }:
        raise ModelInputBinaryProjectionError("Model Input blob marker is malformed")
    if (
        value["version"] != MODEL_INPUT_BINARY_PROJECTION_VERSION
        or value["encoding"] != "base64"
        or not isinstance(value["blobId"], str)
        or not isinstance(value["prefix"], str)
    ):
        raise ModelInputBinaryProjectionError("Model Input blob marker is invalid")
    matches = [
        reference
        for reference in store.records
        if reference.blob_id == value["blobId"]
        and reference.kind == "image"
        and reference.media_type.startswith("image/")
    ]
    if not matches:
        raise ModelInputBinaryProjectionError(
            "Model Input image blob is unavailable in this Session"
        )
    try:
        payload = store.read_bytes(matches[0])
    except (OSError, ValueError) as error:
        raise ModelInputBinaryProjectionError(
            "Model Input image blob failed integrity verification"
        ) from error
    encoded = base64.b64encode(payload).decode("ascii")
    return cast(str, require_json_value(value["prefix"] + encoded))


__all__ = [
    "MODEL_INPUT_BINARY_PROJECTION_VERSION",
    "MODEL_INPUT_BINARY_MAX_BYTES",
    "ModelInputBinaryProjectionError",
    "ProjectedModelInputMapping",
    "SessionModelInputBlobCodec",
]
