"""Installed-composition queries and typed Catalog evidence projection.

Product owns source selection, compilation and Catalog construction. This module
projects their exact evidence; its query port grants no installation, activation,
repair or live Session authority.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from hashlib import sha256
from typing import TYPE_CHECKING, Literal, Protocol

from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.resources._catalog_records import NativeHostOrigin
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef

if TYPE_CHECKING:
    from loushang.harness.capabilities.consumer_requirements import (
        ProductCompositionCompilation,
    )
    from loushang.harness.capabilities.contribution_admission import (
        OwnerContributionAdmissionRecord,
    )
    from loushang.harness.plugin_management.ledger import PluginDesiredStateLedger
    from loushang.harness.plugin_management.package_product import (
        PackageProductSelectedRootSnapshotV1,
    )
    from loushang.harness.resource_catalog.bootstrap_projection import (
        ResourceCatalogBootstrapResult,
    )
    from loushang.harness.resources._catalog_records import ResourceCatalogSnapshot
    from loushang.harness.resources.packages.product_epoch_guard import (
        PackageProductPosixFencedRuntimeOwner,
    )
    from loushang.harness.resources.packages.product_local_wheel_policy import (
        PackageProductLocalWheelPolicy,
    )
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


class _PreviewedComposition(Protocol):
    @property
    def product_composition(self) -> ProductCompositionCompilation: ...


class _PreviewCompositionFailure(Protocol):
    @property
    def code(self) -> str: ...


def observe_current_product_composition(
    policy: PackageProductLocalWheelPolicy,
    desired: PluginDesiredStateLedger,
    before: PluginDesiredStateSnapshotV1,
    *,
    epoch: PackageProductPosixFencedRuntimeOwner,
    requested_plugin_ids: tuple[str, ...],
    executable_trust_classes: frozenset[str],
    excluded_plugin_id: str,
    observe_clock: Callable[[], int],
    composition_set_id: str,
    disabled_skills_known: bool,
    compiled_plugin_ids: tuple[str, ...],
    catalog_result: ResourceCatalogBootstrapResult | None = None,
    product_inputs: tuple[_CurrentProductResourceInput, ...] = (),
    compiled: _PreviewedComposition | None = None,
    blocker: _PreviewCompositionFailure | None = None,
) -> PluginCurrentCompositionPreviewV1:
    """Project one preview against the same Desired and epoch authorities."""
    from loushang.harness.capabilities.consumer_requirements import (
        ProductCompositionError,
    )

    bundle = catalog = None
    selections: list[PluginCurrentResourceSelectionV1] = []
    if catalog_result is not None:
        bundle, catalog = catalog_result.bundle, catalog_result.catalog
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
        excluded_plugin_id=excluded_plugin_id,
    )
    if disabled_skills_known:
        gaps.discard("disabled_skill_settings")
    if blocker is not None:
        gaps.add("resource_catalog_not_reached")
    if before.inventory_revision != after.inventory_revision:
        gaps.add("stale_snapshot")
    admissions, catalog_resources = (
        project_current_product_resource_facts(
            compiled.product_composition.resource_admissions
            if compiled is not None
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
        compiled_plugin_ids=compiled_plugin_ids,
        admitted_resources=admissions,
        catalog_resources=catalog_resources,
        catalog_diagnostic_codes=(
            tuple(sorted({item.code for item in bundle.diagnostics}))
            if bundle is not None
            else ()
        ),
        catalog_generation=catalog.catalog_generation if catalog is not None else None,
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
    def scope_id(self) -> str: ...

    def management_snapshot(self, *, correlation_id: str) -> dict[str, object]: ...

    def support_status(self, *, correlation_id: str) -> dict[str, object]: ...


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
        rows = self.rows
        diagnostics = self.diagnostics
        completeness = self.completeness
        evidence = self.owner_evidence
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
            rows.append(
                {
                    "identityKind": "native_resource",
                    "pluginId": None,
                    "name": candidate.canonical_name,
                    "resourceIdentity": candidate.identity.to_payload(),
                    "resourceKind": candidate.identity.resource_kind,
                    "resourceKinds": [candidate.identity.resource_kind],
                    "version": None,
                    "sourceClass": candidate.source_class,
                    "sourceScope": candidate.content_origin.workspace_or_user_scope,
                    "candidateFingerprint": candidate.candidate_fingerprint,
                    "contentDigest": candidate.expected_content_digest,
                    "sourceEnabled": candidate.invocation_policy.enabled,
                    "enabled": candidate.candidate_fingerprint in selected,
                    "nativeCatalogSelection": (
                        "selected"
                        if candidate.candidate_fingerprint in selected
                        else "not_selected"
                    ),
                    "productCompatibility": "native_catalog_candidate",
                    "productSelection": "not_checked",
                    "mergeReason": merge_reason.get(candidate.candidate_fingerprint),
                    "diagnosticCodes": sorted(
                        {item.code for item in candidate.diagnostics}
                    ),
                }
            )
        diagnostics.update(item.code for item in catalog.diagnostics)
        completeness["catalog"] = (
            "complete" if catalog.complete and not catalog.diagnostics else "partial"
        )
        evidence["catalogGeneration"] = catalog.catalog_generation
        evidence["catalogSnapshotFingerprint"] = catalog.snapshot_fingerprint

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


def _matches_kind(row: dict[str, object], kind: LocalKind) -> bool:
    if kind == "all" or row.get("resourceKind") == kind:
        return True
    kinds = row.get("resourceKinds")
    return isinstance(kinds, list) and kind in kinds
