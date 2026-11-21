"""Session-owned identity of the canonical Coding composition request."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from loushang.coding.composition.sets import (
    CodingCompositionSetPlan,
    resolve_coding_composition_set,
)
from loushang.coding.harness.session.composition_receipt import (
    composition_identity_fields,
    read_composition_header,
    read_composition_receipt,
)
from loushang.foundation.json import JSONValue

CODING_COMPOSITION_HEADER_KEY = "codingCompositionSetV1"
CODING_COMPOSITION_STARTUP_TYPE = "coding.composition-startup/v1"


@dataclass(frozen=True, slots=True)
class CodingCompositionProvenanceV1:
    """Historical Session evidence, independent of the installed set registry."""

    set_id: str
    plan_fingerprint: str


def composition_header_metadata(plan: CodingCompositionSetPlan) -> dict[str, JSONValue]:
    canonical = resolve_coding_composition_set(plan.set_id)
    if canonical != plan:
        raise ValueError("Coding composition header requires a canonical plan")
    return {
        CODING_COMPOSITION_HEADER_KEY: composition_identity_fields(
            plan.set_id, plan.fingerprint
        )
    }


def historical_composition_provenance(
    metadata: Mapping[str, object],
) -> CodingCompositionProvenanceV1 | None:
    """Decode the original Header as evidence without resolving today's plan."""

    identity = read_composition_header(
        metadata, header_key=CODING_COMPOSITION_HEADER_KEY, label="Coding Session"
    )
    return CodingCompositionProvenanceV1(*identity) if identity is not None else None


def pinned_composition_plan(metadata: Mapping[str, object]) -> CodingCompositionSetPlan | None:
    """Resolve an exact current plan for the legacy writable startup gate."""

    evidence = historical_composition_provenance(metadata)
    if evidence is None:
        return None
    plan = resolve_coding_composition_set(evidence.set_id)
    if plan.fingerprint != evidence.plan_fingerprint:
        raise ValueError("Coding Session composition plan has changed")
    return plan


def startup_composition_record(entries: Iterable[object]) -> dict[str, object] | None:
    """Read a receipt for the existing exact-current writable startup gate."""

    return read_composition_receipt(
        entries,
        extension_type=CODING_COMPOSITION_STARTUP_TYPE,
        label="Coding Session",
        require_current=_require_current_composition_plan,
    )


def historical_startup_composition_record(
    entries: Iterable[object],
) -> dict[str, object] | None:
    """Decode a historical receipt without consulting the current set registry."""

    return read_composition_receipt(
        entries,
        extension_type=CODING_COMPOSITION_STARTUP_TYPE,
        label="Coding Session",
    )


def _require_current_composition_plan(set_id: str, plan_fingerprint: str) -> None:
    try:
        canonical = resolve_coding_composition_set(set_id)
    except ValueError as exc:
        raise ValueError("Coding Session composition startup set is unknown") from exc
    if canonical.fingerprint != plan_fingerprint:
        raise ValueError("Coding Session composition startup plan has changed")


__all__ = [
    "CODING_COMPOSITION_HEADER_KEY",
    "CODING_COMPOSITION_STARTUP_TYPE",
    "CodingCompositionProvenanceV1",
    "composition_header_metadata",
    "historical_composition_provenance",
    "historical_startup_composition_record",
    "pinned_composition_plan",
    "startup_composition_record",
]
