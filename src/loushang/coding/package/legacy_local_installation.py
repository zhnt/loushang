"""Internal Product transaction for one accepted legacy data-only Wheel."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from loushang.coding.harness.package_product import legacy_installation as _programs
from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product._legacy_local_migration import (
    _LegacyLocalInstallation,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner as PackageProductPosixFencedRuntimeOwner,
)

from .legacy_data_trust import (
    trust_class_for_legacy_data_resource as trust_class_for_legacy_data_resource,
)
from .legacy_local_acceptance import (
    CodingLegacyLocalAcceptanceV1,
)
from .legacy_local_acceptance import (
    reopen_coding_legacy_installed_local_acceptance as reopen_coding_legacy_installed_local_acceptance,
)
from .product_runtime import (
    CODING_PACKAGE_PRODUCT_POLICY_REVISION as CODING_PACKAGE_PRODUCT_POLICY_REVISION,
)
from .product_runtime import (
    CodingFencedProductApplicationOwner as CodingFencedProductApplicationOwner,
)
from .product_runtime import (
    open_coding_fenced_product_application_owner,
)

_PRODUCT_ID = "coding"


class CodingLegacyLocalInstallationError(RuntimeError):
    """A reviewed local Plugin cannot be installed by this Product operation."""


@dataclass(frozen=True, slots=True)
class CodingLegacyLocalInstallReceiptV1:
    acceptance_id: str
    operation_id: str
    desired_command_id: str
    plugin_id: str
    package_revision: PluginPackageRevisionRefV1


@dataclass(frozen=True, slots=True)
class CodingLegacyLocalEnablementReceiptV1:
    acceptance_id: str
    install_operation_id: str
    install_command_id: str
    enable_operation_id: str
    plugin_id: str
    package_revision: PluginPackageRevisionRefV1


def install_coding_accepted_legacy_local_plugin(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    plugin_id: str,
    runtime_version: str,
    runtime_protocol_epoch: int,
) -> CodingLegacyLocalInstallReceiptV1:
    """Run one accepted data-only Wheel through the real B Package Product."""

    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )
    try:
        return _programs.install_accepted_plugin(owner, lifecycle, plugin_id=plugin_id)
    finally:
        owner.close()


def enable_coding_accepted_legacy_local_skill(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    plugin_id: str,
    runtime_version: str,
    runtime_protocol_epoch: int,
) -> CodingLegacyLocalEnablementReceiptV1:
    """Carry an accepted old enabled Skill into B only after its install handoff."""

    return enable_coding_accepted_legacy_local_data_plugin(
        lifecycle,
        workspace=workspace,
        plugin_id=plugin_id,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
        resource_kind="skill",
    )


def enable_coding_accepted_legacy_local_data_plugin(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    plugin_id: str,
    runtime_version: str,
    runtime_protocol_epoch: int,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> CodingLegacyLocalEnablementReceiptV1:
    """Enable one accepted, installed data Resource of the selected type."""

    return _programs.enable_accepted_data_plugin(
        lifecycle,
        workspace=workspace,
        plugin_id=plugin_id,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
        resource_kind=resource_kind,
    )


def _install_operation_id(store_id: str, acceptance_id: str) -> str:
    return (
        "coding-legacy-local-install:"
        + sha256(f"{store_id}\0{acceptance_id}".encode()).hexdigest()
    )


def _enable_operation_id(store_id: str, acceptance_id: str) -> str:
    return (
        "coding-legacy-local-enable:"
        + sha256(f"{store_id}\0{acceptance_id}".encode()).hexdigest()
    )


def _installation(
    product: PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner,
    key: PluginInstallationKeyV1,
    source_identity: str,
    accepted: CodingLegacyLocalAcceptanceV1,
    *,
    install_operation_id: str,
) -> _LegacyLocalInstallation:
    return _LegacyLocalInstallation(
        product=product,
        key=key,
        source_identity=source_identity,
        install_operation_id=install_operation_id,
        enable_operation_id=_enable_operation_id(
            accepted.review.store_id, accepted.acceptance_id
        ),
        error_type=CodingLegacyLocalInstallationError,
        session_id_prefix="coding-legacy-local:",
    )


__all__ = [
    "CodingLegacyLocalInstallationError",
    "CodingLegacyLocalInstallReceiptV1",
    "CodingLegacyLocalEnablementReceiptV1",
    "install_coding_accepted_legacy_local_plugin",
    "enable_coding_accepted_legacy_local_skill",
    "enable_coding_accepted_legacy_local_data_plugin",
]
