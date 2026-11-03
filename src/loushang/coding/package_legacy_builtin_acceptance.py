"""One-way Product acceptance of a frozen builtin-only migration review."""

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
from loushang.harness.plugin_management.ledger import (
    decode_plugin_desired_state_snapshot,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
)

from ._plugin_lifecycle import CodingPluginLifecycleStateLayout
from .package_epoch_layout import resolve_coding_package_epoch_layout
from .package_legacy_builtin_review import (
    CodingLegacyBuiltinOnlyReviewV1,
    review_coding_first_b_builtin_only,
)
from .package_legacy_disabled_acceptance import (
    _read_private_acceptance,
    _require_empty_product_desired,
)
from .package_legacy_windows_receipt import (
    read_windows_private_receipt,
    read_windows_product_desired_bytes,
    write_windows_private_receipt,
)

_MAX_WINDOWS_ACCEPTANCE_BYTES = 1024 * 1024


class CodingLegacyBuiltinOnlyAcceptanceError(RuntimeError):
    """The reviewed builtin-only Product acceptance is inconsistent."""


@dataclass(frozen=True, slots=True)
class CodingLegacyBuiltinOnlyAcceptanceV1:
    review: CodingLegacyBuiltinOnlyReviewV1
    acceptance_id: str
    acceptance_version: int = 1

    @classmethod
    def create(
        cls, review: CodingLegacyBuiltinOnlyReviewV1
    ) -> CodingLegacyBuiltinOnlyAcceptanceV1:
        if not isinstance(review, CodingLegacyBuiltinOnlyReviewV1):
            raise TypeError("Coding builtin-only review is required")
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
    def from_dict(cls, value: object) -> CodingLegacyBuiltinOnlyAcceptanceV1:
        if type(value) is not dict or set(value) != {
            "acceptanceId",
            "acceptanceVersion",
            "review",
        }:
            raise JournalCodecError(
                "Invalid Coding builtin-only acceptance",
                code="coding_builtin_acceptance_invalid",
            )
        try:
            if (
                type(value["acceptanceVersion"]) is not int
                or value["acceptanceVersion"] != 1
            ):
                raise ValueError("Unsupported builtin-only acceptance version")
            record = cls.create(
                CodingLegacyBuiltinOnlyReviewV1.from_dict(value["review"])
            )
            if record.acceptance_id != value["acceptanceId"]:
                raise ValueError("Builtin-only acceptance identity changed")
            return record
        except (TypeError, ValueError) as exc:
            raise JournalCodecError(
                "Invalid Coding builtin-only acceptance",
                code="coding_builtin_acceptance_invalid",
            ) from exc


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingLegacyBuiltinOnlyAcceptanceV1.to_dict,
    decoder=CodingLegacyBuiltinOnlyAcceptanceV1.from_dict,
)


def accept_coding_first_b_builtin_only(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: (
        PackageProductPosixFencedRuntimeOwner | PackageProductWindowsFencedRuntimeOwner
    ),
    *,
    settings_manager: SettingsManager,
    accepted_review_id: str,
) -> CodingLegacyBuiltinOnlyAcceptanceV1:
    """Accept exactly one review before mutating the Product Desired ledger."""

    review = review_coding_first_b_builtin_only(
        lifecycle, epoch_runtime, settings_manager=settings_manager
    )
    if accepted_review_id != review.review_id:
        raise CodingLegacyBuiltinOnlyAcceptanceError("Builtin-only review ID changed")
    proposed = CodingLegacyBuiltinOnlyAcceptanceV1.create(review)
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    if epoch_runtime.registry.store_id != epoch.store_id:
        raise CodingLegacyBuiltinOnlyAcceptanceError("Product Store changed")
    path = (
        epoch_runtime.prepare_product_state_root() / "legacy-builtin-acceptance.jsonl"
    )
    with journal_file_lock(path, "exclusive"):
        epoch_runtime.assert_current()
        raw = _read_builtin_acceptance(path, epoch_runtime, allow_windows_stage=True)
        records = _decode(raw, path=path)
        if records:
            if len(records) != 1 or records[0] != proposed:
                raise CodingLegacyBuiltinOnlyAcceptanceError(
                    "Builtin-only acceptance conflicts with prior review"
                )
            epoch_runtime.assert_current()
            return records[0]
        desired_path = path.parent / "desired-state.jsonl"
        with journal_file_lock(desired_path, "exclusive"):
            if isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner):
                _require_empty_windows_product_desired(desired_path)
                _write_windows_builtin_acceptance(path, proposed)
            else:
                _require_empty_product_desired(desired_path)
                _write_private_acceptance(path, proposed)
        epoch_runtime.assert_current()
        return proposed


