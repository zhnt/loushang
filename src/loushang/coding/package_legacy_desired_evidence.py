"""Read old Coding desired intent from the authenticated first-B snapshot."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.plugin_management.ledger import (
    PluginDesiredStateSnapshotV1,
    PluginLifecycleError,
    decode_plugin_desired_state_snapshot,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_legacy_snapshot_member import read_coding_first_b_snapshot_member

_MAX_DESIRED_BYTES = 2 * 1024 * 1024


class CodingLegacyDesiredError(ValueError):
    """Old desired intent cannot be projected without guessing."""


@dataclass(frozen=True, slots=True)
class CodingLegacyDesiredEvidenceV1:
    snapshot: PluginDesiredStateSnapshotV1
    journal_digest: str


def read_coding_legacy_desired_evidence(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
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

    if not isinstance(raw, bytes) or len(raw) > _MAX_DESIRED_BYTES:
        raise CodingLegacyDesiredError("Coding legacy desired journal exceeds budget")
    try:
        text = raw.decode("utf-8")
        if text and not text.endswith("\n"):
            raise ValueError("Old desired journal has an incomplete final record")
        for line in text.splitlines():
            if line.strip():
                json.loads(line, object_pairs_hook=_unique_object)
        snapshot = decode_plugin_desired_state_snapshot(
            text,
            path=lifecycle.desired_state,
        )
    except (UnicodeError, ValueError, PluginLifecycleError) as exc:
        raise CodingLegacyDesiredError(
            "Coding legacy desired state is invalid"
        ) from exc
    if any(
        state.installation_key.product_id != "coding"
        or state.installation_key.installation_scope != "workspace"
        or state.installation_key.scope_id != lifecycle.scope_id
        for state in snapshot.installations
    ):
        raise CodingLegacyDesiredError(
            "Coding legacy desired state has a foreign Installation"
        )
    return CodingLegacyDesiredEvidenceV1(
        snapshot=snapshot,
        journal_digest=sha256(raw).hexdigest(),
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Coding legacy desired state has duplicate JSON keys")
        result[key] = value
    return result


__all__ = [
    "CodingLegacyDesiredError",
    "CodingLegacyDesiredEvidenceV1",
    "parse_coding_legacy_desired_evidence",
    "read_coding_legacy_desired_evidence",
]
