"""Replayable Product consumption of one accepted old plugin_sources entry."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from loushang.harness.config.agent import SettingsManager
from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_legacy_configured_source import (
    CodingLegacyLocalConfiguredSourceV1,
    match_coding_legacy_local_skill_configured_source,
)
from .package_legacy_installation_inventory import (
    read_coding_legacy_installation_inventory,
)
from .package_legacy_local_acceptance import (
    CodingLegacyLocalAcceptanceV1,
    reopen_coding_legacy_installed_local_acceptance,
)
from .package_legacy_source_evidence import read_coding_legacy_source_evidence
from .package_source_snapshot import _verify_loaded_settings

_MAX_RECEIPT_BYTES = 4096
_SOURCE_KEYS = frozenset(
    {"package_roots", "package_sources", "packages", "plugin_sources", "resource_roots"}
)


class CodingLegacySourceConsumptionError(RuntimeError):
    """The accepted old Source cannot be safely consumed or replayed."""


@dataclass(frozen=True, slots=True)
class _FrozenSources:
    projection_digest: str
    by_plugin: dict[str, CodingLegacyLocalConfiguredSourceV1 | None]
    ordered_paths: dict[str, tuple[str, ...]]
    raw_digests: dict[str, str]


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

    frozen = _frozen_sources(lifecycle, epoch_runtime, acceptance, settings)
    configured = frozen.by_plugin[acceptance.review.plugin_id]
    if configured is None:
        with settings.transaction():
            settled_others = _settled_other_paths(
                lifecycle, epoch_runtime, acceptance, frozen
            )
            _live_state(settings, None, frozen, settled_others)
        epoch_runtime.assert_current()
        return
    state_root = epoch_runtime.prepare_product_state_root()
    path = _receipt_path(state_root, acceptance.review.plugin_id)
    expected = _identity(acceptance, configured, frozen.projection_digest)
    with _rooted_file(state_root, path) as target:
        target.acquire_lock(exclusive=True, suffix=".lock")
        phase = _read_phase(target, expected)
        with settings.transaction():
            settled_others = _settled_other_paths(
                lifecycle, epoch_runtime, acceptance, frozen
            )
            state = _live_state(settings, configured, frozen, settled_others)
            if phase is None:
                if state != "original":
                    raise CodingLegacySourceConsumptionError(
                        "Accepted configured Source changed before consumption"
                    )
                epoch_runtime.assert_current()
                target.atomic_write(
                    _receipt_bytes(expected, "prepared"), exclusive=True
                )
                phase = "prepared"
            if phase == "settled":
                if state != "cleared":
                    raise CodingLegacySourceConsumptionError(
                        "Consumed configured Source was restored"
                    )
                epoch_runtime.assert_current()
                return
            if state == "original":
                remaining = tuple(
                    path
                    for path in frozen.ordered_paths[configured.scope]
                    if path not in settled_others and path != configured.path
                )
                settings.update_settings(
                    scope=configured.scope, plugin_sources=remaining
                )
                if (
                    _live_state(settings, configured, frozen, settled_others)
                    != "cleared"
                ):
                    raise CodingLegacySourceConsumptionError(
                        "Configured Source setting was not consumed"
                    )
            epoch_runtime.assert_current()
            target.atomic_write(_receipt_bytes(expected, "settled"))
            epoch_runtime.assert_current()


def coding_accepted_legacy_local_source_consumed(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    acceptance: CodingLegacyLocalAcceptanceV1,
    settings: SettingsManager,
) -> bool:
    """Read-only proof that the reviewed old Source no longer selects Plugins."""

    frozen = _frozen_sources(lifecycle, epoch_runtime, acceptance, settings)
    configured = frozen.by_plugin[acceptance.review.plugin_id]
    state_root = epoch_runtime.control_root / "product-state"
    if configured is not None:
        phase = _source_phase(state_root, acceptance, configured, frozen)
        if phase != "settled":
            return False
    with settings.transaction():
        settled_others = _settled_other_paths(
            lifecycle, epoch_runtime, acceptance, frozen
        )
        result = _live_state(settings, configured, frozen, settled_others) == "cleared"
    epoch_runtime.assert_current()
    return result


def _frozen_sources(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    acceptance: CodingLegacyLocalAcceptanceV1,
    settings: SettingsManager,
) -> _FrozenSources:
    evidence = read_coding_legacy_source_evidence(
        lifecycle,
        epoch_runtime,
        global_settings_path=_settings_paths(settings)[0],
        project_settings_path=_settings_paths(settings)[1],
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


def _source_phase(
    state_root: Path,
    acceptance: CodingLegacyLocalAcceptanceV1,
    configured: CodingLegacyLocalConfiguredSourceV1,
    frozen: _FrozenSources,
) -> Literal["prepared", "settled"] | None:
    path = _receipt_path(state_root, acceptance.review.plugin_id)
    try:
        with _rooted_file(state_root, path) as target:
            return _read_phase(
                target, _identity(acceptance, configured, frozen.projection_digest)
            )
    except FileNotFoundError:
        return None


def _settled_other_paths(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    acceptance: CodingLegacyLocalAcceptanceV1,
    frozen: _FrozenSources,
) -> frozenset[str]:
    state_root = epoch_runtime.control_root / "product-state"
    settled: set[str] = set()
    for plugin_id, configured in frozen.by_plugin.items():
        if configured is None or plugin_id == acceptance.review.plugin_id:
            continue
        other = reopen_coding_legacy_installed_local_acceptance(
            lifecycle,
            epoch_runtime,
            plugin_id=plugin_id,
            policy_revision=acceptance.review.policy_revision,
        )
        if other is None:
            continue
        if (
            other.review.legacy_source_identity != f"local:{configured.path}"
            or other.review.configured_plugin_source_scope != configured.scope
        ):
            raise CodingLegacySourceConsumptionError(
                "Other configured Source acceptance changed"
            )
        if _source_phase(state_root, other, configured, frozen) == "settled":
            settled.add(configured.path)
    return frozenset(settled)


def _live_state(
    settings: SettingsManager,
    configured: CodingLegacyLocalConfiguredSourceV1 | None,
    frozen: _FrozenSources,
    settled_others: frozenset[str],
) -> Literal["original", "cleared"]:
    if settings.get_session_settings():
        raise CodingLegacySourceConsumptionError(
            "Session settings cannot enter configured Source consumption"
        )
    scoped = {
        "global": settings.get_global_settings(),
        "project": settings.get_project_settings(),
    }
    state: Literal["original", "cleared"] = "cleared"
    for scope, patch in scoped.items():
        if any(patch.get(key) for key in _SOURCE_KEYS - {"plugin_sources"}):
            raise CodingLegacySourceConsumptionError(
                "Another configured Source appeared during consumption"
            )
        selected = patch.get("plugin_sources", [])
        if not isinstance(selected, list):
            raise CodingLegacySourceConsumptionError(
                "Configured Source setting changed during consumption"
            )
        original = frozen.ordered_paths[scope]
        pending = [path for path in original if path not in settled_others]
        if configured is not None and configured.scope == scope:
            without_current = [path for path in pending if path != configured.path]
            if selected == pending:
                state = "original"
            elif selected == without_current:
                state = "cleared"
            else:
                raise CodingLegacySourceConsumptionError(
                    "Configured Source setting changed during consumption"
                )
        elif selected != pending:
            raise CodingLegacySourceConsumptionError(
                "Other configured Source changed during consumption"
            )
        if original and selected == list(original):
            path = (
                _settings_paths(settings)[0]
                if scope == "global"
                else _settings_paths(settings)[1]
            )
            _present, observed = _verify_loaded_settings(path, patch)
            if observed != frozen.raw_digests[scope]:
                raise CodingLegacySourceConsumptionError(
                    "Configured Source settings changed since first fence"
                )
    return state


def _identity(
    acceptance: CodingLegacyLocalAcceptanceV1,
    configured: CodingLegacyLocalConfiguredSourceV1,
    projection_digest: str,
) -> dict[str, object]:
    return {
        "receiptVersion": 1,
        "acceptanceId": acceptance.acceptance_id,
        "reviewId": acceptance.review.review_id,
        "projectionDigest": projection_digest,
        "scope": configured.scope,
        "sourcePath": configured.path,
    }


def _receipt_path(state_root: Path, plugin_id: str) -> Path:
    return state_root / (
        "legacy-local-source-consumption-"
        + sha256(plugin_id.encode()).hexdigest()[:24]
        + ".json"
    )


def _receipt_bytes(identity: dict[str, object], phase: str) -> bytes:
    return canonical_json_bytes({**identity, "phase": phase}) + b"\n"


def _read_phase(
    target: RootedFile, identity: dict[str, object]
) -> Literal["prepared", "settled"] | None:
    try:
        raw = target.read_bytes(max_bytes=_MAX_RECEIPT_BYTES)
    except FileNotFoundError:
        return None
    if raw == _receipt_bytes(identity, "prepared"):
        return "prepared"
    if raw == _receipt_bytes(identity, "settled"):
        return "settled"
    raise CodingLegacySourceConsumptionError(
        "Configured Source consumption receipt conflicts with accepted review"
    )


def _settings_paths(settings: SettingsManager) -> tuple[Path, Path]:
    global_path = settings.global_settings_path
    project_path = settings.project_settings_path
    if not isinstance(global_path, Path) or not isinstance(project_path, Path):
        raise CodingLegacySourceConsumptionError(
            "Configured Source settings paths are required"
        )
    return global_path, project_path


@contextmanager
def _rooted_file(root: Path, path: Path) -> Iterator[RootedFile]:
    descriptor = os.open(
        root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    try:
        before = os.fstat(descriptor)
        visible = root.lstat()
        if (
            not stat.S_ISDIR(before.st_mode)
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) & 0o077
            or (before.st_dev, before.st_ino) != (visible.st_dev, visible.st_ino)
        ):
            raise CodingLegacySourceConsumptionError(
                "Configured Source Product state directory is unsafe"
            )
        file_io = RootedFileIO(root, descriptor)
        try:
            with file_io.bind(path) as target:
                yield target
        finally:
            file_io.cleanup()
    finally:
        os.close(descriptor)


__all__ = [
    "CodingLegacySourceConsumptionError",
    "coding_accepted_legacy_local_source_consumed",
    "consume_coding_accepted_legacy_local_source",
]
