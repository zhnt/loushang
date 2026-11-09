"""One-way Product acceptance of a reviewed disabled-only first-B snapshot."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.config.agent import SettingsManager
from loushang.harness.journal import (
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalLoadPolicy,
    decode_jsonl,
    encode_jsonl_record,
    journal_file_lock,
    journal_file_read_lock,
)
from loushang.harness.journal._rooted_io import publish_private_bytes, read_private_text
from loushang.harness.plugin_management.ledger import (
    decode_plugin_desired_state_snapshot,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_legacy_disabled_review import (
    CodingLegacyDisabledOnlyReviewV1,
    review_coding_first_b_disabled_only,
)

_BUILTINS = frozenset({"coding.base", "coding.lsp.default", "coding.arch.default"})
_MAX_ACCEPTANCE_BYTES = 16 * 1024 * 1024


class CodingLegacyDisabledOnlyAcceptanceError(RuntimeError):
    """The accepted review or its durable Product receipt is inconsistent."""


@dataclass(frozen=True, slots=True)
class CodingLegacyDisabledOnlyAcceptanceV1:
    review: CodingLegacyDisabledOnlyReviewV1
    acceptance_id: str
    acceptance_version: int = 1

    @classmethod
    def create(
        cls, review: CodingLegacyDisabledOnlyReviewV1
    ) -> CodingLegacyDisabledOnlyAcceptanceV1:
        if not isinstance(review, CodingLegacyDisabledOnlyReviewV1):
            raise TypeError("Coding disabled-only review is required")
        if any(item.plugin_id not in _BUILTINS for item in review.disabled_plugins):
            raise CodingLegacyDisabledOnlyAcceptanceError(
                "Disabled-only adoption supports built-in Coding Plugins only"
            )
        acceptance_id = sha256(
            canonical_json_bytes({"acceptanceVersion": 1, "reviewId": review.review_id})
        ).hexdigest()
        return cls(review=review, acceptance_id=acceptance_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "acceptanceId": self.acceptance_id,
            "acceptanceVersion": self.acceptance_version,
            "review": self.review.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingLegacyDisabledOnlyAcceptanceV1:
        if type(value) is not dict or set(value) != {
            "acceptanceId",
            "acceptanceVersion",
            "review",
        }:
            raise JournalCodecError(
                "Invalid Coding disabled-only acceptance",
                code="coding_disabled_acceptance_invalid",
            )
        try:
            if (
                type(value["acceptanceVersion"]) is not int
                or value["acceptanceVersion"] != 1
            ):
                raise ValueError("Unsupported acceptance version")
            record = cls.create(
                CodingLegacyDisabledOnlyReviewV1.from_dict(value["review"])
            )
            if record.acceptance_id != value["acceptanceId"]:
                raise ValueError("Acceptance identity changed")
            return record
        except (TypeError, ValueError) as exc:
            raise JournalCodecError(
                "Invalid Coding disabled-only acceptance",
                code="coding_disabled_acceptance_invalid",
            ) from exc


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingLegacyDisabledOnlyAcceptanceV1.to_dict,
    decoder=CodingLegacyDisabledOnlyAcceptanceV1.from_dict,
)


def accept_coding_first_b_disabled_only(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    settings_manager: SettingsManager,
    accepted_review_id: str,
) -> CodingLegacyDisabledOnlyAcceptanceV1:
    """Persist exactly one operator-selected review before any Desired mutation."""

    review = review_coding_first_b_disabled_only(
        lifecycle, epoch_runtime, settings_manager=settings_manager
    )
    if accepted_review_id != review.review_id:
        raise CodingLegacyDisabledOnlyAcceptanceError("Disabled-only review ID changed")
    proposed = CodingLegacyDisabledOnlyAcceptanceV1.create(review)
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    if epoch_runtime.registry.store_id != epoch.store_id:
        raise CodingLegacyDisabledOnlyAcceptanceError("Product Store changed")
    path = (
        epoch_runtime.prepare_product_state_root() / "legacy-disabled-acceptance.jsonl"
    )
    with journal_file_lock(path, "exclusive"):
        epoch_runtime.assert_current()
        raw = _read_private_acceptance(path)
        records = (
            decode_jsonl(
                raw,
                target=path,
                record_codec=_CODEC,
                load_policy=JournalLoadPolicy(partial_tail="raise", create_lock=False),
            ).records
            if raw is not None
            else ()
        )
        if records:
            if len(records) != 1 or records[0] != proposed:
                raise CodingLegacyDisabledOnlyAcceptanceError(
                    "Disabled-only Product acceptance conflicts with prior review"
                )
            return records[0]
        desired_path = path.parent / "desired-state.jsonl"
        # The Product ledger takes this lock for every mutation. Hold it
        # through the acceptance append to close the first-adoption race.
        with journal_file_lock(desired_path, "exclusive"):
            _require_empty_product_desired(desired_path)
            _write_private_acceptance(path, proposed)
        epoch_runtime.assert_current()
        return proposed


def read_coding_first_b_disabled_only_acceptance(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    settings_manager: SettingsManager,
) -> CodingLegacyDisabledOnlyAcceptanceV1 | None:
    """Read a committed acceptance without creating or repairing Product state."""

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    if epoch_runtime.registry.store_id != epoch.store_id:
        raise CodingLegacyDisabledOnlyAcceptanceError("Product Store changed")
    path = (
        epoch_runtime.control_root
        / "product-state"
        / "legacy-disabled-acceptance.jsonl"
    )
    with journal_file_read_lock(path, "shared", create_lock=False):
        raw = _read_private_acceptance(path)
        if raw is None:
            return None
        records = decode_jsonl(
            raw,
            target=path,
            record_codec=_CODEC,
            load_policy=JournalLoadPolicy(partial_tail="raise", create_lock=False),
        ).records
    review = review_coding_first_b_disabled_only(
        lifecycle, epoch_runtime, settings_manager=settings_manager
    )
    if len(records) != 1 or records[0] != CodingLegacyDisabledOnlyAcceptanceV1.create(
        review
    ):
        raise CodingLegacyDisabledOnlyAcceptanceError(
            "Disabled-only Product acceptance conflicts with first-B review"
        )
    epoch_runtime.assert_current()
    return records[0]


def _read_private_acceptance(path: Path) -> str | None:
    return read_private_text(
        path,
        max_bytes=_MAX_ACCEPTANCE_BYTES,
        error_type=CodingLegacyDisabledOnlyAcceptanceError,
        directory_label="Disabled-only Product state directory",
        file_label="Disabled-only Product acceptance",
    )


def _write_private_acceptance(
    path: Path, record: CodingLegacyDisabledOnlyAcceptanceV1
) -> None:
    payload = encode_jsonl_record(
        record, record_codec=_CODEC, format_profile=SORTED_UNICODE_JSONL_FORMAT
    )
    publish_private_bytes(
        path,
        payload,
        error_type=CodingLegacyDisabledOnlyAcceptanceError,
        directory_label="Disabled-only Product state directory",
    )


def _require_empty_product_desired(path: Path) -> None:
    try:
        descriptor = os.open(
            path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
        )
    except FileNotFoundError:
        return
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or metadata.st_size > 32 * 1024 * 1024
        ):
            raise CodingLegacyDisabledOnlyAcceptanceError(
                "Product Desired State journal is unsafe"
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024 or (raw and not raw.endswith(b"\n")):
            raise CodingLegacyDisabledOnlyAcceptanceError(
                "Product Desired State journal is incomplete"
            )
        snapshot = decode_plugin_desired_state_snapshot(raw.decode("utf-8"), path=path)
        if snapshot.inventory_revision != 0:
            raise CodingLegacyDisabledOnlyAcceptanceError(
                "Disabled-only adoption requires an untouched Product Desired State"
            )
    finally:
        os.close(descriptor)


__all__ = [
    "CodingLegacyDisabledOnlyAcceptanceError",
    "CodingLegacyDisabledOnlyAcceptanceV1",
    "accept_coding_first_b_disabled_only",
    "read_coding_first_b_disabled_only_acceptance",
]
