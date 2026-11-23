"""Plugin bootstrap/adoption coordination over existing Product owners."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import NamedTuple, TypeVar

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
    PackageProductEntrypoint,
    PackageProductLifecycleAction,
    PackageProductLifecycleIntentV1,
    PackageProductLifecycleOutcomeV1,
)

from ._application_runtime import (
    FencedOrdinaryProductApplication,
    hold_accepted_product_adoption,
)
from ._legacy_runtime import _FencedRuntime
from .product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
    WindowsLocalWheelProductSessionOwner,
)
from .product_runtime import (
    PackageProductRuntimeBindingV1,
    hold_local_wheel_product_runtime,
)

_ProductOwner = (
    PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner
)


def route_project_package(
    runtime: PackageProductRuntimeBindingV1,
    *,
    operation_id: str,
    action: PackageProductLifecycleAction,
    source: str,
    entrypoint: PackageProductEntrypoint,
) -> PackageProductLifecycleOutcomeV1:
    return runtime.lifecycle.route(
        PackageProductLifecycleIntentV1(
            operation_id=operation_id, action=action, source=source, scope="project"
        ),
        entrypoint=entrypoint,
    )


@dataclass(frozen=True, slots=True)
class _PluginBootstrapPolicy:
    product_id: str
    operation_id_prefix: str
    enable_id_prefix: str
    error_prefix: str

    def installation_key(self, scope_id: str, plugin_id: str) -> PluginInstallationKeyV1:
        return PluginInstallationKeyV1.workspace(self.product_id, scope_id, plugin_id)

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
        key = policy.installation_key(product.policy.project_scope_id, plugin_id)
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


def bootstrap_product_plugins(
    product: _ProductOwner,
    plugin_ids: tuple[str, ...],
    *,
    policy: _PluginBootstrapPolicy,
    disabled_ids: Collection[str] = (),
    require_current_admission: Callable[[], None] | None = None,
) -> bool:
    """Replay the Product's ordered first-party selections under its admission."""
    changed = False
    for plugin_id in plugin_ids:
        if require_current_admission is not None:
            require_current_admission()
        changed = bootstrap_product_plugin(
            product,
            plugin_id,
            store_id=product.epoch_runtime.registry.store_id,
            policy=policy,
            enable=plugin_id not in disabled_ids,
        ) or changed
    return changed


