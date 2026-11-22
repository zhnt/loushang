"""Read old Coding desired intent from the authenticated first-B snapshot."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product._legacy_management_evidence import (
    decode_legacy_desired_evidence,
)
from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.ledger import (
    PluginDesiredStateSnapshotV1,
)

from .legacy_snapshot_member import (
    CodingFencedEpochRuntime,
    read_coding_first_b_snapshot_member,
)

_MAX_DESIRED_BYTES = 2 * 1024 * 1024


class CodingLegacyDesiredError(ValueError):
    """Old desired intent cannot be projected without guessing."""


@dataclass(frozen=True, slots=True)
class CodingLegacyDesiredEvidenceV1:
    snapshot: PluginDesiredStateSnapshotV1
    journal_digest: str
    transitions: tuple[PluginDesiredStateJournalTransition, ...] = ()


def read_coding_legacy_desired_evidence(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: CodingFencedEpochRuntime,
) -> CodingLegacyDesiredEvidenceV1 | None:
    """Project committed old desired history without writing its journal."""

    raw = read_coding_first_b_snapshot_member(
        lifecycle,
        epoch_runtime,
        domain="desired_state",
        member_name="desired-state.jsonl",
        maximum_bytes=_MAX_DESIRED_BYTES,
    )
    if raw is None:
        return None
    return parse_coding_legacy_desired_evidence(raw, lifecycle=lifecycle)


def parse_coding_legacy_desired_evidence(
    raw: bytes, *, lifecycle: CodingPluginLifecycleStateLayout
) -> CodingLegacyDesiredEvidenceV1:
    """Decode only a complete committed journal under the old Coding scope."""

    return CodingLegacyDesiredEvidenceV1(
        *decode_legacy_desired_evidence(
            raw,
            path=lifecycle.desired_state,
            product_id="coding",
            scope_id=lifecycle.scope_id,
            maximum_bytes=_MAX_DESIRED_BYTES,
            error_type=CodingLegacyDesiredError,
            label="Coding legacy",
        )
    )


__all__ = [
    "CodingLegacyDesiredError",
    "CodingLegacyDesiredEvidenceV1",
    "parse_coding_legacy_desired_evidence",
    "read_coding_legacy_desired_evidence",
]
