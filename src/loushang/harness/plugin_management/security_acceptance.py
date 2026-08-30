"""Generic durable security-acceptance authority for Plugin Instances."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

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
from loushang.harness.plugin_management.instance_records import (
    PluginInstanceRevocationV1,
)
from loushang.harness.plugin_management.instance_runtime import (
    PluginInstanceRuntimeLedger,
    PluginInstanceRuntimeSnapshotV1,
    plugin_instance_security_acceptance_journal_path,
)
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.selection import (
    PluginInstanceRevisionRef,
)


class PluginInstanceSecurityRetirementJournalError(RuntimeError):
    """Fail-closed durable security-acceptance journal error."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PluginInstanceSecurityRetirementAcceptanceV1:
    """Durable acceptance of one exact Plugin Instance revocation set."""

    journal_revision: int
    acceptance_id: str
    revocations: tuple[PluginInstanceRevocationV1, ...]
    record_version: int = 1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.journal_revision, int)
            or isinstance(self.journal_revision, bool)
            or self.journal_revision <= 0
        ):
            raise ValueError("Plugin security acceptance revision must be positive")
        if self.record_version != 1:
            raise ValueError("Unsupported Plugin security acceptance version")
        validate_plugin_instance_revocations(self.revocations)
        if self.acceptance_id != plugin_instance_security_acceptance_id(
            self.revocations
        ):
            raise ValueError("Plugin security acceptance id does not match")

    def to_dict(self) -> dict[str, object]:
        return {
            "acceptanceId": self.acceptance_id,
            "journalRevision": self.journal_revision,
            "recordVersion": self.record_version,
            "revocations": [item.to_dict() for item in self.revocations],
        }

    @classmethod
    def from_dict(
        cls,
        value: object,
    ) -> PluginInstanceSecurityRetirementAcceptanceV1:
        try:
            if not isinstance(value, dict) or set(value) != {
                "acceptanceId",
                "journalRevision",
                "recordVersion",
                "revocations",
            }:
                raise ValueError("Plugin security acceptance fields are invalid")
            revocations = value["revocations"]
            if not isinstance(revocations, list):
                raise TypeError("Plugin security revocations must be an array")
            return cls(
                journal_revision=cast(int, value["journalRevision"]),
                acceptance_id=cast(str, value["acceptanceId"]),
                revocations=tuple(
                    PluginInstanceRevocationV1.from_dict(item)
                    for item in revocations
                ),
                record_version=cast(int, value["recordVersion"]),
            )
        except JournalCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise JournalCodecError(
                str(exc),
                code="invalid_plugin_security_acceptance_record",
            ) from exc


PLUGIN_INSTANCE_SECURITY_RETIREMENT_ACCEPTANCE_CODEC = FunctionalJournalRecordCodec[
    PluginInstanceSecurityRetirementAcceptanceV1
](
    encoder=PluginInstanceSecurityRetirementAcceptanceV1.to_dict,
    decoder=PluginInstanceSecurityRetirementAcceptanceV1.from_dict,
)


