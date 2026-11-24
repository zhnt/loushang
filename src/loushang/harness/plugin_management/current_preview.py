"""Installed-composition queries and typed Catalog evidence projection.

The installed-resource query reads one Desired snapshot, compiles its selected
manifests through the Product compiler, and rechecks Desired and the epoch before
returning evidence. It borrows read-only Package and Catalog authority.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol, TypeVar, cast

from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.resources._catalog_records import NativeHostOrigin
from loushang.harness.resources._loader_discovery_filesystem import (
    _discover_native_fallback_metadata,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef

if TYPE_CHECKING:
    from loushang.harness.capabilities.consumer_requirements import (
        ProductCompositionCompilation,
    )
    from loushang.harness.capabilities.contribution_admission import (
        OwnerContributionAdmissionRecord,
    )
    from loushang.harness.package_product.product_local_wheel_runtime import (
        PackageProductSelectedPluginManifestV1,
        _LocalWheelSelectedManifestReader,
    )
    from loushang.harness.plugin_management.package_product import (
        PackageProductSelectedRootSnapshotV1,
    )
    from loushang.harness.resource_catalog.bootstrap_projection import (
        ResourceCatalogBootstrapResult,
    )
    from loushang.harness.resource_catalog.product_snapshot_source import (
        ProductSelectedResourceInput,
    )
    from loushang.harness.resources._catalog_input_receipt import (
        ResourceCatalogInputReceipt,
    )
    from loushang.harness.resources._catalog_records import ResourceCatalogSnapshot
    from loushang.harness.resources.packages.product_epoch_guard import (
        PackageProductPosixFencedRuntimeOwner,
    )
    from loushang.harness.resources.packages.product_local_wheel_policy import (
        PackageProductLocalWheelBindingV1,
        PackageProductLocalWheelPolicy,
    )
    from loushang.harness.resources.plugins.selection import PluginSelectionPlanV2
    from loushang.harness.resources.types import ResourceBundle


@dataclass(frozen=True, slots=True)
class PluginCurrentPreviewRequestV1:
    correlation_id: str
    product_id: str
    scope_id: str
    composition_set_id: str

    def __post_init__(self) -> None:
        for name in (
            "correlation_id",
            "product_id",
            "scope_id",
            "composition_set_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"Plugin current preview {name} is invalid")


@dataclass(frozen=True, slots=True)
class PluginCurrentResourceAdmissionV1:
    plugin_id: str
    contribution_id: str
    resource_kind: str
    owner_id: str
    admission_fingerprint: str

    def to_dict(self) -> dict[str, str]:
        return {
            "pluginId": self.plugin_id,
            "contributionId": self.contribution_id,
            "resourceKind": self.resource_kind,
            "ownerId": self.owner_id,
            "admissionFingerprint": self.admission_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class PluginCurrentResourceSelectionV1:
    """One exact Product input selected by a disposable Catalog generation."""

    installation_key: PluginInstallationKeyV1
    package_revision: PluginPackageRevisionRefV1
    instance_revision_ref: PluginInstanceRevisionRef
    contribution_id: str
    resource_kind: str
    admission_fingerprint: str
    candidate_fingerprint: str
    catalog_generation: int
    catalog_snapshot_fingerprint: str

    def __post_init__(self) -> None:
        if (
            self.installation_key.plugin_id != self.package_revision.plugin_id
            or self.installation_key.plugin_id != self.instance_revision_ref.plugin_id
            or not self.contribution_id
            or self.resource_kind not in {"skill", "prompt", "theme"}
            or self.catalog_generation < 1
        ):
            raise ValueError("Plugin current selection identity is invalid")
        for fingerprint in (
            self.admission_fingerprint,
            self.candidate_fingerprint,
            self.catalog_snapshot_fingerprint,
        ):
            if (
                len(fingerprint) != 64
                or any(character not in "0123456789abcdef" for character in fingerprint)
            ):
                raise ValueError("Plugin current selection fingerprint is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "installationKey": self.installation_key.to_dict(),
            "packageRevisionFingerprint": plugin_package_revision_fingerprint(
                self.package_revision
            ),
            "instanceRevisionRef": self.instance_revision_ref.to_dict(),
            "contributionId": self.contribution_id,
            "resourceKind": self.resource_kind,
            "admissionFingerprint": self.admission_fingerprint,
            "candidateFingerprint": self.candidate_fingerprint,
            "catalogGeneration": self.catalog_generation,
            "catalogSnapshotFingerprint": self.catalog_snapshot_fingerprint,
        }


def plugin_package_revision_fingerprint(revision: PluginPackageRevisionRefV1) -> str:
    """Keep Source identity inside the owner while preserving exact revision equality."""

    digest = sha256(b"loushang.plugin-package-revision-fingerprint/v1\0")
    digest.update(
        json.dumps(
            revision.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    )
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class PluginCurrentCompositionPreviewV1:
    """Sanitized Product evidence; partial until the Session owner is joined."""

    product_id: str
    scope_id: str
    composition_set_id: str
    observed_at_unix_ns: int
    desired_inventory_revision: int
    product_policy_revision: str
    product_authority_revision: str
    compiled_plugin_ids: tuple[str, ...]
    admitted_resources: tuple[PluginCurrentResourceAdmissionV1, ...]
    catalog_resources: tuple[tuple[str, str, str], ...]
    catalog_diagnostic_codes: tuple[str, ...]
    requires_authorized_preflight: tuple[str, ...]
    evidence_gaps: tuple[str, ...]
    disposition: Literal["projected", "blocked"] = "projected"
    blocking_owner: str | None = None
    blocking_code: str | None = None
    blocking_admission_fingerprints: tuple[str, ...] = ()
    disabled_skill_settings_revision: str | None = None
    catalog_generation: int | None = None
    catalog_snapshot_fingerprint: str | None = None
    selected_resources: tuple[PluginCurrentResourceSelectionV1, ...] = ()
    snapshot_status: Literal["partial_evidence"] = "partial_evidence"
    preview_version: Literal[1] = 1

    def __post_init__(self) -> None:
        for name in ("product_id", "scope_id", "composition_set_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"Plugin current preview {name} is invalid")
        if self.disposition == "blocked" and (
            not self.blocking_owner or not self.blocking_code
        ):
            raise ValueError("Blocked Plugin preview requires owner and code")
        if self.disposition == "projected" and (
            self.blocking_owner is not None or self.blocking_code is not None
        ):
            raise ValueError("Projected Plugin preview cannot claim a blocker")
        if self.disabled_skill_settings_revision is not None and (
            not self.disabled_skill_settings_revision.startswith("sha256:")
            or len(self.disabled_skill_settings_revision) != 71
            or any(
                character not in "0123456789abcdef"
                for character in self.disabled_skill_settings_revision[7:]
            )
        ):
            raise ValueError("Plugin current preview Skill settings revision is invalid")
        if self.catalog_generation is None:
            if self.catalog_snapshot_fingerprint is not None or self.selected_resources:
                raise ValueError("Plugin current preview Catalog receipt is incomplete")
        elif (
            type(self.catalog_generation) is not int
            or self.catalog_generation < 1
            or self.catalog_snapshot_fingerprint is None
            or len(self.catalog_snapshot_fingerprint) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.catalog_snapshot_fingerprint
            )
            or any(
                item.catalog_generation != self.catalog_generation
                or item.catalog_snapshot_fingerprint != self.catalog_snapshot_fingerprint
                for item in self.selected_resources
            )
        ):
            raise ValueError("Plugin current preview Catalog receipt is inconsistent")
        if self.selected_resources != tuple(
            sorted(
                self.selected_resources,
                key=lambda item: (
                    item.installation_key,
                    item.contribution_id,
                    item.candidate_fingerprint,
                ),
            )
        ):
            raise ValueError("Plugin current preview selections are not canonical")
        for name in (
            "compiled_plugin_ids",
            "catalog_diagnostic_codes",
            "requires_authorized_preflight",
            "evidence_gaps",
        ):
            values = getattr(self, name)
            if values != tuple(sorted(set(values))):
                raise ValueError(f"Plugin current preview {name} is not canonical")

    def to_dict(self) -> dict[str, object]:
        """Serialize only reviewed identifiers and diagnostic codes."""

        return {
            "productId": self.product_id,
            "scopeId": self.scope_id,
            "compositionSetId": self.composition_set_id,
            "observedAtUnixNs": self.observed_at_unix_ns,
            "desiredInventoryRevision": self.desired_inventory_revision,
            "productPolicyRevision": self.product_policy_revision,
            "productAuthorityRevision": self.product_authority_revision,
            "compiledPluginIds": list(self.compiled_plugin_ids),
            "admittedResources": [item.to_dict() for item in self.admitted_resources],
            "catalogResources": [
                {"resourceKind": kind, "name": name, "sourceKind": source}
                for kind, name, source in self.catalog_resources
            ],
            "catalogDiagnosticCodes": list(self.catalog_diagnostic_codes),
            "requiresAuthorizedPreflight": list(self.requires_authorized_preflight),
            "evidenceGaps": list(self.evidence_gaps),
            "disposition": self.disposition,
            "blockingOwner": self.blocking_owner,
            "blockingCode": self.blocking_code,
            "blockingAdmissionFingerprints": list(
                self.blocking_admission_fingerprints
            ),
            "disabledSkillSettingsRevision": self.disabled_skill_settings_revision,
            "catalogGeneration": self.catalog_generation,
            "catalogSnapshotFingerprint": self.catalog_snapshot_fingerprint,
            "selectedResources": [item.to_dict() for item in self.selected_resources],
            "snapshotStatus": self.snapshot_status,
            "previewVersion": self.preview_version,
        }


class PluginCurrentPreviewQueryPort(Protocol):
    def preview_current(
        self, request: PluginCurrentPreviewRequestV1
    ) -> PluginCurrentCompositionPreviewV1: ...


def project_current_selection_evidence(
    policy: PackageProductLocalWheelPolicy,
    desired_snapshot: PluginDesiredStateSnapshotV1,
    requested_plugin_ids: tuple[str, ...],
    *,
    executable_trust_classes: frozenset[str],
    excluded_plugin_id: str,
) -> tuple[set[str], set[str]]:
    """Find requested executable selections and the evidence still required."""

    if not isinstance(desired_snapshot, PluginDesiredStateSnapshotV1):
        raise TypeError("Product preview Desired State snapshot is required")
    desired_selected_ids = {
        item.installation_key.plugin_id
        for item in desired_snapshot.installations
        if item.installation_key.product_id == policy.product_id
        and item.installation_key.scope_id == policy.project_scope_id
        and item.selection.desired_state == "installed_enabled"
    }
    selected_ids = desired_selected_ids & set(requested_plugin_ids)
    binding_ids = {item.plugin_id for item in policy.bindings}
    executable = {
        item.plugin_id
        for item in policy.bindings
        if item.plugin_id in selected_ids
        and item.source_trust_class in executable_trust_classes
        and item.plugin_id != excluded_plugin_id
    }
    gaps = {
        "disabled_skill_settings",
        "session_invocation_options",
        "exact_catalog_generation",
    }
    if desired_selected_ids - binding_ids:
        gaps.add("product_binding_for_selected_plugin")
    if executable:
        gaps.add("capability_authorized_preflight")
    return executable, gaps


def project_plugin_current_preview(
    query: PluginCurrentPreviewQueryPort,
    request: PluginCurrentPreviewRequestV1,
) -> dict[str, object]:
    """Enforce the exact Product result shape for every read transport."""

    if not isinstance(request, PluginCurrentPreviewRequestV1):
        raise TypeError("Plugin current preview requires a typed request")
    result = query.preview_current(request)
    if type(result) is not PluginCurrentCompositionPreviewV1:
        raise TypeError("Plugin current preview requires a typed Product result")
    if (
        result.product_id != request.product_id
        or result.scope_id != request.scope_id
        or result.composition_set_id != request.composition_set_id
    ):
        raise ValueError("Plugin current preview result changed Product request")
    document = result.to_dict()
    if "correlationId" in document:
        raise ValueError("Plugin current preview document cannot set correlation id")
    return {"correlationId": request.correlation_id, **document}


class _CurrentSelectedManifest(Protocol):
    @property
    def snapshot(self) -> PackageProductSelectedRootSnapshotV1: ...


class _CurrentProductResourceInput(Protocol):
    @property
    def admission(self) -> OwnerContributionAdmissionRecord: ...

    @property
    def selected_manifest(self) -> _CurrentSelectedManifest: ...


def project_current_product_resource_selections(
    catalog: ResourceCatalogSnapshot,
    product_inputs: tuple[_CurrentProductResourceInput, ...],
) -> list[PluginCurrentResourceSelectionV1]:
    """Project exact Catalog Product selections without acquiring live authority."""
    from loushang.harness.resources._catalog_records import VerifiedPluginResourceOrigin

    selected_candidates = {
        entry.primary_candidate_fingerprint for entry in catalog.effective_entries
    }
    candidates = {
        item.candidate_fingerprint: item for item in catalog.candidate_summaries
    }
    inputs_by_admission = {item.admission.fingerprint: item for item in product_inputs}
    selections: list[PluginCurrentResourceSelectionV1] = []
    for fingerprint in sorted(selected_candidates):
        candidate = candidates[fingerprint]
        origin = candidate.content_origin
        if not isinstance(origin, VerifiedPluginResourceOrigin):
            continue
        product_input = inputs_by_admission.get(origin.resource_admission_fingerprint)
        if product_input is None:
            continue  # Legacy or built-in package Resources have no Product input.
        admission = product_input.admission
        snapshot = product_input.selected_manifest.snapshot
        instance = admission.candidate.instance_revision_ref
        if (
            admission.contribution_id != origin.resource_contribution_id
            or admission.candidate.package_content_digest
            != origin.package_content_digest
            or f"{instance.instance_id}:{instance.plugin_id}@{instance.revision}"
            != origin.plugin_instance_revision_ref
        ):
            raise ValueError("Product preview Catalog selection changed owner identity")
        selections.append(
            PluginCurrentResourceSelectionV1(
                installation_key=snapshot.installation_key,
                package_revision=snapshot.package_revision,
                instance_revision_ref=instance,
                contribution_id=admission.contribution_id,
                resource_kind=candidate.identity.resource_kind,
                admission_fingerprint=admission.fingerprint,
                candidate_fingerprint=fingerprint,
                catalog_generation=catalog.catalog_generation,
                catalog_snapshot_fingerprint=catalog.snapshot_fingerprint,
            )
        )
    return selections


def project_current_product_resource_facts(
    resource_admissions: tuple[OwnerContributionAdmissionRecord, ...],
    bundle: ResourceBundle,
) -> tuple[
    tuple[PluginCurrentResourceAdmissionV1, ...],
    tuple[tuple[str, str, str], ...],
]:
    """Project admitted and enabled Catalog facts in their original order."""
    from loushang.harness.capabilities.contribution_admission import (
        ResourceContributionSpec,
    )

    admissions = tuple(
        sorted(
            (
                PluginCurrentResourceAdmissionV1(
                    plugin_id=item.plugin_id,
                    contribution_id=item.contribution_id,
                    resource_kind=item.candidate.contribution.resource_kind,
                    owner_id=item.owner_id,
                    admission_fingerprint=item.fingerprint,
                )
                for item in (resource_admissions)
                if isinstance(item.candidate.contribution, ResourceContributionSpec)
            ),
            key=lambda item: (item.plugin_id, item.contribution_id),
        )
    )
    catalog_resources = tuple(
        sorted(
            (
                *(
                    ("skill", item.name, item.source_kind)
                    for item in bundle.skills
                    if item.enabled
                ),
                *(
                    ("prompt", item.name, item.source_kind)
                    for item in bundle.prompts
                    if item.enabled
                ),
                *(
                    ("theme", item.name, item.source_kind)
                    for item in bundle.themes
                    if item.enabled
                ),
            )
        )
    )
    return admissions, catalog_resources


class _InstalledResourceCompilation(Protocol):
    @property
    def product_composition(self) -> ProductCompositionCompilation: ...

    def product_resource_inputs(self) -> tuple[ProductSelectedResourceInput, ...]: ...


class _PreviewCompositionFailure(Protocol):
    @property
    def code(self) -> str: ...


class _InstalledBaseCompilation(_InstalledResourceCompilation, Protocol):
    @property
    def plan(self) -> PluginSelectionPlanV2: ...


_InstalledBaseT = TypeVar("_InstalledBaseT", bound=_InstalledBaseCompilation)


def preview_fenced_product_resources(
    epoch: PackageProductPosixFencedRuntimeOwner,
    policy: PackageProductLocalWheelPolicy,
    manifests: _LocalWheelSelectedManifestReader,
    *,
    base_plugin_id: str,
    composition_set_id: str,
    requested_plugin_ids: tuple[str, ...],
    disabled_skills_known: bool,
    executable_trust_classes: frozenset[str],
    max_files: int,
    max_total_bytes: int,
    evaluation_clock: Callable[[], float],
    observe_clock: Callable[[], int],
    compile_base: Callable[
        [PackageProductSelectedPluginManifestV1, int], _InstalledBaseT
    ],
    compile_data: Callable[
        [_InstalledBaseT | None, tuple[PackageProductSelectedPluginManifestV1, ...], int],
        tuple[_InstalledBaseT | None, _InstalledResourceCompilation | None],
    ],
    prepare_catalog: Callable[
        [_InstalledResourceCompilation | None, int],
        tuple[ResourceCatalogBootstrapResult, tuple[ProductSelectedResourceInput, ...]],
    ],
    base_missing: Callable[[], Exception],
    composition_errors: tuple[type[Exception], ...],
) -> PluginCurrentCompositionPreviewV1:
    """Project exact installed Resources using the caller's read-only Product authority."""
    desired = manifests.root_reader.desired_state
    before, _ = desired.capture_read_only()
    base_key = PluginInstallationKeyV1.workspace(
        policy.product_id, policy.project_scope_id, base_plugin_id
    )
    base_state = before.installation(base_key).selection.desired_state
    external_ids = manifests.selected_external_data_plugin_ids()
    evaluated_at = int(evaluation_clock())
    read_manifest = manifests.capture_selected_manifest_for_plugin

    def capture(
        ids: tuple[str, ...],
    ) -> tuple[PackageProductSelectedPluginManifestV1, ...]:
        return tuple(
            read_manifest(
                plugin_id, max_files=max_files, max_total_bytes=max_total_bytes
            )
            for plugin_id in ids
        )

    def project(
        bundle: ResourceBundle | None = None,
        catalog: ResourceCatalogSnapshot | None = None,
        product_inputs: tuple[ProductSelectedResourceInput, ...] = (),
        compilation: _InstalledResourceCompilation | None = None,
        blocker: _PreviewCompositionFailure | None = None,
    ) -> PluginCurrentCompositionPreviewV1:
        from loushang.harness.capabilities.consumer_requirements import (
            ProductCompositionError,
        )

        selections: list[PluginCurrentResourceSelectionV1] = []
        if bundle is not None and catalog is not None:
            selections = project_current_product_resource_selections(
                catalog, product_inputs
            )
        after, _ = desired.capture_read_only()
        epoch.assert_current()
        executable, gaps = project_current_selection_evidence(
            policy,
            before,
            requested_plugin_ids,
            executable_trust_classes=executable_trust_classes,
            excluded_plugin_id=base_plugin_id,
        )
        if disabled_skills_known:
            gaps.discard("disabled_skill_settings")
        if blocker is not None:
            gaps.add("resource_catalog_not_reached")
        if before.inventory_revision != after.inventory_revision:
            gaps.add("stale_snapshot")
        admissions, catalog_resources = (
            project_current_product_resource_facts(
                compilation.product_composition.resource_admissions
                if compilation is not None
                else (),
                bundle,
            )
            if bundle is not None
            else ((), ())
        )
        return PluginCurrentCompositionPreviewV1(
            product_id=policy.product_id,
            scope_id=policy.project_scope_id,
            composition_set_id=composition_set_id,
            observed_at_unix_ns=observe_clock(),
            desired_inventory_revision=before.inventory_revision,
            product_policy_revision=policy.policy_revision,
            product_authority_revision=policy.authority_revision,
            compiled_plugin_ids=plugin_ids,
            admitted_resources=admissions,
            catalog_resources=catalog_resources,
            catalog_diagnostic_codes=(
                tuple(sorted({item.code for item in bundle.diagnostics}))
                if bundle is not None
                else ()
            ),
            catalog_generation=catalog.catalog_generation
            if catalog is not None
            else None,
            catalog_snapshot_fingerprint=(
                catalog.snapshot_fingerprint if catalog is not None else None
            ),
            selected_resources=tuple(
                sorted(
                    selections,
                    key=lambda item: (
                        item.installation_key.plugin_id,
                        item.contribution_id,
                    ),
                )
            ),
            requires_authorized_preflight=tuple(sorted(executable)),
            evidence_gaps=tuple(sorted(gaps)),
            disposition="blocked" if blocker is not None else "projected",
            blocking_owner="product_composition" if blocker is not None else None,
            blocking_code=blocker.code if blocker is not None else None,
            blocking_admission_fingerprints=(
                blocker.admission_fingerprints
                if isinstance(blocker, ProductCompositionError)
                else ()
            ),
        )

    compiled: _InstalledResourceCompilation | None = None
    plugin_ids: tuple[str, ...] = ()
    try:
        if base_state == "absent":
            raise base_missing()
        if base_state == "installed_disabled":
            if external_ids:
                plugin_ids = external_ids
                _, compiled = compile_data(None, capture(external_ids), evaluated_at)
        else:
            (base,) = capture((base_plugin_id,))
            compiled_base = compile_base(base, evaluated_at)
            plugin_ids = compiled_base.plan.selected_plugin_ids
            if external_ids:
                plugin_ids = tuple(sorted((*plugin_ids, *external_ids)))
                extended, _ = compile_data(
                    compiled_base, capture(external_ids), evaluated_at
                )
                assert extended is not None
                compiled_base = extended
                plugin_ids = compiled_base.plan.selected_plugin_ids
            compiled = compiled_base
    except composition_errors as error:
        return project(blocker=cast(_PreviewCompositionFailure, error))
    projection, inputs = prepare_catalog(compiled, evaluated_at)
    return project(projection.bundle, projection.catalog, inputs, compiled)


