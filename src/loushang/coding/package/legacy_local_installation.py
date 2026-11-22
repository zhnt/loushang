"""Internal Product transaction for one accepted legacy data-only Wheel."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from loushang.coding.plugin_manager.lifecycle import CodingPluginLifecycleStateLayout
from loushang.harness.package_product._legacy_local_migration import (
    _LegacyLocalInstallation,
    _LegacyLocalInstallPolicy,
)
from loushang.harness.plugin_management.records import (
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


class CodingLegacyLocalInstallationError(RuntimeError):
    """A reviewed local Plugin cannot be installed by this Product operation."""


_INSTALL_POLICY = _LegacyLocalInstallPolicy(
    product_id="coding",
    install_prefix="coding-legacy-local-install:",
    enable_prefix="coding-legacy-local-enable:",
    session_prefix="coding-legacy-local:",
    error_type=CodingLegacyLocalInstallationError,
)
_install_operation_id = _INSTALL_POLICY.install_operation_id
_enable_operation_id = _INSTALL_POLICY.enable_operation_id


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

    return cast(
        CodingLegacyLocalInstallReceiptV1,
        _replay_accepted_installation(
            lifecycle,
            workspace=workspace,
            plugin_id=plugin_id,
            runtime_version=runtime_version,
            runtime_protocol_epoch=runtime_protocol_epoch,
            enable=False,
        ),
    )


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

    return cast(
        CodingLegacyLocalEnablementReceiptV1,
        _replay_accepted_installation(
            lifecycle,
            workspace=workspace,
            plugin_id=plugin_id,
            runtime_version=runtime_version,
            runtime_protocol_epoch=runtime_protocol_epoch,
            enable=True,
            resource_kind=resource_kind,
        ),
    )


def _replay_accepted_installation(
    lifecycle: CodingPluginLifecycleStateLayout,
    *,
    workspace: Path,
    plugin_id: str,
    runtime_version: str,
    runtime_protocol_epoch: int,
    enable: bool,
    resource_kind: Literal["skill", "prompt", "theme"] | None = None,
) -> CodingLegacyLocalInstallReceiptV1 | CodingLegacyLocalEnablementReceiptV1:
    application = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=runtime_version,
        runtime_protocol_epoch=runtime_protocol_epoch,
    )
    with closing(application):
        accepted = _reopen_acceptance(application, lifecycle, plugin_id)
        if accepted is None or (
            enable
            and (
                accepted.resource_kind != resource_kind
                or accepted.review.desired_state != "installed_enabled"
            )
        ):
            message = (
                "Legacy local data Resource has no accepted enabled selection"
                if enable
                else "Legacy local Installation has no accepted review"
            )
            raise CodingLegacyLocalInstallationError(message)
        installation = _LegacyLocalInstallation.from_accepted_source(
            application.runtime_owner.product_owner,
            accepted,
            scope_id=lifecycle.scope_id,
            plugin_id=plugin_id,
            source_trust_class=trust_class_for_legacy_data_resource(accepted.resource_kind),
            policy=_INSTALL_POLICY,
        )
        command_id, revision = (
            installation.enable()
            if enable
            else installation.install(
                allow_enabled=accepted.review.desired_state == "installed_enabled"
            )
        )
        application.epoch_runtime.assert_current()
        if enable:
            return CodingLegacyLocalEnablementReceiptV1(
                acceptance_id=accepted.acceptance_id,
                install_operation_id=installation.install_operation_id,
                install_command_id=command_id,
                enable_operation_id=installation.enable_operation_id,
                plugin_id=plugin_id,
                package_revision=revision,
            )
        return CodingLegacyLocalInstallReceiptV1(
            acceptance_id=accepted.acceptance_id,
            operation_id=installation.install_operation_id,
            desired_command_id=command_id,
            plugin_id=plugin_id,
            package_revision=revision,
        )


def _reopen_acceptance(
    owner: CodingFencedProductApplicationOwner,
    lifecycle: CodingPluginLifecycleStateLayout,
    plugin_id: str,
) -> CodingLegacyLocalAcceptanceV1 | None:
    runtime = owner.epoch_runtime
    if not isinstance(runtime, PackageProductPosixFencedRuntimeOwner):
        raise CodingLegacyLocalInstallationError(
            "Legacy local migration requires a POSIX Product epoch"
        )
    return reopen_coding_legacy_installed_local_acceptance(
        lifecycle,
        runtime,
        plugin_id=plugin_id,
        policy_revision=CODING_PACKAGE_PRODUCT_POLICY_REVISION,
    )


__all__ = [
    "CodingLegacyLocalInstallationError",
    "CodingLegacyLocalInstallReceiptV1",
    "CodingLegacyLocalEnablementReceiptV1",
    "install_coding_accepted_legacy_local_plugin",
    "enable_coding_accepted_legacy_local_skill",
    "enable_coding_accepted_legacy_local_data_plugin",
]
