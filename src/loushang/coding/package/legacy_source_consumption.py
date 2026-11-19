"""Replayable Product consumption of one accepted old plugin_sources entry."""

from __future__ import annotations

import json
from pathlib import Path

from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product._legacy_local_migration import (
    _FrozenSources,
    _SourceConsumptionProtocol,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from .._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .legacy_configured_source import match_coding_legacy_local_skill_configured_source
from .legacy_installation_inventory import read_coding_legacy_installation_inventory
from .legacy_local_acceptance import (
    CodingLegacyLocalAcceptanceV1,
    reopen_coding_legacy_installed_local_acceptance,
)
from .legacy_source_evidence import read_coding_legacy_source_evidence
from .source_snapshot import _verify_loaded_settings

_MAX_RECEIPT_BYTES = 4096


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


def _frozen_sources(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    acceptance: CodingLegacyLocalAcceptanceV1,
    settings: SettingsManager,
) -> _FrozenSources:
    evidence = read_coding_legacy_source_evidence(
        lifecycle,
        epoch_runtime,
        global_settings_path=_SourceConsumptionProtocol._settings_paths(
            settings, CodingLegacySourceConsumptionError
        )[0],
        project_settings_path=_SourceConsumptionProtocol._settings_paths(
            settings, CodingLegacySourceConsumptionError
        )[1],
    )
    projection = json.loads(evidence.projection_bytes)
    inventory = read_coding_legacy_installation_inventory(lifecycle, epoch_runtime)
    source_identities = tuple(
        item.binding.source_identity for item in inventory.inventory.active_local
    )
    by_plugin = {
        item.binding.plugin_id: match_coding_legacy_local_skill_configured_source(
            projection,
            source_identity=item.binding.source_identity,
            installed_source_identities=source_identities,
        )
        for item in inventory.inventory.active_local
    }
    if acceptance.review.plugin_id not in by_plugin:
        raise CodingLegacySourceConsumptionError(
            "Accepted Plugin differs from first-fence Installation"
        )
    configured = by_plugin[acceptance.review.plugin_id]
    if (
        None if configured is None else configured.scope
    ) != acceptance.review.configured_plugin_source_scope:
        raise CodingLegacySourceConsumptionError(
            "Accepted configured Source differs from first fence"
        )
    ordered_paths: dict[str, tuple[str, ...]] = {}
    raw_digests: dict[str, str] = {}
    for scope in ("global", "project"):
        layer = projection["scopes"][scope]
        paths = tuple(layer["sourcePatch"].get("plugin_sources", ()))
        ordered_paths[scope] = paths
        if paths:
            raw_digest = layer["rawSha256"]
            if not isinstance(raw_digest, str):
                raise CodingLegacySourceConsumptionError(
                    "Configured Source settings snapshot has no raw digest"
                )
            raw_digests[scope] = raw_digest
    matched = {item.path for item in by_plugin.values() if item is not None}
    if matched != set(ordered_paths["global"] + ordered_paths["project"]):
        raise CodingLegacySourceConsumptionError(
            "Installed Source set differs from configured Sources"
        )
    return _FrozenSources(
        projection_digest=evidence.projection_digest,
        by_plugin=by_plugin,
        ordered_paths=ordered_paths,
        raw_digests=raw_digests,
    )


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
    frozen = _frozen_sources(lifecycle, epoch_runtime, acceptance, settings)
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
        lambda path, patch: _verify_loaded_settings(path, patch),
        lambda identity, phase: _receipt_bytes(identity, phase),
        CodingLegacySourceConsumptionError,
        _MAX_RECEIPT_BYTES,
    )


__all__ = [
    "CodingLegacySourceConsumptionError",
    "coding_accepted_legacy_local_source_consumed",
    "consume_coding_accepted_legacy_local_source",
]