__all__ = [
    "PluginCurrentPreviewQueryPort",
    "PluginCurrentPreviewRequestV1",
    "PluginCurrentCompositionPreviewV1",
    "PluginCurrentResourceAdmissionV1",
    "PluginCurrentResourceSelectionV1",
    "plugin_package_revision_fingerprint",
    "project_plugin_current_preview",
    "project_current_product_resource_selections",
    "project_current_product_resource_facts",
]


LocalKind = Literal["all", "plugin", "skill", "prompt", "theme"]
LocalSource = Literal["all", "project_local", "user_global", "local", "builtin"]


class LocalDiscoveryEvidenceError(ValueError):
    @property
    def code(self) -> str:
        return str(self)


class _LocalDiscoveryReader(Protocol):
    @property
    def workspace(self) -> Path: ...

    @property
    def scope_id(self) -> str: ...

    def management_snapshot(self, *, correlation_id: str) -> dict[str, object]: ...

    def support_status(self, *, correlation_id: str) -> dict[str, object]: ...

    def assert_workspace_current(self) -> None: ...


_ReadInertKinds = Callable[
    [dict[str, PluginPackageRevisionRefV1]],
    tuple[dict[str, tuple[str, ...]], dict[str, str], dict[str, str]],
]


@dataclass(slots=True)
class LocalDiscoveryEvidence:
    rows: list[dict[str, object]] = field(default_factory=list)
    diagnostics: set[str] = field(default_factory=set)
    completeness: dict[str, str] = field(
        default_factory=lambda: {"product": "unavailable", "catalog": "unavailable"}
    )
    owner_evidence: dict[str, object] = field(default_factory=dict)
    management_revisions: object | None = None

    def read_installations(
        self,
        client: _LocalDiscoveryReader,
        *,
        product_id: str,
        read_inert_kinds: _ReadInertKinds,
    ) -> None:
        """Read one Product's management view with its original custody checks."""
        rows = self.rows
        diagnostics = self.diagnostics
        completeness = self.completeness
        evidence = self.owner_evidence
        try:
            management = client.management_snapshot(
                correlation_id="cli:local-discovery"
            )
            if management.get("projectionVersion") != 1:
                raise LocalDiscoveryEvidenceError("local_discovery_owner_version_invalid")
            self.management_revisions = management.get("ownerRevisions")
            installations = management.get("installations")
            if not isinstance(installations, list):
                raise LocalDiscoveryEvidenceError("local_discovery_owner_invalid")
            status: dict[str, object] | None = None
            try:
                status = client.support_status(
                    correlation_id="cli:local-discovery-status"
                )
            except (OSError, RuntimeError):
                diagnostics.add("local_discovery_product_preview_unavailable")
            if status is not None:
                if status.get("scopeId") != client.scope_id:
                    raise LocalDiscoveryEvidenceError("local_discovery_scope_changed")
                status_rows = status.get("installations")
                if not isinstance(status_rows, list):
                    raise LocalDiscoveryEvidenceError("local_discovery_owner_invalid")
                owner_evidence = status.get("ownerEvidence")
                if not isinstance(owner_evidence, dict) or owner_evidence.get(
                    "managementRevisions"
                ) != management.get("ownerRevisions"):
                    diagnostics.add("local_discovery_product_stale")
                    status_rows = []
            else:
                status_rows = []
            status_by_plugin = {
                item["pluginId"]: item
                for item in status_rows
                if isinstance(item, dict) and isinstance(item.get("pluginId"), str)
            }
            revisions_by_plugin: dict[str, PluginPackageRevisionRefV1] = {}
            for item in installations:
                if not isinstance(item, dict):
                    raise LocalDiscoveryEvidenceError("local_discovery_owner_invalid")
                try:
                    key = PluginInstallationKeyV1.from_dict(
                        item.get("installationKey")
                    )
                except (TypeError, ValueError):
                    raise LocalDiscoveryEvidenceError("local_discovery_scope_changed")
                if (
                    key.product_id != product_id
                    or key.installation_scope != "workspace"
                    or key.scope_id != client.scope_id
                ):
                    raise LocalDiscoveryEvidenceError("local_discovery_scope_changed")
                source_record = item.get("source")
                if source_record is not None and not isinstance(source_record, dict):
                    raise LocalDiscoveryEvidenceError("local_discovery_owner_invalid")
                if (
                    source_record is None
                    or source_record.get("availability") != "available"
                ):
                    diagnostics.add("local_discovery_source_unavailable")
                package_ref = item.get("selectedPackageRevision")
                try:
                    revision = (
                        PluginPackageRevisionRefV1.from_dict(package_ref)
                        if package_ref is not None
                        else None
                    )
                    package_fingerprint = (
                        plugin_package_revision_fingerprint(revision)
                        if revision is not None
                        else None
                    )
                except (TypeError, ValueError):
                    raise LocalDiscoveryEvidenceError("local_discovery_owner_invalid")
                if revision is not None:
                    revisions_by_plugin[key.plugin_id] = revision
                status_row = status_by_plugin.get(key.plugin_id, {})
                rows.append(
                    {
                        "identityKind": "plugin_installation",
                        "pluginId": key.plugin_id,
                        "installationKey": key.to_dict(),
                        "name": key.plugin_id,
                        "resourceKind": "plugin",
                        "resourceKinds": status_row.get("resourceKinds", []),
                        "resourceKindEvidence": (
                            "current_preview"
                            if status_row.get("resourceKinds")
                            else "not_checked"
                        ),
                        "version": (
                            source_record.get("pluginVersion")
                            if source_record
                            else None
                        ),
                        "sourceClass": (
                            source_record.get("sourceKind")
                            if source_record
                            else "unknown"
                        ),
                        "sourceScope": "workspace",
                        "sourceIdentity": (
                            source_record.get("sourceIdentity")
                            if source_record
                            else None
                        ),
                        "sourceLocation": (
                            source_record.get("sourceLocation")
                            if source_record
                            else None
                        ),
                        "sourceAvailability": (
                            source_record.get("availability")
                            if source_record
                            else "unknown"
                        ),
                        "packageRevisionFingerprint": package_fingerprint,
                        "desiredState": item.get("desiredState"),
                        "productCompatibility": (
                            "observed_in_current_projection"
                            if status_row.get("productAdmission")
                            == "observed_in_preview"
                            else "not_checked"
                        ),
                        "productAdmission": status_row.get(
                            "productAdmission", "not_checked"
                        ),
                        "productSelection": status_row.get(
                            "productSelection", "unknown"
                        ),
                        "productUse": "not_checked",
                        "diagnosticCodes": status_row.get("reasonCodes", []),
                    }
                )
            try:
                inert_kinds, inert_diagnostics, inert_evidence = (
                    read_inert_kinds(revisions_by_plugin)
                )
            except (OSError, RuntimeError, ValueError):
                inert_kinds = {}
                inert_evidence = {}
                inert_diagnostics = {
                    plugin_id: "local_discovery_artifact_metadata_unavailable"
                    for plugin_id in revisions_by_plugin
                }
            diagnostics.update(inert_diagnostics.values())
            for row in rows:
                plugin_id = row.get("pluginId")
                kinds = (
                    inert_kinds.get(plugin_id) if isinstance(plugin_id, str) else None
                )
                error_code = (
                    inert_diagnostics.get(plugin_id)
                    if isinstance(plugin_id, str)
                    else None
                )
                if error_code:
                    previous_codes = row.get("diagnosticCodes")
                    row["diagnosticCodes"] = sorted(
                        set(previous_codes if isinstance(previous_codes, list) else [])
                        | {error_code}
                    )
                if kinds and isinstance(plugin_id, str):
                    previous = row.get("resourceKinds")
                    row["resourceKinds"] = sorted(
                        set(previous if isinstance(previous, list) else []) | set(kinds)
                    )
                    row["resourceKindEvidence"] = inert_evidence[plugin_id]
            completeness["product"] = "complete" if not diagnostics else "partial"
            evidence["managementRevisions"] = management.get("ownerRevisions")
            evidence["supportStatus"] = (
                status.get("snapshotStatus") if status is not None else "unavailable"
            )
            if status is None or status.get("snapshotStatus") != "partial_evidence":
                completeness["product"] = "partial"
                diagnostics.add("local_discovery_product_stale")
        except LocalDiscoveryEvidenceError:
            raise
        except (OSError, RuntimeError):
            completeness["product"] = "partial"
            diagnostics.add("local_discovery_product_unavailable")
        except (TypeError, ValueError):
            raise LocalDiscoveryEvidenceError("local_discovery_owner_invalid")

    def project_native_catalog(self, catalog: ResourceCatalogSnapshot) -> None:
        """Project observed native resources and their live selection evidence."""
        selected = {
            entry.primary_candidate_fingerprint for entry in catalog.effective_entries
        }
        merge_reason = {
            fingerprint: decision.reason
            for decision in catalog.merge_decisions
            for fingerprint in decision.candidate_fingerprints
        }
        for candidate in catalog.candidate_summaries:
            if not isinstance(candidate.content_origin, NativeHostOrigin):
                continue
            enabled = candidate.candidate_fingerprint in selected
            self.rows.append(
                {
                    **_native_discovery_identity(
                        candidate.canonical_name,
                        candidate.identity.resource_kind,
                        candidate.source_class,
                        candidate.content_origin.workspace_or_user_scope,
                    ),
                    "resourceIdentity": candidate.identity.to_payload(),
                    "candidateFingerprint": candidate.candidate_fingerprint,
                    "contentDigest": candidate.expected_content_digest,
                    "sourceEnabled": candidate.invocation_policy.enabled,
                    "enabled": enabled,
                    "nativeCatalogSelection": "selected" if enabled else "not_selected",
                    "productCompatibility": "native_catalog_candidate",
                    "mergeReason": merge_reason.get(candidate.candidate_fingerprint),
                    "diagnosticCodes": sorted(
                        {item.code for item in candidate.diagnostics}
                    ),
                }
            )
        self.diagnostics.update(item.code for item in catalog.diagnostics)
        self.completeness["catalog"] = (
            "complete" if catalog.complete and not catalog.diagnostics else "partial"
        )
        self.owner_evidence["catalogGeneration"] = catalog.catalog_generation
        self.owner_evidence["catalogSnapshotFingerprint"] = catalog.snapshot_fingerprint

    def recheck_installations(self, client: _LocalDiscoveryReader) -> None:
        rows = self.rows
        diagnostics = self.diagnostics
        completeness = self.completeness
        if self.management_revisions is not None:
            try:
                final_management = client.management_snapshot(
                    correlation_id="cli:local-discovery:after"
                )
                final_revisions = final_management.get("ownerRevisions")
            except (OSError, RuntimeError):
                final_revisions = None
            except (TypeError, ValueError):
                raise LocalDiscoveryEvidenceError("local_discovery_owner_invalid")
            if final_revisions != self.management_revisions:
                completeness["product"] = "partial"
                diagnostics.add("local_discovery_product_stale")
                for row in rows:
                    if row["identityKind"] != "plugin_installation":
                        continue
                    row["productAdmission"] = "not_checked"
                    row["productSelection"] = "stale_evidence"
                    row["productCompatibility"] = "not_checked"

    def result(
        self, *, product_id: str, scope_id: str, query: str, kind: LocalKind,
        source: LocalSource, limit: int,
    ) -> dict[str, object]:
        rows = self.rows
        diagnostics = self.diagnostics
        completeness = self.completeness
        evidence = self.owner_evidence
        needle = query.casefold()
        filtered = [
            row
            for row in rows
            if _matches_kind(row, kind)
            and (source == "all" or row["sourceClass"] == source)
            and (
                not needle
                or needle in str(row["name"]).casefold()
                or needle in str(row.get("pluginId") or "").casefold()
            )
        ]
        filtered.sort(
            key=lambda row: (
                str(row["identityKind"]),
                str(row["resourceKind"]),
                str(row["name"]),
                str(row.get("sourceClass")),
                str(row.get("candidateFingerprint", "")),
            )
        )
        source_truncated = bool(
            {
                "local_discovery_source_truncated",
                "resource_source_discovery_budget_exceeded",
            }
            & diagnostics
        )
        truncated = len(filtered) > limit or source_truncated
        if truncated:
            diagnostics.add("local_discovery_result_truncated")
        disposition = (
            "complete"
            if all(value == "complete" for value in completeness.values()) and not truncated
            else "partial"
        )
        return {
            "discoveryVersion": 1,
            "productId": product_id,
            "scopeId": scope_id,
            "disposition": disposition,
            "sourceCompleteness": completeness,
            "truncated": truncated,
            "sourceTruncation": (
                "observed"
                if source_truncated
                else "none"
                if completeness["catalog"] == "complete"
                else "unknown"
            ),
            "totalMatchingRows": len(filtered),
            "totalMatchingRowsKnown": (
                not source_truncated
                and completeness["catalog"] == "complete"
                and completeness["product"] == "complete"
            ),
            "rows": filtered[:limit],
            "diagnosticCodes": sorted(diagnostics),
            "ownerEvidence": evidence,
        }


