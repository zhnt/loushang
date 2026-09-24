"""Durable evidence that one exact private-data plan was separately confirmed.

Only a trusted Product/operator command may record a confirmation. This owner
does not delete data or authorize Package remove/GC to do so.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, replace
from pathlib import Path

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalLoadPolicy,
    JsonlSnapshot,
    append_jsonl_record,
    journal_file_lock,
    load_jsonl,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionPlanV1,
)

PRIVATE_DATA_CONFIRMATION_RECORD_VERSION = 1


@dataclass(frozen=True, slots=True)
class PluginPrivateDataConfirmationRecordV1:
    record_revision: int
    plan: PluginPrivateDataDeletionPlanV1
    confirmation: PluginPrivateDataDeletionConfirmationV1
    actor_id: str
    policy_revision: str
    record_version: int = PRIVATE_DATA_CONFIRMATION_RECORD_VERSION

    def __post_init__(self) -> None:
        if type(self.record_revision) is not int or self.record_revision < 1:
            raise ValueError("Private-data confirmation revision is invalid")
        if not isinstance(self.plan, PluginPrivateDataDeletionPlanV1) or not isinstance(
            self.confirmation, PluginPrivateDataDeletionConfirmationV1
        ):
            raise TypeError("Private-data confirmation requires an exact plan")
        if self.confirmation.plan_fingerprint != self.plan.fingerprint:
            raise ValueError("Private-data confirmation plan changed")
        if not isinstance(self.actor_id, str) or not self.actor_id.strip():
            raise ValueError("Private-data confirmation actor is required")
        if not isinstance(self.policy_revision, str) or not self.policy_revision.strip():
            raise ValueError("Private-data confirmation policy is required")
        if (
            type(self.record_version) is not int
            or self.record_version != PRIVATE_DATA_CONFIRMATION_RECORD_VERSION
        ):
            raise ValueError("Unsupported private-data confirmation record")

    def to_dict(self) -> dict[str, object]:
        return {
            "actorId": self.actor_id,
            "confirmation": self.confirmation.to_dict(),
            "plan": self.plan.to_dict(),
            "policyRevision": self.policy_revision,
            "recordRevision": self.record_revision,
            "recordVersion": self.record_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginPrivateDataConfirmationRecordV1:
        if type(value) is not dict or set(value) != {
            "actorId", "confirmation", "plan", "policyRevision",
            "recordRevision", "recordVersion",
        }:
            raise JournalCodecError(
                "Private-data confirmation fields are invalid",
                code="invalid_private_data_confirmation_record",
            )
        try:
            return cls(
                record_revision=value["recordRevision"],
                plan=PluginPrivateDataDeletionPlanV1.from_dict(value["plan"]),
                confirmation=PluginPrivateDataDeletionConfirmationV1.from_dict(
                    value["confirmation"]
                ),
                actor_id=value["actorId"],
                policy_revision=value["policyRevision"],
                record_version=value["recordVersion"],
            )
        except (TypeError, ValueError) as exc:
            raise JournalCodecError(
                "Private-data confirmation record is invalid",
                code="invalid_private_data_confirmation_record",
            ) from exc


_CODEC = FunctionalJournalRecordCodec(
    encoder=PluginPrivateDataConfirmationRecordV1.to_dict,
    decoder=PluginPrivateDataConfirmationRecordV1.from_dict,
)


class PluginPrivateDataConfirmationJournal:
    """Replayable confirmation authority, injected into the deletion boundary."""

    def __init__(self, path: str | Path) -> None:
        candidate = Path(path)
        if not candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("Private-data confirmation journal path must be absolute")
        self._path = candidate
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def record_confirmation(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
        *,
        actor_id: str,
        policy_revision: str,
    ) -> PluginPrivateDataConfirmationRecordV1:
        if not isinstance(plan, PluginPrivateDataDeletionPlanV1) or not isinstance(
            confirmation, PluginPrivateDataDeletionConfirmationV1
        ):
            raise TypeError("Exact private-data plan and confirmation are required")
        if confirmation.plan_fingerprint != plan.fingerprint:
            raise ValueError("Private-data confirmation plan changed")
        self._require_private_parent()
        with journal_file_lock(self._path, "exclusive"):
            records = self._load_unlocked()
            prior = next(
                (
                    record
                    for record in records
                    if record.confirmation.confirmation_id == confirmation.confirmation_id
                ),
                None,
            )
            proposed = PluginPrivateDataConfirmationRecordV1(
                record_revision=(
                    prior.record_revision if prior is not None else len(records) + 1
                ),
                plan=plan,
                confirmation=confirmation,
                actor_id=actor_id,
                policy_revision=policy_revision,
            )
            if prior is not None:
                if prior != proposed:
                    raise ValueError("Private-data confirmation identity was reused")
                return prior
            append_jsonl_record(
                self._path,
                proposed,
                record_codec=_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
            )
            return proposed

    def is_confirmed(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> bool:
        if not isinstance(plan, PluginPrivateDataDeletionPlanV1) or not isinstance(
            confirmation, PluginPrivateDataDeletionConfirmationV1
        ):
            raise TypeError("Exact private-data plan and confirmation are required")
        self._require_private_parent()
        with journal_file_lock(self._path, "exclusive"):
            records = self._load_unlocked()
        return any(
            record.plan == plan and record.confirmation == confirmation
            for record in records
        )

    def _load_unlocked(self) -> tuple[PluginPrivateDataConfirmationRecordV1, ...]:
        try:
            metadata = self._path.lstat()
        except FileNotFoundError:
            return ()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or (os.name == "posix" and metadata.st_mode & 0o077)
            or (
                os.name == "posix"
                and metadata.st_uid != os.geteuid()
            )
        ):
            raise ValueError("Private-data confirmation journal is unsafe")
        loaded: JsonlSnapshot[None, PluginPrivateDataConfirmationRecordV1] = load_jsonl(
            self._path,
            record_codec=_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._unlocked_durability,
            load_policy=self._load_policy,
        )
        records = loaded.records
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    json.loads(line, object_pairs_hook=_unique_json_object)
        seen_ids: set[str] = set()
        for revision, record in enumerate(records, start=1):
            confirmation_id = record.confirmation.confirmation_id
            if record.record_revision != revision or confirmation_id in seen_ids:
                raise ValueError("Private-data confirmation journal is inconsistent")
            seen_ids.add(confirmation_id)
        return records

    def _require_private_parent(self) -> None:
        metadata = self._path.parent.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or (os.name == "posix" and metadata.st_mode & 0o077)
            or (os.name == "posix" and metadata.st_uid != os.geteuid())
        ):
            raise ValueError("Private-data confirmation parent is not private")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Private-data confirmation has a duplicate JSON key")
        result[key] = value
    return result


__all__ = [
    "PRIVATE_DATA_CONFIRMATION_RECORD_VERSION",
    "PluginPrivateDataConfirmationJournal",
    "PluginPrivateDataConfirmationRecordV1",
]
