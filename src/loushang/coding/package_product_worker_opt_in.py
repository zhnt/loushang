"""Durable, default-dark Coding Product decisions for local Worker candidates.

The journal records a per-Plugin operator decision. It grants no Package
selection, activation receipt, native launch, or Capability publication.
"""

from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Literal

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalLoadPolicy,
    append_jsonl_record,
    decode_jsonl,
)
from loushang.harness.journal._rooted_io import RootedFile, RootedFileIO
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .package_product_worker_history_segments import (
    CodingWorkerHistorySegmentError,
    CodingWorkerSegmentedHistoryV1,
    read_coding_worker_segmented_history,
    seal_coding_worker_active_segment,
)
from .package_product_worker_policy import CodingWorkerOptInV1

_OPAQUE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._:@+-]*[A-Za-z0-9])?\Z")
_IDENTIFIER = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_EVENTS = 4096
_MAX_SEGMENT_BYTES = 32 * 1024 * 1024
_STEM = "worker-opt-in"


class CodingWorkerOptInJournalError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWorkerOptInDecisionV1:
    journal_revision: int
    scope_id: str
    plugin_id: str
    operation_id: str
    generation: int
    kill_switch_generation: int
    action: Literal["allow", "revoke"]
    opt_in: CodingWorkerOptInV1 | None
    decision_digest: str
    record_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.journal_revision) is not int
            or self.journal_revision < 1
            or type(self.generation) is not int
            or self.generation < 1
            or type(self.kill_switch_generation) is not int
            or self.kill_switch_generation < 0
            or not isinstance(self.scope_id, str)
            or len(self.scope_id) > 128
            or _OPAQUE.fullmatch(self.scope_id) is None
            or not isinstance(self.plugin_id, str)
            or len(self.plugin_id) > 128
            or _IDENTIFIER.fullmatch(self.plugin_id) is None
            or not isinstance(self.operation_id, str)
            or len(self.operation_id) > 128
            or _OPAQUE.fullmatch(self.operation_id) is None
            or self.action not in {"allow", "revoke"}
            or self.record_version != 1
            or not isinstance(self.decision_digest, str)
            or _DIGEST.fullmatch(self.decision_digest) is None
        ):
            raise ValueError("Coding Worker opt-in decision is invalid")
        if self.action == "allow":
            if (
                not isinstance(self.opt_in, CodingWorkerOptInV1)
                or self.opt_in.plugin_id != self.plugin_id
                or self.opt_in.owner_selection_generation != self.generation
                or self.opt_in.kill_switch_generation != self.kill_switch_generation
            ):
                raise ValueError("Coding Worker opt-in generation is invalid")
        elif self.opt_in is not None:
            raise ValueError("Coding Worker revoke cannot retain an opt-in")
        if self.decision_digest != self._fingerprint():
            raise ValueError("Coding Worker opt-in decision digest changed")

    @classmethod
    def create(
        cls,
        *,
        journal_revision: int,
        scope_id: str,
        plugin_id: str,
        operation_id: str,
        generation: int,
        kill_switch_generation: int,
        action: Literal["allow", "revoke"],
        opt_in: CodingWorkerOptInV1 | None,
    ) -> CodingWorkerOptInDecisionV1:
        values = {
            "action": action,
            "generation": generation,
            "journalRevision": journal_revision,
            "killSwitchGeneration": kill_switch_generation,
            "operationId": operation_id,
            "optIn": None if opt_in is None else opt_in.to_dict(),
            "pluginId": plugin_id,
            "recordVersion": 1,
            "scopeId": scope_id,
        }
        return cls(
            journal_revision=journal_revision,
            scope_id=scope_id,
            plugin_id=plugin_id,
            operation_id=operation_id,
            generation=generation,
            kill_switch_generation=kill_switch_generation,
            action=action,
            opt_in=opt_in,
            decision_digest=sha256(canonical_json_bytes(values)).hexdigest(),
        )

    def _fingerprint(self) -> str:
        return sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "generation": self.generation,
            "journalRevision": self.journal_revision,
            "killSwitchGeneration": self.kill_switch_generation,
            "operationId": self.operation_id,
            "optIn": None if self.opt_in is None else self.opt_in.to_dict(),
            "pluginId": self.plugin_id,
            "recordVersion": self.record_version,
            "scopeId": self.scope_id,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._unsigned_dict(), "decisionDigest": self.decision_digest}

    @classmethod
    def from_dict(cls, value: object) -> CodingWorkerOptInDecisionV1:
        fields = {
            "action",
            "decisionDigest",
            "generation",
            "journalRevision",
            "killSwitchGeneration",
            "operationId",
            "optIn",
            "pluginId",
            "recordVersion",
            "scopeId",
        }
        if type(value) is not dict or set(value) != fields:
            raise ValueError("Coding Worker opt-in decision record is invalid")
        opt_in = value["optIn"]
        return cls(
            journal_revision=value["journalRevision"],
            scope_id=value["scopeId"],
            plugin_id=value["pluginId"],
            operation_id=value["operationId"],
            generation=value["generation"],
            kill_switch_generation=value["killSwitchGeneration"],
            action=value["action"],
            opt_in=None if opt_in is None else CodingWorkerOptInV1.from_dict(opt_in),
            decision_digest=value["decisionDigest"],
            record_version=value["recordVersion"],
        )


