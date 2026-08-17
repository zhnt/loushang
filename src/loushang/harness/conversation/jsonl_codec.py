from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar, cast

from loushang.foundation.json import JSONValue, JsonValueError, require_json_mapping
from loushang.foundation.json import require_json_value as snapshot_json_value
from loushang.harness.conversation.types import (
    ConversationHeader,
    ConversationRecord,
    OpaquePayload,
)
from loushang.harness.journal import JournalCodecError

PayloadT = TypeVar("PayloadT")

CONVERSATION_ENVELOPE_TYPE = "conversation"
CONVERSATION_RECORD_TYPE = "record"
MIN_CONVERSATION_FORMAT_VERSION = 1
CURRENT_CONVERSATION_FORMAT_VERSION = 1


class ConversationPayloadCodec(Protocol, Generic[PayloadT]):
    """Encode and decode one version of a conversation payload kind."""

    def encode_payload(self, payload: PayloadT) -> JSONValue: ...

    def decode_payload(self, value: JSONValue) -> PayloadT: ...


@dataclass(frozen=True)
class FunctionalConversationPayloadCodec(Generic[PayloadT]):
    encoder: Callable[[PayloadT], JSONValue]
    decoder: Callable[[JSONValue], PayloadT]

    def encode_payload(self, payload: PayloadT) -> JSONValue:
        return self.encoder(payload)

    def decode_payload(self, value: JSONValue) -> PayloadT:
        return self.decoder(value)


class ConversationPayloadCodecRegistry:
    """Versioned payload codecs used by the Conversation JSONL envelope."""

    def __init__(self) -> None:
        self._codecs: dict[
            tuple[str, int],
            ConversationPayloadCodec[object],
        ] = {}
        self._required_kinds: set[str] = set()

    def register(
        self,
        kind: str,
        payload_version: int,
        codec: ConversationPayloadCodec[PayloadT],
    ) -> None:
        key = _payload_key(kind, payload_version)
        if key in self._codecs:
            raise ValueError(
                "conversation payload codec is already registered for "
                f"{kind!r} version {payload_version}"
            )
        if not callable(getattr(codec, "encode_payload", None)) or not callable(
            getattr(codec, "decode_payload", None)
        ):
            raise TypeError(
                "conversation payload codec must provide encode_payload and "
                "decode_payload"
            )
        self._codecs[key] = cast(ConversationPayloadCodec[object], codec)

    @property
    def registered_keys(self) -> tuple[tuple[str, int], ...]:
        return tuple(sorted(self._codecs))

    @property
    def required_kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._required_kinds))

    def require_known_payload_versions(self, *kinds: str) -> None:
        """Fail closed when one core kind uses an unregistered version."""

        if not kinds:
            raise ValueError("required conversation payload kinds must not be empty")
        for kind in kinds:
            _require_payload_kind(kind)
            self._required_kinds.add(kind)

    def encode(
        self,
        kind: str,
        payload_version: int,
        payload: object,
    ) -> JSONValue:
        key = _payload_key(kind, payload_version)
        codec = self._codecs.get(key)
        if codec is None:
            if kind in self._required_kinds:
                raise JournalCodecError(
                    "Required conversation payload version is unsupported for "
                    f"{kind!r} version {payload_version}",
                    code="unsupported_required_payload_version",
                )
            if isinstance(payload, OpaquePayload):
                return payload.value
            raise JournalCodecError(
                "No conversation payload codec is registered for "
                f"{kind!r} version {payload_version}",
                code="unregistered_payload_codec",
            )
        if isinstance(payload, OpaquePayload):
            return payload.value
        try:
            encoded = codec.encode_payload(payload)
            return snapshot_json_value(
                encoded,
                name=f"conversation payload {kind!r} version {payload_version}",
            )
        except Exception as exc:
            raise JournalCodecError(
                "Conversation payload could not be encoded for "
                f"{kind!r} version {payload_version}",
                code="invalid_known_payload",
            ) from exc

    def decode(
        self,
        kind: str,
        payload_version: int,
        value: object,
    ) -> object:
        key = _payload_key(kind, payload_version)
        try:
            snapshot = snapshot_json_value(
                value,
                name=f"conversation payload {kind!r} version {payload_version}",
            )
        except JsonValueError as exc:
            raise JournalCodecError(
                "Conversation payload is outside strict JSON",
                code="invalid_record_payload",
            ) from exc
        codec = self._codecs.get(key)
        if codec is None:
            if kind in self._required_kinds:
                raise JournalCodecError(
                    "Required conversation payload version is unsupported for "
                    f"{kind!r} version {payload_version}",
                    code="unsupported_required_payload_version",
                )
            return OpaquePayload(snapshot)
        try:
            return codec.decode_payload(snapshot)
        except Exception as exc:
            raise JournalCodecError(
                "Conversation payload could not be decoded for "
                f"{kind!r} version {payload_version}",
                code="invalid_known_payload",
            ) from exc


