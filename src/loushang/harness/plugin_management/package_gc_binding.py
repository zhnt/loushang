"""Durable crosswalk from Product desired selection to a committed Store root.

The crosswalk is written only after the management command commits.  It grants
no deletion authority; a GC owner must still prove the exact committed set,
Store settlement, reference fence, and candidate at execution time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFileError,
    JournalLoadPolicy,
    JsonlSnapshot,
    append_jsonl_record,
    journal_file_lock,
    load_jsonl,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredStateTransitionV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageDesiredStateCommitRequestV1,
)


class PluginPackageGcBindingError(RuntimeError):
    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PluginPackageGcBindingV1:
    record_revision: int
    binding_id: str
    request: PackageDesiredStateCommitRequestV1
    package_revision: PluginPackageRevisionRefV1
    desired_transition_revision: int
    record_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.record_revision) is not int
            or self.record_revision < 1
            or type(self.desired_transition_revision) is not int
            or self.desired_transition_revision
            != self.request.expected_inventory_revision + 1
            or self.package_revision.plugin_id != self.request.plugin_id
            or self.package_revision.plugin_version != self.request.root_ref.version
            or self.package_revision.package_content_digest
            != self.request.root_ref.artifact_digest
            or self.record_version != 1
            or self.binding_id != _binding_id(
                self.request,
                self.package_revision,
                self.desired_transition_revision,
            )
        ):
            raise ValueError("Package GC crosswalk identity is invalid")

    @classmethod
    def create(
        cls,
        *,
        record_revision: int,
        request: PackageDesiredStateCommitRequestV1,
        package_revision: PluginPackageRevisionRefV1,
        transition: PluginDesiredStateTransitionV1,
    ) -> PluginPackageGcBindingV1:
        if (
            transition.inventory_revision
            != request.expected_inventory_revision + 1
            or transition.mutation.operation_id != request.command_id
            or transition.mutation.idempotency_key != request.desired_request_id
            or transition.committed_state.selection.package_revision
            != package_revision
            or transition.mutation.installation_key.product_id != request.product_id
            or transition.mutation.installation_key.scope_id != request.scope_id
            or transition.mutation.installation_key.plugin_id != request.plugin_id
        ):
            raise ValueError("Package GC crosswalk does not match desired commit")
        return cls(
            record_revision=record_revision,
            binding_id=_binding_id(
                request, package_revision, transition.inventory_revision
            ),
            request=request,
            package_revision=package_revision,
            desired_transition_revision=transition.inventory_revision,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "bindingId": self.binding_id,
            "desiredTransitionRevision": self.desired_transition_revision,
            "packageRevision": self.package_revision.to_dict(),
            "recordRevision": self.record_revision,
            "recordVersion": self.record_version,
            "request": self.request.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginPackageGcBindingV1:
        if type(value) is not dict or set(value) != {
            "bindingId",
            "desiredTransitionRevision",
            "packageRevision",
            "recordRevision",
            "recordVersion",
            "request",
        }:
            raise JournalCodecError(
                "Invalid Package GC crosswalk record",
                code="invalid_plugin_package_gc_binding_record",
            )
        try:
            return cls(
                record_revision=_integer(value["recordRevision"]),
                binding_id=_string(value["bindingId"]),
                request=PackageDesiredStateCommitRequestV1.from_dict(value["request"]),
                package_revision=PluginPackageRevisionRefV1.from_dict(
                    value["packageRevision"]
                ),
                desired_transition_revision=_integer(
                    value["desiredTransitionRevision"]
                ),
                record_version=_integer(value["recordVersion"]),
            )
        except (TypeError, ValueError) as exc:
            raise JournalCodecError(
                "Invalid Package GC crosswalk record",
                code="invalid_plugin_package_gc_binding_record",
            ) from exc


_CODEC = FunctionalJournalRecordCodec(
    encoder=PluginPackageGcBindingV1.to_dict,
    decoder=PluginPackageGcBindingV1.from_dict,
)


class PluginPackageGcBindingJournal:
    """One append-only, idempotent mapping for each B desired handoff."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def record(
        self,
        request: PackageDesiredStateCommitRequestV1,
        package_revision: PluginPackageRevisionRefV1,
        transition: PluginDesiredStateTransitionV1,
    ) -> PluginPackageGcBindingV1:
        with journal_file_lock(self._path, "exclusive"):
            records = self._load_unlocked()
            proposed = PluginPackageGcBindingV1.create(
                record_revision=len(records) + 1,
                request=request,
                package_revision=package_revision,
                transition=transition,
            )
            existing = next(
                (
                    item
                    for item in records
                    if item.request.desired_request_id == request.desired_request_id
                ),
                None,
            )
            if existing is not None:
                if (
                    existing.request != request
                    or existing.package_revision != package_revision
                    or existing.desired_transition_revision
                    != transition.inventory_revision
                ):
                    raise self._error(
                        "Package GC crosswalk identity was reused",
                        "plugin_package_gc_binding_conflict",
                    )
                return existing
            append_jsonl_record(
                self._path,
                proposed,
                record_codec=_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
            )
            return proposed

    def for_revision(
        self, package_revision: PluginPackageRevisionRefV1
    ) -> tuple[PluginPackageGcBindingV1, ...]:
        with journal_file_lock(self._path, "exclusive"):
            return tuple(
                item
                for item in self._load_unlocked()
                if item.package_revision == package_revision
            )

    def records(self) -> tuple[PluginPackageGcBindingV1, ...]:
        with journal_file_lock(self._path, "exclusive"):
            return self._load_unlocked()

    def _load_unlocked(self) -> tuple[PluginPackageGcBindingV1, ...]:
        if not self._path.exists():
            return ()
        try:
            loaded: JsonlSnapshot[None, PluginPackageGcBindingV1] = load_jsonl(
                self._path,
                record_codec=_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
            )
            records = loaded.records
            requests: set[str] = set()
            for revision, record in enumerate(records, start=1):
                if (
                    record.record_revision != revision
                    or record.request.desired_request_id in requests
                ):
                    raise ValueError("Package GC crosswalk chain is invalid")
                requests.add(record.request.desired_request_id)
            return records
        except (JournalFileError, ValueError) as exc:
            raise self._error(
                "Package GC crosswalk journal is corrupt",
                "plugin_package_gc_binding_corrupt",
            ) from exc

    def _error(self, message: str, code: str) -> PluginPackageGcBindingError:
        return PluginPackageGcBindingError(message, code=code, path=self._path)


def _binding_id(
    request: PackageDesiredStateCommitRequestV1,
    package_revision: PluginPackageRevisionRefV1,
    desired_transition_revision: int,
) -> str:
    payload = json.dumps(
        [request.to_dict(), package_revision.to_dict(), desired_transition_revision],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(b"plugin-package-gc-binding-v1\0" + payload).hexdigest()


def _integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError("Package GC crosswalk integer is invalid")
    return value


def _string(value: object) -> str:
    if type(value) is not str or not value:
        raise ValueError("Package GC crosswalk string is invalid")
    return value


__all__ = [
    "PluginPackageGcBindingError",
    "PluginPackageGcBindingJournal",
    "PluginPackageGcBindingV1",
]
