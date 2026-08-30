"""Coding Product adapter for the common durable Plugin lifecycle."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from loushang.coding.product_plan import CODING_PRODUCT_ID
from loushang.foundation.platform_paths import PlatformPaths, resolve_platform_paths
from loushang.harness.plugin_management import (
    PluginDesiredStateLedger,
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginInstanceLeaseFamilyReleaseV1,
    PluginInstanceLeaseFamilyV1,
    PluginInstanceRuntimeLedger,
    PluginManagementCommandV1,
    PluginManagementService,
    PluginPackageRevisionRefV1,
    PluginRetirementIntentLedger,
    PluginRetirementSetLedger,
)
from loushang.harness.plugin_management.continuity_adapter import (
    PluginContinuitySecurityRetirementJournal,
)
from loushang.harness.resources.plugins import PluginInstanceRevisionRef

_PRODUCT_POLICY_REVISION = "coding-plugin-lifecycle-v1"
_DEFAULT_APPROVAL_REFERENCE = "coding-first-party-default"


class CodingPluginLifecycleError(RuntimeError):
    """Stable Product failure at the common management boundary."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingPluginLifecycleStateLayout:
    """One workspace namespace for every Coding Plugin Installation."""

    root: Path
    private_state_base: Path
    scope_id: str
    desired_state: Path
    management_operations: Path
    retirement_intents: Path
    retirement_sets: Path
    instance_runtime: Path
    package_lifecycle: Path


