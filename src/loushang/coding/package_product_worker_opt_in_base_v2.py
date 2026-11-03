"""Typed opt-in state at a V2 Worker history retirement boundary.

This is a projection and replay primitive. It does not publish a cutover or
authorize deletion of any V1 source segment.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .package_product_worker_history_segments import (
    CodingWorkerSegmentedHistoryV1,
)
from .package_product_worker_opt_in import (
    _MAX_EVENTS,
    _MAX_SEGMENT_BYTES,
    _OPAQUE,
    CodingWorkerOptInDecisionV1,
    CodingWorkerOptInJournalError,
    _fold_opt_in_events,
    _opt_in_line,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BASE_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWorkerOptInSemanticBaseV2:
    scope_id: str
    first_retained_generation: int
    cutoff_revision: int
    retired_sealed_digest: str
    latest_decisions: tuple[CodingWorkerOptInDecisionV1, ...]
    retired_operation_ids: tuple[str, ...]
    version: int = 2

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
                type(item) is not CodingWorkerOptInDecisionV1
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

    def to_bytes(self) -> bytes:
        raw = canonical_json_bytes(
            {
                "cutoffRevision": self.cutoff_revision,
                "firstRetainedGeneration": self.first_retained_generation,
                "latestDecisions": [item.to_dict() for item in self.latest_decisions],
                "retiredOperationIds": list(self.retired_operation_ids),
                "retiredSealedDigest": self.retired_sealed_digest,
                "scopeId": self.scope_id,
                "version": self.version,
            }
        )
        if len(raw) > _MAX_BASE_BYTES:
            raise ValueError("Coding Worker opt-in V2 semantic base exceeds capacity")
        return raw

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWorkerOptInSemanticBaseV2:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_BASE_BYTES:
            raise ValueError("Coding Worker opt-in V2 semantic base bytes are invalid")
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "cutoffRevision",
                    "firstRetainedGeneration",
                    "latestDecisions",
                    "retiredOperationIds",
                    "retiredSealedDigest",
                    "scopeId",
                    "version",
                }
                or type(value["latestDecisions"]) is not list
                or type(value["retiredOperationIds"]) is not list
            ):
                raise ValueError("Coding Worker opt-in V2 semantic base fields changed")
            base = cls(
                scope_id=value["scopeId"],
                first_retained_generation=value["firstRetainedGeneration"],
                cutoff_revision=value["cutoffRevision"],
                retired_sealed_digest=value["retiredSealedDigest"],
                latest_decisions=tuple(
                    CodingWorkerOptInDecisionV1.from_dict(item)
                    for item in value["latestDecisions"]
                ),
                retired_operation_ids=tuple(value["retiredOperationIds"]),
                version=value["version"],
            )
            if base.to_bytes() != raw:
                raise ValueError(
                    "Coding Worker opt-in V2 semantic base encoding changed"
                )
            return base
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise ValueError(
                "Coding Worker opt-in V2 semantic base bytes are invalid"
            ) from exc

    @classmethod
    def from_v1_history(
        cls,
        *,
        history: CodingWorkerSegmentedHistoryV1,
        scope_id: str,
        first_retained_generation: int,
    ) -> CodingWorkerOptInSemanticBaseV2:
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
        events: list[CodingWorkerOptInDecisionV1] = []
        for seal, raw in zip(
            retired, history.segments[:first_retained_generation], strict=True
        ):
            if len(raw) != seal.byte_count or sha256(raw).hexdigest() != seal.digest:
                raise ValueError("Coding Worker opt-in V2 source changed")
            events.extend(_parse_opt_in_segment(raw))
            if len(events) != seal.last_revision:
                raise ValueError("Coding Worker opt-in V2 source revision changed")
        cutoff_revision = retired[-1].last_revision
        if len(events) != cutoff_revision:
            raise ValueError("Coding Worker opt-in V2 source revision changed")
        try:
            latest, seen = _fold_opt_in_events(tuple(events), scope_id=scope_id)
        except CodingWorkerOptInJournalError as exc:
            raise ValueError("Coding Worker opt-in V2 source is invalid") from exc
        return cls(
            scope_id=scope_id,
            first_retained_generation=first_retained_generation,
            cutoff_revision=cutoff_revision,
            retired_sealed_digest=sha256(
                canonical_json_bytes([item.to_dict() for item in retired])
            ).hexdigest(),
            latest_decisions=tuple(latest[key] for key in sorted(latest)),
            retired_operation_ids=tuple(sorted(seen)),
        )

    def replay_retained(self, segments: tuple[bytes, ...]) -> CodingWorkerOptInReplayV2:
        """Replay kept records against the base; source digests belong to V2 IO."""

        if type(segments) is not tuple or not segments:
            raise ValueError("Coding Worker opt-in V2 retained segments are invalid")
        events = tuple(
            event for raw in segments for event in _parse_opt_in_segment(raw)
        )
        try:
            latest, operations = _fold_opt_in_events(
                events,
                scope_id=self.scope_id,
                start_revision=self.cutoff_revision + 1,
                initial_latest={item.plugin_id: item for item in self.latest_decisions},
                initial_operations=frozenset(self.retired_operation_ids),
            )
        except CodingWorkerOptInJournalError as exc:
            raise ValueError(
                "Coding Worker opt-in V2 retained replay is invalid"
            ) from exc
        return CodingWorkerOptInReplayV2(
            last_revision=self.cutoff_revision + len(events),
            latest_decisions=tuple(latest[key] for key in sorted(latest)),
            operation_ids=frozenset(operations),
        )


@dataclass(frozen=True, slots=True)
class CodingWorkerOptInReplayV2:
    last_revision: int
    latest_decisions: tuple[CodingWorkerOptInDecisionV1, ...]
    operation_ids: frozenset[str]


def _parse_opt_in_segment(raw: bytes) -> tuple[CodingWorkerOptInDecisionV1, ...]:
    if type(raw) is not bytes or len(raw) > _MAX_SEGMENT_BYTES:
        raise ValueError("Coding Worker opt-in V2 segment is invalid")
    lines = raw.splitlines(keepends=True)
    if len(lines) > _MAX_EVENTS:
        raise ValueError("Coding Worker opt-in V2 segment exceeds capacity")
    events: list[CodingWorkerOptInDecisionV1] = []
    try:
        for line in lines:
            event = CodingWorkerOptInDecisionV1.from_dict(json.loads(line))
            if line != _opt_in_line(event):
                raise ValueError("Coding Worker opt-in V2 segment encoding changed")
            events.append(event)
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("Coding Worker opt-in V2 segment is invalid") from exc
    return tuple(events)


__all__ = ["CodingWorkerOptInReplayV2", "CodingWorkerOptInSemanticBaseV2"]
