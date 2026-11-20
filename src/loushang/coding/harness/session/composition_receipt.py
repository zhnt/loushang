"""The versioned identity and receipt for one Session composition."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from re import fullmatch
from typing import TypeGuard

from loushang.foundation.json import JSONValue

_IDENTITY_FIELDS = {"version", "setId", "planFingerprint"}


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