@dataclass(slots=True)
class CodingPluginLifecycle:
    """Installed common Harness authorities bound to Coding Product policy."""

    layout: CodingPluginLifecycleStateLayout
    desired: PluginDesiredStateLedger = field(repr=False)
    management: PluginManagementService = field(repr=False)
    instances: PluginInstanceRuntimeLedger = field(repr=False)
    security: PluginContinuitySecurityRetirementJournal = field(repr=False)

    def installation_key(self, plugin_id: str) -> PluginInstallationKeyV1:
        return PluginInstallationKeyV1(
            product_id=CODING_PRODUCT_ID,
            installation_scope="workspace",
            scope_id=self.layout.scope_id,
            plugin_id=_nonempty(plugin_id, name="Plugin id"),
        )

    def bootstrap_first_party_default(
        self,
        key: PluginInstallationKeyV1,
        package_revision: PluginPackageRevisionRefV1,
    ) -> None:
        """Install+enable only a truly unseen first-party Installation.

        An absent record retained after remove is deliberately *seen* and is
        therefore never resurrected by Product composition.
        """

        snapshot = self.desired.snapshot()
        if any(item.installation_key == key for item in snapshot.installations):
            return
        self._submit_default(
            key,
            action="install",
            desired_state="installed_disabled",
            package_revision=package_revision,
        )
        state = self.desired.snapshot().installation(key)
        if (
            state.selection.desired_state != "installed_disabled"
            or state.selection.package_revision != package_revision
        ):
            raise CodingPluginLifecycleError(
                "First-party Plugin install did not retain its exact package",
                code="coding_plugin_default_install_conflict",
            )
        self._submit_default(
            key,
            action="enable",
            desired_state="installed_enabled",
            package_revision=None,
        )

    def reconcile_retirements(self) -> None:
        """Project committed management cutovers into the Instance runtime."""

        self.security.reconcile(self.instances)
        runtime = self.instances.snapshot()
        for intent in self.management_retirement_intents():
            instance = runtime.instance(intent.instance_revision_ref)
            if instance is None or instance.state in {"REVOKING", "RETIRED"}:
                continue
            self.instances.begin_drain(intent)
            runtime = self.instances.snapshot()

    def management_retirement_intents(self):
        return PluginRetirementIntentLedger(
            self.layout.retirement_intents
        ).snapshot().intents

    def acquire_session(
        self,
        key: PluginInstallationKeyV1,
        *,
        session_id: str,
    ) -> CodingPluginSessionLease:
        self.reconcile_retirements()
        state = self.desired.snapshot().installation(key)
        ref = state.selection.instance_revision_ref
        if state.selection.desired_state != "installed_enabled" or ref is None:
            raise CodingPluginLifecycleError(
                "Plugin Installation is not selected for a new Coding Session",
                code="coding_plugin_not_enabled",
            )
        instance = self.instances.snapshot().instance(ref)
        identity = _identity(key, ref, session_id)
        if instance is None:
            instance = self.instances.activate_current(
                key,
                operation_id=f"coding-plugin-activate:{identity}",
                idempotency_key=f"coding-plugin-activate:{identity}",
                direct_host_reference=f"coding-plugin-host:{self.layout.scope_id}",
            )
        if instance.state != "ACTIVE" or instance.instance_revision_ref != ref:
            raise CodingPluginLifecycleError(
                "Selected Plugin Instance is not ACTIVE",
                code="coding_plugin_instance_not_active",
            )
        family = self.instances.acquire_current_family(
            (key,),
            lease_kind="session_membership",
            operation_id=f"coding-plugin-session:{identity}",
            idempotency_key=f"coding-plugin-session:{identity}",
            holder_reference=f"coding-session:{_nonempty(session_id, name='Session id')}",
        )
        [member] = family.members
        if member.instance_revision_ref != ref:
            release = _family_release(family)
            self.instances.release_family(release)
            raise CodingPluginLifecycleError(
                "Session lease returned another Plugin Instance Revision",
                code="coding_plugin_instance_revision_stale",
            )
        return CodingPluginSessionLease(
            lifecycle=self,
            installation_key=key,
            family=family,
            package_revision=member.package_revision,
            instance_revision_ref=member.instance_revision_ref,
        )

    def _submit_default(
        self,
        key: PluginInstallationKeyV1,
        *,
        action: Literal["install", "enable"],
        desired_state: Literal["installed_disabled", "installed_enabled"],
        package_revision: PluginPackageRevisionRefV1 | None,
    ) -> None:
        revision = self.desired.snapshot().inventory_revision
        identity = hashlib.sha256(
            repr((key, action, package_revision)).encode("utf-8")
        ).hexdigest()
        event = self.management.submit(
            PluginManagementCommandV1(
                action=action,
                mutation=PluginDesiredStateMutationV1(
                    operation_id=f"coding-default:{identity}",
                    idempotency_key=f"coding-default:{identity}",
                    expected_inventory_revision=revision,
                    installation_key=key,
                    desired_state=desired_state,
                    package_revision=package_revision,
                    actor_id="product:coding",
                    policy_revision=_PRODUCT_POLICY_REVISION,
                    approval_reference=_DEFAULT_APPROVAL_REFERENCE,
                ),
            )
        )
        result = getattr(event, "result", None)
        if result is None or result.disposition != "succeeded":
            raise CodingPluginLifecycleError(
                "First-party Plugin bootstrap management command failed",
                code=getattr(
                    result,
                    "error_code",
                    "coding_plugin_default_management_failed",
                ),
            )


@dataclass(slots=True)
class CodingPluginSessionLease:
    """One exact Plugin Instance family pinned by a Coding Session."""

    lifecycle: CodingPluginLifecycle = field(repr=False)
    installation_key: PluginInstallationKeyV1
    family: PluginInstanceLeaseFamilyV1
    package_revision: PluginPackageRevisionRefV1
    instance_revision_ref: PluginInstanceRevisionRef
    _closed: bool = field(default=False, init=False, repr=False)

    def evaluate_management_change(self) -> CodingPluginManagementChange:
        snapshot = self.lifecycle.desired.snapshot()
        state = snapshot.installation(self.installation_key)
        current_ref = state.selection.instance_revision_ref
        current_package = state.selection.package_revision
        if (
            state.selection.desired_state == "installed_enabled"
            and current_ref == self.instance_revision_ref
            and current_package == self.package_revision
        ):
            disposition: Literal["no_change", "restart_required"] = "no_change"
            reason = "selected_revision_unchanged"
        else:
            disposition = "restart_required"
            reason = {
                "absent": "plugin_removed",
                "installed_disabled": "plugin_disabled",
                "installed_enabled": "plugin_updated",
            }[state.selection.desired_state]
        return CodingPluginManagementChange(
            disposition=disposition,
            reason=reason,
            inventory_revision=snapshot.inventory_revision,
            desired_state=state.selection.desired_state,
            pinned_instance_revision_ref=self.instance_revision_ref,
            current_instance_revision_ref=current_ref,
            pinned_package_revision=self.package_revision,
            current_package_revision=current_package,
        )

    def close(self) -> None:
        if self._closed:
            return
        self.lifecycle.instances.release_family(_family_release(self.family))
        self._closed = True


