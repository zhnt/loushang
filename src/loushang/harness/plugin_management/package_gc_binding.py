"""Durable precommit claims and committed crosswalks for Package Store roots.

Claims are written before the desired-state command and remain conservative
blockers after a crash or failed command. Neither journal grants deletion
authority; GC must prove all reference and Store evidence at execution time.
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
from loushang.harness.plugin_management.updates import (
    PluginDesiredStateUpdateTransitionV2,
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
class PluginPackageGcClaimV1:
    record_revision: int
    claim_id: str
    request: PackageDesiredStateCommitRequestV1
    package_revision: PluginPackageRevisionRefV1
    record_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.record_revision) is not int
            or self.record_revision < 1
            or self.record_version != 1
            or not _matches_request(self.request, self.package_revision)
            or self.claim_id != _claim_id(self.request, self.package_revision)
        ):
            raise ValueError("Package GC precommit claim identity is invalid")

    @classmethod
    def create(
        cls,
        *,
        record_revision: int,
        request: PackageDesiredStateCommitRequestV1,
        package_revision: PluginPackageRevisionRefV1,
    ) -> PluginPackageGcClaimV1:
        return cls(
            record_revision=record_revision,
            claim_id=_claim_id(request, package_revision),
            request=request,
            package_revision=package_revision,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "claimId": self.claim_id,
            "packageRevision": self.package_revision.to_dict(),
            "recordRevision": self.record_revision,
            "recordVersion": self.record_version,
            "request": self.request.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginPackageGcClaimV1:
        if type(value) is not dict or set(value) != {
            "claimId", "packageRevision", "recordRevision", "recordVersion", "request"
        }:
            raise JournalCodecError(
                "Invalid Package GC precommit claim record",
                code="invalid_plugin_package_gc_claim_record",
            )
        try:
            return cls(
                record_revision=_integer(value["recordRevision"]),
                claim_id=_string(value["claimId"]),
                request=PackageDesiredStateCommitRequestV1.from_dict(value["request"]),
                package_revision=PluginPackageRevisionRefV1.from_dict(
                    value["packageRevision"]
                ),
                record_version=_integer(value["recordVersion"]),
            )
        except (TypeError, ValueError) as exc:
            raise JournalCodecError(
                "Invalid Package GC precommit claim record",
                code="invalid_plugin_package_gc_claim_record",
            ) from exc


_CLAIM_CODEC = FunctionalJournalRecordCodec(
    encoder=PluginPackageGcClaimV1.to_dict,
    decoder=PluginPackageGcClaimV1.from_dict,
)


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
            or not _matches_request(self.request, self.package_revision)
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
        transition: PluginDesiredStateTransitionV1 | PluginDesiredStateUpdateTransitionV2,
    ) -> PluginPackageGcBindingV1:
        mutation = (
            transition.mutation
            if isinstance(transition, PluginDesiredStateTransitionV1)
            else transition.mutation.command
        )
        if (
            transition.inventory_revision
            != request.expected_inventory_revision + 1
            or mutation.operation_id != request.command_id
            or mutation.idempotency_key != request.desired_request_id
            or transition.committed_state.selection.package_revision
            != package_revision
            or mutation.installation_key.product_id != request.product_id
            or mutation.installation_key.scope_id != request.scope_id
            or mutation.installation_key.plugin_id != request.plugin_id
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


@dataclass(frozen=True, slots=True)
class PluginPackageUpdateAnchorV1:
    record_revision: int
    operation_id: str
    source_identity: str
    plugin_id: str
    expected_inventory_revision: int
    expected_package_revision: PluginPackageRevisionRefV1

    def __post_init__(self) -> None:
        if (
            type(self.record_revision) is not int
            or self.record_revision < 1
            or not self.operation_id
            or not self.source_identity
            or not self.plugin_id
            or type(self.expected_inventory_revision) is not int
            or self.expected_inventory_revision < 1
            or not isinstance(
                self.expected_package_revision, PluginPackageRevisionRefV1
            )
            or self.expected_package_revision.plugin_id != self.plugin_id
        ):
            raise ValueError("Package update anchor is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "expectedInventoryRevision": self.expected_inventory_revision,
            "expectedPackageRevision": self.expected_package_revision.to_dict(),
            "operationId": self.operation_id,
            "pluginId": self.plugin_id,
            "recordRevision": self.record_revision,
            "sourceIdentity": self.source_identity,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginPackageUpdateAnchorV1:
        if type(value) is not dict or set(value) != {
            "expectedInventoryRevision", "expectedPackageRevision", "operationId",
            "pluginId", "recordRevision", "sourceIdentity",
        }:
            raise JournalCodecError(
                "Invalid Package update anchor record",
                code="invalid_plugin_package_update_anchor_record",
            )
        try:
            return cls(
                record_revision=_integer(value["recordRevision"]),
                operation_id=_string(value["operationId"]),
                source_identity=_string(value["sourceIdentity"]),
                plugin_id=_string(value["pluginId"]),
                expected_inventory_revision=_integer(value["expectedInventoryRevision"]),
                expected_package_revision=PluginPackageRevisionRefV1.from_dict(
                    value["expectedPackageRevision"]
                ),
            )
        except (TypeError, ValueError) as exc:
            raise JournalCodecError(
                "Invalid Package update anchor record",
                code="invalid_plugin_package_update_anchor_record",
            ) from exc


_UPDATE_ANCHOR_CODEC = FunctionalJournalRecordCodec(
    encoder=PluginPackageUpdateAnchorV1.to_dict,
    decoder=PluginPackageUpdateAnchorV1.from_dict,
)


class PluginPackageGcBindingJournal:
    """One append-only, idempotent mapping for each B desired handoff."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._claim_path = self._path.with_name(f"{self._path.name}.claims")
        self._update_anchor_path = self._path.with_name(f"{self._path.name}.updates")
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    @property
    def claim_path(self) -> Path:
        return self._claim_path

    def anchor_update(
        self,
        *,
        operation_id: str,
        source_identity: str,
        plugin_id: str,
        expected_inventory_revision: int,
        expected_package_revision: PluginPackageRevisionRefV1,
    ) -> PluginPackageUpdateAnchorV1:
        """Bind an update predecessor before its Package operation is accepted."""

        with journal_file_lock(self._update_anchor_path, "exclusive"):
            records = self._load_update_anchors_unlocked()
            existing = next(
                (item for item in records if item.operation_id == operation_id), None
            )
            if existing is not None:
                if (
                    existing.source_identity != source_identity
                    or existing.plugin_id != plugin_id
                ):
                    raise self._error(
                        "Package update anchor identity was reused",
                        "plugin_package_update_anchor_conflict",
                    )
                return existing
            anchor = PluginPackageUpdateAnchorV1(
                record_revision=len(records) + 1,
                operation_id=operation_id,
                source_identity=source_identity,
                plugin_id=plugin_id,
                expected_inventory_revision=expected_inventory_revision,
                expected_package_revision=expected_package_revision,
            )
            append_jsonl_record(
                self._update_anchor_path,
                anchor,
                record_codec=_UPDATE_ANCHOR_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
            )
            return anchor

    def update_anchor(self, operation_id: str) -> PluginPackageUpdateAnchorV1 | None:
        with journal_file_lock(self._update_anchor_path, "shared"):
            return next(
                (
                    item for item in self._load_update_anchors_unlocked()
                    if item.operation_id == operation_id
                ),
                None,
            )

    def _load_update_anchors_unlocked(self) -> tuple[PluginPackageUpdateAnchorV1, ...]:
        if not self._update_anchor_path.exists():
            return ()
        records = load_jsonl(
            self._update_anchor_path,
            record_codec=_UPDATE_ANCHOR_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._unlocked_durability,
            load_policy=JournalLoadPolicy(partial_tail="raise"),
        ).records
        if any(
            item.record_revision != index
            for index, item in enumerate(records, start=1)
        ) or len({item.operation_id for item in records}) != len(records):
            raise self._error(
                "Package update anchor chain changed",
                "plugin_package_update_anchor_corrupt",
            )
        return records

    def prepare(
        self,
        request: PackageDesiredStateCommitRequestV1,
        package_revision: PluginPackageRevisionRefV1,
    ) -> PluginPackageGcClaimV1:
        """Persist a conservative root claim before the desired-state commit."""

        with journal_file_lock(self._claim_path, "exclusive"):
            claims = self._load_claims_unlocked()
            proposed = PluginPackageGcClaimV1.create(
                record_revision=len(claims) + 1,
                request=request,
                package_revision=package_revision,
            )
            existing = next(
                (
                    item for item in claims
                    if item.request.desired_request_id == request.desired_request_id
                ),
                None,
            )
            if existing is not None:
                if existing.claim_id != proposed.claim_id:
                    raise self._error(
                        "Package GC claim identity was reused",
                        "plugin_package_gc_claim_conflict",
                    )
                return existing
            try:
                append_jsonl_record(
                    self._claim_path,
                    proposed,
                    record_codec=_CLAIM_CODEC,
                    format_profile=SORTED_UNICODE_JSONL_FORMAT,
                    durability=self._unlocked_durability,
                )
            except JournalFileError as exc:
                raise self._error(
                    "Package GC precommit claim append failed",
                    "plugin_package_gc_claim_corrupt",
                ) from exc
            return proposed

    def record(
        self,
        request: PackageDesiredStateCommitRequestV1,
        package_revision: PluginPackageRevisionRefV1,
        transition: PluginDesiredStateTransitionV1 | PluginDesiredStateUpdateTransitionV2,
    ) -> PluginPackageGcBindingV1:
        if not any(
            claim.request == request and claim.package_revision == package_revision
            for claim in self.claims()
        ):
            raise self._error(
                "Package GC crosswalk lacks its precommit claim",
                "plugin_package_gc_claim_missing",
            )
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

    def claims(self) -> tuple[PluginPackageGcClaimV1, ...]:
        with journal_file_lock(self._claim_path, "exclusive"):
            return self._load_claims_unlocked()

    def _load_claims_unlocked(self) -> tuple[PluginPackageGcClaimV1, ...]:
        if not self._claim_path.exists():
            return ()
        try:
            loaded: JsonlSnapshot[None, PluginPackageGcClaimV1] = load_jsonl(
                self._claim_path,
                record_codec=_CLAIM_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
            )
            claims = loaded.records
            _assert_no_duplicate_json_keys(self._claim_path)
            requests: set[str] = set()
            for revision, claim in enumerate(claims, start=1):
                if (
                    claim.record_revision != revision
                    or claim.request.desired_request_id in requests
                ):
                    raise ValueError("Package GC precommit claim chain is invalid")
                requests.add(claim.request.desired_request_id)
            return claims
        except (JournalFileError, JournalCodecError, OSError, UnicodeError, ValueError) as exc:
            raise self._error(
                "Package GC precommit claim journal is corrupt",
                "plugin_package_gc_claim_corrupt",
            ) from exc

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
            _assert_no_duplicate_json_keys(self._path)
            requests: set[str] = set()
            for revision, record in enumerate(records, start=1):
                if (
                    record.record_revision != revision
                    or record.request.desired_request_id in requests
                ):
                    raise ValueError("Package GC crosswalk chain is invalid")
                requests.add(record.request.desired_request_id)
            return records
        except (JournalFileError, JournalCodecError, OSError, UnicodeError, ValueError) as exc:
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


