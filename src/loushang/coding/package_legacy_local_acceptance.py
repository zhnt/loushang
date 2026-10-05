"""Durable Product acceptance of one reviewed old local Installation.

Acceptance records the operator's exact review choice. It does not authorize
Source publication, mutate Desired State, or run a Package transaction.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from loushang.harness.journal import (
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalLoadPolicy,
    decode_jsonl,
)
from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO
from loushang.harness.plugin_management.ledger import (
    decode_plugin_desired_state_snapshot,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_legacy_classification import classify_coding_legacy_source_configuration
from .package_legacy_configured_source import (
    match_coding_legacy_local_skill_configured_source,
)
from .package_legacy_installation_inventory import (
    read_coding_legacy_installation_inventory,
)
from .package_legacy_review import (
    CodingLegacyLocalAdoptionReviewV1,
    review_coding_legacy_installed_local_source,
)
from .package_legacy_snapshot_member import (
    CodingFirstBLegacyStateObserver,
    read_coding_first_b_snapshot_member,
)

_MAX_ACCEPTANCE_BYTES = 1024 * 1024
_MAX_DESIRED_BYTES = 32 * 1024 * 1024
_BUILTINS = frozenset({"coding.base", "coding.lsp.default", "coding.arch.default"})


class CodingLegacyLocalAcceptanceError(RuntimeError):
    """An operator review choice or its Product receipt is inconsistent."""


@dataclass(frozen=True, slots=True)
class CodingLegacyLocalAcceptanceV1:
    review: CodingLegacyLocalAdoptionReviewV1
    acceptance_id: str
    acceptance_version: int = 1
    resource_kind: Literal["skill", "prompt", "theme"] = "skill"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.review, CodingLegacyLocalAdoptionReviewV1)
            or type(self.acceptance_version) is not int
            or (self.acceptance_version, self.resource_kind)
            not in {(1, "skill"), (2, "prompt"), (3, "theme")}
        ):
            raise ValueError("Coding legacy local acceptance record is invalid")
        identity = {
            "acceptanceVersion": self.acceptance_version,
            "reviewId": self.review.review_id,
            "pluginId": self.review.plugin_id,
        }
        if self.acceptance_version >= 2:
            identity["resourceKind"] = self.resource_kind
        if self.acceptance_id != sha256(canonical_json_bytes(identity)).hexdigest():
            raise ValueError("Coding legacy local acceptance identity changed")

    @classmethod
    def create(
        cls,
        review: CodingLegacyLocalAdoptionReviewV1,
        *,
        resource_kind: Literal["skill", "prompt", "theme"] = "skill",
    ) -> CodingLegacyLocalAcceptanceV1:
        if not isinstance(review, CodingLegacyLocalAdoptionReviewV1):
            raise TypeError("Coding legacy local review is required")
        if any(item.plugin_id not in _BUILTINS for item in review.disabled_plugins):
            raise ValueError("Legacy local adoption supports built-in disables only")
        if resource_kind not in {"skill", "prompt", "theme"}:
            raise ValueError("Unsupported legacy local Resource type")
        acceptance_version = {"skill": 1, "prompt": 2, "theme": 3}[resource_kind]
        identity = {
            "acceptanceVersion": acceptance_version,
            "reviewId": review.review_id,
            "pluginId": review.plugin_id,
        }
        if acceptance_version >= 2:
            identity["resourceKind"] = resource_kind
        return cls(
            review,
            sha256(canonical_json_bytes(identity)).hexdigest(),
            acceptance_version=acceptance_version,
            resource_kind=resource_kind,
        )

    def to_dict(self) -> dict[str, object]:
        record: dict[str, object] = {
            "acceptanceId": self.acceptance_id,
            "acceptanceVersion": self.acceptance_version,
            "review": self.review.to_dict(),
        }
        if self.acceptance_version >= 2:
            record["resourceKind"] = self.resource_kind
        return record

    @classmethod
    def from_dict(cls, value: object) -> CodingLegacyLocalAcceptanceV1:
        if type(value) is not dict or set(value) not in (
            {"acceptanceId", "acceptanceVersion", "review"},
            {"acceptanceId", "acceptanceVersion", "review", "resourceKind"},
        ):
            raise JournalCodecError(
                "Invalid Coding legacy local acceptance",
                code="coding_legacy_local_acceptance_invalid",
            )
        try:
            if type(value["acceptanceVersion"]) is not int:
                raise ValueError("Unsupported Coding legacy local acceptance version")
            resource_kind: Literal["skill", "prompt", "theme"]
            if value["acceptanceVersion"] == 1 and "resourceKind" not in value:
                resource_kind = "skill"
            elif (
                value["acceptanceVersion"] == 2
                and value.get("resourceKind") == "prompt"
            ):
                resource_kind = "prompt"
            elif (
                value["acceptanceVersion"] == 3
                and value.get("resourceKind") == "theme"
            ):
                resource_kind = "theme"
            else:
                raise ValueError("Unsupported Coding legacy local acceptance type")
            record = cls.create(
                CodingLegacyLocalAdoptionReviewV1.from_dict(value["review"]),
                resource_kind=resource_kind,
            )
            if record.acceptance_id != value["acceptanceId"]:
                raise ValueError("Coding legacy local acceptance identity changed")
            return record
        except (TypeError, ValueError) as exc:
            raise JournalCodecError(
                "Invalid Coding legacy local acceptance",
                code="coding_legacy_local_acceptance_invalid",
            ) from exc


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingLegacyLocalAcceptanceV1.to_dict,
    decoder=CodingLegacyLocalAcceptanceV1.from_dict,
)


def accept_coding_legacy_installed_local_review(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    policy_revision: str,
    accepted_review_id: str,
    resource_kind: Literal["skill", "prompt", "theme"] = "skill",
) -> CodingLegacyLocalAcceptanceV1:
    """Accept one exact current review while that Installation is untouched in B."""

    review = review_coding_legacy_installed_local_source(
        lifecycle, epoch_runtime, plugin_id=plugin_id, policy_revision=policy_revision
    )
    if accepted_review_id != review.review_id:
        raise CodingLegacyLocalAcceptanceError("Coding legacy local review ID changed")
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    if (
        epoch_runtime.registry.store_id != epoch.store_id
        or epoch_runtime.control_root != epoch.control_root
    ):
        raise CodingLegacyLocalAcceptanceError(
            "Coding legacy local Product epoch changed"
        )
    proposed = CodingLegacyLocalAcceptanceV1.create(review, resource_kind=resource_kind)
    state_root = epoch_runtime.prepare_product_state_root()
    path = _acceptance_path(state_root, review.plugin_id)
    descriptor = os.open(
        state_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    try:
        before = os.fstat(descriptor)
        _require_private_parent(state_root, before)
        file_io = RootedFileIO(state_root, descriptor)
        try:
            with file_io.bind(path) as target:
                target.acquire_lock(exclusive=True, suffix=".lock")
                epoch_runtime.assert_current()
                try:
                    raw = target.read_bytes(max_bytes=_MAX_ACCEPTANCE_BYTES)
                except FileNotFoundError:
                    raw = None
                if raw is not None:
                    records = decode_jsonl(
                        raw.decode("utf-8"),
                        target=path,
                        record_codec=_CODEC,
                        load_policy=JournalLoadPolicy(
                            partial_tail="raise", create_lock=False
                        ),
                    ).records
                    if len(records) != 1 or records[0] != proposed:
                        raise CodingLegacyLocalAcceptanceError(
                            "Coding legacy local acceptance conflicts with prior review"
                        )
                else:
                    desired = target.sibling("desired-state.jsonl")
                    desired.acquire_lock(exclusive=True, suffix=".lock")
                    _require_unseen_installation(
                        desired, state_root / "desired-state.jsonl", review
                    )
                    _require_live_resource_kind(
                        lifecycle,
                        epoch_runtime,
                        plugin_id=plugin_id,
                        resource_kind=resource_kind,
                    )
                    # Reacquire under the locks so accepted Source and first-B
                    # evidence still match the operator's reviewed identity.
                    if (
                        review_coding_legacy_installed_local_source(
                            lifecycle,
                            epoch_runtime,
                            plugin_id=plugin_id,
                            policy_revision=policy_revision,
                        )
                        != review
                    ):
                        raise CodingLegacyLocalAcceptanceError(
                            "Coding legacy local review changed before acceptance"
                        )
                    payload = (
                        json.dumps(
                            _CODEC.encode_record(proposed),
                            ensure_ascii=SORTED_UNICODE_JSONL_FORMAT.ensure_ascii,
                            sort_keys=SORTED_UNICODE_JSONL_FORMAT.sort_keys,
                            separators=SORTED_UNICODE_JSONL_FORMAT.separators,
                            allow_nan=False,
                        )
                        + SORTED_UNICODE_JSONL_FORMAT.newline
                    ).encode(SORTED_UNICODE_JSONL_FORMAT.encoding)
                    target.atomic_write(payload, exclusive=True)
                    epoch_runtime.assert_current()
            _require_private_parent_after(state_root, descriptor, before)
            return proposed
        finally:
            file_io.cleanup()
    finally:
        os.close(descriptor)


def reopen_coding_legacy_installed_local_acceptance(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    policy_revision: str,
) -> CodingLegacyLocalAcceptanceV1 | None:
    """Reopen a receipt against frozen first-B evidence without live Source."""

    if not isinstance(plugin_id, str) or not plugin_id:
        raise ValueError("Coding legacy local Plugin identity is required")
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    if (
        epoch_runtime.registry.store_id != epoch.store_id
        or epoch_runtime.control_root != epoch.control_root
    ):
        raise CodingLegacyLocalAcceptanceError(
            "Coding legacy local Product epoch changed"
        )
    state_root = epoch_runtime.control_root / "product-state"
    path = _acceptance_path(state_root, plugin_id)
    try:
        descriptor = os.open(
            state_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
    except FileNotFoundError:
        epoch_runtime.assert_current()
        return None
    try:
        before = os.fstat(descriptor)
        _require_private_parent(state_root, before)
        file_io = RootedFileIO(state_root, descriptor)
        try:
            with file_io.bind(path) as target:
                try:
                    raw = target.read_bytes(max_bytes=_MAX_ACCEPTANCE_BYTES)
                except FileNotFoundError:
                    raw = None
            _require_private_parent_after(state_root, descriptor, before)
        finally:
            file_io.cleanup()
    finally:
        os.close(descriptor)
    if raw is None:
        epoch_runtime.assert_current()
        return None
    records = decode_jsonl(
        raw.decode("utf-8"),
        target=path,
        record_codec=_CODEC,
        load_policy=JournalLoadPolicy(partial_tail="raise", create_lock=False),
    ).records
    if len(records) != 1:
        raise CodingLegacyLocalAcceptanceError(
            "Coding legacy local acceptance has multiple records"
        )
    _require_frozen_review(
        lifecycle,
        epoch_runtime,
        records[0].review,
        plugin_id=plugin_id,
        policy_revision=policy_revision,
    )
    epoch_runtime.assert_current()
    return records[0]


def read_coding_legacy_installed_local_acceptance(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    policy_revision: str,
) -> CodingLegacyLocalAcceptanceV1 | None:
    """Additionally require that the original live Source still matches."""

    record = reopen_coding_legacy_installed_local_acceptance(
        lifecycle,
        epoch_runtime,
        plugin_id=plugin_id,
        policy_revision=policy_revision,
    )
    if record is None:
        return None
    review = review_coding_legacy_installed_local_source(
        lifecycle, epoch_runtime, plugin_id=plugin_id, policy_revision=policy_revision
    )
    if record != CodingLegacyLocalAcceptanceV1.create(
        review, resource_kind=record.resource_kind
    ):
        raise CodingLegacyLocalAcceptanceError(
            "Coding legacy local acceptance conflicts with current review"
        )
    epoch_runtime.assert_current()
    return record


def _require_live_resource_kind(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    plugin_id: str,
    resource_kind: Literal["skill", "prompt", "theme"],
) -> None:
    # The inspector is imported here to keep Product cutover composition out of
    # the acceptance record codec's module initialization path.
    from .package_legacy_reacquisition import (
        reacquire_coding_legacy_installed_local_source,
    )
    from .package_legacy_skill_cutover_admission import (
        inspect_coding_legacy_local_data_wheel,
    )

    reacquired = reacquire_coding_legacy_installed_local_source(
        lifecycle, epoch_runtime, plugin_id=plugin_id
    )
    try:
        inspected = inspect_coding_legacy_local_data_wheel(reacquired.wheel)
    except (OSError, ValueError) as exc:
        raise CodingLegacyLocalAcceptanceError(
            "Coding legacy local Resource type is unsupported"
        ) from exc
    if inspected.resource_kind != resource_kind:
        raise CodingLegacyLocalAcceptanceError(
            "Coding legacy local Resource type differs from accepted route"
        )


def _require_frozen_review(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    review: CodingLegacyLocalAdoptionReviewV1,
    *,
    plugin_id: str,
    policy_revision: str,
) -> None:
    fence = epoch_runtime.cutover_result.fence
    switch = epoch_runtime.cutover_result.switch_receipt
    inventory = read_coding_legacy_installation_inventory(lifecycle, epoch_runtime)
    selected = next(
        (
            item
            for item in inventory.inventory.active_local
            if item.binding.plugin_id == plugin_id
        ),
        None,
    )
    if fence is None or switch is None or selected is None:
        raise CodingLegacyLocalAcceptanceError(
            "Coding legacy local acceptance lost its first-B Installation"
        )
    legacy_state = CodingFirstBLegacyStateObserver(lifecycle, epoch_runtime).observe(
        store_id=fence.store_id,
        legacy_root_identity=fence.request.legacy_root_identity,
    )
    binding = selected.binding
    source_raw = read_coding_first_b_snapshot_member(
        lifecycle,
        epoch_runtime,
        domain="source_configuration",
        member_name="coding-source-configuration.json",
        maximum_bytes=2 * 1024 * 1024,
    )
    if source_raw is None:
        raise CodingLegacyLocalAcceptanceError(
            "Coding legacy local acceptance lost its Source configuration"
        )
    source_projection = json.loads(source_raw)
    source = classify_coding_legacy_source_configuration(source_projection)
    configured = match_coding_legacy_local_skill_configured_source(
        source_projection,
        source_identity=binding.source_identity,
        installed_source_identities=tuple(
            item.binding.source_identity for item in inventory.inventory.active_local
        ),
    )
    expected_prefix = (
        "loushang_legacy_"
        + sha256(f"{plugin_id}\0{binding.content_digest}".encode()).hexdigest()[:24]
    )
    if (
        review.store_id != fence.store_id
        or review.namespace_id != switch.namespace_id
        or review.scope_id != lifecycle.scope_id
        or review.first_fence_id != inventory.first_fence_id
        or review.snapshot_receipt_id != inventory.snapshot_receipt_id
        or review.legacy_root_identity != legacy_state.legacy_root_identity
        or review.legacy_state_evidence_id != legacy_state.evidence_id
        or review.legacy_state_digest != legacy_state.state_digest
        or review.legacy_entry_count != legacy_state.entry_count
        or review.legacy_byte_count != legacy_state.byte_count
        or review.plugin_id != plugin_id
        or review.desired_state != selected.desired_state
        or review.legacy_source_identity != binding.source_identity
        or review.legacy_binding_digest != binding.binding_digest
        or review.legacy_lockfile_digest != binding.lockfile_digest
        or review.legacy_desired_journal_digest
        != inventory.inventory.desired_journal_digest
        or review.source_content_digest != binding.content_digest
        or review.manifest_digest != binding.manifest_digest
        or review.dependency_lock_digest != binding.dependency_lock.digest
        or review.wheel_filename != f"{expected_prefix}-1-py3-none-any.whl"
        or review.policy_revision != policy_revision
        or review.disabled_plugins != source.disabled_plugins
        or review.builtin_intent != inventory.inventory.builtin_intent
        or review.removed_builtin_ids
        != tuple(
            item
            for item in inventory.inventory.removed_plugin_ids
            if item in {"coding.base", "coding.lsp.default", "coding.arch.default"}
        )
        or review.configured_plugin_source_scope
        != (None if configured is None else configured.scope)
    ):
        raise CodingLegacyLocalAcceptanceError(
            "Coding legacy local acceptance changed first-B evidence"
        )


def _acceptance_path(state_root: Path, plugin_id: str) -> Path:
    name_digest = sha256(plugin_id.encode()).hexdigest()[:24]
    return state_root / f"legacy-local-acceptance-{name_digest}.jsonl"


def _require_unseen_installation(
    desired: RootedFile,
    path: Path,
    review: CodingLegacyLocalAdoptionReviewV1,
) -> None:
    try:
        raw = desired.read_bytes(max_bytes=_MAX_DESIRED_BYTES)
    except FileNotFoundError:
        return
    if raw and not raw.endswith(b"\n"):
        raise CodingLegacyLocalAcceptanceError("Product Desired State is incomplete")
    snapshot = decode_plugin_desired_state_snapshot(raw.decode("utf-8"), path=path)
    key = PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id=review.scope_id,
        plugin_id=review.plugin_id,
    )
    if any(item.installation_key == key for item in snapshot.installations):
        raise CodingLegacyLocalAcceptanceError(
            "Coding legacy local Installation already has Product Desired history"
        )


def _require_private_parent(path: Path, opened: os.stat_result) -> None:
    visible = path.lstat()
    if (
        not stat.S_ISDIR(opened.st_mode)
        or opened.st_uid != os.geteuid()
        or stat.S_IMODE(opened.st_mode) & 0o077
        or (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino)
    ):
        raise CodingLegacyLocalAcceptanceError(
            "Coding legacy local Product state directory is unsafe"
        )


def _require_private_parent_after(
    path: Path, descriptor: int, before: os.stat_result
) -> None:
    after = os.fstat(descriptor)
    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        raise CodingLegacyLocalAcceptanceError(
            "Coding legacy local Product state directory changed"
        )
    _require_private_parent(path, after)


__all__ = [
    "CodingLegacyLocalAcceptanceError",
    "CodingLegacyLocalAcceptanceV1",
    "accept_coding_legacy_installed_local_review",
    "read_coding_legacy_installed_local_acceptance",
    "reopen_coding_legacy_installed_local_acceptance",
]