@dataclass(frozen=True, slots=True)
class CodingPluginManagementChange:
    disposition: Literal["no_change", "restart_required"]
    reason: str
    inventory_revision: int
    desired_state: Literal["absent", "installed_disabled", "installed_enabled"]
    pinned_instance_revision_ref: PluginInstanceRevisionRef
    current_instance_revision_ref: PluginInstanceRevisionRef | None
    pinned_package_revision: PluginPackageRevisionRefV1
    current_package_revision: PluginPackageRevisionRefV1 | None

    def diagnostic_details(self) -> dict[str, object]:
        return {
            "currentInstanceRevisionRef": (
                None
                if self.current_instance_revision_ref is None
                else self.current_instance_revision_ref.to_dict()
            ),
            "currentPackageRevision": (
                None
                if self.current_package_revision is None
                else self.current_package_revision.to_dict()
            ),
            "desiredState": self.desired_state,
            "inventoryRevision": self.inventory_revision,
            "pinnedInstanceRevisionRef": self.pinned_instance_revision_ref.to_dict(),
            "pinnedPackageRevision": self.pinned_package_revision.to_dict(),
            "reason": self.reason,
            "restartRequired": self.disposition == "restart_required",
        }


def resolve_coding_plugin_lifecycle_state_layout(
    cwd: str | Path,
    *,
    platform_paths: PlatformPaths | None = None,
) -> CodingPluginLifecycleStateLayout:
    workspace = Path(cwd).expanduser().resolve(strict=False)
    # Keep the deployed Continuity workspace identity and location.  PLC6D
    # widens that namespace into the one Coding Product lifecycle authority;
    # changing it would silently strand existing desired-state journals.
    digest = hashlib.sha256(
        b"loushang.coding-continuity-workspace/v1\0" + os.fsencode(str(workspace))
    ).hexdigest()
    paths = platform_paths or resolve_platform_paths()
    root = paths.state / "plugins" / "coding" / "continuity" / "workspaces" / digest
    private_state_base = (
        paths.home
        if paths.state == paths.home or paths.home in paths.state.parents
        else paths.state
    )
    return CodingPluginLifecycleStateLayout(
        root=root,
        private_state_base=private_state_base,
        scope_id=f"workspace:{digest}",
        desired_state=root / "desired-state.jsonl",
        management_operations=root / "management-operations.jsonl",
        retirement_intents=root / "retirement-intents.jsonl",
        retirement_sets=root / "retirement-sets.jsonl",
        instance_runtime=root / "instance-runtime.jsonl",
        package_lifecycle=root / "package-lifecycle.jsonl",
    )


def resolve_ephemeral_coding_plugin_lifecycle_state_layout(
    session_dir: str | Path,
    *,
    cwd: str | Path,
) -> CodingPluginLifecycleStateLayout:
    """Bind non-persistent Sessions to disposable management evidence."""

    base = Path(session_dir).expanduser().resolve(strict=False)
    root = base / "plugin-state" / "coding-lifecycle"
    workspace = Path(cwd).expanduser().resolve(strict=False)
    digest = hashlib.sha256(
        b"loushang.coding-continuity-workspace/v1\0" + os.fsencode(str(workspace))
    ).hexdigest()
    return CodingPluginLifecycleStateLayout(
        root=root,
        private_state_base=base,
        scope_id=f"workspace:{digest}",
        desired_state=root / "desired-state.jsonl",
        management_operations=root / "management-operations.jsonl",
        retirement_intents=root / "retirement-intents.jsonl",
        retirement_sets=root / "retirement-sets.jsonl",
        instance_runtime=root / "instance-runtime.jsonl",
        package_lifecycle=root / "package-lifecycle.jsonl",
    )


