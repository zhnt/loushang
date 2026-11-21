"""Project Session composition history and hash original plan documents."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from loushang.coding.composition.provenance import CodingCompositionProvenanceV1
    from loushang.coding.composition.sets import CodingCompositionSetPlan
    from loushang.coding.resume.history import CodingResumeHistoryPreview

_ComparisonStatus = Literal["same", "changed", "legacy_unknown", "unavailable"]


def composition_plan_fingerprint(document: object, *, digest_domain: bytes) -> str:
    """Encode the deployed composition fingerprint with its original JSON codec."""
    payload = json.dumps(
        document, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return sha256(digest_domain + payload).hexdigest()


def compare_history(
    history: CodingResumeHistoryPreview,
    current: CodingCompositionSetPlan,
    *,
    product_id: str,
) -> tuple[
    _ComparisonStatus,
    CodingCompositionProvenanceV1 | None,
    tuple[str, ...],
    tuple[str, ...],
]:
    """Classify the selected historical facts in the original precedence order."""
    origin = history.header_preview.composition
    status: _ComparisonStatus
    difference_codes: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    if history.header_preview.product_identity != product_id:
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
    return status, origin, difference_codes, reason_codes
