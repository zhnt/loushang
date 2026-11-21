"""Replayable Product consumption of one accepted old plugin_sources entry."""

from __future__ import annotations

import json as json
from pathlib import Path

from loushang.coding.harness.package_product import (
    legacy_source_consumption as _programs,
)
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product._legacy_local_migration import (
    _SourceConsumptionProtocol,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from .legacy_configured_source import (
    match_coding_legacy_local_skill_configured_source as match_coding_legacy_local_skill_configured_source,
)
from .legacy_installation_inventory import (
    read_coding_legacy_installation_inventory as read_coding_legacy_installation_inventory,
)
from .legacy_local_acceptance import (
    CodingLegacyLocalAcceptanceV1,
    reopen_coding_legacy_installed_local_acceptance,
)
from .legacy_source_evidence import (
    read_coding_legacy_source_evidence as read_coding_legacy_source_evidence,
)
from .source_snapshot import _CONSUMPTION_BLOCKING_SOURCE_KEYS, _source_projection

_MAX_RECEIPT_BYTES = 4096


_LEGACY_PROGRAM_VALUES = {
    "value_001": "Accepted Plugin differs from first-fence Installation",
    "value_002": "Accepted configured Source differs from first fence",
    "value_003": "Installed Source set differs from configured Sources",
    "value_004": "Configured Source settings snapshot has no raw digest",
}


class CodingLegacySourceConsumptionError(RuntimeError):
    """The accepted old Source cannot be safely consumed or replayed."""


def consume_coding_accepted_legacy_local_source(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    acceptance: CodingLegacyLocalAcceptanceV1,
    settings: SettingsManager,
) -> None:
    """Record intent, clear exactly one old setting, then record completion.

    A crash after intent or after the settings write can be replayed. An
    unrecognized live settings change is never overwritten.
    """

    _consumption_protocol(lifecycle, epoch_runtime, acceptance, settings).consume()


def coding_accepted_legacy_local_source_consumed(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    acceptance: CodingLegacyLocalAcceptanceV1,
    settings: SettingsManager,
) -> bool:
    """Read-only proof that the reviewed old Source no longer selects Plugins."""

    return _consumption_protocol(
        lifecycle, epoch_runtime, acceptance, settings
    ).consumed()


def _receipt_bytes(identity: dict[str, object], phase: str) -> bytes:
    return canonical_json_bytes({**identity, "phase": phase}) + b"\n"


def _receipt_path(state_root: Path, plugin_id: str) -> Path:
    return _SourceConsumptionProtocol._receipt_path(state_root, plugin_id)


def _consumption_protocol(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    acceptance: CodingLegacyLocalAcceptanceV1,
    settings: SettingsManager,
) -> _SourceConsumptionProtocol:
    frozen = _programs.frozen_sources(lifecycle, epoch_runtime, acceptance, settings)
    return _SourceConsumptionProtocol(
        epoch_runtime,
        acceptance,
        settings,
        frozen,
        lambda plugin_id: reopen_coding_legacy_installed_local_acceptance(
            lifecycle,
            epoch_runtime,
            plugin_id=plugin_id,
            policy_revision=acceptance.review.policy_revision,
        ),
        _source_projection,
        _CONSUMPTION_BLOCKING_SOURCE_KEYS,
        lambda identity, phase: _receipt_bytes(identity, phase),
        CodingLegacySourceConsumptionError,
        _MAX_RECEIPT_BYTES,
    )


__all__ = [
    "CodingLegacySourceConsumptionError",
    "coding_accepted_legacy_local_source_consumed",
    "consume_coding_accepted_legacy_local_source",
]