def read_coding_first_b_builtin_only_acceptance(
    lifecycle: CodingPluginLifecycleStateLayout,
    epoch_runtime: (
        PackageProductPosixFencedRuntimeOwner | PackageProductWindowsFencedRuntimeOwner
    ),
    *,
    settings_manager: SettingsManager,
) -> CodingLegacyBuiltinOnlyAcceptanceV1 | None:
    """Reopen the accepted review without creating Product state."""

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    if epoch_runtime.registry.store_id != epoch.store_id:
        raise CodingLegacyBuiltinOnlyAcceptanceError("Product Store changed")
    epoch_runtime.assert_current()
    path = (
        epoch_runtime.control_root / "product-state" / "legacy-builtin-acceptance.jsonl"
    )
    with journal_file_read_lock(path, "shared", create_lock=False):
        records = _decode(_read_builtin_acceptance(path, epoch_runtime), path=path)
    if not records:
        epoch_runtime.assert_current()
        return None
    review = review_coding_first_b_builtin_only(
        lifecycle, epoch_runtime, settings_manager=settings_manager
    )
    if len(records) != 1 or records[0] != CodingLegacyBuiltinOnlyAcceptanceV1.create(
        review
    ):
        raise CodingLegacyBuiltinOnlyAcceptanceError(
            "Builtin-only acceptance conflicts with first-B review"
        )
    epoch_runtime.assert_current()
    return records[0]


def _read_builtin_acceptance(
    path: Path,
    epoch_runtime: (
        PackageProductPosixFencedRuntimeOwner | PackageProductWindowsFencedRuntimeOwner
    ),
    *,
    allow_windows_stage: bool = False,
) -> str | None:
    if isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner):
        raw = read_windows_private_receipt(
            path,
            maximum_bytes=_MAX_WINDOWS_ACCEPTANCE_BYTES,
            allow_unpublished_stage=allow_windows_stage,
        )
        return None if raw is None else raw.decode("utf-8")
    return _read_private_acceptance(path)


def _require_empty_windows_product_desired(path: Path) -> None:
    """Require the same untouched Product Desired revision as the POSIX route."""

    raw = read_windows_product_desired_bytes(path)
    if raw is None:
        return
    if raw and not raw.endswith(b"\n"):
        raise CodingLegacyBuiltinOnlyAcceptanceError(
            "Windows Product Desired State journal is incomplete"
        )
    snapshot = decode_plugin_desired_state_snapshot(raw.decode("utf-8"), path=path)
    if snapshot.inventory_revision != 0:
        raise CodingLegacyBuiltinOnlyAcceptanceError(
            "Builtin-only adoption requires untouched Windows Product Desired State"
        )


def _write_windows_builtin_acceptance(
    path: Path, record: CodingLegacyBuiltinOnlyAcceptanceV1
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
    write_windows_private_receipt(path, payload)


def _decode(
    raw: str | None, *, path: Path
) -> tuple[CodingLegacyBuiltinOnlyAcceptanceV1, ...]:
    if raw is None:
        return ()
    return decode_jsonl(
        raw,
        target=path,
        record_codec=_CODEC,
        load_policy=JournalLoadPolicy(partial_tail="raise", create_lock=False),
    ).records


def _write_private_acceptance(
    path: Path, record: CodingLegacyBuiltinOnlyAcceptanceV1
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
        _require_private_parent(path.parent, parent)
        file_io = RootedFileIO(path.parent, parent_fd)
        try:
            with file_io.bind(path) as rooted:
                rooted.atomic_write(payload, exclusive=True)
        finally:
            file_io.cleanup()
        parent_after = os.fstat(parent_fd)
        if (parent.st_dev, parent.st_ino) != (parent_after.st_dev, parent_after.st_ino):
            raise CodingLegacyBuiltinOnlyAcceptanceError(
                "Builtin-only Product state directory changed during write"
            )
        _require_private_parent(path.parent, parent_after)
    finally:
        os.close(parent_fd)


def _require_private_parent(path: Path, opened: os.stat_result) -> None:
    visible = path.lstat()
    if (
        not stat.S_ISDIR(opened.st_mode)
        or opened.st_uid != os.geteuid()
        or stat.S_IMODE(opened.st_mode) & 0o077
        or (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino)
    ):
        raise CodingLegacyBuiltinOnlyAcceptanceError(
            "Builtin-only Product state directory is unsafe"
        )


__all__ = [
    "CodingLegacyBuiltinOnlyAcceptanceError",
    "CodingLegacyBuiltinOnlyAcceptanceV1",
    "accept_coding_first_b_builtin_only",
    "read_coding_first_b_builtin_only_acceptance",
]
