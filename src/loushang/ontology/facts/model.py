"""Immutable semantic fact, provenance, and batch contracts."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import TypeAlias, cast
from uuid import UUID

from loushang.foundation.json import (
    JSONValue,
    JsonValueError,
    dump_json_value,
    require_json_mapping,
    require_json_value,
)
from loushang.ontology.schema.identity import SchemaIdentity

FACT_FORMAT = "loushang.ontology.fact/v2"
FACT_BATCH_FORMAT = "loushang.ontology.fact-batch/v2"


class FactValidationError(ValueError):
    """Raised when a semantic fact or batch violates the public contract."""


class AssertionKind(str, Enum):
    """How a fact entered the semantic authority."""

    ASSERTED = "asserted"
    DERIVED = "derived"
    INFERRED = "inferred"


@dataclass(frozen=True, slots=True)
class ObjectAssertion:
    """Assert that the subject exists as one stable object-type ID."""

    object_type_id: str

    def __post_init__(self) -> None:
        _require_text("object_type_id", self.object_type_id)


@dataclass(frozen=True, slots=True, init=False)
class PropertyAssertion:
    """Assert one strict-JSON value for a stable property ID."""

    property_id: str
    _value_json: str = field(repr=False)

    def __init__(self, property_id: str, value: object) -> None:
        _require_text("property_id", property_id)
        try:
            value_json = dump_json_value(value, name="fact property value", sort_keys=True)
        except JsonValueError as exc:
            raise FactValidationError(str(exc)) from exc
        object.__setattr__(self, "property_id", property_id)
        object.__setattr__(self, "_value_json", value_json)

    @property
    def value(self) -> JSONValue:
        return cast(JSONValue, json.loads(self._value_json))


@dataclass(frozen=True, slots=True, init=False)
class LinkAssertion:
    """Assert one stable link-type edge from the subject to ``target_id``."""

    link_type_id: str
    target_id: UUID
    _properties_json: str = field(repr=False)

    def __init__(
        self,
        link_type_id: str,
        target_id: UUID,
        properties: object | None = None,
    ) -> None:
        _require_text("link_type_id", link_type_id)
        _require_uuid("target_id", target_id)
        try:
            properties_json = dump_json_value(
                {} if properties is None else require_json_mapping(
                    properties,
                    name="fact link properties",
                ),
                name="fact link properties",
                sort_keys=True,
            )
        except JsonValueError as exc:
            raise FactValidationError(str(exc)) from exc
        object.__setattr__(self, "link_type_id", link_type_id)
        object.__setattr__(self, "target_id", target_id)
        object.__setattr__(self, "_properties_json", properties_json)

    @property
    def properties(self) -> dict[str, JSONValue]:
        return cast(dict[str, JSONValue], json.loads(self._properties_json))


FactAssertion: TypeAlias = ObjectAssertion | PropertyAssertion | LinkAssertion


@dataclass(frozen=True, slots=True)
class FactRecord:
    """One append-only bitemporal semantic assertion with provenance."""

    fact_id: UUID
    subject_id: UUID
    schema_identity: SchemaIdentity
    assertion: FactAssertion
    assertion_kind: AssertionKind
    source_ref: str
    source_record_ref: str
    valid_from: float
    recorded_at: float
    valid_to: float | None = None
    evidence_refs: tuple[str, ...] | list[str] = field(default_factory=tuple)
    methodology_ref: str | None = None
    confidence: float | None = None
    author_ref: str | None = None
    agent_ref: str | None = None
    supersedes: UUID | None = None
    corrects: UUID | None = None

    def __post_init__(self) -> None:
        _require_uuid("fact_id", self.fact_id)
        _require_uuid("subject_id", self.subject_id)
        if not isinstance(self.schema_identity, SchemaIdentity):
            raise FactValidationError("schema_identity must be a SchemaIdentity")
        if not isinstance(
            self.assertion,
            (ObjectAssertion, PropertyAssertion, LinkAssertion),
        ):
            raise FactValidationError("assertion must be a typed fact assertion")
        if not isinstance(self.assertion_kind, AssertionKind):
            raise FactValidationError("assertion_kind must be an AssertionKind")
        _require_text("source_ref", self.source_ref)
        _require_text("source_record_ref", self.source_record_ref)
        valid_from = _require_time("valid_from", self.valid_from)
        recorded_at = _require_time("recorded_at", self.recorded_at)
        valid_to = (
            None if self.valid_to is None else _require_time("valid_to", self.valid_to)
        )
        if valid_to is not None and valid_to <= valid_from:
            raise FactValidationError("valid_to must be greater than valid_from")
        object.__setattr__(self, "valid_from", valid_from)
        object.__setattr__(self, "recorded_at", recorded_at)
        object.__setattr__(self, "valid_to", valid_to)

        evidence_refs = tuple(self.evidence_refs)
        for evidence_ref in evidence_refs:
            _require_text("evidence_refs item", evidence_ref)
        object.__setattr__(self, "evidence_refs", evidence_refs)
        for name in ("methodology_ref", "author_ref", "agent_ref"):
            value = cast(str | None, getattr(self, name))
            if value is not None:
                _require_text(name, value)

        if self.confidence is not None:
            confidence = _require_time("confidence", self.confidence)
            if not 0.0 <= confidence <= 1.0:
                raise FactValidationError("confidence must be between 0 and 1")
            object.__setattr__(self, "confidence", confidence)

        if self.supersedes is not None:
            _require_uuid("supersedes", self.supersedes)
        if self.corrects is not None:
            _require_uuid("corrects", self.corrects)
        if self.supersedes is not None and self.corrects is not None:
            raise FactValidationError("a fact may declare at most one lineage edge")
        predecessor = self.predecessor_id
        if predecessor == self.fact_id:
            raise FactValidationError("a fact cannot replace itself")

    @property
    def predecessor_id(self) -> UUID | None:
        return self.supersedes if self.supersedes is not None else self.corrects

    @property
    def assertion_category(self) -> str:
        if isinstance(self.assertion, ObjectAssertion):
            return "object"
        if isinstance(self.assertion, PropertyAssertion):
            return "property"
        return "link"

    @property
    def predicate(self) -> str:
        if isinstance(self.assertion, ObjectAssertion):
            return "$type"
        if isinstance(self.assertion, PropertyAssertion):
            return self.assertion.property_id
        return self.assertion.link_type_id

    @property
    def lineage_coordinate(self) -> tuple[UUID, str, str, str, str, str]:
        return (
            self.subject_id,
            self.assertion_category,
            self.predicate,
            self.assertion_kind.value,
            self.source_ref,
            self.source_record_ref,
        )

    def is_valid_at(self, timestamp: float) -> bool:
        checked = _require_time("valid_at", timestamp)
        return self.valid_from <= checked and (
            self.valid_to is None or checked < self.valid_to
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "format": FACT_FORMAT,
            "fact_id": str(self.fact_id),
            "subject_id": str(self.subject_id),
            "schema_identity": self.schema_identity.to_dict(),
            "assertion": _assertion_to_document(self.assertion),
            "assertion_kind": self.assertion_kind.value,
            "source_ref": self.source_ref,
            "source_record_ref": self.source_record_ref,
            "evidence_refs": list(self.evidence_refs),
            "methodology_ref": self.methodology_ref,
            "confidence": self.confidence,
            "author_ref": self.author_ref,
            "agent_ref": self.agent_ref,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "recorded_at": self.recorded_at,
            "supersedes": str(self.supersedes) if self.supersedes is not None else None,
            "corrects": str(self.corrects) if self.corrects is not None else None,
        }

    def to_json(self) -> str:
        return dump_json_value(self.to_dict(), name="ontology fact", sort_keys=True)

    @classmethod
    def from_dict(cls, value: object) -> FactRecord:
        try:
            document = require_json_mapping(value, name="ontology fact")
            if document.get("format") != FACT_FORMAT:
                raise FactValidationError("unsupported ontology fact format")
            return cls(
                fact_id=UUID(_require_document_text(document, "fact_id")),
                subject_id=UUID(_require_document_text(document, "subject_id")),
                schema_identity=SchemaIdentity.from_dict(document["schema_identity"]),
                assertion=_assertion_from_document(document["assertion"]),
                assertion_kind=AssertionKind(
                    _require_document_text(document, "assertion_kind")
                ),
                source_ref=_require_document_text(document, "source_ref"),
                source_record_ref=_require_document_text(
                    document,
                    "source_record_ref",
                ),
                evidence_refs=_require_text_list(document.get("evidence_refs", [])),
                methodology_ref=_optional_document_text(document, "methodology_ref"),
                confidence=_optional_number(document, "confidence"),
                author_ref=_optional_document_text(document, "author_ref"),
                agent_ref=_optional_document_text(document, "agent_ref"),
                valid_from=_require_number(document, "valid_from"),
                valid_to=_optional_number(document, "valid_to"),
                recorded_at=_require_number(document, "recorded_at"),
                supersedes=_optional_uuid(document, "supersedes"),
                corrects=_optional_uuid(document, "corrects"),
            )
        except FactValidationError:
            raise
        except (JsonValueError, KeyError, TypeError, ValueError) as exc:
            raise FactValidationError(f"invalid ontology fact: {exc}") from exc

    @classmethod
    def from_json(cls, payload: str) -> FactRecord:
        try:
            return cls.from_dict(json.loads(payload))
        except json.JSONDecodeError as exc:
            raise FactValidationError(f"invalid ontology fact JSON: {exc}") from exc


@dataclass(frozen=True, slots=True)
class FactBatch:
    """Atomic, idempotent sequence of facts."""

    batch_id: str
    facts: tuple[FactRecord, ...] | list[FactRecord]

    def __post_init__(self) -> None:
        _require_text("batch_id", self.batch_id)
        facts = tuple(self.facts)
        if not facts:
            raise FactValidationError("a FactBatch must contain at least one fact")
        if any(not isinstance(fact, FactRecord) for fact in facts):
            raise FactValidationError("FactBatch facts must be FactRecord values")
        identities = {fact.schema_identity for fact in facts}
        if len(identities) != 1:
            raise FactValidationError(
                "FactBatch facts must share one complete schema identity"
            )
        fact_ids = [fact.fact_id for fact in facts]
        if len(set(fact_ids)) != len(fact_ids):
            raise FactValidationError("FactBatch contains a duplicate fact_id")
        object.__setattr__(self, "facts", facts)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "format": FACT_BATCH_FORMAT,
            "batch_id": self.batch_id,
            "schema_identity": self.schema_identity.to_dict(),
            "facts": [fact.to_dict() for fact in self.facts],
        }

    @property
    def schema_identity(self) -> SchemaIdentity:
        return self.facts[0].schema_identity

    def to_json(self) -> str:
        return dump_json_value(self.to_dict(), name="ontology fact batch", sort_keys=True)

    @property
    def content_digest(self) -> str:
        """Return the canonical digest used for idempotent commit identity."""

        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_json(cls, payload: str) -> FactBatch:
        try:
            document = require_json_mapping(json.loads(payload), name="ontology fact batch")
            if document.get("format") != FACT_BATCH_FORMAT:
                raise FactValidationError("unsupported ontology fact batch format")
            raw_facts = document["facts"]
            if not isinstance(raw_facts, list):
                raise FactValidationError("ontology fact batch facts must be a list")
            batch = cls(
                batch_id=_require_document_text(document, "batch_id"),
                facts=[FactRecord.from_dict(item) for item in raw_facts],
            )
            declared_identity = SchemaIdentity.from_dict(document["schema_identity"])
            if batch.schema_identity != declared_identity:
                raise FactValidationError(
                    "FactBatch schema identity does not match its facts"
                )
            return batch
        except FactValidationError:
            raise
        except (json.JSONDecodeError, JsonValueError, KeyError, TypeError, ValueError) as exc:
            raise FactValidationError(f"invalid ontology fact batch: {exc}") from exc


def _assertion_to_document(assertion: FactAssertion) -> dict[str, JSONValue]:
    if isinstance(assertion, ObjectAssertion):
        return {"kind": "object", "object_type_id": assertion.object_type_id}
    if isinstance(assertion, PropertyAssertion):
        return {
            "kind": "property",
            "property_id": assertion.property_id,
            "value": require_json_value(assertion.value, name="fact property value"),
        }
    return {
        "kind": "link",
        "link_type_id": assertion.link_type_id,
        "target_id": str(assertion.target_id),
        "properties": assertion.properties,
    }


def _assertion_from_document(value: object) -> FactAssertion:
    document = require_json_mapping(value, name="fact assertion")
    kind = _require_document_text(document, "kind")
    if kind == "object":
        return ObjectAssertion(_require_document_text(document, "object_type_id"))
    if kind == "property":
        return PropertyAssertion(
            _require_document_text(document, "property_id"),
            document["value"],
        )
    if kind == "link":
        return LinkAssertion(
            _require_document_text(document, "link_type_id"),
            UUID(_require_document_text(document, "target_id")),
            document.get("properties", {}),
        )
    raise FactValidationError(f"unsupported fact assertion kind '{kind}'")


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FactValidationError(f"{name} must be a non-empty string")
    return value


def _require_uuid(name: str, value: object) -> UUID:
    if not isinstance(value, UUID):
        raise FactValidationError(f"{name} must be a UUID")
    return value


def _require_time(name: str, value: object) -> float:
    if type(value) not in (int, float):
        raise FactValidationError(f"{name} must be a finite number")
    number = cast(int | float, value)
    if not math.isfinite(float(number)):
        raise FactValidationError(f"{name} must be a finite number")
    return float(number)


def _require_document_text(document: dict[str, JSONValue], name: str) -> str:
    return _require_text(name, document[name])


def _optional_document_text(
    document: dict[str, JSONValue],
    name: str,
) -> str | None:
    value = document.get(name)
    return None if value is None else _require_text(name, value)


def _require_number(document: dict[str, JSONValue], name: str) -> float:
    return _require_time(name, document[name])


def _optional_number(document: dict[str, JSONValue], name: str) -> float | None:
    value = document.get(name)
    return None if value is None else _require_time(name, value)


def _optional_uuid(document: dict[str, JSONValue], name: str) -> UUID | None:
    value = document.get(name)
    return None if value is None else UUID(_require_text(name, value))


def _require_text_list(value: object) -> tuple[str, ...]:
    checked = require_json_value(value, name="evidence_refs")
    if not isinstance(checked, list):
        raise FactValidationError("evidence_refs must be a list")
    return tuple(_require_text("evidence_refs item", item) for item in checked)


__all__ = [
    "FACT_BATCH_FORMAT",
    "FACT_FORMAT",
    "AssertionKind",
    "FactAssertion",
    "FactBatch",
    "FactRecord",
    "FactValidationError",
    "LinkAssertion",
    "ObjectAssertion",
    "PropertyAssertion",
]
