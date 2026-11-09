"""Opt-in value, sequence and retained-history mechanics, without admission authority."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from hashlib import sha256
from pathlib import Path
from typing import ClassVar, Literal, Protocol, Self, TypeVar, cast

from loushang.harness.journal import (
    JournalLoadPolicy,
    JournalRecordCodec,
    decode_jsonl,
)
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .._segmented_history import CodingWorkerSegmentedHistoryV1
from ._base_codec import _BaseWireMethods, _unchanged

_OPAQUE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._:@+-]*[A-Za-z0-9])?\Z")
_IDENTIFIER = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_EVENTS = 4096
_MAX_SEGMENT_BYTES = 32 * 1024 * 1024


class _OptInValue(Protocol):
    @property
    def plugin_id(self) -> str: ...

    @property
    def owner_selection_generation(self) -> int: ...

    @property
    def kill_switch_generation(self) -> int: ...

    def to_dict(self) -> dict[str, object]: ...

    @classmethod
    def from_dict(cls, value: object) -> Self: ...


class _OptInDecisionMethods:
    __slots__ = ()

    journal_revision: int
    scope_id: str
    plugin_id: str
    operation_id: str
    generation: int
    kill_switch_generation: int
    action: Literal["allow", "revoke"]
    opt_in: _OptInValue | None
    decision_digest: str
    record_version: int = 1

    _opt_in_type: ClassVar[type[_OptInValue]]

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
                not isinstance(self.opt_in, self._opt_in_type)
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
        opt_in: _OptInValue | None,
    ) -> Self:
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
        return cast(Callable[..., Self], cls)(
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
    def from_dict(cls, value: object) -> Self:
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
        return cast(Callable[..., Self], cls)(
            journal_revision=value["journalRevision"],
            scope_id=value["scopeId"],
            plugin_id=value["pluginId"],
            operation_id=value["operationId"],
            generation=value["generation"],
            kill_switch_generation=value["killSwitchGeneration"],
            action=value["action"],
            opt_in=None if opt_in is None else cls._opt_in_type.from_dict(opt_in),
            decision_digest=value["decisionDigest"],
            record_version=value["recordVersion"],
        )


_DecisionT = TypeVar("_DecisionT", bound=_OptInDecisionMethods)


def fold_opt_in_events(
    events: tuple[_DecisionT, ...],
    *,
    scope_id: str,
    error_type: type[RuntimeError],
    start_revision: int = 1,
    initial_latest: Mapping[str, _DecisionT] | None = None,
    initial_operations: frozenset[str] = frozenset(),
) -> tuple[dict[str, _DecisionT], frozenset[str]]:
    """Validate global revisions and decisions across a V1 or V2 boundary."""

    seen_operations = set(initial_operations)
    latest = {} if initial_latest is None else dict(initial_latest)
    for revision, event in enumerate(events, start_revision):
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
            raise error_type("coding_worker_opt_in_corrupt")
        seen_operations.add(event.operation_id)
        latest[event.plugin_id] = event
    return latest, frozenset(seen_operations)


def decode_opt_in_history(
    raw: bytes,
    *,
    path: Path,
    scope_id: str,
    record_codec: JournalRecordCodec[_DecisionT],
    error_type: type[RuntimeError],
    max_events: int,
    max_segment_bytes: int,
) -> tuple[_DecisionT, ...]:
    """Replay one exact scope's decisions for either Product platform owner."""

    if len(raw) > max_segment_bytes:
        raise error_type("coding_worker_opt_in_capacity")
    events: tuple[_DecisionT, ...] = decode_jsonl(
        raw.decode("utf-8"),
        target=path,
        record_codec=record_codec,
        load_policy=JournalLoadPolicy(partial_tail="raise", create_lock=False),
    ).records
    if len(events) > max_events:
        raise error_type("coding_worker_opt_in_capacity")
    fold_opt_in_events(events, scope_id=scope_id, error_type=error_type)
    return events


def opt_in_line(decision: _OptInDecisionMethods) -> bytes:
    return (
        json.dumps(decision.to_dict(), ensure_ascii=False, sort_keys=True).encode(
            "utf-8"
        )
        + b"\n"
    )


def parse_opt_in_segment(
    raw: bytes, *, decision_type: type[_DecisionT]
) -> tuple[_DecisionT, ...]:
    if type(raw) is not bytes or len(raw) > _MAX_SEGMENT_BYTES:
        raise ValueError("Coding Worker opt-in V2 segment is invalid")
    lines = raw.splitlines(keepends=True)
    if len(lines) > _MAX_EVENTS:
        raise ValueError("Coding Worker opt-in V2 segment exceeds capacity")
    events: list[_DecisionT] = []
    try:
        for line in lines:
            event = decision_type.from_dict(json.loads(line))
            if line != opt_in_line(event):
                raise ValueError("Coding Worker opt-in V2 segment encoding changed")
            events.append(event)
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("Coding Worker opt-in V2 segment is invalid") from exc
    return tuple(events)


class _OptInReplayFields:
    __slots__ = ()

    last_revision: int
    latest_decisions: tuple[_OptInDecisionMethods, ...]
    operation_ids: frozenset[str]