class ConversationJsonlHeaderCodec:
    """Codec for every supported Conversation JSONL header version."""

    def encode_header(self, header: ConversationHeader) -> Mapping[str, object]:
        _require_supported_format_version(header.version)
        return {
            "type": CONVERSATION_ENVELOPE_TYPE,
            "conversationId": header.conversation_id,
            "version": header.version,
            "createdAt": header.created_at,
            "parentConversationId": header.parent_conversation_id,
            "metadata": dict(header.metadata),
        }

    def decode_header(self, value: Mapping[str, object]) -> ConversationHeader:
        envelope = _require_envelope(value, name="conversation header")
        _require_discriminator(
            envelope,
            expected=CONVERSATION_ENVELOPE_TYPE,
            name="conversation header",
        )
        try:
            header = ConversationHeader(
                conversation_id=_require_text_field(envelope, "conversationId"),
                version=_require_positive_integer_field(envelope, "version"),
                created_at=_require_text_field(envelope, "createdAt"),
                parent_conversation_id=_require_optional_text_field(
                    envelope,
                    "parentConversationId",
                ),
                metadata=_require_metadata_field(envelope),
            )
            _require_supported_format_version(header.version)
            return header
        except JournalCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise JournalCodecError(
                "Conversation header envelope is invalid",
                code="invalid_conversation_header",
            ) from exc


class ConversationJsonlRecordCodec:
    """Conversation JSONL record envelope backed by versioned payload codecs."""

    def __init__(self, registry: ConversationPayloadCodecRegistry) -> None:
        if not isinstance(registry, ConversationPayloadCodecRegistry):
            raise TypeError("registry must be a ConversationPayloadCodecRegistry")
        self._registry = registry

    @property
    def registry(self) -> ConversationPayloadCodecRegistry:
        return self._registry

    def encode_record(
        self,
        record: ConversationRecord[PayloadT],
    ) -> Mapping[str, object]:
        return {
            "type": CONVERSATION_RECORD_TYPE,
            "recordId": record.record_id,
            "parentId": record.parent_id,
            "kind": record.kind,
            "payloadVersion": record.payload_version,
            "createdAt": record.created_at,
            "payload": self._registry.encode(
                record.kind,
                record.payload_version,
                record.payload,
            ),
            "metadata": dict(record.metadata),
        }

    def decode_record(
        self,
        value: Mapping[str, object],
    ) -> ConversationRecord[object]:
        envelope = _require_envelope(value, name="conversation record")
        _require_discriminator(
            envelope,
            expected=CONVERSATION_RECORD_TYPE,
            name="conversation record",
        )
        try:
            kind = _require_text_field(envelope, "kind")
            payload_version = _require_positive_integer_field(
                envelope,
                "payloadVersion",
            )
            return ConversationRecord(
                record_id=_require_text_field(envelope, "recordId"),
                parent_id=_require_optional_text_field(envelope, "parentId"),
                kind=kind,
                payload_version=payload_version,
                created_at=_require_text_field(envelope, "createdAt"),
                payload=self._registry.decode(
                    kind,
                    payload_version,
                    _require_field(envelope, "payload"),
                ),
                metadata=_require_metadata_field(envelope),
            )
        except JournalCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise JournalCodecError(
                "Conversation record envelope is invalid",
                code="invalid_conversation_record",
            ) from exc


