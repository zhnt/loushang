"""Shared field traversal for inert records with conventional camel-case keys.

Schemas are static data. Object admission, scalar validation, construction and
all cross-field invariants stay with the original record and its value helpers.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, fields
from typing import TypeVar, cast

RecordT = TypeVar("RecordT")
ValueDecoder = Callable[..., object]


@dataclass(frozen=True, slots=True)
class RecordField:
    attribute: str
    label: str | None = None
    decoder: ValueDecoder | None = None
    encoder: ValueDecoder | None = None
    wire_key: str = field(init=False)

    def __post_init__(self) -> None:
        head, *tail = self.attribute.split("_")
        object.__setattr__(
            self, "wire_key", head + "".join(part.title() for part in tail)
        )


@dataclass(frozen=True, slots=True)
class RecordSchema:
    text_decoder: ValueDecoder
    fields: tuple[RecordField, ...]

    @classmethod
    def for_dataclass(
        cls,
        record_type: type,
        text_decoder: ValueDecoder,
        *overrides: RecordField,
        derive_labels: bool = False,
    ) -> RecordSchema:
        """Compile once: all dataclass fields are wire fields in declaration order."""
        names = tuple(member.name for member in fields(record_type))
        configured = {item.attribute: item for item in overrides}
        if len(configured) != len(overrides) or not configured.keys() <= set(names):
            raise ValueError("Record schema overrides do not match dataclass fields")
        return cls(
            text_decoder,
            tuple(
                configured[name]
                if name in configured
                else RecordField(
                    name, name.replace("_", " ") if derive_labels else None
                )
                for name in names
            ),
        )

    @property
    def keys(self) -> set[str]:
        return {item.wire_key for item in self.fields}

    def encode(self, value: object, *, sort_keys: bool = False) -> dict[str, object]:
        result: dict[str, object] = {}
        for item in self.fields:
            member = getattr(value, item.attribute)
            result[item.wire_key] = (
                member if item.encoder is None else item.encoder(member)
            )
        return {key: result[key] for key in sorted(result)} if sort_keys else result

    def decode(
        self, constructor: Callable[..., RecordT], document: dict[str, object]
    ) -> RecordT:
        values: dict[str, object] = {}
        for item in self.fields:
            decoder = item.decoder or self.text_decoder
            value = document[item.wire_key]
            values[item.attribute] = (
                decoder(value)
                if item.label is None
                else decoder(value, name=item.label)
            )
        return constructor(**values)


def decode_tuple(
    value: object,
    *,
    list_decoder: ValueDecoder,
    list_label: str | None,
    item_decoder: ValueDecoder,
    item_label: str | None,
) -> tuple[object, ...]:
    items = (
        list_decoder(value)
        if list_label is None
        else list_decoder(value, name=list_label)
    )
    return tuple(
        item_decoder(item)
        if item_label is None
        else item_decoder(item, name=item_label)
        for item in cast(Iterable[object], items)
    )


def decode_nullable(value: object, *, decoder: ValueDecoder) -> object:
    return None if value is None else decoder(value)