class _OptInBaseMethods(_BaseWireMethods):
    __slots__ = ()

    _wire_label = "Coding Worker opt-in V2 semantic base"
    _wire_lists = ("latestDecisions", "retiredOperationIds")

    @classmethod
    def _make_wire_schema(cls) -> RecordSchema:
        return RecordSchema.for_dataclass(
            cls,
            _unchanged,
            RecordField(
                "latest_decisions",
                encoder=lambda xs: [x.to_dict() for x in xs],
                decoder=lambda xs: tuple(cls._decision_type.from_dict(x) for x in xs),
            ),
            RecordField("retired_operation_ids", encoder=list, decoder=tuple),
        )

    scope_id: str
    first_retained_generation: int
    cutoff_revision: int
    retired_sealed_digest: str
    latest_decisions: tuple[_OptInDecisionMethods, ...]
    retired_operation_ids: tuple[str, ...]
    version: int = 2

    _decision_type: ClassVar[type[_OptInDecisionMethods]]
    _error_type: ClassVar[type[RuntimeError]]
    _replay_type: ClassVar[type[_OptInReplayFields]]

    def __post_init__(self) -> None:
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or _OPAQUE.fullmatch(self.scope_id) is None
            or type(self.first_retained_generation) is not int
            or self.first_retained_generation < 1
            or type(self.cutoff_revision) is not int
            or self.cutoff_revision < self.first_retained_generation
            or type(self.retired_sealed_digest) is not str
            or _DIGEST.fullmatch(self.retired_sealed_digest) is None
            or type(self.latest_decisions) is not tuple
            or not self.latest_decisions
            or any(
                type(item) is not self._decision_type
                or item.scope_id != self.scope_id
                or item.journal_revision > self.cutoff_revision
                for item in self.latest_decisions
            )
            or tuple(item.plugin_id for item in self.latest_decisions)
            != tuple(sorted({item.plugin_id for item in self.latest_decisions}))
            or type(self.retired_operation_ids) is not tuple
            or any(
                type(item) is not str
                or len(item) > 128
                or _OPAQUE.fullmatch(item) is None
                for item in self.retired_operation_ids
            )
            or self.retired_operation_ids
            != tuple(sorted(set(self.retired_operation_ids)))
            or len(self.retired_operation_ids) != self.cutoff_revision
            or any(
                item.operation_id not in self.retired_operation_ids
                for item in self.latest_decisions
            )
            or type(self.version) is not int
            or self.version != 2
        ):
            raise ValueError("Coding Worker opt-in V2 semantic base is invalid")

    @classmethod
    def from_v1_history(
        cls,
        *,
        history: CodingWorkerSegmentedHistoryV1,
        scope_id: str,
        first_retained_generation: int,
    ) -> Self:
        """Project a sealed, exact V1 prefix into a candidate semantic base."""

        if type(history) is not CodingWorkerSegmentedHistoryV1:
            raise ValueError("Coding Worker opt-in V2 source is invalid")
        manifest = history.manifest
        if (
            manifest is None
            or manifest.stream_id != "worker-opt-in"
            or type(first_retained_generation) is not int
            or not 1 <= first_retained_generation <= manifest.active_generation
            or len(history.segments) != manifest.active_generation + 1
        ):
            raise ValueError("Coding Worker opt-in V2 source is invalid")
        retired = manifest.sealed[:first_retained_generation]
        events: list[_OptInDecisionMethods] = []
        for seal, raw in zip(
            retired, history.segments[:first_retained_generation], strict=True
        ):
            if len(raw) != seal.byte_count or sha256(raw).hexdigest() != seal.digest:
                raise ValueError("Coding Worker opt-in V2 source changed")
            events.extend(parse_opt_in_segment(raw, decision_type=cls._decision_type))
            if len(events) != seal.last_revision:
                raise ValueError("Coding Worker opt-in V2 source revision changed")
        cutoff_revision = retired[-1].last_revision
        if len(events) != cutoff_revision:
            raise ValueError("Coding Worker opt-in V2 source revision changed")
        try:
            latest, seen = fold_opt_in_events(
                tuple(events), scope_id=scope_id, error_type=cls._error_type
            )
        except cls._error_type as exc:
            raise ValueError("Coding Worker opt-in V2 source is invalid") from exc
        return cast(Callable[..., Self], cls)(
            scope_id=scope_id,
            first_retained_generation=first_retained_generation,
            cutoff_revision=cutoff_revision,
            retired_sealed_digest=sha256(
                canonical_json_bytes([item.to_dict() for item in retired])
            ).hexdigest(),
            latest_decisions=tuple(latest[key] for key in sorted(latest)),
            retired_operation_ids=tuple(sorted(seen)),
        )

    def replay_retained(self, segments: tuple[bytes, ...]) -> _OptInReplayFields:
        """Replay kept records against the base; source digests belong to V2 IO."""

        if type(segments) is not tuple or not segments:
            raise ValueError("Coding Worker opt-in V2 retained segments are invalid")
        events = tuple(
            event
            for raw in segments
            for event in parse_opt_in_segment(raw, decision_type=self._decision_type)
        )
        try:
            latest, operations = fold_opt_in_events(
                events,
                scope_id=self.scope_id,
                error_type=self._error_type,
                start_revision=self.cutoff_revision + 1,
                initial_latest={item.plugin_id: item for item in self.latest_decisions},
                initial_operations=frozenset(self.retired_operation_ids),
            )
        except self._error_type as exc:
            raise ValueError(
                "Coding Worker opt-in V2 retained replay is invalid"
            ) from exc
        return cast(Callable[..., _OptInReplayFields], self._replay_type)(
            last_revision=self.cutoff_revision + len(events),
            latest_decisions=tuple(latest[key] for key in sorted(latest)),
            operation_ids=frozenset(operations),
        )
