"""Internal Product transaction for one accepted legacy data-only Wheel."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
    PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginDesiredStateTransitionV1,
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleIntentV1,
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
        install_command_id = product.settled_install_command_id(
            operation_id=install_id, plugin_id=plugin_id
        )
        if install_command_id is None:
            raise CodingLegacyLocalInstallationError(
                "Legacy local Product install handoff is not settled"
            )
        key = PluginInstallationKeyV1(
            product_id="coding",
            installation_scope="workspace",
            scope_id=lifecycle.scope_id,
            plugin_id=plugin_id,
        )
        snapshot = product.desired_state.snapshot()
        selected = snapshot.installation(key)
        revision = selected.selection.package_revision
        if (
            revision is None
            or revision.package_source_identity != source.source_identity
            or selected.selection.desired_state
            not in {"installed_disabled", "installed_enabled"}
        ):
            raise CodingLegacyLocalInstallationError(
                "Legacy local Product Installation selection changed"
            )
        enable_id = _enable_operation_id(
            accepted.review.store_id, accepted.acceptance_id
        )
        transitions = tuple(
            transition
            for transition in product.desired_state.transitions()
            if transition.mutation.installation_key == key
        )
        if (
            not transitions
            or not isinstance(transitions[0], PluginDesiredStateTransitionV1)
            or transitions[0].mutation.operation_id != install_command_id
            or transitions[0].mutation.actor_id != product.actor_id
            or transitions[0].committed_state.selection.desired_state
            != "installed_disabled"
            or transitions[0].committed_state.selection.package_revision != revision
        ):
            raise CodingLegacyLocalInstallationError(
                "Legacy local Product install was superseded"
            )
        if selected.selection.desired_state == "installed_enabled":
            if (
                len(transitions) != 2
                or not isinstance(transitions[1], PluginDesiredStateTransitionV1)
                or transitions[1].mutation.operation_id != enable_id
                or transitions[1].mutation.actor_id != product.actor_id
                or transitions[1].committed_state != selected
            ):
                raise CodingLegacyLocalInstallationError(
                    "Legacy local Product enablement was independently changed"
                )
        else:
            if len(transitions) != 1 or transitions[0].committed_state != selected:
                raise CodingLegacyLocalInstallationError(
                    "Legacy local Product disablement was independently changed"
                )
            enabled = product.management.submit(
                PluginManagementCommandV1(
                    action="enable",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id=enable_id,
                        idempotency_key=enable_id,
                        expected_inventory_revision=snapshot.inventory_revision,
                        installation_key=key,
                        desired_state="installed_enabled",
                        package_revision=None,
                        actor_id=product.actor_id,
                        policy_revision=product.desired_policy_revision,
                    ),
                )
            )
            if enabled.result is None or enabled.result.disposition != "succeeded":
                raise CodingLegacyLocalInstallationError(
                    "Legacy local Product enablement refused"
                )
            selected = product.desired_state.snapshot().installation(key)
            if (
                selected.selection.desired_state != "installed_enabled"
                or selected.selection.package_revision != revision
            ):
                raise CodingLegacyLocalInstallationError(
                    "Legacy local Product enablement handoff changed"
                )
        final_transitions = tuple(
            transition
            for transition in product.desired_state.transitions()
            if transition.mutation.installation_key == key
        )
        if (
            len(final_transitions) != 2
            or not isinstance(final_transitions[1], PluginDesiredStateTransitionV1)
            or final_transitions[1].mutation.operation_id != enable_id
            or final_transitions[1].mutation.actor_id != product.actor_id
            or final_transitions[1].committed_state != selected
            or product.desired_state.snapshot().installation(key) != selected
        ):
            raise CodingLegacyLocalInstallationError(
                "Legacy local Product enablement was superseded"
            )
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
    initial = product.desired_state.snapshot()
    prior_state = next(
        (item for item in initial.installations if item.installation_key == key), None
    )
    if prior_state is not None and prior_state.selection.desired_state not in {
        "installed_disabled",
        "installed_enabled",
    }:
        raise CodingLegacyLocalInstallationError(
            "Legacy local Product Desired State was independently changed"
        )
    if prior_state is None:
        _route_install(owner, operation_id=operation_id, source=source.source_identity)
    command_id = product.settled_install_command_id(
        operation_id=operation_id, plugin_id=plugin_id
    )
    if command_id is None:
        raise CodingLegacyLocalInstallationError(
            "Legacy local Product install handoff is not settled"
        )
    selected = product.desired_state.snapshot().installation(key)
    if (
        selected.selection.desired_state
        not in {"installed_disabled", "installed_enabled"}
        or selected.selection.package_revision is None
        or selected.selection.package_revision.package_source_identity
        != source.source_identity
    ):
        raise CodingLegacyLocalInstallationError(
            "Legacy local Product Installation selection changed"
        )
    transitions = tuple(
        transition
        for transition in product.desired_state.transitions()
        if transition.mutation.installation_key == key
    )
    if (
        not transitions
        or not isinstance(transitions[0], PluginDesiredStateTransitionV1)
        or transitions[0].mutation.operation_id != command_id
        or transitions[0].mutation.actor_id != product.actor_id
        or transitions[0].committed_state.selection.desired_state
        != "installed_disabled"
        or transitions[0].committed_state.selection.package_revision
        != selected.selection.package_revision
    ):
        raise CodingLegacyLocalInstallationError(
            "Legacy local Product install was superseded"
        )
    if selected.selection.desired_state == "installed_disabled":
        if len(transitions) != 1 or transitions[0].committed_state != selected:
            raise CodingLegacyLocalInstallationError(
                "Legacy local Product disablement was independently changed"
            )
    elif (
        accepted.review.desired_state != "installed_enabled"
        or len(transitions) != 2
        or not isinstance(transitions[1], PluginDesiredStateTransitionV1)
        or transitions[1].mutation.operation_id
        != _enable_operation_id(accepted.review.store_id, accepted.acceptance_id)
        or transitions[1].mutation.actor_id != product.actor_id
        or transitions[1].committed_state != selected
    ):
        raise CodingLegacyLocalInstallationError(
            "Legacy local Product enablement was independently changed"
        )
    owner.epoch_runtime.assert_current()
    return CodingLegacyLocalInstallReceiptV1(
        acceptance_id=accepted.acceptance_id,
        operation_id=operation_id,
        desired_command_id=command_id,
        plugin_id=plugin_id,
        package_revision=selected.selection.package_revision,
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


def _route_install(
    owner: CodingFencedProductApplicationOwner,
    *,
    operation_id: str,
    source: str,
) -> None:
    product = owner.runtime_owner.product_owner
    session_id = "coding-legacy-local:" + secrets.token_hex(16)
    factory = product.factory_for_session(
        session_id=session_id,
        cwd=product.workspace,
        runtime_id=session_id,
    )
    binding: PackageProductRuntimeBindingV1 | None = None
    try:
        binding = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id=session_id, cwd=str(product.workspace)
            )
        )
        binding.activate()
        outcome = binding.lifecycle.route(
            PackageProductLifecycleIntentV1(
                operation_id=operation_id,
                action="install",
                source=source,
                scope="project",
            ),
            entrypoint="operations",
        )
        if (
            not outcome.handled
            or outcome.record is None
            or outcome.record.lifecycle != "installed"
            or outcome.evidence is None
            or outcome.evidence.operation_id != operation_id
        ):
            raise CodingLegacyLocalInstallationError(
                "Legacy local Product Package install refused"
            )
    finally:
        if binding is None:
            factory.dispose_unbound_runtime()
        else:
            binding.dispose_runtime()


__all__ = [
    "CodingLegacyLocalInstallationError",
    "CodingLegacyLocalInstallReceiptV1",
    "CodingLegacyLocalEnablementReceiptV1",
    "install_coding_accepted_legacy_local_plugin",
    "enable_coding_accepted_legacy_local_skill",
    "enable_coding_accepted_legacy_local_data_plugin",
]
