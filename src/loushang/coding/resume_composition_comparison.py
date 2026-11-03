"""Pure Coding Resume comparison of historical and current composition facts.

This result can seed planning. It cannot admit a writable Session, grant
authority, or substitute for the current Plugin and Resource owners' selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .composition_provenance import CodingCompositionProvenanceV1
from .composition_sets import CodingCompositionSetPlan, resolve_coding_composition_set
from .resume_history import CodingResumeHistoryPreview


@dataclass(frozen=True, slots=True)
class CodingResumeCompositionComparisonV1:
    status: Literal["same", "changed", "legacy_unknown", "unavailable"]
    origin: CodingCompositionProvenanceV1 | None
    candidate_set_id: str
    candidate_fingerprint: str
    difference_codes: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()


def compare_coding_resume_composition(
    history: CodingResumeHistoryPreview,
    current: CodingCompositionSetPlan,
) -> CodingResumeCompositionComparisonV1:
    """Compare one owner-selected canonical set with bounded history evidence.

    Unknown Binding or damaged ancestry blocks this planning comparison; it
    remains viewable history. A `same` result says only that this one static
    composition request matches, not that present execution is authorized.
    """

    if not isinstance(history, CodingResumeHistoryPreview):
        raise TypeError("Coding Resume comparison requires a history preview")
    if (
        not isinstance(current, CodingCompositionSetPlan)
        or resolve_coding_composition_set(current.set_id) != current
    ):
        raise ValueError("Coding Resume comparison requires a canonical current set")
    origin = history.header_preview.composition
    status: Literal["same", "changed", "legacy_unknown", "unavailable"]
    difference_codes: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    if history.header_preview.product_identity != "coding":
        status, reason_codes = "unavailable", ("history.identity_unverified",)
    elif history.provenance_conflict:
        status, reason_codes = "unavailable", ("history.provenance_conflict",)
    elif history.selected_ancestry_digest is None:
        status, reason_codes = "unavailable", ("history.ancestry_invalid",)
    elif history.binding_status in {"unknown_version", "invalid"}:
        status = "unavailable"
        reason_codes = (f"history.binding_{history.binding_status}",)
    elif history.activation_status != "none":
        status = "unavailable"
        reason_codes = (f"history.activation_{history.activation_status}",)
    elif origin is None:
        status, difference_codes = "legacy_unknown", ("composition.origin_unknown",)
    elif origin.set_id != current.set_id:
        status, difference_codes = "changed", ("composition.set_changed",)
    elif origin.plan_fingerprint != current.fingerprint:
        status, difference_codes = "changed", ("composition.definition_changed",)
    else:
        status = "same"
    return CodingResumeCompositionComparisonV1(
        status=status,
        origin=origin,
        candidate_set_id=current.set_id,
        candidate_fingerprint=current.fingerprint,
        difference_codes=difference_codes,
        reason_codes=reason_codes,
    )


__all__ = [
    "CodingResumeCompositionComparisonV1",
    "compare_coding_resume_composition",
]