def _native_discovery_identity(
    name: str, kind: str, source_class: str, scope: str,
) -> dict[str, object]:
    return {
        "identityKind": "native_resource",
        "pluginId": None,
        "name": name,
        "resourceKind": kind,
        "resourceKinds": [kind],
        "version": None,
        "sourceClass": source_class,
        "sourceScope": scope,
        "productSelection": "not_checked",
    }


def _fallback_native_row(name: str, kind: str, source_class: str, scope: str) -> dict[str, object]:
    return {
        **_native_discovery_identity(name, kind, source_class, scope),
        "candidateFingerprint": None,
        "contentDigest": None,
        "enabled": None,
        "nativeCatalogSelection": "not_checked",
        "productCompatibility": "not_checked",
        "discoveryEvidence": "fallback_metadata",
        "diagnosticCodes": ["local_discovery_catalog_unavailable"],
    }


read_local_native_fallback_metadata = partial(
    _discover_native_fallback_metadata,
    name_pattern=re.compile(r"[a-z][a-z0-9-]{0,127}\Z"),
    diagnostic_prefix="local_discovery_",
    row_factory=_fallback_native_row,
)


def discover_local_plugins(
    client: _LocalDiscoveryReader,
    *,
    product_id: str,
    query: str,
    kind: LocalKind,
    source: LocalSource,
    limit: int,
    max_rows: int,
    read_product_fence: Callable[[Path], bool],
    read_inert_kinds: _ReadInertKinds,
    capture_settings: Callable[[Path], tuple[tuple[str, ...], str]],
    prepare_receipt: Callable[[Path], ResourceCatalogInputReceipt],
    project_catalog: Callable[
        [Path, ResourceCatalogInputReceipt, tuple[str, ...]], ResourceCatalogSnapshot
    ],
    fallback_metadata: Callable[[ResourceCatalogInputReceipt], tuple[list[dict[str, object]], set[str]]],
    catalog_admission_error: type[RuntimeError],
    fallback_authority_error: type[RuntimeError],
) -> dict[str, object]:
    """Join scoped Product, Catalog and native fallback evidence before projection."""
    if kind not in {"all", "plugin", "skill", "prompt", "theme"}:
        raise ValueError("Local discovery kind is invalid")
    if source not in {"all", "project_local", "user_global", "local", "builtin"}:
        raise ValueError("Local discovery source is invalid")
    if type(limit) is not int or not 1 <= limit <= max_rows:
        raise ValueError("Local discovery limit is invalid")
    if not isinstance(query, str) or len(query) > 128 or not query.isprintable():
        raise ValueError("Local discovery query is invalid")
    client.assert_workspace_current()
    workspace = client.workspace
    discovery = LocalDiscoveryEvidence()
    try:
        if read_product_fence(workspace):
            discovery.read_installations(
                client, product_id=product_id, read_inert_kinds=read_inert_kinds
            )
        else:
            discovery.diagnostics.add("local_discovery_product_not_fenced")
    except LocalDiscoveryEvidenceError as error:
        return blocked_local_plugin_discovery(product_id, error.code)

    receipt: ResourceCatalogInputReceipt | None = None
    try:
        disabled_skills, settings_revision = capture_settings(workspace)
        receipt = prepare_receipt(workspace)
        discovery.project_native_catalog(project_catalog(workspace, receipt, disabled_skills))
        discovery.owner_evidence["disabledSkillSettingsRevision"] = settings_revision
        _, after_settings_revision = capture_settings(workspace)
        if settings_revision != after_settings_revision:
            discovery.completeness["catalog"] = "partial"
            discovery.diagnostics.add("local_discovery_settings_stale")
    except (catalog_admission_error, TypeError, ValueError):
        return blocked_local_plugin_discovery(product_id, "local_discovery_catalog_authority_invalid")
    except (OSError, RuntimeError):
        discovery.completeness["catalog"] = "partial"
        discovery.diagnostics.add("local_discovery_catalog_unavailable")
        if receipt is not None:
            try:
                rows, diagnostics = fallback_metadata(receipt)
            except fallback_authority_error:
                return blocked_local_plugin_discovery(product_id, "local_discovery_catalog_authority_invalid")
            discovery.rows.extend(rows)
            discovery.diagnostics.update(diagnostics)
    try:
        discovery.recheck_installations(client)
    except LocalDiscoveryEvidenceError as error:
        return blocked_local_plugin_discovery(product_id, error.code)
    client.assert_workspace_current()
    return discovery.result(
        product_id=product_id, scope_id=client.scope_id,
        query=query, kind=kind, source=source, limit=limit,
    )


