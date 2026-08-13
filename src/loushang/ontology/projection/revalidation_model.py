"""Immutable receipt for reusing selected Facts under a newer schema."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import cast
from uuid import UUID

from loushang.foundation.json import JSONValue, dump_json_value, require_json_mapping
from loushang.ontology.facts import FactSelection
from loushang.ontology.schema import CompiledOntologySchema, SchemaIdentity

FACT_SCHEMA_REVALIDATION_FORMAT = (
    "loushang.ontology.fact-schema-revalidation/v1"
)


class FactSchemaRevalidationStatus(str, Enum):
    """Outcome of validating one immutable Fact selection against a target."""

    ACCEPTED = "accepted"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class FactSchemaRevalidationDiagnostic:
    code: str
    path: str
    message: str

    def __post_init__(self) -> None:
        for name in ("code", "path", "message"):
            _non_empty_text(name, getattr(self, name))

    def to_dict(self) -> dict[str, JSONValue]:
        return {"code": self.code, "path": self.path, "message": self.message}

    @classmethod
    def from_dict(cls, value: object) -> FactSchemaRevalidationDiagnostic:
        document = require_json_mapping(value, name="Fact revalidation diagnostic")
        return cls(
            code=_document_text(document, "code"),
            path=_document_text(document, "path"),
            message=_document_text(document, "message"),
        )


@dataclass(frozen=True, slots=True)
class FactSchemaRevalidationReceipt:
    """Content-addressed proof for one detached, immutable Fact selection."""

    source_schema: SchemaIdentity
    target_schema: SchemaIdentity
    source_schema_digest: str
    target_schema_digest: str
    fact_selection_digest: str
    fact_watermark: int
    valid_at: float
    recorded_at: float
    fact_ids: tuple[UUID, ...]
    schema_change_codes: tuple[str, ...]
    status: FactSchemaRevalidationStatus
    diagnostics: tuple[FactSchemaRevalidationDiagnostic, ...] = ()
    format: str = FACT_SCHEMA_REVALIDATION_FORMAT

    def __post_init__(self) -> None:
        if not isinstance(self.source_schema, SchemaIdentity) or not isinstance(
            self.target_schema,
            SchemaIdentity,
        ):
            raise TypeError("receipt schemas must be SchemaIdentity values")
        for name in (
            "source_schema_digest",
            "target_schema_digest",
            "fact_selection_digest",
        ):
            _require_digest(name, getattr(self, name))
        if type(self.fact_watermark) is not int or self.fact_watermark < 0:
            raise ValueError("fact_watermark must be a non-negative integer")
        for name in ("valid_at", "recorded_at"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(float(value)):
                raise ValueError(f"{name} must be a finite number")
            object.__setattr__(self, name, float(value))
        if not isinstance(self.fact_ids, tuple) or any(
            not isinstance(item, UUID) for item in self.fact_ids
        ):
            raise TypeError("fact_ids must be a tuple of UUID values")
        if len(self.fact_ids) != len(set(self.fact_ids)):
            raise ValueError("fact_ids must not contain duplicates")
        if not isinstance(self.schema_change_codes, tuple) or any(
            not isinstance(item, str) or not item
            for item in self.schema_change_codes
        ):
            raise TypeError("schema_change_codes must be a tuple of strings")
        if tuple(sorted(set(self.schema_change_codes))) != self.schema_change_codes:
            raise ValueError("schema_change_codes must be unique and sorted")
        if not isinstance(self.status, FactSchemaRevalidationStatus):
            raise TypeError("status must be a FactSchemaRevalidationStatus")
        if not isinstance(self.diagnostics, tuple) or any(
            not isinstance(item, FactSchemaRevalidationDiagnostic)
            for item in self.diagnostics
        ):
            raise TypeError("diagnostics must contain revalidation diagnostics")
        if self.status is FactSchemaRevalidationStatus.ACCEPTED and self.diagnostics:
            raise ValueError("an accepted receipt cannot contain diagnostics")
        if self.status is FactSchemaRevalidationStatus.BLOCKED and not self.diagnostics:
            raise ValueError("a blocked receipt requires diagnostics")
        if self.format != FACT_SCHEMA_REVALIDATION_FORMAT:
            raise ValueError("unsupported Fact schema revalidation format")

    @property
    def accepted(self) -> bool:
        return self.status is FactSchemaRevalidationStatus.ACCEPTED

    @property
    def receipt_digest(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "format": self.format,
            "source_schema": self.source_schema.to_dict(),
            "target_schema": self.target_schema.to_dict(),
            "source_schema_digest": self.source_schema_digest,
            "target_schema_digest": self.target_schema_digest,
            "fact_selection_digest": self.fact_selection_digest,
            "fact_watermark": self.fact_watermark,
            "valid_at": self.valid_at,
            "recorded_at": self.recorded_at,
            "fact_ids": [str(item) for item in self.fact_ids],
            "schema_change_codes": list(self.schema_change_codes),
            "status": self.status.value,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }

    def to_json(self) -> str:
        return dump_json_value(
            self.to_dict(),
            name="Fact schema revalidation receipt",
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, payload: str) -> FactSchemaRevalidationReceipt:
        try:
            document = require_json_mapping(
                json.loads(payload),
                name="Fact schema revalidation receipt",
            )
            if document.get("format") != FACT_SCHEMA_REVALIDATION_FORMAT:
                raise ValueError("unsupported Fact schema revalidation format")
            raw_fact_ids = document["fact_ids"]
            raw_codes = document["schema_change_codes"]
            raw_diagnostics = document["diagnostics"]
            if not isinstance(raw_fact_ids, list) or not all(
                isinstance(item, str) for item in raw_fact_ids
            ):
                raise ValueError("receipt fact_ids must be a list of UUID strings")
            if not isinstance(raw_codes, list) or not all(
                isinstance(item, str) for item in raw_codes
            ):
                raise ValueError("receipt schema_change_codes must be a string list")
            if not isinstance(raw_diagnostics, list):
                raise ValueError("receipt diagnostics must be a list")
            return cls(
                source_schema=SchemaIdentity.from_dict(document["source_schema"]),
                target_schema=SchemaIdentity.from_dict(document["target_schema"]),
                source_schema_digest=_document_text(
                    document,
                    "source_schema_digest",
                ),
                target_schema_digest=_document_text(
                    document,
                    "target_schema_digest",
                ),
                fact_selection_digest=_document_text(
                    document,
                    "fact_selection_digest",
                ),
                fact_watermark=_document_int(document, "fact_watermark"),
                valid_at=_document_number(document, "valid_at"),
                recorded_at=_document_number(document, "recorded_at"),
                fact_ids=tuple(UUID(item) for item in cast(list[str], raw_fact_ids)),
                schema_change_codes=tuple(cast(list[str], raw_codes)),
                status=FactSchemaRevalidationStatus(
                    _document_text(document, "status")
                ),
                diagnostics=tuple(
                    FactSchemaRevalidationDiagnostic.from_dict(item)
                    for item in raw_diagnostics
                ),
            )
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid Fact revalidation receipt JSON: {exc}") from exc

    def validate_for(
        self,
        selection: FactSelection,
        target_schema: CompiledOntologySchema,
    ) -> None:
        if not self.accepted:
            raise ValueError("Fact schema revalidation receipt is blocked")
        if self.target_schema != SchemaIdentity.from_schema(target_schema):
            raise ValueError("receipt target schema identity does not match")
        if self.target_schema_digest != schema_content_digest(target_schema):
            raise ValueError("receipt target schema content does not match")
        if (
            self.fact_watermark != selection.fact_watermark
            or self.valid_at != selection.valid_at
            or self.recorded_at != selection.recorded_at
            or self.fact_ids != tuple(item.fact.fact_id for item in selection.facts)
            or self.fact_selection_digest != fact_selection_digest(selection)
        ):
            raise ValueError("receipt Fact selection coordinates do not match")
        if any(
            item.fact.schema_identity != self.source_schema
            for item in selection.facts
        ):
            raise ValueError("receipt source schema identity does not match Facts")


def fact_selection_digest(selection: FactSelection) -> str:
    if not isinstance(selection, FactSelection):
        raise TypeError("selection must be a FactSelection")
    document: dict[str, JSONValue] = {
        "fact_watermark": selection.fact_watermark,
        "valid_at": selection.valid_at,
        "recorded_at": selection.recorded_at,
        "facts": [
            {"sequence": item.sequence, "fact": item.fact.to_dict()}
            for item in selection.facts
        ],
    }
    payload = dump_json_value(
        document,
        name="Fact selection revalidation input",
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def schema_content_digest(schema: CompiledOntologySchema) -> str:
    if not isinstance(schema, CompiledOntologySchema):
        raise TypeError("schema must be a CompiledOntologySchema")
    return hashlib.sha256(schema.to_json().encode("utf-8")).hexdigest()


def _require_digest(name: str, value: object) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _non_empty_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _document_text(document: dict[str, JSONValue], name: str) -> str:
    try:
        return _non_empty_text(name, document[name])
    except KeyError as exc:
        raise ValueError(f"revalidation receipt is missing {name}") from exc


def _document_int(document: dict[str, JSONValue], name: str) -> int:
    try:
        value = document[name]
    except KeyError as exc:
        raise ValueError(f"revalidation receipt is missing {name}") from exc
    if type(value) is not int:
        raise ValueError(f"revalidation receipt {name} must be an integer")
    return value


def _document_number(document: dict[str, JSONValue], name: str) -> float:
    try:
        value = document[name]
    except KeyError as exc:
        raise ValueError(f"revalidation receipt is missing {name}") from exc
    if type(value) not in (int, float):
        raise ValueError(f"revalidation receipt {name} must be a number")
    return float(cast(int | float, value))


__all__ = [
    "FACT_SCHEMA_REVALIDATION_FORMAT",
    "FactSchemaRevalidationDiagnostic",
    "FactSchemaRevalidationReceipt",
    "FactSchemaRevalidationStatus",
    "fact_selection_digest",
    "schema_content_digest",
]
