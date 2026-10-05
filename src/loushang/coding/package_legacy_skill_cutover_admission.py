"""Pre-fence admission for old local Skills under the frozen B snapshot."""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from loushang.harness.plugin_authoring.resource_item import (
    ResourceItemDeclarationPayload,
)
from loushang.harness.resources._descriptor_parsing import (
    _prompt_descriptor_from_text,
    _skill_descriptor_from_text,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverSnapshotReceiptV1,
    PackagePosixEpochCutoverError,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.plugins.declarations import (
    PluginDeclarationDocumentCodec,
)
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.resources.theme_document import parse_theme_document_v1

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_legacy_configured_source import (
    match_coding_legacy_local_skill_configured_source,
)
from .package_legacy_desired_evidence import (
    parse_coding_legacy_desired_evidence,
    read_coding_legacy_desired_evidence,
)
from .package_legacy_installation_inventory import (
    classify_coding_legacy_installations,
    classify_coding_legacy_removed_local_installations,
    read_coding_legacy_installation_inventory,
)
from .package_legacy_instance_evidence import (
    parse_coding_legacy_retired_instance_capture,
)
from .package_legacy_local_wheel import (
    CodingLegacyLocalWheelCandidateV1,
    reacquire_coding_legacy_local_plugin_wheel,
)
from .package_legacy_lock_evidence import (
    parse_coding_legacy_local_binding_heads,
    read_coding_legacy_local_binding_heads,
)
from .package_legacy_operation_evidence import (
    CodingLegacyRetirementCaptureV1,
    classify_coding_legacy_management_members,
    parse_coding_legacy_operation_evidence,
)
from .package_legacy_reacquisition import (
    reacquire_coding_legacy_installed_local_source,
)
from .package_legacy_snapshot_member import (
    CodingLegacyEvidenceDomain,
    CodingLegacyInventoryDomain,
    list_coding_first_b_snapshot_domain_members,
    read_coding_first_b_snapshot_member,
)
from .package_pre_b_snapshot import CodingPreBSnapshotPreparation

_SKILL_PATH = re.compile(r"[A-Za-z0-9._-]+/skills/[A-Za-z0-9._-]+/SKILL\.md\Z")
_PROMPT_PATH = re.compile(r"[A-Za-z0-9._-]+/prompts/[A-Za-z0-9._-]+\.md\Z")
_THEME_PATH = re.compile(r"[A-Za-z0-9._-]+/themes/[A-Za-z0-9._-]+\.json\Z")
# Each member is reacquired and rebuilt while the first-fence lock is held.
_MAX_LOCAL_DATA_PLUGINS = 16
_REMOVABLE_BUILTIN_PLUGIN_IDS = frozenset(
    {"coding.base", "coding.lsp.default", "coding.arch.default"}
)


@dataclass(frozen=True, slots=True)
class CodingLegacyLocalDataWheelInspectionV1:
    resource_kind: Literal["skill", "prompt", "theme"]
    canonical_name: str


def admit_coding_single_legacy_skill_snapshot(
    lifecycle: CodingPluginLifecycleStateLayout,
    prepared: CodingPreBSnapshotPreparation,
    snapshot: PackageEpochCutoverSnapshotReceiptV1,
    *,
    plugin_id: str,
    resource_kind: Literal["skill", "prompt", "theme"] = "skill",
) -> None:
    """Verify the whole old data Resource set while cutover holds quiescence.

    The function name predates multi-Skill admission; ``plugin_id`` must name
    one member of the verified set before its review command continues.
    """

    if not isinstance(lifecycle, CodingPluginLifecycleStateLayout):
        raise TypeError("Coding lifecycle layout is required")
    if not isinstance(prepared, CodingPreBSnapshotPreparation):
        raise TypeError("Coding pre-B snapshot preparation is required")
    if not isinstance(snapshot, PackageEpochCutoverSnapshotReceiptV1):
        raise TypeError("Package snapshot receipt is required")
    if not isinstance(plugin_id, str) or not plugin_id:
        raise ValueError("Coding legacy Plugin identity is required")
    if resource_kind not in {"skill", "prompt", "theme"}:
        raise ValueError("Unsupported legacy Resource type")
    owner = prepared.owner
    receipt_id = snapshot.receipt_id
    try:
        evidence = owner.snapshot(receipt_id)
        if (
            evidence is None
            or evidence.snapshot != snapshot
            or prepared.legacy_classification.kind != "legacy_state"
            or owner.list_domain_members(receipt_id, domain="binding_history")
            != ("package-lock.json",)
            or owner.list_domain_members(receipt_id, domain="source_configuration")
            != ("coding-source-configuration.json",)
            or owner.list_domain_members(receipt_id, domain="enablement_state") != ()
        ):
            raise ValueError("Legacy Skill snapshot shape is unsupported")
        lock_members = (
            owner.list_domain_members(receipt_id, domain="lock_history") or ()
        )
        instance_members = (
            owner.list_domain_members(receipt_id, domain="instance_state") or ()
        )
        has_operations = classify_coding_legacy_management_members(
            desired_members=owner.list_domain_members(
                receipt_id, domain="desired_state"
            )
            or (),
            instance_members=instance_members,
            lock_members=lock_members,
            allow_retirement=True,
            allow_retired_runtime=True,
        )
        if (
            "package-lock.json.lock" in lock_members
            and owner.read_regular_member(
                receipt_id,
                domain="lock_history",
                member_name="package-lock.json.lock",
                maximum_bytes=8,
            )
            != b"\0"
        ):
            raise ValueError("Legacy Package lock changed")
        source_raw = owner.read_regular_member(
            receipt_id,
            domain="source_configuration",
            member_name="coding-source-configuration.json",
        )
        lock_raw = owner.read_regular_member(
            receipt_id,
            domain="binding_history",
            member_name="package-lock.json",
        )
        desired_raw = owner.read_regular_member(
            receipt_id,
            domain="desired_state",
            member_name="desired-state.jsonl",
        )
        if source_raw is None or lock_raw is None or desired_raw is None:
            raise ValueError("Legacy Skill snapshot members are incomplete")
        source = json.loads(source_raw)
        bindings = parse_coding_legacy_local_binding_heads(lock_raw)
        desired = parse_coding_legacy_desired_evidence(desired_raw, lifecycle=lifecycle)
        if has_operations:
            management_locks: tuple[tuple[CodingLegacyEvidenceDomain, str], ...] = (
                ("desired_state", "desired-state.jsonl.lock"),
                ("desired_state", "management-operations.jsonl.lock"),
                ("instance_state", "retirement-intents.jsonl.lock"),
                ("instance_state", "retirement-sets.jsonl.lock"),
            )
            if "instance-runtime.jsonl" in instance_members:
                management_locks += (
                    ("instance_state", "instance-runtime.jsonl.lock"),
                    (
                        "instance_state",
                        "instance-runtime.security-acceptances.jsonl.lock",
                    ),
                )
            for domain, name in management_locks:
                if (
                    owner.read_regular_member(
                        receipt_id,
                        domain=domain,
                        member_name=name,
                        maximum_bytes=8,
                    )
                    != b"\0"
                ):
                    raise ValueError("Legacy management lock changed")
            operations_raw = owner.read_regular_member(
                receipt_id,
                domain="desired_state",
                member_name="management-operations.jsonl",
                maximum_bytes=2 * 1024 * 1024,
            )
            if operations_raw is None:
                raise ValueError("Legacy management operation journal is missing")
            retirements = None
            if "retirement-intents.jsonl" in instance_members:
                intents_raw = owner.read_regular_member(
                    receipt_id,
                    domain="instance_state",
                    member_name="retirement-intents.jsonl",
                    maximum_bytes=2 * 1024 * 1024,
                )
                sets_raw = owner.read_regular_member(
                    receipt_id,
                    domain="instance_state",
                    member_name="retirement-sets.jsonl",
                    maximum_bytes=2 * 1024 * 1024,
                )
                if intents_raw is None or sets_raw is None:
                    raise ValueError("Legacy retirement journals are missing")
                retirements = CodingLegacyRetirementCaptureV1(
                    intents_raw=intents_raw,
                    sets_raw=sets_raw,
                    intents_path=lifecycle.retirement_intents,
                    sets_path=lifecycle.retirement_sets,
                )
            parse_coding_legacy_operation_evidence(
                operations_raw,
                desired=desired,
                path=lifecycle.management_operations,
                retirements=retirements,
            )
            if "instance-runtime.jsonl" in instance_members:
                runtime_raw = owner.read_regular_member(
                    receipt_id,
                    domain="instance_state",
                    member_name="instance-runtime.jsonl",
                    maximum_bytes=2 * 1024 * 1024,
                )
                if runtime_raw is None or retirements is None:
                    raise ValueError("Legacy Instance evidence is missing")
                parse_coding_legacy_retired_instance_capture(
                    runtime_raw,
                    intents_raw=retirements.intents_raw,
                    sets_raw=retirements.sets_raw,
                    desired=desired,
                    lifecycle=lifecycle,
                )
        inventory = classify_coding_legacy_installations(
            bindings, desired, scope_id=lifecycle.scope_id
        )
        removed_local = (
            classify_coding_legacy_removed_local_installations(
                bindings, desired, scope_id=lifecycle.scope_id
            )
            if inventory.unselected_source_identities
            else ()
        )
        removed_local_ids = {item.binding.plugin_id for item in removed_local}
        if (
            not 0 < len(inventory.active_local) <= _MAX_LOCAL_DATA_PLUGINS
            or plugin_id
            not in {item.binding.plugin_id for item in inventory.active_local}
            or any(
                item not in _REMOVABLE_BUILTIN_PLUGIN_IDS | removed_local_ids
                for item in inventory.removed_plugin_ids
            )
        ):
            raise ValueError("Legacy data Installation set is unsupported")
        canonical_names: set[tuple[str, str]] = set()
        source_identities = tuple(
            item.binding.source_identity for item in inventory.active_local
        )
        for installation in inventory.active_local:
            binding = installation.binding
            if not binding.source_identity.startswith("local:/"):
                raise ValueError("Legacy Skill Source is not local")
            match_coding_legacy_local_skill_configured_source(
                source,
                source_identity=binding.source_identity,
                installed_source_identities=source_identities,
            )
            with TemporaryDirectory(prefix="loushang-legacy-pre-fence-") as staging:
                wheel = reacquire_coding_legacy_local_plugin_wheel(
                    Path(binding.source_identity.removeprefix("local:")),
                    legacy_package_root=lifecycle.package_root,
                    staging_parent=Path(staging),
                    plugin_id=binding.plugin_id,
                    expected_source_identity=binding.source_identity,
                    expected_content_digest=binding.content_digest,
                    expected_manifest_digest=binding.manifest_digest,
                    expected_dependency_lock=binding.dependency_lock,
                )
            inspected = inspect_coding_legacy_local_data_wheel(wheel)
            if (
                binding.plugin_id == plugin_id
                and inspected.resource_kind != resource_kind
            ):
                raise ValueError("Legacy data Resource type changed")
            identity = (inspected.resource_kind, inspected.canonical_name)
            if identity in canonical_names:
                raise ValueError("Legacy data names conflict across Installations")
            canonical_names.add(identity)
    except PackagePosixEpochCutoverError:
        raise
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        raise PackagePosixEpochCutoverError(
            "Coding legacy data snapshot cannot be admitted before first fence",
            code=(
                "coding_legacy_skill_snapshot_refused"
                if resource_kind == "skill"
                else (
                    "coding_legacy_prompt_snapshot_refused"
                    if resource_kind == "prompt"
                    else "coding_legacy_theme_snapshot_refused"
                )
            ),
        ) from exc


def require_coding_fenced_single_legacy_skill_snapshot(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
) -> None:
    """Check frozen old inputs without depending on the original live Source."""

    checks: tuple[tuple[CodingLegacyInventoryDomain, tuple[str, ...]], ...] = (
        ("binding_history", ("package-lock.json",)),
        ("source_configuration", ("coding-source-configuration.json",)),
        ("enablement_state", ()),
    )
    for domain, expected in checks:
        if (
            list_coding_first_b_snapshot_domain_members(
                lifecycle, epoch_runtime, domain=domain
            )
            != expected
        ):
            raise ValueError("Coding first-B local Skill snapshot is unsupported")
    classify_coding_legacy_management_members(
        desired_members=list_coding_first_b_snapshot_domain_members(
            lifecycle, epoch_runtime, domain="desired_state"
        ),
        instance_members=list_coding_first_b_snapshot_domain_members(
            lifecycle, epoch_runtime, domain="instance_state"
        ),
        lock_members=list_coding_first_b_snapshot_domain_members(
            lifecycle, epoch_runtime, domain="lock_history"
        ),
        allow_retirement=True,
        allow_retired_runtime=True,
    )
    source_raw = read_coding_first_b_snapshot_member(
        lifecycle,
        epoch_runtime,
        domain="source_configuration",
        member_name="coding-source-configuration.json",
        maximum_bytes=2 * 1024 * 1024,
    )
    if source_raw is None:
        raise ValueError("Coding first-B Source configuration is missing")
    source = json.loads(source_raw)
    inventory = read_coding_legacy_installation_inventory(
        lifecycle, epoch_runtime
    ).inventory
    removed_local_ids: set[str] = set()
    if inventory.unselected_source_identities:
        desired = read_coding_legacy_desired_evidence(lifecycle, epoch_runtime)
        if desired is None:
            raise ValueError("Coding first-B Desired history is missing")
        removed_local_ids = {
            item.binding.plugin_id
            for item in classify_coding_legacy_removed_local_installations(
                read_coding_legacy_local_binding_heads(lifecycle, epoch_runtime),
                desired,
                scope_id=lifecycle.scope_id,
            )
        }
    if (
        not 0 < len(inventory.active_local) <= _MAX_LOCAL_DATA_PLUGINS
        or plugin_id not in {item.binding.plugin_id for item in inventory.active_local}
        or any(
            item not in _REMOVABLE_BUILTIN_PLUGIN_IDS | removed_local_ids
            for item in inventory.removed_plugin_ids
        )
    ):
        raise ValueError("Coding first-B Installation set is unsupported")
    source_identities = tuple(
        item.binding.source_identity for item in inventory.active_local
    )
    for installation in inventory.active_local:
        match_coding_legacy_local_skill_configured_source(
            source,
            source_identity=installation.binding.source_identity,
            installed_source_identities=source_identities,
        )
    epoch_runtime.assert_current()


def require_coding_fenced_single_legacy_skill(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
) -> None:
    """Also reacquire the exact live Skill before first public acceptance."""

    require_coding_fenced_single_legacy_data(
        lifecycle,
        epoch_runtime,
        plugin_id=plugin_id,
        resource_kind="skill",
    )


def require_coding_fenced_single_legacy_data(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> None:
    """Reacquire exact live bytes and enforce the operator's selected type."""

    if resource_kind not in {"skill", "prompt", "theme"}:
        raise ValueError("Unsupported legacy Resource type")

    require_coding_fenced_single_legacy_skill_snapshot(
        lifecycle, epoch_runtime, plugin_id=plugin_id
    )
    reacquired = reacquire_coding_legacy_installed_local_source(
        lifecycle, epoch_runtime, plugin_id=plugin_id
    )
    inspected = inspect_coding_legacy_local_data_wheel(reacquired.wheel)
    if inspected.resource_kind != resource_kind:
        raise ValueError("Legacy data Resource type changed")
    epoch_runtime.assert_current()


def inspect_coding_legacy_local_data_wheel(
    wheel: CodingLegacyLocalWheelCandidateV1,
) -> CodingLegacyLocalDataWheelInspectionV1:
    """Inspect inert reacquired bytes; Product migration still needs its own gate."""

    if (
        not isinstance(wheel, CodingLegacyLocalWheelCandidateV1)
        or not isinstance(wheel.wheel_bytes, bytes)
        or sha256(wheel.wheel_bytes).hexdigest() != wheel.artifact_digest
    ):
        raise ValueError("Legacy data Wheel digest is invalid")
    root = wheel.plugin_manifest_path.removesuffix("/plugin.json")
    if (
        re.fullmatch(r"loushang_legacy_[0-9a-f]{24}", root) is None
        or wheel.filename != f"{root}-1-py3-none-any.whl"
        or wheel.requested_package != f"{root.replace('_', '-')}==1"
    ):
        raise ValueError("Legacy Skill Wheel identity is unsupported")
    dist_info = f"{root}-1.dist-info"
    fixed = {
        f"{root}/plugin.json",
        f"{root}/declarations/resources.json",
        f"{dist_info}/WHEEL",
        f"{dist_info}/METADATA",
        f"{dist_info}/RECORD",
    }
    with zipfile.ZipFile(BytesIO(wheel.wheel_bytes)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or len(names) != len(fixed) + 1:
            raise ValueError("Legacy Skill Wheel members are unsupported")
        [body_path] = tuple(name for name in names if name not in fixed)
        if _SKILL_PATH.fullmatch(body_path) is not None:
            resource_kind: Literal["skill", "prompt", "theme"] = "skill"
        elif _PROMPT_PATH.fullmatch(body_path) is not None:
            resource_kind = "prompt"
        elif _THEME_PATH.fullmatch(body_path) is not None:
            resource_kind = "theme"
        else:
            raise ValueError("Legacy data Wheel contains unsupported Resource members")
        if (
            not body_path.startswith(f"{root}/")
            or set(names) != fixed | {body_path}
            or any(archive.getinfo(name).external_attr >> 16 & 0o111 for name in names)
        ):
            raise ValueError("Legacy data Wheel contains unsupported members")
        files = {name: archive.read(name) for name in names}
    manifest = PluginManifestParser().parse_file_set(
        files, manifest_logical_path=wheel.plugin_manifest_path
    )
    if (
        manifest.name != wheel.plugin_id
        or manifest.version != "1"
        or len(manifest.contribution_index.items) != 1
    ):
        raise ValueError("Legacy Skill manifest is unsupported")
    reservation = manifest.contribution_index.items[0]
    if (
        reservation.kind != "resource_item"
        or reservation.owner != f"resources.{resource_kind}"
        or reservation.contribution_execution_model != "data_only"
        or reservation.declaration_source.kind != "document"
        or reservation.declaration_source.relative_path.as_posix()
        != "declarations/resources.json"
        or reservation.requested_authorities
        or reservation.configuration
        or reservation.worker_configuration is not None
    ):
        raise ValueError("Legacy Skill contribution is unsupported")
    document = PluginDeclarationDocumentCodec.decode_bytes(
        files[f"{root}/declarations/resources.json"]
    )
    if len(document.declarations) != 1:
        raise ValueError("Legacy data declaration is unsupported")
    declaration = document.declarations[0]
    payload = ResourceItemDeclarationPayload.from_dict(dict(declaration.payload))
    if (
        declaration.plugin_id != wheel.plugin_id
        or declaration.contribution_id != reservation.contribution_id
        or declaration.kind != reservation.kind
        or declaration.owner != reservation.owner
        or declaration.reservation_fingerprint != reservation.fingerprint
        or declaration.source_descriptor_fingerprint
        != reservation.source_descriptor_fingerprint
        or declaration.source_kind != "document"
        or declaration.contribution_execution_model not in (None, "data_only")
        or declaration.worker_configuration is not None
        or payload.resource_kind != resource_kind
        or payload.locator_kind != ("directory" if resource_kind == "skill" else "file")
        or payload.schema_id != f"loushang.resource.{resource_kind}"
        or payload.schema_version != 1
        or payload.owner_namespace != f"resources.{resource_kind}"
        or payload.media_type
        != ("application/json" if resource_kind == "theme" else "text/markdown")
        or payload.locator
        != (
            body_path.removeprefix(f"{root}/").removesuffix("/SKILL.md")
            if resource_kind == "skill"
            else body_path.removeprefix(f"{root}/")
        )
    ):
        raise ValueError("Legacy data Resource payload is unsupported")
    logical_path = Path(body_path.removeprefix(f"{root}/"))
    content = files[body_path].decode("utf-8").strip()
    if not content:
        raise ValueError("Legacy data Resource content is empty")
    if resource_kind == "skill":
        descriptor, diagnostics = _skill_descriptor_from_text(
            parent_name=logical_path.parent.name,
            source_path=logical_path,
            content=content,
            canonical_name=logical_path.parent.name,
            source_kind="external_package",
            source_scope="package",
            source="legacy-local-reacquired",
            source_root=Path(root),
        )
        if descriptor is None or diagnostics:
            raise ValueError("Legacy Skill content is not Product admissible")
        return CodingLegacyLocalDataWheelInspectionV1("skill", descriptor.name)
    if resource_kind == "theme":
        parse_theme_document_v1(files[body_path])
        return CodingLegacyLocalDataWheelInspectionV1("theme", logical_path.name)
    prompt, diagnostics = _prompt_descriptor_from_text(
        name=logical_path.stem,
        source_path=logical_path,
        text=content,
        canonical_name=logical_path.name,
        source_kind="external_package",
        source_scope="package",
        source="legacy-local-reacquired",
        source_root=Path(root),
    )
    if prompt is None or diagnostics or prompt.diagnostics:
        raise ValueError("Legacy Prompt content is not Product admissible")
    return CodingLegacyLocalDataWheelInspectionV1(
        "prompt", prompt.canonical_name or prompt.name
    )


__all__ = [
    "CodingLegacyLocalDataWheelInspectionV1",
    "admit_coding_single_legacy_skill_snapshot",
    "require_coding_fenced_single_legacy_skill",
    "require_coding_fenced_single_legacy_data",
    "require_coding_fenced_single_legacy_skill_snapshot",
    "inspect_coding_legacy_local_data_wheel",
]
