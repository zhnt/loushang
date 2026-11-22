"""Read Session composition evidence and resolve capability mount intent."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from hashlib import sha256
from itertools import chain
from re import fullmatch
from typing import TYPE_CHECKING, Protocol, TypeGuard, TypeVar, cast

from loushang.foundation.json import JSONValue
from loushang.harness.config.agent import CapabilityMountMode
from loushang.harness.plugin_management.current_preview import (
    plugin_package_revision_fingerprint,
)
from loushang.harness.resources._catalog_records import (
    ResourceCatalogSnapshot,
    fingerprint_catalog_value,
)
from loushang.harness.transcript.directory import AgentTranscriptDirectoryRuntime

if TYPE_CHECKING:
    from loushang.harness.capabilities.consumer_requirements import (
        ProductCompositionAuthorityContext,
    )
    from loushang.harness.package_product.product_local_wheel_runtime import (
        PackageProductSelectedPluginManifestV1,
    )
    from loushang.harness.package_product.product_runtime import (
        PackageProductRuntimeBindingV1,
    )
    from loushang.harness.plugin_management.records import PluginPackageRevisionRefV1
    from loushang.harness.resources.plugins.selection import (
        PluginInstanceRevisionRef,
        PluginPreflightContextV1,
    )
    from loushang.harness.runtime.registration import OwnerGenerationRetirementReceipt
    from loushang.harness.transcript.product_session import ProductTranscriptSession
    from loushang.harness.worker.product_activation import (
        ProductWorkerActivationReceiptV1,
    )

_IDENTITY_FIELDS = {"version", "setId", "planFingerprint"}
_MOUNT_MODES = frozenset({"disabled", "on_demand", "always"})


def composition_plan_fingerprint(document: object, *, digest_domain: bytes) -> str:
    """Encode the deployed composition fingerprint with its original JSON codec."""
    payload = json.dumps(
        document, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return sha256(digest_domain + payload).hexdigest()


def composition_identity_fields(
    set_id: str, plan_fingerprint: str
) -> dict[str, JSONValue]:
    return {"version": 1, "setId": set_id, "planFingerprint": plan_fingerprint}


def composition_receipt_matches(
    receipt: Mapping[str, object], set_id: str, plan_fingerprint: str
) -> bool:
    return not (
        receipt["setId"] != set_id or receipt["planFingerprint"] != plan_fingerprint
    )


def read_composition_header(
    metadata: Mapping[str, object], *, header_key: str, label: str
) -> tuple[str, str] | None:
    if header_key not in metadata:
        return None
    raw = metadata.get(header_key)
    if not isinstance(raw, dict) or set(raw) != _IDENTITY_FIELDS:
        raise ValueError(f"{label} composition provenance is malformed")
    if raw.get("version") != 1 or type(raw.get("version")) is not int:
        raise ValueError(f"{label} composition provenance version is invalid")
    set_id, fingerprint = raw.get("setId"), raw.get("planFingerprint")
    if not _nonempty_text(set_id) or not _digest(fingerprint):
        raise ValueError(f"{label} composition provenance identity is invalid")
    return set_id, fingerprint


def read_composition_receipt(
    entries: Iterable[object],
    *,
    extension_type: str,
    label: str,
    require_current: Callable[[str, str], None] | None = None,
) -> dict[str, object] | None:
    """Validate one owned receipt without resolving a current composition by default."""
    from loushang.harness.transcript.types import ExtensionData

    found: dict[str, object] | None = None
    for entry in entries:
        payload = getattr(entry, "payload", None)
        if (
            not isinstance(payload, ExtensionData)
            or payload.extension_type != extension_type
        ):
            continue
        if found is not None or not isinstance(payload.data, dict):
            raise ValueError(f"{label} composition startup provenance is malformed")
        found = _validate_startup_record(
            payload.data, label=label, require_current=require_current
        )
    return found


class _StartupReceiptOwner(Protocol):
    def issue(self) -> ProductWorkerActivationReceiptV1 | None: ...


_ReceiptOwnerT = TypeVar("_ReceiptOwnerT", bound=_StartupReceiptOwner)
_ReceiptContextT = TypeVar("_ReceiptContextT")


def bind_ordinary_worker_startup(
    transcript: ProductTranscriptSession,
    runtime: PackageProductRuntimeBindingV1,
    *,
    plugin_id: str,
    base_context: ProductCompositionAuthorityContext,
    plan_context: PluginPreflightContextV1,
    extension_type: str,
    label: str,
    max_files: int,
    max_total_bytes: int,
    open_receipt_owner: Callable[[AgentTranscriptDirectoryRuntime], _ReceiptOwnerT],
    bind_receipt_context: Callable[[ProductWorkerActivationReceiptV1], _ReceiptContextT],
    failure: Callable[[str], RuntimeError],
) -> tuple[
    _ReceiptOwnerT,
    ProductWorkerActivationReceiptV1,
    PackageProductSelectedPluginManifestV1,
    _ReceiptContextT,
]:
    """Issue authority for the attached transcript and reprove its selected manifest."""
    if (
        runtime.session_id != transcript.get_header().conversation_id
        or plan_context.scope_id != f"session:{runtime.session_id}"
        or base_context.product_policy_revision != plan_context.policy_revision
    ):
        raise failure("product_scope_changed")
    startup = read_composition_receipt(
        transcript.get_entries(), extension_type=extension_type, label=label
    )
    if startup is None and transcript.get_entries():
        raise failure("startup_provenance_missing")
    owner = open_receipt_owner(
        AgentTranscriptDirectoryRuntime(session_dir=transcript.get_session_dir())
    )
    receipt = owner.issue()
    if receipt is None:
        raise failure("candidate_not_allowed")
    context = bind_receipt_context(receipt)
    selected = _capture_worker_startup_selection(
        runtime=runtime,
        plugin_id=plugin_id,
        receipt=receipt,
        existing_startup=startup,
        max_files=max_files,
        max_total_bytes=max_total_bytes,
        failure=failure,
    )
    return owner, receipt, selected, context


def _capture_worker_startup_selection(
    *,
    runtime: PackageProductRuntimeBindingV1,
    plugin_id: str,
    receipt: ProductWorkerActivationReceiptV1,
    existing_startup: dict[str, object] | None,
    max_files: int,
    max_total_bytes: int,
    failure: Callable[[str], RuntimeError],
) -> PackageProductSelectedPluginManifestV1:
    selected_worker = runtime.capture_selected_plugin_manifest_for(
        plugin_id, max_files=max_files, max_total_bytes=max_total_bytes
    )

    if (
        selected_worker.snapshot.root_ref.artifact_digest
        != receipt.policy.plugin_revision_digest
    ):
        raise failure("selection_changed")

    if existing_startup is not None:
        worker = existing_startup.get("workerSelection")
        expected_revision = {
            "pluginId": plugin_id,
            "packageRevisionFingerprint": plugin_package_revision_fingerprint(
                selected_worker.snapshot.package_revision
            ),
            "instanceRevisionRef": selected_worker.snapshot.instance_revision_ref.to_dict(),
        }
        revisions = existing_startup.get("selectedRevisions")
        if (
            not isinstance(worker, dict)
            or not isinstance(revisions, list)
            or expected_revision not in revisions
            or (worker.get("pluginId") != receipt.policy.plugin_id)
            or (
                worker.get("productPolicyRevision")
                != receipt.policy.product_policy_revision
            )
            or (worker.get("nativeProfileId") != receipt.policy.native_profile_id)
            or (
                worker.get("selectedLocatorRevision")
                != receipt.policy.selected_locator_revision
            )
            or (
                worker.get("selectedLocatorFingerprint")
                != receipt.policy.selected_locator_fingerprint
            )
            or (
                worker.get("workerConfigurationFingerprint")
                != receipt.policy.worker_configuration_fingerprint
            )
        ):
            raise failure("startup_selection_changed")

    return selected_worker


def _validate_startup_record(
    raw: dict[str, JSONValue],
    *,
    label: str,
    require_current: Callable[[str, str], None] | None,
) -> dict[str, object]:
    from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef

    receipt_label = f"{label} composition startup"
    keys = _IDENTITY_FIELDS | {
        "productPolicyRevision",
        "catalogSelectionFingerprint",
        "selectedRevisions",
        "ownerGenerations",
    }
    if (
        set(raw) not in (keys, keys | {"workerSelection"})
        or type(raw["version"]) is not int
        or raw["version"] != 1
    ):
        raise ValueError(f"{receipt_label} provenance is malformed")
    set_id, fingerprint = raw["setId"], raw["planFingerprint"]
    if not _nonempty_text(set_id) or not _digest(fingerprint):
        raise ValueError(f"{receipt_label} identity is malformed")
    if require_current is not None:
        require_current(set_id, fingerprint)
    policy = raw["productPolicyRevision"]
    if policy is not None and not _nonempty_text(policy):
        raise ValueError(f"{receipt_label} policy is malformed")
    catalog = raw["catalogSelectionFingerprint"]
    if catalog is not None and not _digest(catalog):
        raise ValueError(f"{receipt_label} Catalog evidence is malformed")
    revisions = raw["selectedRevisions"]
    if not isinstance(revisions, list):
        raise ValueError(f"{receipt_label} revisions are malformed")
    revision_ids: list[str] = []
    for item in revisions:
        if not isinstance(item, dict) or set(item) != {
            "pluginId",
            "packageRevisionFingerprint",
            "instanceRevisionRef",
        }:
            raise ValueError(f"{receipt_label} revision is malformed")
        plugin_id = item["pluginId"]
        if not _nonempty_text(plugin_id) or not _digest(
            item["packageRevisionFingerprint"]
        ):
            raise ValueError(f"{receipt_label} revision identity is malformed")
        try:
            instance = PluginInstanceRevisionRef.from_dict(item["instanceRevisionRef"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{receipt_label} Instance revision is malformed") from exc
        if instance.plugin_id != plugin_id:
            raise ValueError(f"{receipt_label} revision ids differ")
        revision_ids.append(plugin_id)
    if revision_ids != sorted(set(revision_ids)):
        raise ValueError(f"{receipt_label} revisions are not canonical")
    if "workerSelection" in raw:
        worker = raw["workerSelection"]
        if not isinstance(worker, dict) or set(worker) != {
            "pluginId",
            "receiptFingerprint",
            "productPolicyRevision",
            "nativeProfileId",
            "selectedLocatorRevision",
            "selectedLocatorFingerprint",
            "workerConfigurationFingerprint",
        }:
            raise ValueError(f"{label} Worker startup evidence is malformed")
        if (
            not isinstance(worker["pluginId"], str)
            or worker["pluginId"] not in revision_ids
            or not _digest(worker["receiptFingerprint"])
            or not _digest(worker["workerConfigurationFingerprint"])
            or not _digest(worker["selectedLocatorFingerprint"])
            or any(
                not _nonempty_text(worker[key])
                for key in (
                    "productPolicyRevision",
                    "nativeProfileId",
                    "selectedLocatorRevision",
                )
            )
        ):
            raise ValueError(f"{label} Worker startup identity is malformed")
    generations = raw["ownerGenerations"]
    if not isinstance(generations, list):
        raise ValueError(f"{receipt_label} owner generations are malformed")
    generation_keys: list[tuple[str, str]] = []
    for item in generations:
        if not isinstance(item, dict) or set(item) != {
            "ownerReference",
            "ownerGenerationReference",
            "contributionIds",
        }:
            raise ValueError(f"{receipt_label} owner generation is malformed")
        owner, generation, contributions = (
            item["ownerReference"],
            item["ownerGenerationReference"],
            item["contributionIds"],
        )
        if (
            not _nonempty_text(owner)
            or not _nonempty_text(generation)
            or not isinstance(contributions, list)
            or not contributions
            or any(not _nonempty_text(value) for value in contributions)
        ):
            raise ValueError(f"{receipt_label} owner identity is malformed")
        values = [str(value) for value in contributions]
        if values != sorted(set(values)):
            raise ValueError(f"{receipt_label} contributions are not canonical")
        generation_keys.append((owner, generation))
    if generation_keys != sorted(set(generation_keys)):
        raise ValueError(f"{receipt_label} owner generations are not canonical")
    return deepcopy(dict[str, object](raw))


def _nonempty_text(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value)


def _digest(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and fullmatch(r"[0-9a-f]{64}", value) is not None


def configured_mount_mode(
    settings_manager: object | None, capability: str, default: CapabilityMountMode
) -> CapabilityMountMode:
    """Read one mode from the existing Settings owner with its Product default."""
    if settings_manager is None:
        return default
    get_settings = getattr(settings_manager, "get_settings", None)
    if not callable(get_settings):
        return default
    configured = getattr(get_settings(), "capabilities", {})
    if not isinstance(configured, Mapping):
        return default
    mode = configured.get(capability, default)
    return mode if mode in _MOUNT_MODES else default


def parse_mount(value: str) -> tuple[str, CapabilityMountMode]:
    """Parse the existing command-line capability mount syntax."""
    capability, separator, mode = value.partition("=")
    capability = capability.strip()
    mode = mode.strip()
    if not separator or not capability:
        raise ValueError("expected CAPABILITY=disabled|on_demand|always")
    if mode not in _MOUNT_MODES:
        raise ValueError("mount mode must be disabled, on_demand, or always")
    return capability, cast(CapabilityMountMode, mode)


def should_defer_mount(
    plugin_id: str,
    *,
    enabled: bool,
    mode: CapabilityMountMode,
    has_history: bool,
    startup: Mapping[str, object] | None,
    legacy_disabled: bool,
) -> bool:
    """Defer a fresh on-demand mount when history has no eager selection."""
    if not enabled or mode != "on_demand" or legacy_disabled:
        return False
    if not has_history:
        return True
    if startup is None:
        return False
    return not any(
        item["pluginId"] == plugin_id
        for item in cast(list[dict[str, object]], startup["selectedRevisions"])
    )


def composition_manifest_revision_evidence(
    selected: Iterable[PackageProductSelectedPluginManifestV1],
    *,
    managed_revisions: Iterable[
        tuple[str, PluginPackageRevisionRefV1, PluginInstanceRevisionRef]
    ] = (),
) -> list[dict[str, object]]:
    """Project both Store manifests and managed leases with the same receipt format."""
    revisions = chain(
        (
            (
                item.manifest.name,
                item.snapshot.package_revision,
                item.snapshot.instance_revision_ref,
            )
            for item in selected
        ),
        managed_revisions,
    )
    return [
        {
            "pluginId": plugin_id,
            "packageRevisionFingerprint": plugin_package_revision_fingerprint(package),
            "instanceRevisionRef": instance.to_dict(),
        }
        for plugin_id, package, instance in revisions
    ]


def composition_generation_evidence(
    receipts: Iterable[OwnerGenerationRetirementReceipt],
) -> list[dict[str, object]]:
    """Project the ordered live generations without changing their ownership."""
    return sorted(
        (
            {
                "ownerReference": receipt.owner_reference,
                "ownerGenerationReference": receipt.owner_generation_reference,
                "contributionIds": list(receipt.contribution_ids),
            }
            for receipt in receipts
        ),
        key=lambda item: (
            str(item["ownerReference"]),
            str(item["ownerGenerationReference"]),
        ),
    )

def catalog_composition_selection_fingerprint(
    catalog_snapshot: object | None, *, catalog_schema: str
) -> str | None:
    """Fingerprint the currently projected Catalog selections."""
    return (
        fingerprint_catalog_value(
            catalog_schema,
            {
                "activationPolicyFingerprint": (
                    catalog_snapshot.activation_policy_fingerprint
                ),
                "mergePolicyRevision": catalog_snapshot.merge_policy_revision,
                "effectiveEntries": [
                    {
                        "identity": item.identity.to_payload(),
                        "modelInvocable": item.model_invocable,
                        "candidates": [
                            {
                                "canonicalName": candidate.canonical_name,
                                "description": candidate.description,
                                "mediaType": candidate.media_type,
                                "sourceClass": candidate.source_class,
                                "sourceRootOrder": candidate.source_root_order,
                                "expectedContentDigest": candidate.expected_content_digest,
                                "expectedContentLength": candidate.expected_content_length,
                                "invocationPolicy": candidate.invocation_policy.to_payload(),
                            }
                            for candidate in sorted(
                                (
                                    catalog_snapshot.candidate_by_fingerprint(
                                        fingerprint
                                    )
                                    for fingerprint in item.candidate_fingerprints
                                ),
                                key=lambda candidate: (
                                    candidate.canonical_name,
                                    candidate.source_class,
                                    candidate.expected_content_digest or "",
                                ),
                            )
                        ],
                    }
                    for item in catalog_snapshot.effective_entries
                ],
            },
        )
        if isinstance(catalog_snapshot, ResourceCatalogSnapshot)
        else None
    )

def worker_composition_selection_evidence(
    worker_receipt: ProductWorkerActivationReceiptV1 | None,
) -> dict[str, object] | None:
    """Project the ordered Worker activation facts already selected by the caller."""
    return (
        {
            "pluginId": worker_receipt.policy.plugin_id,
            "receiptFingerprint": worker_receipt.fingerprint,
            "productPolicyRevision": worker_receipt.policy.product_policy_revision,
            "nativeProfileId": worker_receipt.policy.native_profile_id,
            "selectedLocatorRevision": worker_receipt.policy.selected_locator_revision,
            "selectedLocatorFingerprint": (
                worker_receipt.policy.selected_locator_fingerprint
            ),
            "workerConfigurationFingerprint": (
                worker_receipt.policy.worker_configuration_fingerprint
            ),
        }
        if worker_receipt is not None
        else None
    )


def observe_session_composition_evidence(
    selected: Iterable[PackageProductSelectedPluginManifestV1],
    *,
    managed_revisions: Iterable[
        tuple[str, PluginPackageRevisionRefV1, PluginInstanceRevisionRef]
    ],
    policy_revision: str | None,
    base_receipts: Iterable[OwnerGenerationRetirementReceipt],
    capability_receipts: Iterable[Iterable[OwnerGenerationRetirementReceipt]],
    catalog_snapshot: object | None,
    catalog_schema: str,
    worker_receipt: ProductWorkerActivationReceiptV1 | None,
) -> dict[str, object]:
    """Project detached startup and Resume evidence from the selected authorities."""
    revisions = composition_manifest_revision_evidence(
        selected, managed_revisions=managed_revisions
    )
    generations = composition_generation_evidence(
        chain(base_receipts, chain.from_iterable(capability_receipts))
    )
    evidence: dict[str, object] = {
        "productPolicyRevision": policy_revision,
        "catalogSelectionFingerprint": catalog_composition_selection_fingerprint(
            catalog_snapshot, catalog_schema=catalog_schema
        ),
        "selectedRevisions": sorted(revisions, key=lambda item: str(item["pluginId"])),
        "ownerGenerations": generations,
    }
    worker = worker_composition_selection_evidence(worker_receipt)
    if worker is not None:
        evidence["workerSelection"] = worker
    return evidence


async def publish_composition_startup(
    transcript: ProductTranscriptSession,
    *,
    set_id: str,
    existing_only: bool,
    had_entries_at_construction: Callable[[], bool],
    build_current_receipt: Callable[[], dict[str, object]],
    mark_prepared: Callable[[], None],
    header_key: str,
    extension_type: str,
    label: str,
) -> None:
    """Correlate sealed history under the caller's existing startup lock."""
    identity = read_composition_header(
        transcript.get_header().metadata, header_key=header_key, label=label
    )
    if identity is None or identity[0] != set_id:
        raise ValueError(f"{label} composition startup changed its pinned set")
    set_id, plan_fingerprint = identity
    existing = read_composition_receipt(
        transcript.get_entries(), extension_type=extension_type, label=label
    )
    if existing is not None:
        if (
            existing.get("setId") != set_id
            or existing.get("planFingerprint") != plan_fingerprint
        ):
            raise ValueError(f"{label} composition startup differs from its header")
        if not existing_only:
            mark_prepared()
        return
    startup_data = build_current_receipt()
    if had_entries_at_construction():
        raise ValueError(
            f"{label} has input without startup composition evidence; "
            "create a new Session"
        )
    if existing_only:
        return
    await transcript.append_custom_entry(
        extension_type,
        startup_data,
    )
    mark_prepared()
