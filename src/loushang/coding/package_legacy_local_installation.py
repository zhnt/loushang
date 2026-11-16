"""Internal Product transaction for one accepted legacy data-only Wheel."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

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
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_legacy_data_trust import trust_class_for_legacy_data_resource
from .package_legacy_local_acceptance import (
    CodingLegacyLocalAcceptanceV1,
    reopen_coding_legacy_installed_local_acceptance,
)
from .package_product_runtime import (
    CODING_PACKAGE_PRODUCT_POLICY_REVISION,
    CodingFencedProductApplicationOwner,
    open_coding_fenced_product_application_owner,
)


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
        return _install(owner, lifecycle, plugin_id=plugin_id)
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

    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )
    try:
        product = owner.runtime_owner.product_owner
        if not isinstance(owner.epoch_runtime, PackageProductPosixFencedRuntimeOwner):
            raise CodingLegacyLocalInstallationError(
                "Legacy local migration requires a POSIX Product epoch"
            )
        accepted = reopen_coding_legacy_installed_local_acceptance(
            lifecycle,
            owner.epoch_runtime,
            plugin_id=plugin_id,
            policy_revision=CODING_PACKAGE_PRODUCT_POLICY_REVISION,
        )
        if (
            accepted is None
            or accepted.resource_kind != resource_kind
            or accepted.review.desired_state != "installed_enabled"
        ):
            raise CodingLegacyLocalInstallationError(
                "Legacy local data Resource has no accepted enabled selection"
            )
        source = _accepted_source(owner, plugin_id, accepted)
        install_id = _install_operation_id(
            accepted.review.store_id, accepted.acceptance_id
        )
        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=lifecycle.scope_id,
            plugin_id=plugin_id,
        )
        installation = _installation(
            product,
            key,
            source.source_identity,
            accepted,
            install_operation_id=install_id,
        )
        install_command_id, revision = installation.enable()
        enable_id = installation.enable_operation_id
        owner.epoch_runtime.assert_current()
        return CodingLegacyLocalEnablementReceiptV1(
            acceptance_id=accepted.acceptance_id,
            install_operation_id=install_id,
            install_command_id=install_command_id,
            enable_operation_id=enable_id,
            plugin_id=plugin_id,
            package_revision=revision,
        )
    finally:
        owner.close()


def _install(
    owner: CodingFencedProductApplicationOwner,
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    plugin_id: str,
) -> CodingLegacyLocalInstallReceiptV1:
    product = owner.runtime_owner.product_owner
    if not isinstance(owner.epoch_runtime, PackageProductPosixFencedRuntimeOwner):
        raise CodingLegacyLocalInstallationError(
            "Legacy local migration requires a POSIX Product epoch"
        )
    accepted = reopen_coding_legacy_installed_local_acceptance(
        lifecycle,
        owner.epoch_runtime,
        plugin_id=plugin_id,
        policy_revision=CODING_PACKAGE_PRODUCT_POLICY_REVISION,
    )
    if accepted is None:
        raise CodingLegacyLocalInstallationError(
            "Legacy local Installation has no accepted review"
        )
    source = _accepted_source(owner, plugin_id, accepted)
    operation_id = _install_operation_id(
        accepted.review.store_id, accepted.acceptance_id
    )
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=lifecycle.scope_id,
        plugin_id=plugin_id,
    )
    installation = _installation(
        product,
        key,
        source.source_identity,
        accepted,
        install_operation_id=operation_id,
    )
    command_id, revision = installation.install(
        allow_enabled=accepted.review.desired_state == "installed_enabled"
    )
    owner.epoch_runtime.assert_current()
    return CodingLegacyLocalInstallReceiptV1(
        acceptance_id=accepted.acceptance_id,
        operation_id=operation_id,
        desired_command_id=command_id,
        plugin_id=plugin_id,
        package_revision=revision,
    )


def _accepted_source(
    owner: CodingFencedProductApplicationOwner,
    plugin_id: str,
    accepted: CodingLegacyLocalAcceptanceV1,
) -> PackageProductLocalWheelBindingV1:
    sources = tuple(
        item
        for item in owner.runtime_owner.product_owner.policy.bindings
        if item.plugin_id == plugin_id
        and item.source_trust_class
        == trust_class_for_legacy_data_resource(accepted.resource_kind)
        and item.artifact_digest == accepted.review.wheel_artifact_digest
        and Path(item.source_identity).name == accepted.review.wheel_filename
    )
    if len(sources) != 1:
        raise CodingLegacyLocalInstallationError(
            "Legacy local Installation has no exact Product Source binding"
        )
    return sources[0]


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