def _decode(value: object) -> CodingWorkerOptInDecisionV1:
    try:
        return CodingWorkerOptInDecisionV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Coding Worker opt-in decision record is invalid",
            code="coding_worker_opt_in_record_invalid",
        ) from exc


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingWorkerOptInDecisionV1.to_dict,
    decoder=_decode,
)


def _decode_coding_worker_opt_in_history(
    raw: bytes, *, path: Path, scope_id: str
) -> tuple[CodingWorkerOptInDecisionV1, ...]:
    """Replay one exact scope's decisions for either Product platform owner."""

    if len(raw) > _MAX_SEGMENT_BYTES:
        raise CodingWorkerOptInJournalError("coding_worker_opt_in_capacity")
    events: tuple[CodingWorkerOptInDecisionV1, ...] = decode_jsonl(
        raw.decode("utf-8"),
        target=path,
        record_codec=_CODEC,
        load_policy=JournalLoadPolicy(partial_tail="raise", create_lock=False),
    ).records
    if len(events) > _MAX_EVENTS:
        raise CodingWorkerOptInJournalError("coding_worker_opt_in_capacity")
    _validate_opt_in_events(events, scope_id=scope_id)
    return events


def _validate_opt_in_events(
    events: tuple[CodingWorkerOptInDecisionV1, ...], *, scope_id: str
) -> None:
    seen_operations: set[str] = set()
    latest: dict[str, CodingWorkerOptInDecisionV1] = {}
    for revision, event in enumerate(events, 1):
        prior = latest.get(event.plugin_id)
        expected_generation = 1 if prior is None else prior.generation + 1
        expected_kill = 0 if prior is None else prior.kill_switch_generation
        if event.action == "revoke":
            expected_kill += 1
        if (
            event.scope_id != scope_id
            or event.journal_revision != revision
            or event.operation_id in seen_operations
            or event.generation != expected_generation
            or event.kill_switch_generation != expected_kill
            or (event.action == "revoke" and prior is None)
        ):
            raise CodingWorkerOptInJournalError("coding_worker_opt_in_corrupt")
        seen_operations.add(event.operation_id)
        latest[event.plugin_id] = event


