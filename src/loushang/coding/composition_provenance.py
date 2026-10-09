"""Session-owned identity of the canonical Coding composition request."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from re import fullmatch

from loushang.foundation.json import JSONValue

from .composition_sets import CodingCompositionSetPlan, resolve_coding_composition_set

CODING_COMPOSITION_HEADER_KEY = "codingCompositionSetV1"
CODING_COMPOSITION_STARTUP_TYPE = "coding.composition-startup/v1"


def composition_header_metadata(plan: CodingCompositionSetPlan) -> dict[str, JSONValue]:
    canonical = resolve_coding_composition_set(plan.set_id)
    if canonical != plan:
        raise ValueError("Coding composition header requires a canonical plan")
    return {
        CODING_COMPOSITION_HEADER_KEY: {
            "version": 1,
            "setId": plan.set_id,
            "planFingerprint": plan.fingerprint,
        }
    }


def pinned_composition_plan(metadata: Mapping[str, object]) -> CodingCompositionSetPlan | None:
    if CODING_COMPOSITION_HEADER_KEY not in metadata:
        return None
    raw = metadata.get(CODING_COMPOSITION_HEADER_KEY)
    if not isinstance(raw, dict) or set(raw) != {"version", "setId", "planFingerprint"}:
        raise ValueError("Coding Session composition provenance is malformed")
    if raw.get("version") != 1 or type(raw.get("version")) is not int:
        raise ValueError("Coding Session composition provenance version is invalid")
    set_id = raw.get("setId")
    fingerprint = raw.get("planFingerprint")
    if not isinstance(set_id, str) or not isinstance(fingerprint, str):
        raise ValueError("Coding Session composition provenance identity is invalid")
    plan = resolve_coding_composition_set(set_id)
    if plan.fingerprint != fingerprint:
        raise ValueError("Coding Session composition plan has changed")
    return plan


def startup_composition_record(entries: Iterable[object]) -> dict[str, object] | None:
    """Read the single Session-owned startup receipt without trusting its shape."""

    from loushang.harness.transcript.types import ExtensionData

    found: dict[str, object] | None = None
    for entry in entries:
        payload = getattr(entry, "payload", None)
        if not isinstance(payload, ExtensionData) or payload.extension_type != CODING_COMPOSITION_STARTUP_TYPE:
            continue
        if found is not None or not isinstance(payload.data, dict):
            raise ValueError("Coding Session composition startup provenance is malformed")
        found = _validate_startup_record(payload.data)
    return found


def _validate_startup_record(raw: dict[str, JSONValue]) -> dict[str, object]:
    from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef

    keys = {
        "version", "setId", "planFingerprint", "productPolicyRevision",
        "catalogSelectionFingerprint", "selectedRevisions", "ownerGenerations",
    }
    if set(raw) not in (keys, keys | {"workerSelection"}) or type(raw["version"]) is not int or raw["version"] != 1:
        raise ValueError("Coding Session composition startup provenance is malformed")
    if not isinstance(raw["setId"], str) or not _digest(raw["planFingerprint"]):
        raise ValueError("Coding Session composition startup identity is malformed")
    try:
        canonical = resolve_coding_composition_set(raw["setId"])
    except ValueError as exc:
        raise ValueError("Coding Session composition startup set is unknown") from exc
    if canonical.fingerprint != raw["planFingerprint"]:
        raise ValueError("Coding Session composition startup plan has changed")
    policy = raw["productPolicyRevision"]
    if policy is not None and (not isinstance(policy, str) or not policy):
        raise ValueError("Coding Session composition startup policy is malformed")
    catalog = raw["catalogSelectionFingerprint"]
    if catalog is not None and not _digest(catalog):
        raise ValueError("Coding Session composition startup Catalog evidence is malformed")
    revisions = raw["selectedRevisions"]
    if not isinstance(revisions, list):
        raise ValueError("Coding Session composition startup revisions are malformed")
    revision_ids: list[str] = []
    for item in revisions:
        if not isinstance(item, dict) or set(item) != {
            "pluginId", "packageRevisionFingerprint", "instanceRevisionRef"
        }:
            raise ValueError("Coding Session composition startup revision is malformed")
        plugin_id = item["pluginId"]
        if not isinstance(plugin_id, str) or not plugin_id or not _digest(item["packageRevisionFingerprint"]):
            raise ValueError("Coding Session composition startup revision identity is malformed")
        try:
            instance = PluginInstanceRevisionRef.from_dict(item["instanceRevisionRef"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Coding Session composition startup Instance revision is malformed") from exc
        if instance.plugin_id != plugin_id:
            raise ValueError("Coding Session composition startup revision ids differ")
        revision_ids.append(plugin_id)
    if revision_ids != sorted(set(revision_ids)):
        raise ValueError("Coding Session composition startup revisions are not canonical")
    if "workerSelection" in raw:
        worker = raw["workerSelection"]
        if not isinstance(worker, dict) or set(worker) != {
            "pluginId", "receiptFingerprint", "productPolicyRevision",
            "nativeProfileId", "selectedLocatorRevision",
            "workerConfigurationFingerprint",
        }:
            raise ValueError("Coding Session Worker startup evidence is malformed")
        if (
            not isinstance(worker["pluginId"], str)
            or worker["pluginId"] not in revision_ids
            or not _digest(worker["receiptFingerprint"])
            or not _digest(worker["workerConfigurationFingerprint"])
            or any(
                not isinstance(worker[key], str) or not worker[key]
                for key in (
                    "productPolicyRevision", "nativeProfileId",
                    "selectedLocatorRevision",
                )
            )
        ):
            raise ValueError("Coding Session Worker startup identity is malformed")
    generations = raw["ownerGenerations"]
    if not isinstance(generations, list):
        raise ValueError("Coding Session composition startup owner generations are malformed")
    generation_keys: list[tuple[str, str]] = []
    for item in generations:
        if not isinstance(item, dict) or set(item) != {
            "ownerReference", "ownerGenerationReference", "contributionIds"
        }:
            raise ValueError("Coding Session composition startup owner generation is malformed")
        owner, generation, contributions = (
            item["ownerReference"], item["ownerGenerationReference"], item["contributionIds"]
        )
        if (
            not isinstance(owner, str) or not owner
            or not isinstance(generation, str) or not generation
            or not isinstance(contributions, list) or not contributions
            or any(not isinstance(value, str) or not value for value in contributions)
        ):
            raise ValueError("Coding Session composition startup owner identity is malformed")
        values = [str(value) for value in contributions]
        if values != sorted(set(values)):
            raise ValueError("Coding Session composition startup contributions are not canonical")
        generation_keys.append((owner, generation))
    if generation_keys != sorted(set(generation_keys)):
        raise ValueError("Coding Session composition startup owner generations are not canonical")
    return deepcopy(dict[str, object](raw))


def _digest(value: object) -> bool:
    return isinstance(value, str) and fullmatch(r"[0-9a-f]{64}", value) is not None


__all__ = [
    "CODING_COMPOSITION_HEADER_KEY",
    "CODING_COMPOSITION_STARTUP_TYPE",
    "composition_header_metadata",
    "pinned_composition_plan",
    "startup_composition_record",
]