def bootstrap_product_plugin(
    product: _ProductOwner,
    plugin_id: str,
    *,
    store_id: str,
    policy: _PluginBootstrapPolicy,
    enable: bool = True,
) -> bool:
    desired = product.desired_state
    key = policy.installation_key(product.policy.project_scope_id, plugin_id)
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
    with hold_local_wheel_product_runtime(
        product, product_id=policy.product_id, session_id=bootstrap_id
    ) as binding:
        if current == "absent":
            source = next(
                item.source_identity
                for item in product.policy.bindings
                if item.plugin_id == plugin_id
            )
            outcome = route_project_package(
                binding,
                operation_id=operation_id,
                action="install",
                source=source,
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


def preserve_removed_product_plugin(
    product: _ProductOwner,
    key: PluginInstallationKeyV1,
    operation_id: str,
    *,
    error_prefix: str,
) -> None:
    """Replay one reviewed absent choice through existing Product management.

    A matching first transition proves the choice was already seeded; later
    operator choices are preserved. Only an empty history submits a tombstone.
    The caller owns selection, admission and the Product resource scope.
    """
    history = tuple(
        item
        for item in product.desired_state.transitions()
        if item.mutation.installation_key == key
    )
    if history:
        first = history[0]
        if (
            first.mutation.operation_id != operation_id
            or not isinstance(first.mutation, PluginDesiredStateMutationV1)
            or first.mutation.actor_id != product.actor_id
            or first.committed_state.selection.desired_state != "absent"
        ):
            raise RuntimeError(f"{error_prefix} history changed")
        return
    command = PluginManagementCommandV1(
        action="remove",
        mutation=PluginDesiredStateMutationV1(
            operation_id=operation_id,
            idempotency_key=operation_id,
            expected_inventory_revision=(
                product.desired_state.snapshot().inventory_revision
            ),
            installation_key=key,
            desired_state="absent",
            package_revision=None,
            actor_id=product.actor_id,
            policy_revision=product.desired_policy_revision,
        ),
    )
    result = product.management.submit(command)
    if result.result is None or result.result.disposition != "succeeded":
        raise RuntimeError(f"{error_prefix} tombstone refused")


def _require_reviewed_bootstrap_history(
    product: _ProductOwner,
    plugin_id: str,
    history: tuple[object, ...],
    *,
    store_id: str,
    policy: _PluginBootstrapPolicy,
    history_label: str,
) -> None:
    operation_id = policy.operation_id(store_id, plugin_id)
    command_id = product.settled_install_command_id(
        operation_id=operation_id, plugin_id=plugin_id
    )
    first = history[0]
    mutation = getattr(first, "mutation", None)
    committed = getattr(first, "committed_state", None)
    selection = getattr(committed, "selection", None)
    if (
        command_id is None
        or not isinstance(mutation, PluginDesiredStateMutationV1)
        or mutation.operation_id != command_id
        or mutation.actor_id != product.actor_id
        or getattr(selection, "desired_state", None) != "installed_disabled"
        or getattr(selection, "package_revision", None) is None
    ):
        raise RuntimeError(f"{history_label} bootstrap history changed")
    if len(history) > 1:
        second = history[1]
        second_mutation = getattr(second, "mutation", None)
        second_selection = getattr(
            getattr(second, "committed_state", None), "selection", None
        )
        if getattr(second_mutation, "actor_id", None) == product.actor_id and (
            not isinstance(second_mutation, PluginDesiredStateMutationV1)
            or not second_mutation.operation_id.startswith(policy.enable_id_prefix)
            or getattr(second_selection, "desired_state", None) != "installed_enabled"
            or getattr(second_selection, "package_revision", None)
            != getattr(selection, "package_revision", None)
        ):
            raise RuntimeError(f"{history_label} enable history changed")


def replay_reviewed_product_plugins(
    product: _ProductOwner,
    plugin_ids: tuple[str, ...],
    *,
    disabled_ids: Collection[str],
    removed_ids: Collection[str],
    operation_id_for: Callable[[str], str],
    removal_label: str,
    policy: _PluginBootstrapPolicy,
    strict_history: bool,
    history_label: str = "Product",
) -> None:
    """Replay reviewed removals before applying the remaining builtin choices.

    Strict first-adoption paths validate exact scoped history. Active-local
    continuation retains its older plugin-only history selection and yields
    to subsequent operator choices. Products choose the supported mode.
    """
    for plugin_id in removed_ids:
        removal_key = policy.installation_key(product.policy.project_scope_id, plugin_id)
        preserve_removed_product_plugin(
            product, removal_key, operation_id_for(plugin_id), error_prefix=removal_label
        )

    for plugin_id in plugin_ids:
        if plugin_id in removed_ids:
            continue
        key = (
            policy.installation_key(product.policy.project_scope_id, plugin_id)
            if strict_history
            else None
        )
        history = tuple(
            item
            for item in product.desired_state.transitions()
            if (
                item.mutation.installation_key == key
                if strict_history
                else item.mutation.installation_key.plugin_id == plugin_id
            )
        )
        if history:
            if strict_history:
                _require_reviewed_bootstrap_history(
                    product,
                    plugin_id,
                    history,
                    store_id=product.epoch_runtime.registry.store_id,
                    policy=policy,
                    history_label=history_label,
                )
            if getattr(history[-1].mutation, "actor_id", None) != product.actor_id:
                continue
        bootstrap_product_plugin(
            product,
            plugin_id,
            store_id=product.epoch_runtime.registry.store_id,
            policy=policy,
            enable=plugin_id not in disabled_ids,
        )


class ReviewedPluginChoices(NamedTuple):
    disabled_ids: Collection[str]
    removed_ids: Collection[str]
    operation_id_for: Callable[[str], str]


_EpochT = TypeVar("_EpochT", bound=_FencedRuntime)
_ReceiptT = TypeVar("_ReceiptT")


def adopt_reviewed_product_plugins(
    *,
    open_epoch: Callable[[], _EpochT],
    accept_review: Callable[[_EpochT], _ReceiptT],
    open_application: Callable[[], FencedOrdinaryProductApplication],
    reviewed_choices: Callable[[_ReceiptT], ReviewedPluginChoices],
    plugin_ids: tuple[str, ...],
    policy: _PluginBootstrapPolicy,
    removal_label: str,
    history_label: str,
) -> _ReceiptT:
    """Commit acceptance and replay the exact reviewed choices against scoped history."""
    with hold_accepted_product_adoption(
        open_epoch=open_epoch,
        accept_review=accept_review,
        open_application=open_application,
    ) as (receipt, application):
        product = application.runtime_owner.product_owner
        choices = reviewed_choices(receipt)
        replay_reviewed_product_plugins(
            product,
            plugin_ids,
            disabled_ids=choices.disabled_ids,
            removed_ids=choices.removed_ids,
            operation_id_for=choices.operation_id_for,
            removal_label=removal_label,
            policy=policy,
            strict_history=True,
            history_label=history_label,
        )
        return receipt