def build_coding_plugin_lifecycle(
    layout: CodingPluginLifecycleStateLayout,
) -> CodingPluginLifecycle:
    if not isinstance(layout, CodingPluginLifecycleStateLayout):
        raise TypeError("Coding Plugin lifecycle layout is required")
    _prepare_private_state_layout(layout)
    desired = PluginDesiredStateLedger(layout.desired_state)
    intents = PluginRetirementIntentLedger(layout.retirement_intents)
    retirement_sets = PluginRetirementSetLedger(
        layout.retirement_sets,
        retirement_intents=intents,
    )
    management = PluginManagementService(
        desired_state=desired,
        operation_journal_path=layout.management_operations,
        retirement_intents=intents,
        retirement_sets=retirement_sets,
    )
    management.recover()
    security = PluginContinuitySecurityRetirementJournal.for_instance_runtime(
        layout.instance_runtime
    )
    instances = PluginInstanceRuntimeLedger(
        layout.instance_runtime,
        management_operation_journal_path=layout.management_operations,
        desired_state=desired,
        retirement_intents=intents,
        retirement_sets=retirement_sets,
        security_acceptances=security,
    )
    return CodingPluginLifecycle(
        layout=layout,
        desired=desired,
        management=management,
        instances=instances,
        security=security,
    )


def package_revision_ref(
    *,
    plugin_id: str,
    plugin_version: str | None,
    package_content_digest: str,
    dependency_lock_digest: str,
    package_source_identity: str,
) -> PluginPackageRevisionRefV1:
    return PluginPackageRevisionRefV1(
        plugin_id=plugin_id,
        plugin_version=plugin_version,
        package_content_digest=package_content_digest,
        dependency_lock_digest=dependency_lock_digest,
        package_source_identity=package_source_identity,
    )


def _family_release(
    family: PluginInstanceLeaseFamilyV1,
) -> PluginInstanceLeaseFamilyReleaseV1:
    return PluginInstanceLeaseFamilyReleaseV1(
        family_id=family.family_id,
        operation_id=f"coding-plugin-release:{family.family_id}",
        idempotency_key=f"coding-plugin-release:{family.family_id}",
        release_reference=family.holder_reference,
    )


def _identity(
    key: PluginInstallationKeyV1,
    ref: PluginInstanceRevisionRef,
    session_id: str,
) -> str:
    return hashlib.sha256(
        repr((key, ref, _nonempty(session_id, name="Session id"))).encode("utf-8")
    ).hexdigest()


def _prepare_private_state_layout(layout: CodingPluginLifecycleStateLayout) -> None:
    base = layout.private_state_base.expanduser().absolute()
    root = layout.root.expanduser().absolute()
    try:
        relative = root.relative_to(base)
    except ValueError:
        raise CodingPluginLifecycleError(
            "Coding Plugin state root is outside its private base",
            code="coding_plugin_state_permissions_failed",
        ) from None
    current = base
    _prepare_private_directory(current)
    for part in relative.parts:
        current /= part
        _prepare_private_directory(current)


def _prepare_private_directory(root: Path) -> None:
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        before = root.lstat()
        if (
            not stat.S_ISDIR(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or bool(getattr(before, "st_reparse_tag", 0))
        ):
            raise OSError("private root is not a direct directory")
        getuid = getattr(os, "getuid", None)
        if os.name == "posix" and callable(getuid) and before.st_uid != getuid():
            raise PermissionError("private root belongs to another user")
        if os.name == "posix":
            root.chmod(0o700)
        if not os.path.samestat(before, root.lstat()):
            raise OSError("private root identity changed")
    except OSError:
        raise CodingPluginLifecycleError(
            "Coding Plugin state root is not private",
            code="coding_plugin_state_permissions_failed",
        ) from None


def _nonempty(value: str, *, name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{name} must be non-empty")
    return value


__all__ = [
    "CodingPluginLifecycle",
    "CodingPluginLifecycleError",
    "CodingPluginLifecycleStateLayout",
    "CodingPluginManagementChange",
    "CodingPluginSessionLease",
    "build_coding_plugin_lifecycle",
    "package_revision_ref",
    "resolve_coding_plugin_lifecycle_state_layout",
    "resolve_ephemeral_coding_plugin_lifecycle_state_layout",
]