def read_inert_data_kinds(
    bindings: Sequence[PackageProductLocalWheelBindingV1],
    revisions: Mapping[str, PluginPackageRevisionRefV1],
    *,
    legacy_kinds: Mapping[str, str],
    artifact_kinds: frozenset[str],
    validate_artifact: Callable[[str | Path], Mapping[str, object]],
) -> tuple[dict[str, tuple[str, ...]], dict[str, str], dict[str, str]]:
    """Classify exact Product-bound data bytes regardless of enablement."""
    kinds: dict[str, tuple[str, ...]] = {}
    diagnostics: dict[str, str] = {}
    evidence: dict[str, str] = {}
    for plugin_id, revision in revisions.items():
        matches = tuple(
            binding
            for binding in bindings
            if binding.plugin_id == plugin_id
            and binding.source_identity == revision.package_source_identity
            and binding.artifact_digest == revision.package_content_digest
        )
        if len(matches) != 1:
            diagnostics[plugin_id] = "local_discovery_binding_unavailable"
            continue
        binding = matches[0]
        legacy_kind = legacy_kinds.get(binding.source_trust_class or "")
        if legacy_kind is not None:
            kinds[plugin_id] = (legacy_kind,)
            evidence[plugin_id] = "product_binding"
            continue
        if binding.source_trust_class != "local-data-only":
            continue
        report = validate_artifact(binding.source_identity)
        if (
            report.get("valid") is not True
            or report.get("pluginId") != plugin_id
            or report.get("version") != revision.plugin_version
            or report.get("sha256") != revision.package_content_digest
            or report.get("resourceKind") not in artifact_kinds
        ):
            diagnostics[plugin_id] = "local_discovery_artifact_metadata_unavailable"
            continue
        resource_kind = report["resourceKind"]
        assert isinstance(resource_kind, str)
        kinds[plugin_id] = (resource_kind,)
        evidence[plugin_id] = "inert_artifact"
    return kinds, diagnostics, evidence


