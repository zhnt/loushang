"""Read old Coding desired intent from the authenticated first-B snapshot."""

from __future__ import annotations

import json as json
from dataclasses import dataclass
from hashlib import sha256 as sha256

from loushang.coding.harness.package_product import legacy_desired_evidence as _programs
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.foundation.json import _unique_json_object_hook
from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.ledger import (
    PluginDesiredStateSnapshotV1,
)
from loushang.harness.plugin_management.ledger import (
    PluginLifecycleError as PluginLifecycleError,
)
from loushang.harness.plugin_management.ledger import (
    decode_plugin_desired_state_capture as decode_plugin_desired_state_capture,
)

from .legacy_snapshot_member import (
    CodingFencedEpochRuntime,
    read_coding_first_b_snapshot_member,
)

_MAX_DESIRED_BYTES = 2 * 1024 * 1024


_LEGACY_EVIDENCE_VALUES = {
    "value_001": "Coding legacy desired journal exceeds budget",
    "value_002": "Coding legacy desired state has a foreign Installation",
    "value_003": "Old desired journal has an incomplete final record",
    "value_004": "Coding legacy desired state is invalid",
    "value_005": "coding",
}


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

    return _programs.parse_desired_evidence(raw, lifecycle=lifecycle)


_unique_object = _unique_json_object_hook(
    lambda: "Coding legacy desired state has duplicate JSON keys",
)


__all__ = [
    "CodingLegacyDesiredError",
    "CodingLegacyDesiredEvidenceV1",
    "parse_coding_legacy_desired_evidence",
    "read_coding_legacy_desired_evidence",
]
