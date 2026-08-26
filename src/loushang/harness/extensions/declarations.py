"""Pure Extension runtime-capability declaration compatibility facts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.extensions.manifest import ExtensionManifest
from loushang.harness.extensions.types import LoadedExtension, extension_is_active


@dataclass(frozen=True, order=True)
class ExtensionRuntimeCapabilityDeclaration:
    """Redacted identity of one Extension-declared runtime replacement."""

    extension_id: str
    slot: str
    name: str
    implementation_version: int
    priority: int
    granted_permissions: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "extensionId": self.extension_id,
            "slot": self.slot,
            "name": self.name,
            "implementationVersion": self.implementation_version,
            "priority": self.priority,
            "grantedPermissions": list(self.granted_permissions),
        }


@dataclass(frozen=True)
class ExtensionCapabilityDeclarationSnapshot:
    """Canonical pure facts that can affect bound runtime mechanisms."""

    declarations: tuple[ExtensionRuntimeCapabilityDeclaration, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "unsupported Extension capability declaration schema version"
            )
        canonical = tuple(sorted(self.declarations))
        if canonical != self.declarations:
            raise ValueError(
                "Extension capability declarations must use canonical ordering"
            )

    @classmethod
    def from_extensions(
        cls,
        extensions: Iterable[LoadedExtension],
    ) -> ExtensionCapabilityDeclarationSnapshot:
        active = tuple(
            extension for extension in extensions if extension_is_active(extension)
        )
        declaring_ids = tuple(
            extension_declaration_id(extension)
            for extension in active
            if extension.runtime_capability_replacements
        )
        if len(set(declaring_ids)) != len(declaring_ids):
            raise ValueError(
                "runtime capability declarations require unique Extension identities"
            )
        declarations = tuple(
            sorted(
                ExtensionRuntimeCapabilityDeclaration(
                    extension_id=extension_declaration_id(extension),
                    slot=replacement.slot,
                    name=replacement.name,
                    implementation_version=replacement.implementation_version,
                    priority=replacement.priority,
                    granted_permissions=tuple(
                        sorted(
                            extension.policy.capabilities
                            if extension.policy is not None
                            else ()
                        )
                    ),
                )
                for extension in active
                for replacement in extension.runtime_capability_replacements
            )
        )
        return cls(declarations=declarations)

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            self.to_json(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def to_json(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "declarations": [item.to_json() for item in self.declarations],
        }


class ExtensionGraphProviderRestartRequiredError(RuntimeError):
    """A live Extension refresh would change a graph-owned Provider input."""

    code = "extension_graph_provider_restart_required"

    def __init__(
        self,
        *,
        capability_ids: tuple[str, ...],
        changed_slots: tuple[str, ...],
        baseline_fingerprint: str,
        candidate_fingerprint: str,
        baseline_fingerprint_kind: str = "graph_provider_input",
        candidate_fingerprint_kind: str = "graph_provider_input",
    ) -> None:
        if not capability_ids or not changed_slots:
            raise ValueError(
                "restart-required graph Provider evidence must identify changes"
            )
        self.baseline_fingerprint = baseline_fingerprint
        self.candidate_fingerprint = candidate_fingerprint
        self.changed_slots = tuple(sorted(changed_slots))
        self.capability_ids = capability_ids
        self.baseline_fingerprint_kind = baseline_fingerprint_kind
        self.candidate_fingerprint_kind = candidate_fingerprint_kind
        slots = ", ".join(self.changed_slots)
        super().__init__(
            f"Extension runtime capability declarations changed for {slots}; "
            "restart is required"
        )

    @property
    def diagnostic(self) -> DiagnosticDraft:
        return DiagnosticDraft(
            code=self.code,
            message=str(self),
            details={
                "restartRequired": True,
                "capabilityIds": list(self.capability_ids),
                "changedSlots": list(self.changed_slots),
                "baselineFingerprint": self.baseline_fingerprint,
                "baselineFingerprintKind": self.baseline_fingerprint_kind,
                "candidateFingerprint": self.candidate_fingerprint,
                "candidateFingerprintKind": self.candidate_fingerprint_kind,
            },
        )


def extension_declaration_id(extension: LoadedExtension) -> str:
    manifest = extension.manifest
    return manifest.id if isinstance(manifest, ExtensionManifest) else extension.name


def extension_set_fingerprint(extensions: Iterable[LoadedExtension]) -> str:
    """Fingerprint the exact ordered active Extension owner set.

    This is generation provenance, not a package-content attestation.  Resource
    source snapshots bind it together with their runtime and generation ids.
    """

    active_extensions = tuple(
        extension for extension in extensions if extension_is_active(extension)
    )
    entries: list[dict[str, object]] = []
    for ordinal, extension in enumerate(active_extensions):
        manifest = extension.manifest
        manifest = manifest if isinstance(manifest, ExtensionManifest) else None
        policy = extension.policy
        entries.append(
            {
                "ordinal": ordinal,
                "extensionId": extension_declaration_id(extension),
                "runtimeName": extension.name,
                "manifestVersion": manifest.version if manifest is not None else None,
                "source": extension.source,
                "sourceKind": extension.source_kind,
                "sourceScope": extension.source_scope,
                "sourceRootOrder": extension.source_root_order,
                "sourcePath": extension.source_path.as_posix(),
                "entryPath": (
                    extension.entry_path.as_posix()
                    if extension.entry_path is not None
                    else None
                ),
                "enabled": policy.enabled if policy is not None else True,
                "permissionLevel": (
                    policy.permission_level
                    if policy is not None
                    else manifest.permissions.level
                    if manifest is not None
                    else "safe"
                ),
                "capabilities": sorted(
                    policy.capabilities
                    if policy is not None
                    else manifest.permissions.capabilities
                    if manifest is not None
                    else ()
                ),
            }
        )
    payload = json.dumps(
        {"schemaVersion": 1, "extensions": entries},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "ExtensionCapabilityDeclarationSnapshot",
    "ExtensionGraphProviderRestartRequiredError",
    "ExtensionRuntimeCapabilityDeclaration",
    "extension_declaration_id",
    "extension_set_fingerprint",
]
