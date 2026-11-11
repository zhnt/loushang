from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from loushang.foundation.json import _unique_json_object_hook

H = TypeVar("H")
R = TypeVar("R")


class JournalCodecError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_value") -> None:
        super().__init__(message)
        self.code = code


class JournalRecordCodec(Protocol, Generic[R]):
    def encode_record(self, record: R) -> Mapping[str, object]: ...

    def decode_record(self, value: Mapping[str, object]) -> R: ...


class JournalHeaderCodec(Protocol, Generic[H]):
    def encode_header(self, header: H) -> Mapping[str, object]: ...

    def decode_header(self, value: Mapping[str, object]) -> H: ...


@dataclass(frozen=True)
class FunctionalJournalRecordCodec(Generic[R]):
    encoder: Callable[[R], Mapping[str, object]]
    decoder: Callable[[Mapping[str, object]], R]

    def encode_record(self, record: R) -> Mapping[str, object]:
        return self.encoder(record)

    def decode_record(self, value: Mapping[str, object]) -> R:
        return self.decoder(value)


@dataclass(frozen=True)
class FunctionalJournalHeaderCodec(Generic[H]):
    encoder: Callable[[H], Mapping[str, object]]
    decoder: Callable[[Mapping[str, object]], H]

    def encode_header(self, header: H) -> Mapping[str, object]:
        return self.encoder(header)

    def decode_header(self, value: Mapping[str, object]) -> H:
        return self.decoder(value)


def decode_json_record(
    raw: bytes,
    decoder: Callable[[object], R],
    *,
    label: str,
    duplicate_message: str | None = None,
) -> R:
    """Decode one existing record, retaining caller schema and error-cause policy."""

    unique_object = _unique_json_object_hook(
        lambda: duplicate_message
        if duplicate_message is not None
        else f"{label} has duplicate fields"
    )

    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
        return decoder(document)
    except (TypeError, UnicodeError, ValueError) as error:
        raise ValueError(f"{label} is invalid") from error


__all__ = [
    "FunctionalJournalHeaderCodec",
    "FunctionalJournalRecordCodec",
    "JournalCodecError",
    "JournalHeaderCodec",
    "JournalRecordCodec",
]