def format_local_plugin_discovery(document: dict[str, object], output: str) -> str:
    if output == "json":
        return json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n"
    if output != "text":
        raise ValueError("Local discovery format is invalid")
    lines = [
        f"Local discovery: {document['disposition']} "
        f"({document['totalMatchingRows']} matching; truncated={str(document['truncated']).lower()})"
    ]
    rows = document.get("rows")
    codes = document.get("diagnosticCodes")
    if not isinstance(rows, list) or not isinstance(codes, list):
        raise ValueError("Local discovery document is invalid")
    for row in rows:
        assert isinstance(row, dict)
        if row["identityKind"] == "plugin_installation":
            lines.append(
                f"plugin {row['name']} version={row.get('version') or 'unknown'} "
                f"scope={row['sourceScope']} source={row['sourceClass']} "
                f"availability={row['sourceAvailability']} "
                f"desired={row['desiredState']} "
                f"compatibility={row['productCompatibility']} "
                f"selection={row['productSelection']} "
                f"kinds={','.join(row.get('resourceKinds', [])) or 'unknown'}"
            )
        else:
            lines.append(
                f"native {row['resourceKind']} {row['name']} "
                f"scope={row['sourceScope']} source={row['sourceClass']} "
                f"enabled={row.get('enabled')} "
                f"catalog={row['nativeCatalogSelection']} "
                f"product={row['productSelection']}"
            )
        for code in row.get("diagnosticCodes", []):
            lines.append(f"  diagnostic: {code}")
    for code in codes:
        lines.append(f"diagnostic: {code}")
    return "\n".join(lines) + "\n"


def blocked_local_plugin_discovery(product_id: str, code: str) -> dict[str, object]:
    return {
        "discoveryVersion": 1,
        "productId": product_id,
        "scopeId": None,
        "disposition": "blocked",
        "sourceCompleteness": {"product": "blocked", "catalog": "blocked"},
        "truncated": False,
        "sourceTruncation": "unknown",
        "totalMatchingRows": 0,
        "totalMatchingRowsKnown": False,
        "rows": [],
        "diagnosticCodes": [code],
        "ownerEvidence": {},
    }


def _matches_kind(row: dict[str, object], kind: LocalKind) -> bool:
    if kind == "all" or row.get("resourceKind") == kind:
        return True
    kinds = row.get("resourceKinds")
    return isinstance(kinds, list) and kind in kinds
