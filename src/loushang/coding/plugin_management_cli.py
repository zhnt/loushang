"""Coding Product binding for transport-neutral Plugin management CLI ports."""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from loushang.coding._plugin_lifecycle import (
    _CODING_PLUGIN_RUNTIME_BOOT_ID,
    CodingPluginLifecycleStateLayout,
    _hold_process_startup_lease,
    _release_process_startup_lease,
    build_coding_plugin_management_application,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_product_management_cli import (
    CODING_CLI_MANAGEMENT_ACTOR_ID,
    CODING_CLI_MANAGEMENT_POLICY_REVISION,
    build_coding_fenced_product_management_cli_ports,
    coding_fenced_product_exists,
)
from loushang.coding.plugin_enablement_compatibility import (
    bind_coding_plugin_enablement_compatibility,
)
from loushang.coding.product_plan import CODING_PRODUCT_ID
from loushang.harness.cli.plugin_management import (
    PluginManagementCliBinding,
    PluginManagementCliProfile,
    bind_plugin_management_cli_commands,
    bind_plugin_management_cli_read,
)
from loushang.harness.plugin_management import (
    PluginManagementApplicationPorts,
    PluginManagementSourceSnapshotV1,
)
from loushang.harness.plugin_management.configured_sources import (
    ConfiguredPluginSourceIdentityConflict,
    ConfiguredPluginSourceProfile,
    project_configured_plugin_sources,
)


class CodingPluginManagementCliError(RuntimeError):
    """Stable Product failure while projecting configured Plugin Sources."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@runtime_checkable
class CodingConfiguredPluginSourceSettingsPort(Protocol):
    """Coding settings owner used only to capture the current Source list."""

    def get_settings(self) -> object: ...


@dataclass(frozen=True, slots=True)
class CodingConfiguredPluginSourceProjection:
    settings_manager: object | None
    scope_id: str
    workspace_root: Path

    def snapshot(self) -> PluginManagementSourceSnapshotV1:
        profile = ConfiguredPluginSourceProfile(
            product_id=CODING_PRODUCT_ID,
            installation_scope="workspace",
            scope_id=self.scope_id,
            workspace_root=self.workspace_root,
            source_strings=self._configured_sources(),
            owner_revision_namespace="coding-settings",
        )
        try:
            return project_configured_plugin_sources(profile)
        except ConfiguredPluginSourceIdentityConflict as exc:
            raise CodingPluginManagementCliError(
                str(exc), code="coding_plugin_source_identity_conflict"
            ) from exc

    def _configured_sources(self) -> tuple[str, ...]:
        if self.settings_manager is None:
            return ()
        if not isinstance(
            self.settings_manager, CodingConfiguredPluginSourceSettingsPort
        ):
            raise CodingPluginManagementCliError(
                "configured Plugin Source settings owner is invalid",
                code="coding_plugin_sources_owner_invalid",
            )
        settings = self.settings_manager.get_settings()
        raw_sources = getattr(settings, "plugin_sources", None)
        if not isinstance(raw_sources, (list, tuple)) or any(
            not isinstance(item, str) or not item for item in raw_sources
        ):
            raise CodingPluginManagementCliError(
                "configured Plugin Sources are invalid",
                code="coding_plugin_sources_invalid",
            )
        return tuple(sorted(set(raw_sources)))


@dataclass(frozen=True, slots=True)
class _CodingManagementReadOwner:
    layout: CodingPluginLifecycleStateLayout
    source: CodingConfiguredPluginSourceProjection
    workspace_identity: tuple[int, int] | None

    def fenced_product_exists(self) -> bool:
        if self.workspace_identity is not None:
            _assert_workspace_identity(self.source.workspace_root, self.workspace_identity)
        return coding_fenced_product_exists(self.layout)

    def open_fenced_ports(self) -> PluginManagementApplicationPorts:
        return build_coding_fenced_product_management_cli_ports(
            self.layout,
            workspace_guard=lambda: _assert_workspace_identity(
                self.source.workspace_root, self.workspace_identity
            ),
        )

    def legacy_state_exists(self) -> bool:
        if self.workspace_identity is not None:
            _assert_workspace_identity(self.source.workspace_root, self.workspace_identity)
        try:
            self.layout.root.lstat()
        except FileNotFoundError:
            return False
        return True

    def open_legacy_read_ports(self) -> PluginManagementApplicationPorts:
        if self.workspace_identity is not None:
            _assert_workspace_identity(self.source.workspace_root, self.workspace_identity)
        return build_coding_plugin_management_application(
            self.layout, source=self.source, read_only=True
        )


@dataclass(frozen=True, slots=True)
class _CodingManagementCommandOwner:
    layout: CodingPluginLifecycleStateLayout
    source: CodingConfiguredPluginSourceProjection
    settings_manager: object | None
    workspace_identity: tuple[int, int] | None

    def fenced_product_exists(self) -> bool:
        return coding_fenced_product_exists(self.layout)

    def open_fenced_ports(self) -> PluginManagementApplicationPorts:
        return build_coding_fenced_product_management_cli_ports(
            self.layout,
            workspace_guard=lambda: _assert_workspace_identity(
                self.source.workspace_root, self.workspace_identity
            ),
        )

    def acquire_legacy_startup(self) -> Callable[[], None] | None:
        if not (sys.platform.startswith("linux") or os.name == "nt"):
            return None
        if not _hold_process_startup_lease(
            self.layout, startup_id=_CODING_PLUGIN_RUNTIME_BOOT_ID
        ):
            return None
        return lambda: _release_process_startup_lease(
            self.layout, startup_id=_CODING_PLUGIN_RUNTIME_BOOT_ID
        )

    def open_legacy_ports(self) -> PluginManagementApplicationPorts:
        return build_coding_plugin_management_application(
            self.layout, source=self.source
        )

    def bind_legacy_compatibility(self) -> Callable[[], None] | None:
        compatibility = bind_coding_plugin_enablement_compatibility(
            self.layout, self.settings_manager
        )
        return None if compatibility is None else compatibility.reconcile


def _management_profile(
    layout: CodingPluginLifecycleStateLayout,
) -> PluginManagementCliProfile:
    return PluginManagementCliProfile(
        product_id=CODING_PRODUCT_ID,
        installation_scope="workspace",
        scope_id=layout.scope_id,
        actor_id=CODING_CLI_MANAGEMENT_ACTOR_ID,
        policy_revision=CODING_CLI_MANAGEMENT_POLICY_REVISION,
    )


def _capture_workspace_identity(workspace: Path) -> tuple[int, int] | None:
    try:
        metadata = workspace.lstat()
    except OSError:
        return None
    if not stat.S_ISDIR(metadata.st_mode):
        return None
    return metadata.st_dev, metadata.st_ino


def _assert_workspace_identity(
    workspace: Path, identity: tuple[int, int] | None
) -> None:
    if identity is None or _capture_workspace_identity(workspace) != identity:
        raise CodingPluginManagementCliError(
            "Coding management workspace changed",
            code="coding_management_workspace_changed",
        )
    try:
        current = workspace.resolve(strict=True)
    except OSError as exc:
        raise CodingPluginManagementCliError(
            "Coding management workspace changed",
            code="coding_management_workspace_changed",
        ) from exc
    if current != workspace:
        raise CodingPluginManagementCliError(
            "Coding management workspace changed",
            code="coding_management_workspace_changed",
        )


def build_coding_plugin_management_cli_binding(
    cwd: str | Path,
    settings_manager: object | None,
) -> PluginManagementCliBinding:
    workspace_root = Path(cwd).expanduser().resolve(strict=False)
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace_root)
    source = CodingConfiguredPluginSourceProjection(
        settings_manager=settings_manager,
        scope_id=layout.scope_id,
        workspace_root=workspace_root,
    )

    return bind_plugin_management_cli_commands(
        _management_profile(layout),
        _CodingManagementCommandOwner(
            layout, source, settings_manager, _capture_workspace_identity(workspace_root)
        ),
    )


def build_coding_plugin_management_cli_read_binding(
    cwd: str | Path,
    settings_manager: object | None,
    *,
    workspace_identity: tuple[int, int] | None = None,
) -> PluginManagementCliBinding:
    """Bind CLI listing without startup recovery or compatibility publication."""

    workspace_root = Path(cwd).expanduser().resolve(strict=False)
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace_root)
    source = CodingConfiguredPluginSourceProjection(
        settings_manager=settings_manager,
        scope_id=layout.scope_id,
        workspace_root=workspace_root,
    )
    captured_identity = _capture_workspace_identity(workspace_root)
    if workspace_identity is not None:
        _assert_workspace_identity(workspace_root, workspace_identity)
        captured_identity = workspace_identity

    return bind_plugin_management_cli_read(
        _management_profile(layout),
        _CodingManagementReadOwner(
            layout, source, captured_identity
        ),
    )


__all__ = [
    "CodingConfiguredPluginSourceProjection",
    "CodingConfiguredPluginSourceSettingsPort",
    "CodingPluginManagementCliError",
    "build_coding_plugin_management_cli_binding",
    "build_coding_plugin_management_cli_read_binding",
]