def _claim_id(
    request: PackageDesiredStateCommitRequestV1,
    package_revision: PluginPackageRevisionRefV1,
) -> str:
    payload = json.dumps(
        [request.to_dict(), package_revision.to_dict()],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(b"plugin-package-gc-claim-v1\0" + payload).hexdigest()


def _matches_request(
    request: PackageDesiredStateCommitRequestV1,
    package_revision: PluginPackageRevisionRefV1,
) -> bool:
    return (
        package_revision.plugin_id == request.plugin_id
        and package_revision.plugin_version == request.root_ref.version
        and package_revision.package_content_digest == request.root_ref.artifact_digest
    )


def _integer(value: object) -> int:
    if type(value) is not int:
        raise ValueError("Package GC crosswalk integer is invalid")
    return value


def _string(value: object) -> str:
    if type(value) is not str or not value:
        raise ValueError("Package GC crosswalk string is invalid")
    return value


def _assert_no_duplicate_json_keys(path: Path) -> None:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                json.loads(line, object_pairs_hook=_unique_json_object)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("Package GC binding evidence has a duplicate JSON key")
        document[key] = value
    return document


__all__ = [
    "PluginPackageGcBindingError",
    "PluginPackageGcBindingJournal",
    "PluginPackageGcBindingV1",
    "PluginPackageGcClaimV1",
]
