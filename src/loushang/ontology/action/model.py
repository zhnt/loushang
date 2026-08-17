"""Immutable, strict-JSON contracts for pure Ontology Action planning."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import cast
from uuid import UUID

from loushang.foundation.json import (
    JSONValue,
    dump_json_value,
    require_json_mapping,
)
from loushang.ontology.facts import FactBatch
from loushang.ontology.projection import MaterializationCut, ProjectionState
from loushang.ontology.schema import SchemaIdentity
from loushang.ontology.source import SourceCoverage, SourceInputCut

ACTION_REQUEST_FORMAT = "loushang.ontology.action-request/v1"
ACTION_PLAN_FORMAT = "loushang.ontology.action-plan/v1"


@dataclass(frozen=True, slots=True)
class ProjectionGuard:
    """Exact immutable Projection coordinates against which an Action was chosen."""

    schema_identity: SchemaIdentity
    projection_version: int
    materialization_cut: MaterializationCut

    def __post_init__(self) -> None:
        if not isinstance(self.schema_identity, SchemaIdentity):
            raise TypeError("schema_identity must be a SchemaIdentity")
        if type(self.projection_version) is not int or self.projection_version < 1:
            raise ValueError("projection_version must be a positive integer")
        if not isinstance(self.materialization_cut, MaterializationCut):
            raise TypeError("materialization_cut must be a MaterializationCut")
        if self.materialization_cut.schema_identity != self.schema_identity:
            raise ValueError("ProjectionGuard schema and cut identities disagree")

    @classmethod
    def from_state(cls, state: ProjectionState) -> ProjectionGuard:
        if not isinstance(state, ProjectionState):
            raise TypeError("state must be a ProjectionState")
        return cls(
            schema_identity=state.schema_identity,
            projection_version=state.projection_version,
            materialization_cut=state.materialization_cut,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "schema_identity": self.schema_identity.to_dict(),
            "projection_version": self.projection_version,
            "materialization_cut": _cut_to_dict(self.materialization_cut),
        }

    @classmethod
    def from_dict(cls, value: object) -> ProjectionGuard:
        document = _exact_document(
            value,
            name="projection guard",
            keys={"schema_identity", "projection_version", "materialization_cut"},
        )
        return cls(
            schema_identity=SchemaIdentity.from_dict(document["schema_identity"]),
            projection_version=_document_int(document, "projection_version", minimum=1),
            materialization_cut=_cut_from_value(document["materialization_cut"]),
        )


@dataclass(frozen=True, slots=True, init=False)
class ActionRequest:
    """One idempotent request bound to an exact deployment and read snapshot."""

    deployment_id: str
    deployment_profile_digest: str
    schema_identity: SchemaIdentity
    action_id: str
    request_id: str
    target_object_id: UUID
    projection_guard: ProjectionGuard
    actor_context_ref: str
    valid_from: float
    recorded_at: float
    _arguments_json: str = field(init=False, repr=False)

    def __init__(
        self,
        *,
        deployment_id: str,
        deployment_profile_digest: str,
        schema_identity: SchemaIdentity,
        action_id: str,
        request_id: str,
        target_object_id: UUID,
        arguments: object,
        projection_guard: ProjectionGuard,
        actor_context_ref: str,
        valid_from: float,
        recorded_at: float,
    ) -> None:
        for name, value in (
            ("deployment_id", deployment_id),
            ("action_id", action_id),
            ("request_id", request_id),
            ("actor_context_ref", actor_context_ref),
        ):
            _non_empty_text(name, value)
        _require_digest("deployment_profile_digest", deployment_profile_digest)
        if not isinstance(schema_identity, SchemaIdentity):
            raise TypeError("schema_identity must be a SchemaIdentity")
        if not isinstance(target_object_id, UUID):
            raise TypeError("target_object_id must be a UUID")
        if not isinstance(projection_guard, ProjectionGuard):
            raise TypeError("projection_guard must be a ProjectionGuard")
        if projection_guard.schema_identity != schema_identity:
            raise ValueError("ActionRequest schema and ProjectionGuard disagree")
        checked_arguments = require_json_mapping(arguments, name="action arguments")
        object.__setattr__(self, "deployment_id", deployment_id)
        object.__setattr__(
            self,
            "deployment_profile_digest",
            deployment_profile_digest,
        )
        object.__setattr__(self, "schema_identity", schema_identity)
        object.__setattr__(self, "action_id", action_id)
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "target_object_id", target_object_id)
        object.__setattr__(self, "projection_guard", projection_guard)
        object.__setattr__(self, "actor_context_ref", actor_context_ref)
        object.__setattr__(self, "valid_from", _finite("valid_from", valid_from))
        object.__setattr__(self, "recorded_at", _finite("recorded_at", recorded_at))
        object.__setattr__(
            self,
            "_arguments_json",
            dump_json_value(checked_arguments, name="action arguments", sort_keys=True),
        )

    @property
    def arguments(self) -> dict[str, JSONValue]:
        return cast(dict[str, JSONValue], json.loads(self._arguments_json))

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "format": ACTION_REQUEST_FORMAT,
            "deployment_id": self.deployment_id,
            "deployment_profile_digest": self.deployment_profile_digest,
            "schema_identity": self.schema_identity.to_dict(),
            "action_id": self.action_id,
            "request_id": self.request_id,
            "target_object_id": str(self.target_object_id),
            "arguments": self.arguments,
            "projection_guard": self.projection_guard.to_dict(),
            "actor_context_ref": self.actor_context_ref,
            "valid_from": self.valid_from,
            "recorded_at": self.recorded_at,
        }

    def to_json(self) -> str:
        return dump_json_value(self.to_dict(), name="action request", sort_keys=True)

    @property
    def request_digest(self) -> str:
        return _sha256_text(self.to_json())

    @classmethod
    def from_json(cls, payload: str) -> ActionRequest:
        try:
            document = _exact_document(
                json.loads(payload),
                name="action request",
                keys={
                    "format",
                    "deployment_id",
                    "deployment_profile_digest",
                    "schema_identity",
                    "action_id",
                    "request_id",
                    "target_object_id",
                    "arguments",
                    "projection_guard",
                    "actor_context_ref",
                    "valid_from",
                    "recorded_at",
                },
            )
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid action request JSON: {exc}") from exc
        if document["format"] != ACTION_REQUEST_FORMAT:
            raise ValueError("unsupported action request format")
        return cls(
            deployment_id=_document_text(document, "deployment_id"),
            deployment_profile_digest=_document_text(
                document,
                "deployment_profile_digest",
            ),
            schema_identity=SchemaIdentity.from_dict(document["schema_identity"]),
            action_id=_document_text(document, "action_id"),
            request_id=_document_text(document, "request_id"),
            target_object_id=UUID(_document_text(document, "target_object_id")),
            arguments=document["arguments"],
            projection_guard=ProjectionGuard.from_dict(document["projection_guard"]),
            actor_context_ref=_document_text(document, "actor_context_ref"),
            valid_from=_document_number(document, "valid_from"),
            recorded_at=_document_number(document, "recorded_at"),
        )


@dataclass(frozen=True, slots=True)
class OntologyFactEffect:
    """One deterministic Fact batch guarded by its planning watermark."""

    fact_batch: FactBatch
    expected_fact_watermark: int

    def __post_init__(self) -> None:
        if not isinstance(self.fact_batch, FactBatch):
            raise TypeError("fact_batch must be a FactBatch")
        if (
            type(self.expected_fact_watermark) is not int
            or self.expected_fact_watermark < 0
        ):
            raise ValueError("expected_fact_watermark must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class ActionPlan:
    """Pure first-slice plan; authorization and execution remain external."""

    schema_identity: SchemaIdentity
    action_id: str
    request_id: str
    request_digest: str
    target_object_id: UUID
    policy_requirement_ref: str
    effect: OntologyFactEffect
    format: str = ACTION_PLAN_FORMAT

    def __post_init__(self) -> None:
        if not isinstance(self.schema_identity, SchemaIdentity):
            raise TypeError("schema_identity must be a SchemaIdentity")
        for name in ("action_id", "request_id", "policy_requirement_ref"):
            _non_empty_text(name, getattr(self, name))
        _require_digest("request_digest", self.request_digest)
        if not isinstance(self.target_object_id, UUID):
            raise TypeError("target_object_id must be a UUID")
        if not isinstance(self.effect, OntologyFactEffect):
            raise TypeError("effect must be an OntologyFactEffect")
        if self.effect.fact_batch.schema_identity != self.schema_identity:
            raise ValueError("ActionPlan and FactBatch schema identities disagree")
        if self.format != ACTION_PLAN_FORMAT:
            raise ValueError("unsupported action plan format")

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "format": self.format,
            "schema_identity": self.schema_identity.to_dict(),
            "action_id": self.action_id,
            "request_id": self.request_id,
            "request_digest": self.request_digest,
            "target_object_id": str(self.target_object_id),
            "policy_requirement_ref": self.policy_requirement_ref,
            "effect": {
                "kind": "ontology_fact",
                "expected_fact_watermark": self.effect.expected_fact_watermark,
                "fact_batch": self.effect.fact_batch.to_dict(),
            },
        }

    def to_json(self) -> str:
        return dump_json_value(self.to_dict(), name="action plan", sort_keys=True)

    @property
    def plan_digest(self) -> str:
        return _sha256_text(self.to_json())

    @classmethod
    def from_json(cls, payload: str) -> ActionPlan:
        try:
            document = _exact_document(
                json.loads(payload),
                name="action plan",
                keys={
                    "format",
                    "schema_identity",
                    "action_id",
                    "request_id",
                    "request_digest",
                    "target_object_id",
                    "policy_requirement_ref",
                    "effect",
                },
            )
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid action plan JSON: {exc}") from exc
        if document["format"] != ACTION_PLAN_FORMAT:
            raise ValueError("unsupported action plan format")
        effect_document = _exact_document(
            document["effect"],
            name="action effect",
            keys={"kind", "expected_fact_watermark", "fact_batch"},
        )
        if effect_document["kind"] != "ontology_fact":
            raise ValueError("unsupported action effect kind")
        fact_batch_document = require_json_mapping(
            effect_document["fact_batch"],
            name="action FactBatch",
        )
        return cls(
            schema_identity=SchemaIdentity.from_dict(document["schema_identity"]),
            action_id=_document_text(document, "action_id"),
            request_id=_document_text(document, "request_id"),
            request_digest=_document_text(document, "request_digest"),
            target_object_id=UUID(_document_text(document, "target_object_id")),
            policy_requirement_ref=_document_text(
                document,
                "policy_requirement_ref",
            ),
            effect=OntologyFactEffect(
                fact_batch=FactBatch.from_json(
                    dump_json_value(
                        fact_batch_document,
                        name="action FactBatch",
                        sort_keys=True,
                    )
                ),
                expected_fact_watermark=_document_int(
                    effect_document,
                    "expected_fact_watermark",
                    minimum=0,
                ),
            ),
        )


def _cut_to_dict(cut: MaterializationCut) -> dict[str, JSONValue]:
    return {
        "schema_identity": cut.schema_identity.to_dict(),
        "source_inputs": [
            {
                "binding_id": item.binding_id,
                "mapping_version": item.mapping_version,
                "source_revision": item.source_revision,
                "payload_digest": item.payload_digest,
                "coverage": item.coverage.value,
            }
            for item in cut.source_inputs
        ],
        "fact_watermark": cut.fact_watermark,
        "valid_at": cut.valid_at,
        "recorded_at": cut.recorded_at,
        "fact_revalidation_digest": cut.fact_revalidation_digest,
    }


def _cut_from_value(value: object) -> MaterializationCut:
    document = _exact_document(
        value,
        name="materialization cut",
        keys={
            "schema_identity",
            "source_inputs",
            "fact_watermark",
            "valid_at",
            "recorded_at",
            "fact_revalidation_digest",
        },
    )
    raw_source_inputs = document["source_inputs"]
    if not isinstance(raw_source_inputs, list):
        raise ValueError("materialization cut source_inputs must be a list")
    source_inputs: list[SourceInputCut] = []
    for value in raw_source_inputs:
        source = _exact_document(
            value,
            name="materialization source input",
            keys={
                "binding_id",
                "mapping_version",
                "source_revision",
                "payload_digest",
                "coverage",
            },
        )
        source_inputs.append(
            SourceInputCut(
                binding_id=_document_text(source, "binding_id"),
                mapping_version=_document_text(source, "mapping_version"),
                source_revision=_document_text(source, "source_revision"),
                payload_digest=_document_text(source, "payload_digest"),
                coverage=SourceCoverage(_document_text(source, "coverage")),
            )
        )
    raw_revalidation = document["fact_revalidation_digest"]
    if raw_revalidation is not None and not isinstance(raw_revalidation, str):
        raise ValueError("fact_revalidation_digest must be a string or null")
    return MaterializationCut(
        schema_identity=SchemaIdentity.from_dict(document["schema_identity"]),
        source_inputs=tuple(source_inputs),
        fact_watermark=_document_int(document, "fact_watermark", minimum=0),
        valid_at=_document_number(document, "valid_at"),
        recorded_at=_document_number(document, "recorded_at"),
        fact_revalidation_digest=cast(str | None, raw_revalidation),
    )


def _exact_document(
    value: object,
    *,
    name: str,
    keys: set[str],
) -> dict[str, JSONValue]:
    document = require_json_mapping(value, name=name)
    if set(document) != keys:
        raise ValueError(f"{name} fields do not match the supported format")
    return document


def _non_empty_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_digest(name: str, value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _finite(name: str, value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(
        float(cast(int | float, value))
    ):
        raise ValueError(f"{name} must be a finite number")
    return float(cast(int | float, value))


def _document_text(document: dict[str, JSONValue], name: str) -> str:
    try:
        return _non_empty_text(name, document[name])
    except KeyError as exc:  # pragma: no cover - exact fields report first
        raise ValueError(f"document is missing {name}") from exc


def _document_number(document: dict[str, JSONValue], name: str) -> float:
    return _finite(name, document[name])


def _document_int(
    document: dict[str, JSONValue],
    name: str,
    *,
    minimum: int,
) -> int:
    value = document[name]
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer greater than or equal to {minimum}")
    return cast(int, value)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "ACTION_PLAN_FORMAT",
    "ACTION_REQUEST_FORMAT",
    "ActionPlan",
    "ActionRequest",
    "OntologyFactEffect",
    "ProjectionGuard",
]
