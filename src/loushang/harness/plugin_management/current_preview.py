"""Transport-neutral request and read port for installed-composition preview.

The Product owns selection and Catalog projection. This seam grants no
installation, activation, repair, or live Session authority.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, Protocol

from loushang.harness.plugin_management.records import (
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef


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


__all__ = [
    "PluginCurrentPreviewQueryPort",
    "PluginCurrentPreviewRequestV1",
    "PluginCurrentCompositionPreviewV1",
    "PluginCurrentResourceAdmissionV1",
    "PluginCurrentResourceSelectionV1",
    "plugin_package_revision_fingerprint",
    "project_plugin_current_preview",
]