class CodingWorkerOptInJournal:
    """Product-private CAS journal serialized with Desired State and GC."""

    def __init__(
        self,
        path: Path,
        *,
        scope_id: str,
        gc_gate: PluginPackageGcReservationJournal,
    ) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise ValueError("Coding Worker opt-in journal path is invalid")
        if (
            not isinstance(scope_id, str)
            or len(scope_id) > 128
            or _OPAQUE.fullmatch(scope_id) is None
        ):
            raise ValueError("Coding Worker opt-in scope is invalid")
        if not isinstance(gc_gate, PluginPackageGcReservationJournal):
            raise TypeError("Product GC gate is required")
        if path != gc_gate.path.parent / "worker-opt-in.jsonl":
            raise ValueError("Coding Worker opt-in journal is outside Product state")
        self._path = path
        self._scope_id = scope_id
        self._gc_gate = gc_gate
        self._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def scope_id(self) -> str:
        return self._scope_id

    @property
    def gc_gate(self) -> PluginPackageGcReservationJournal:
        return self._gc_gate

    def current(self, plugin_id: str) -> CodingWorkerOptInDecisionV1 | None:
        """Read the latest Product decision under the shared selection gate."""

        self._require_plugin_id(plugin_id)
        with self._gc_gate.guard(), self._bound_journal(create_lock=False) as rooted:
            events, _history = self._load_history(rooted)
            return self._latest(events, plugin_id)

    def current_read_only(self, plugin_id: str) -> CodingWorkerOptInDecisionV1 | None:
        """Inspect an existing Product decision without creating owner state."""

        self._require_plugin_id(plugin_id)
        with self._gc_gate.read_guard(), self._bound_journal(
            create_lock=False
        ) as rooted:
            events, _history = self._load_history(rooted)
            return self._latest(events, plugin_id)

    def change(
        self,
        *,
        plugin_id: str,
        operation_id: str,
        expected_generation: int,
        action: Literal["allow", "revoke"],
        opt_in: CodingWorkerOptInV1 | None,
    ) -> CodingWorkerOptInDecisionV1:
        """Persist one explicit decision; replay the same operation exactly."""

        self._require_plugin_id(plugin_id)
        if (
            not isinstance(operation_id, str)
            or len(operation_id) > 128
            or _OPAQUE.fullmatch(operation_id) is None
            or type(expected_generation) is not int
            or expected_generation < 0
            or action not in {"allow", "revoke"}
            or (action == "allow" and not isinstance(opt_in, CodingWorkerOptInV1))
            or (action == "revoke" and opt_in is not None)
        ):
            raise ValueError("Coding Worker opt-in command is invalid")
        with self._gc_gate.guard(), self._bound_journal() as rooted:
            events, history = self._load_history(rooted)
            replay = next(
                (event for event in events if event.operation_id == operation_id), None
            )
            if replay is not None:
                if (
                    replay.plugin_id != plugin_id
                    or replay.action != action
                    or replay.opt_in != opt_in
                    or replay.generation != expected_generation + 1
                ):
                    raise CodingWorkerOptInJournalError(
                        "coding_worker_opt_in_operation_conflict"
                    )
                return replay
            previous = self._latest(events, plugin_id)
            generation = 0 if previous is None else previous.generation
            if generation != expected_generation:
                raise CodingWorkerOptInJournalError("coding_worker_opt_in_stale")
            if action == "revoke" and previous is None:
                raise CodingWorkerOptInJournalError("coding_worker_opt_in_absent")
            kill = 0 if previous is None else previous.kill_switch_generation
            if action == "revoke":
                kill += 1
            if action == "allow" and (
                opt_in is None
                or opt_in.plugin_id != plugin_id
                or opt_in.owner_selection_generation != generation + 1
                or opt_in.kill_switch_generation != kill
            ):
                raise CodingWorkerOptInJournalError(
                    "coding_worker_opt_in_generation_invalid"
                )
            decision = CodingWorkerOptInDecisionV1.create(
                journal_revision=len(events) + 1,
                scope_id=self._scope_id,
                plugin_id=plugin_id,
                operation_id=operation_id,
                generation=generation + 1,
                kill_switch_generation=kill,
                action=action,
                opt_in=opt_in,
            )
            line = _opt_in_line(decision)
            if len(line) > _MAX_SEGMENT_BYTES:
                raise CodingWorkerOptInJournalError("coding_worker_opt_in_capacity")
            if (
                len(events) - history.last_sealed_revision >= _MAX_EVENTS
                or len(history.active_raw) + len(line) > _MAX_SEGMENT_BYTES
            ):
                try:
                    seal_coding_worker_active_segment(
                        rooted,
                        stem=_STEM,
                        stream_id=_STEM,
                        history=history,
                        last_revision=len(events),
                    )
                except CodingWorkerHistorySegmentError as exc:
                    raise CodingWorkerOptInJournalError(exc.code) from exc
                generation = history.active_generation + 1
            else:
                generation = history.active_generation
            target = rooted.sibling(
                f"{_STEM}.jsonl"
                if generation == 0
                else f"{_STEM}.g{generation:08d}.jsonl"
            )
            append_jsonl_record(
                self._path,
                decision,
                record_codec=_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._durability,
                bound_file=target,
            )
            return decision

    @contextmanager
    def _bound_journal(self, *, create_lock: bool = True) -> Iterator[RootedFile]:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        parent_fd = os.open(self._path.parent, flags)
        try:
            opened = os.fstat(parent_fd)
            visible = self._path.parent.lstat()
            if (
                not stat.S_ISDIR(opened.st_mode)
                or opened.st_uid != os.geteuid()
                or stat.S_IMODE(opened.st_mode) & 0o077
                or (opened.st_dev, opened.st_ino)
                != (visible.st_dev, visible.st_ino)
            ):
                raise CodingWorkerOptInJournalError(
                    "coding_worker_opt_in_state_root_unsafe"
                )
            file_io = RootedFileIO(self._path.parent, parent_fd)
            try:
                with file_io.bind(self._path, durable=True) as rooted:
                    if create_lock:
                        try:
                            rooted.stat()
                        except FileNotFoundError:
                            try:
                                rooted.sibling(self._path.name + ".lock").stat()
                            except FileNotFoundError:
                                pass
                            else:
                                raise CodingWorkerOptInJournalError(
                                    "coding_worker_opt_in_orphan_lock"
                                ) from None
                        else:
                            try:
                                rooted.sibling(self._path.name + ".lock").stat()
                            except FileNotFoundError as exc:
                                raise CodingWorkerOptInJournalError(
                                    "coding_worker_opt_in_lock_missing"
                                ) from exc
                        rooted.acquire_lock(
                            exclusive=True,
                            suffix=".lock",
                            initialize_empty_target_if_new=True,
                        )
                    else:
                        try:
                            rooted.stat()
                        except FileNotFoundError:
                            try:
                                rooted.sibling(self._path.name + ".lock").stat()
                            except FileNotFoundError:
                                pass
                            else:
                                raise CodingWorkerOptInJournalError(
                                    "coding_worker_opt_in_orphan_lock"
                                ) from None
                        else:
                            try:
                                rooted.acquire_lock(
                                    exclusive=False, suffix=".lock", create=False
                                )
                            except FileNotFoundError as exc:
                                raise CodingWorkerOptInJournalError(
                                    "coding_worker_opt_in_lock_missing"
                                ) from exc
                    yield rooted
            finally:
                file_io.cleanup()
            visible_after = self._path.parent.lstat()
            if (opened.st_dev, opened.st_ino) != (
                visible_after.st_dev,
                visible_after.st_ino,
            ):
                raise CodingWorkerOptInJournalError(
                    "coding_worker_opt_in_state_root_changed"
                )
        finally:
            os.close(parent_fd)

    def _load(self, rooted: RootedFile) -> tuple[CodingWorkerOptInDecisionV1, ...]:
        events, _history = self._load_history(rooted)
        return events

    def _load_history(
        self, rooted: RootedFile
    ) -> tuple[
        tuple[CodingWorkerOptInDecisionV1, ...], CodingWorkerSegmentedHistoryV1
    ]:
        try:
            history = read_coding_worker_segmented_history(
                rooted,
                stem=_STEM,
                stream_id=_STEM,
                max_segment_bytes=_MAX_SEGMENT_BYTES,
            )
        except CodingWorkerHistorySegmentError as exc:
            raise CodingWorkerOptInJournalError(exc.code) from exc
        events: list[CodingWorkerOptInDecisionV1] = []
        for generation, raw in enumerate(history.segments):
            segment = decode_jsonl(
                raw.decode("utf-8"),
                target=self._path,
                record_codec=_CODEC,
                load_policy=JournalLoadPolicy(
                    partial_tail="raise", create_lock=False
                ),
            ).records
            lines = raw.splitlines(keepends=True)
            if (
                len(segment) > _MAX_EVENTS
                or len(segment) != len(lines)
                or any(
                    event.journal_revision != revision
                    or line != _opt_in_line(event)
                    for revision, (event, line) in enumerate(
                        zip(segment, lines, strict=True), len(events) + 1
                    )
                )
            ):
                raise CodingWorkerOptInJournalError("coding_worker_opt_in_corrupt")
            events.extend(segment)
            if (
                history.manifest is not None
                and generation < history.active_generation
                and len(events) != history.manifest.sealed[generation].last_revision
            ):
                raise CodingWorkerOptInJournalError("coding_worker_opt_in_corrupt")
        result = tuple(events)
        _validate_opt_in_events(result, scope_id=self._scope_id)
        return result, history

    @staticmethod
    def _latest(
        events: tuple[CodingWorkerOptInDecisionV1, ...], plugin_id: str
    ) -> CodingWorkerOptInDecisionV1 | None:
        return next(
            (event for event in reversed(events) if event.plugin_id == plugin_id),
            None,
        )

    @staticmethod
    def _require_plugin_id(plugin_id: str) -> None:
        if (
            not isinstance(plugin_id, str)
            or len(plugin_id) > 128
            or _IDENTIFIER.fullmatch(plugin_id) is None
        ):
            raise ValueError("Coding Worker opt-in Plugin id is invalid")


def _opt_in_line(decision: CodingWorkerOptInDecisionV1) -> bytes:
    return json.dumps(decision.to_dict(), ensure_ascii=False, sort_keys=True).encode(
        "utf-8"
    ) + b"\n"


__all__ = [
    "CodingWorkerOptInDecisionV1",
    "CodingWorkerOptInJournal",
    "CodingWorkerOptInJournalError",
]
