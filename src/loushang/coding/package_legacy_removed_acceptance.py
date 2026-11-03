"""Durable Product acceptance of one frozen old local removal review."""

from __future__ import annotations

import json
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
    journal_file_lock,
    journal_file_read_lock,
)
from loushang.harness.journal._rooted_io import RootedFileIO
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_legacy_disabled_acceptance import (
    _read_private_acceptance,
    _require_empty_product_desired,
)
from .package_legacy_removed_review import (
    CodingLegacyRemovedReviewV1,
    review_coding_first_b_removed_local,
)


class CodingLegacyRemovedAcceptanceError(RuntimeError):
    """The accepted old removal does not match the frozen Product input."""


@dataclass(frozen=True, slots=True)
class CodingLegacyRemovedAcceptanceV1:
    review: CodingLegacyRemovedReviewV1
    acceptance_id: str
    acceptance_version: int = 1

    @classmethod
    def create(
        cls, review: CodingLegacyRemovedReviewV1
    ) -> CodingLegacyRemovedAcceptanceV1:
        if not isinstance(review, CodingLegacyRemovedReviewV1):
            raise TypeError("Old local removal review is required")
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
    def from_dict(cls, value: object) -> CodingLegacyRemovedAcceptanceV1:
        if type(value) is not dict or set(value) != {
            "acceptanceId",
            "acceptanceVersion",
            "review",
        }:
            raise JournalCodecError(
                "Invalid Coding old removal acceptance",
                code="coding_removed_acceptance_invalid",
            )
        try:
            if (
                type(value["acceptanceVersion"]) is not int
                or value["acceptanceVersion"] != 1
            ):
                raise ValueError("Unsupported old removal acceptance version")
            record = cls.create(CodingLegacyRemovedReviewV1.from_dict(value["review"]))
            if record.acceptance_id != value["acceptanceId"]:
                raise ValueError("Old removal acceptance identity changed")
            return record
        except (TypeError, ValueError) as exc:
            raise JournalCodecError(
                "Invalid Coding old removal acceptance",
                code="coding_removed_acceptance_invalid",
            ) from exc


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingLegacyRemovedAcceptanceV1.to_dict,
    decoder=CodingLegacyRemovedAcceptanceV1.from_dict,
)
_FILENAME = "legacy-removed-acceptance.jsonl"


def accept_coding_first_b_removed_local(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    settings_manager: SettingsManager,
    accepted_review_id: str,
) -> CodingLegacyRemovedAcceptanceV1:
    """Commit acceptance before the first Product Desired mutation."""

    review = review_coding_first_b_removed_local(
        lifecycle, epoch_runtime, settings_manager=settings_manager
    )
    if accepted_review_id != review.review_id:
        raise CodingLegacyRemovedAcceptanceError("Old removal review ID changed")
    proposed = CodingLegacyRemovedAcceptanceV1.create(review)
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    if epoch_runtime.registry.store_id != epoch.store_id:
        raise CodingLegacyRemovedAcceptanceError("Product Store changed")
    path = epoch_runtime.prepare_product_state_root() / _FILENAME
    with journal_file_lock(path, "exclusive"):
        epoch_runtime.assert_current()
        records = _decode(_read_private_acceptance(path), path=path)
        if records:
            if len(records) != 1 or records[0] != proposed:
                raise CodingLegacyRemovedAcceptanceError(
                    "Old removal acceptance conflicts with prior review"
                )
            return records[0]
        desired_path = path.parent / "desired-state.jsonl"
        with journal_file_lock(desired_path, "exclusive"):
            _require_empty_product_desired(desired_path)
            _write_private_acceptance(path, proposed)
        epoch_runtime.assert_current()
        return proposed


def read_coding_first_b_removed_local_acceptance(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    *,
    settings_manager: SettingsManager,
) -> CodingLegacyRemovedAcceptanceV1 | None:
    """Reopen acceptance against the current authenticated first-B review."""

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    if epoch_runtime.registry.store_id != epoch.store_id:
        raise CodingLegacyRemovedAcceptanceError("Product Store changed")
    path = epoch_runtime.control_root / "product-state" / _FILENAME
    with journal_file_read_lock(path, "shared", create_lock=False):
        records = _decode(_read_private_acceptance(path), path=path)
    if not records:
        return None
    review = review_coding_first_b_removed_local(
        lifecycle, epoch_runtime, settings_manager=settings_manager
    )
    if len(records) != 1 or records[0] != CodingLegacyRemovedAcceptanceV1.create(
        review
    ):
        raise CodingLegacyRemovedAcceptanceError(
            "Old removal acceptance conflicts with first-B review"
        )
    epoch_runtime.assert_current()
    return records[0]


def _decode(
    raw: str | None, *, path: Path
) -> tuple[CodingLegacyRemovedAcceptanceV1, ...]:
    if raw is None:
        return ()
    return decode_jsonl(
        raw,
        target=path,
        record_codec=_CODEC,
        load_policy=JournalLoadPolicy(partial_tail="raise", create_lock=False),
    ).records


def _write_private_acceptance(
    path: Path, record: CodingLegacyRemovedAcceptanceV1
) -> None:
    payload = (
        json.dumps(
            _CODEC.encode_record(record),
            ensure_ascii=SORTED_UNICODE_JSONL_FORMAT.ensure_ascii,
            sort_keys=SORTED_UNICODE_JSONL_FORMAT.sort_keys,
            separators=SORTED_UNICODE_JSONL_FORMAT.separators,
            allow_nan=False,
        )
        + SORTED_UNICODE_JSONL_FORMAT.newline
    ).encode(SORTED_UNICODE_JSONL_FORMAT.encoding)
    parent_fd = os.open(
        path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    try:
        parent = os.fstat(parent_fd)
        visible = path.parent.lstat()
        if (
            not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != os.geteuid()
            or stat.S_IMODE(parent.st_mode) & 0o077
            or (parent.st_dev, parent.st_ino) != (visible.st_dev, visible.st_ino)
        ):
            raise CodingLegacyRemovedAcceptanceError(
                "Old removal Product state directory is unsafe"
            )
        file_io = RootedFileIO(path.parent, parent_fd)
        try:
            with file_io.bind(path) as rooted:
                rooted.atomic_write(payload, exclusive=True)
        finally:
            file_io.cleanup()
        after = os.fstat(parent_fd)
        visible_after = path.parent.lstat()
        if (
            (parent.st_dev, parent.st_ino) != (after.st_dev, after.st_ino)
            or not stat.S_ISDIR(after.st_mode)
            or after.st_uid != os.geteuid()
            or stat.S_IMODE(after.st_mode) & 0o077
            or (after.st_dev, after.st_ino)
            != (visible_after.st_dev, visible_after.st_ino)
        ):
            raise CodingLegacyRemovedAcceptanceError(
                "Old removal Product state directory changed during write"
            )
    finally:
        os.close(parent_fd)


__all__ = [
    "CodingLegacyRemovedAcceptanceError",
    "CodingLegacyRemovedAcceptanceV1",
    "accept_coding_first_b_removed_local",
    "read_coding_first_b_removed_local_acceptance",
]