class PluginInstanceSecurityRetirementJournal:
    """Append-only barrier accepted before an Instance is poisoned."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @classmethod
    def for_instance_runtime(
        cls,
        runtime_path: str | Path,
    ) -> PluginInstanceSecurityRetirementJournal:
        return cls(plugin_instance_security_acceptance_journal_path(runtime_path))

    @property
    def path(self) -> Path:
        return self._path

    def _accept(
        self,
        revocations: tuple[PluginInstanceRevocationV1, ...],
    ) -> PluginInstanceSecurityRetirementAcceptanceV1:
        validate_plugin_instance_revocations(revocations)
        acceptance_id = plugin_instance_security_acceptance_id(revocations)
        with journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            records = self._load_unlocked()
            for record in records:
                if record.acceptance_id == acceptance_id:
                    if record.revocations != revocations:
                        raise self._conflict(
                            "Plugin security acceptance identity was reused"
                        )
                    return record
                if set(_revocation_refs(record.revocations)) & set(
                    _revocation_refs(revocations)
                ):
                    raise self._conflict(
                        "Plugin Instance revision has another security acceptance"
                    )
            record = PluginInstanceSecurityRetirementAcceptanceV1(
                journal_revision=len(records) + 1,
                acceptance_id=acceptance_id,
                revocations=revocations,
            )
            append_jsonl_record(
                self._path,
                record,
                record_codec=PLUGIN_INSTANCE_SECURITY_RETIREMENT_ACCEPTANCE_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
            )
            return record

    def records(
        self,
    ) -> tuple[PluginInstanceSecurityRetirementAcceptanceV1, ...]:
        with journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        ):
            return self._load_unlocked()

    def accepted_instance_revision_refs(
        self,
    ) -> tuple[PluginInstanceRevisionRef, ...]:
        refs = {item.instance_revision_ref for item in self.accepted_revocations()}
        return tuple(sorted(refs, key=_instance_ref_sort_key))

    def accepted_revocations(self) -> tuple[PluginInstanceRevocationV1, ...]:
        return tuple(
            revocation
            for record in self.records()
            for revocation in record.revocations
        )

    def reconcile(
        self,
        ledger: PluginInstanceRuntimeLedger,
    ) -> tuple[PluginInstanceRuntimeSnapshotV1, ...]:
        if not isinstance(ledger, PluginInstanceRuntimeLedger):
            raise TypeError("Plugin security recovery requires Instance ledger")
        revocations = self.accepted_revocations()
        if not revocations:
            return ()
        snapshots = ledger.apply_accepted_security_revocations(revocations)
        for revocation, snapshot in zip(revocations, snapshots, strict=True):
            if (
                snapshot.instance_revision_ref != revocation.instance_revision_ref
                or snapshot.installation_key != revocation.installation_key
                or snapshot.state not in {"REVOKING", "RETIRED"}
                or snapshot.revocation != revocation
            ):
                raise PluginInstanceSecurityRetirementJournalError(
                    "Recovered security revocation evidence is invalid.",
                    code="plugin_security_recovery_invalid",
                    path=self._path,
                )
        return snapshots

    def _load_unlocked(
        self,
    ) -> tuple[PluginInstanceSecurityRetirementAcceptanceV1, ...]:
        if not self._path.exists():
            return ()
        try:
            snapshot: JsonlSnapshot[
                None,
                PluginInstanceSecurityRetirementAcceptanceV1,
            ] = load_jsonl(
                self._path,
                record_codec=PLUGIN_INSTANCE_SECURITY_RETIREMENT_ACCEPTANCE_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
            )
            records = snapshot.records
            if any(
                item.journal_revision != index
                for index, item in enumerate(records, start=1)
            ):
                raise ValueError("Plugin security revisions are not contiguous")
            return records
        except (JournalCodecError, JournalFileError, ValueError) as exc:
            raise PluginInstanceSecurityRetirementJournalError(
                "Plugin security acceptance journal is corrupt.",
                code="plugin_security_acceptance_journal_corrupt",
                path=self._path,
            ) from exc

    def _conflict(
        self,
        message: str,
    ) -> PluginInstanceSecurityRetirementJournalError:
        return PluginInstanceSecurityRetirementJournalError(
            message,
            code="plugin_security_acceptance_conflict",
            path=self._path,
        )


def validate_plugin_instance_revocations(
    revocations: tuple[PluginInstanceRevocationV1, ...],
) -> None:
    if not revocations or any(
        not isinstance(item, PluginInstanceRevocationV1) for item in revocations
    ):
        raise TypeError("Plugin security retirement requires revocations")
    refs = _revocation_refs(revocations)
    if len(refs) != len(set(refs)):
        raise ValueError("Plugin security retirement repeats an Instance revision")
    if refs != tuple(sorted(refs, key=_instance_ref_sort_key)):
        raise ValueError("Plugin security retirement set must be canonical")


def _revocation_refs(
    revocations: tuple[PluginInstanceRevocationV1, ...],
) -> tuple[PluginInstanceRevisionRef, ...]:
    return tuple(item.instance_revision_ref for item in revocations)


def _instance_ref_sort_key(
    value: PluginInstanceRevisionRef,
) -> tuple[str, str, int]:
    return value.plugin_id, value.instance_id, value.revision


def plugin_instance_security_acceptance_id(
    revocations: tuple[PluginInstanceRevocationV1, ...],
) -> str:
    payload = StrictPluginJsonCodec.encode([item.to_dict() for item in revocations])
    # Preserve the deployed v1 digest namespace while moving its ownership out
    # of the Continuity adapter.
    return hashlib.sha256(
        b"loushang.continuity-security-acceptance/v1\0" + payload
    ).hexdigest()


__all__ = [
    "PLUGIN_INSTANCE_SECURITY_RETIREMENT_ACCEPTANCE_CODEC",
    "PluginInstanceSecurityRetirementAcceptanceV1",
    "PluginInstanceSecurityRetirementJournal",
    "PluginInstanceSecurityRetirementJournalError",
    "plugin_instance_security_acceptance_id",
    "validate_plugin_instance_revocations",
]
