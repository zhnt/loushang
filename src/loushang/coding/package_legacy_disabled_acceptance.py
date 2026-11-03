"""One-way Product acceptance of a reviewed disabled-only first-B snapshot."""

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
    """Read a bounded receipt through pinned private directory and file FDs."""

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        parent_fd = os.open(path.parent, flags)
    except FileNotFoundError:
        return None
    try:
        parent = os.fstat(parent_fd)
        visible_parent = path.parent.lstat()
        if (
            not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != os.geteuid()
            or stat.S_IMODE(parent.st_mode) & 0o077
            or (parent.st_dev, parent.st_ino)
            != (visible_parent.st_dev, visible_parent.st_ino)
        ):
            raise CodingLegacyDisabledOnlyAcceptanceError(
                "Disabled-only Product state directory is unsafe"
            )
        try:
            file_fd = os.open(
                path.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=parent_fd,
            )
        except FileNotFoundError:
            return None
        try:
            opened = os.fstat(file_fd)
            visible = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or opened.st_uid != os.geteuid()
                or stat.S_IMODE(opened.st_mode) & 0o077
                or opened.st_size > _MAX_ACCEPTANCE_BYTES
                or _file_version(opened) != _file_version(visible)
            ):
                raise CodingLegacyDisabledOnlyAcceptanceError(
                    "Disabled-only Product acceptance file is unsafe"
                )
            with os.fdopen(file_fd, "rb", closefd=False) as handle:
                raw = handle.read(_MAX_ACCEPTANCE_BYTES + 1)
            after = os.fstat(file_fd)
            visible_after = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                len(raw) > _MAX_ACCEPTANCE_BYTES
                or _file_version(opened) != _file_version(after)
                or _file_version(after) != _file_version(visible_after)
            ):
                raise CodingLegacyDisabledOnlyAcceptanceError(
                    "Disabled-only Product acceptance changed during read"
                )
        finally:
            os.close(file_fd)
        parent_after = os.fstat(parent_fd)
        if (parent.st_dev, parent.st_ino) != (
            parent_after.st_dev,
            parent_after.st_ino,
        ):
            raise CodingLegacyDisabledOnlyAcceptanceError(
                "Disabled-only Product state directory changed during read"
            )
        _require_private_parent(path.parent, parent_after)
        return raw.decode("utf-8")
    finally:
        os.close(parent_fd)


def _file_version(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _write_private_acceptance(
    path: Path, record: CodingLegacyDisabledOnlyAcceptanceV1
) -> None:
    """Publish one complete receipt without reopening or replacing its name."""

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
        if (parent.st_dev, parent.st_ino) != (
            parent_after.st_dev,
            parent_after.st_ino,
        ):
            raise CodingLegacyDisabledOnlyAcceptanceError(
                "Disabled-only Product state directory changed during write"
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
        raise CodingLegacyDisabledOnlyAcceptanceError(
            "Disabled-only Product state directory is unsafe"
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