def _payload_key(kind: str, payload_version: int) -> tuple[str, int]:
    _require_payload_kind(kind)
    if isinstance(payload_version, bool) or not isinstance(payload_version, int):
        raise TypeError("conversation payload version must be an integer")
    if payload_version < 1:
        raise ValueError("conversation payload version must be positive")
    return kind, payload_version


def _require_payload_kind(kind: object) -> str:
    if not isinstance(kind, str) or not kind.strip():
        raise ValueError("conversation payload kind must be a non-empty string")
    return kind


def _require_supported_format_version(version: int) -> None:
    if (
        version < MIN_CONVERSATION_FORMAT_VERSION
        or version > CURRENT_CONVERSATION_FORMAT_VERSION
    ):
        raise JournalCodecError(
            "Conversation JSONL version is unsupported",
            code="unsupported_conversation_format_version",
        )


def _require_envelope(
    value: Mapping[str, object],
    *,
    name: str,
) -> dict[str, JSONValue]:
    if not isinstance(value, Mapping):
        raise JournalCodecError(
            f"{name.capitalize()} must be a JSON object",
            code="invalid_envelope_shape",
        )
    try:
        return require_json_mapping(dict(value), name=name)
    except JsonValueError as exc:
        raise JournalCodecError(
            f"{name.capitalize()} contains a value outside strict JSON",
            code="invalid_envelope_value",
        ) from exc


def _require_field(value: Mapping[str, JSONValue], name: str) -> JSONValue:
    if name not in value:
        raise JournalCodecError(
            f"Conversation envelope is missing {name!r}",
            code="missing_envelope_field",
        )
    return value[name]


def _require_text_field(value: Mapping[str, JSONValue], name: str) -> str:
    field = _require_field(value, name)
    if type(field) is not str or not field.strip():
        raise JournalCodecError(
            f"Conversation envelope field {name!r} must be a non-empty string",
            code="invalid_envelope_field",
        )
    return field


def _require_optional_text_field(
    value: Mapping[str, JSONValue],
    name: str,
) -> str | None:
    field = value.get(name)
    if field is None:
        return None
    if type(field) is not str or not field.strip():
        raise JournalCodecError(
            f"Conversation envelope field {name!r} must be a string or null",
            code="invalid_envelope_field",
        )
    return field


def _require_positive_integer_field(
    value: Mapping[str, JSONValue],
    name: str,
) -> int:
    field = _require_field(value, name)
    if type(field) is not int:
        raise JournalCodecError(
            f"Conversation envelope field {name!r} must be an integer",
            code="invalid_envelope_field",
        )
    if field < 1:
        raise JournalCodecError(
            f"Conversation envelope field {name!r} must be positive",
            code="invalid_envelope_field",
        )
    return field


def _require_metadata_field(
    value: Mapping[str, JSONValue],
) -> dict[str, JSONValue]:
    field = value.get("metadata", {})
    try:
        return require_json_mapping(field, name="conversation envelope metadata")
    except JsonValueError as exc:
        raise JournalCodecError(
            "Conversation envelope metadata must be a JSON object",
            code="invalid_envelope_field",
        ) from exc


def _require_discriminator(
    value: Mapping[str, JSONValue],
    *,
    expected: str,
    name: str,
) -> None:
    discriminator = _require_field(value, "type")
    if discriminator != expected:
        raise JournalCodecError(
            f"{name.capitalize()} must have type={expected!r}",
            code="invalid_envelope_type",
        )


__all__ = [
    "CONVERSATION_ENVELOPE_TYPE",
    "CONVERSATION_RECORD_TYPE",
    "CURRENT_CONVERSATION_FORMAT_VERSION",
    "MIN_CONVERSATION_FORMAT_VERSION",
    "ConversationJsonlHeaderCodec",
    "ConversationJsonlRecordCodec",
    "ConversationPayloadCodec",
    "ConversationPayloadCodecRegistry",
    "FunctionalConversationPayloadCodec",
]
