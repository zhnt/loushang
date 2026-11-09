"""Default Plugin install/enable coordination over existing Product owners."""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.plugin_management.journal_codecs import (
    PluginDesiredStateJournalTransition,
)
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginDesiredStateTransitionV1,
    PluginInstallationKeyV1,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleIntentV1,
)

from .product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
    WindowsLocalWheelProductSessionOwner,
)
from .product_runtime import (
    PackageProductRuntimeBindingV1,
    PackageProductRuntimeRequestV1,
)

_ProductOwner = (
    PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner
)


@dataclass(frozen=True, slots=True)
class _PluginBootstrapPolicy:
    product_id: str
    operation_id_prefix: str
    enable_id_prefix: str
    error_prefix: str

    def operation_id(self, store_id: str, plugin_id: str) -> str:
        return (
            self.operation_id_prefix
            + sha256(f"{store_id}:{plugin_id}".encode()).hexdigest()
        )


def _initial_install_was_enabled(
    history: Sequence[PluginDesiredStateJournalTransition],
    initial_command: str | None,
    actor_id: str,
    enable_prefix: str,
) -> bool:
    return (
        initial_command is not None
        and len(history) >= 2
        and history[0].mutation.operation_id == initial_command
        and history[0].committed_state.selection.desired_state == "installed_disabled"
        and history[1].mutation.operation_id.startswith(enable_prefix)
        and isinstance(history[1].mutation, PluginDesiredStateMutationV1)
        and history[1].mutation.actor_id == actor_id
        and history[1].committed_state.selection.desired_state == "installed_enabled"
        and history[1].committed_state.selection.package_revision
        == history[0].committed_state.selection.package_revision
    )


def product_bootstrap_completed(
    product: _ProductOwner,
    plugin_ids: tuple[str, ...],
    *,
    store_id: str,
    policy: _PluginBootstrapPolicy,
) -> bool:
    transitions = product.desired_state.transitions()
    for plugin_id in plugin_ids:
        key = PluginInstallationKeyV1(
            product_id=policy.product_id,
            installation_scope="workspace",
            scope_id=product.policy.project_scope_id,
            plugin_id=plugin_id,
        )
        history = tuple(
            item for item in transitions if item.mutation.installation_key == key
        )
        initial_command = product.settled_install_command_id(
            operation_id=policy.operation_id(store_id, plugin_id),
            plugin_id=plugin_id,
        )
        if not _initial_install_was_enabled(
            history, initial_command, product.actor_id, policy.enable_id_prefix
        ):
            return False
    return True


def bootstrap_product_plugin(
    product: _ProductOwner,
    plugin_id: str,
    *,
    store_id: str,
    policy: _PluginBootstrapPolicy,
    enable: bool = True,
) -> bool:
    desired = product.desired_state
    key = PluginInstallationKeyV1(
        product_id=policy.product_id,
        installation_scope="workspace",
        scope_id=product.policy.project_scope_id,
        plugin_id=plugin_id,
    )
    operation_id = policy.operation_id(store_id, plugin_id)
    snapshot = desired.snapshot()
    current = snapshot.installation(key).selection.desired_state
    if current == "installed_enabled":
        return False
    if current == "installed_disabled" and enable:
        initial_command = product.settled_install_command_id(
            operation_id=operation_id,
            plugin_id=plugin_id,
        )
        history = tuple(
            item
            for item in desired.transitions()
            if item.mutation.installation_key == key
        )
        if (
            _initial_install_was_enabled(
                history, initial_command, product.actor_id, policy.enable_id_prefix
            )
            and snapshot.installation(key).selection.package_revision
            == history[0].committed_state.selection.package_revision
        ):
            # A later operator disable is now the current Product choice.
            raise RuntimeError(f"{policy.error_prefix} was superseded")
    if current == "absent" and any(
        item.installation_key == key for item in snapshot.installations
    ):
        raise RuntimeError(f"{policy.error_prefix} was removed")
    bootstrap_id = f"{policy.operation_id_prefix}{secrets.token_hex(16)}"
    factory = product.factory_for_session(
        session_id=bootstrap_id,
        cwd=product.workspace,
        runtime_id=bootstrap_id,
    )
    binding: PackageProductRuntimeBindingV1 | None = None
    try:
        binding = factory.create(
            PackageProductRuntimeRequestV1(
                product_id=policy.product_id,
                session_id=bootstrap_id,
                cwd=str(product.workspace),
            )
        )
        binding.activate()
        if current == "absent":
            source = next(
                item.source_identity
                for item in product.policy.bindings
                if item.plugin_id == plugin_id
            )
            outcome = binding.lifecycle.route(
                PackageProductLifecycleIntentV1(
                    operation_id=operation_id,
                    action="install",
                    source=source,
                    scope="project",
                ),
                entrypoint="startup",
            )
            if (
                not outcome.handled
                or outcome.record is None
                or outcome.record.lifecycle != "installed"
                or outcome.evidence.operation_id != operation_id
            ):
                failure_code = (
                    outcome.record.failure_code if outcome.record is not None else None
                ) or "no_failure_record"
                raise RuntimeError(
                    f"{policy.error_prefix} install refused: {failure_code}"
                )
        expected_command_id = product.settled_install_command_id(
            operation_id=operation_id,
            plugin_id=plugin_id,
        )
        if expected_command_id is None:
            raise RuntimeError(f"{policy.error_prefix} handoff is missing")
    finally:
        if binding is None:
            factory.dispose_unbound_runtime()
        else:
            binding.dispose_runtime()

    snapshot = desired.snapshot()
    selected = snapshot.installation(key)
    if selected.selection.desired_state != "installed_disabled":
        raise RuntimeError(f"{policy.error_prefix} selection changed")
    prior = next(
        (
            transition
            for transition in reversed(desired.transitions())
            if transition.mutation.installation_key == key
        ),
        None,
    )
    if (
        not isinstance(prior, PluginDesiredStateTransitionV1)
        or prior.mutation.operation_id != expected_command_id
        or prior.mutation.actor_id != product.actor_id
        or prior.committed_state != selected
    ):
        raise RuntimeError(f"{policy.error_prefix} was superseded")
    if not enable:
        return current == "absent"
    enable_id = (
        policy.enable_id_prefix
        + sha256(f"{operation_id}:{snapshot.inventory_revision}".encode()).hexdigest()
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
        raise RuntimeError(f"{policy.error_prefix} enable refused")
    return True
