"""Source-bound Windows launch intent semantics over existing history records."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from typing import ClassVar, Self, cast

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.history._base_codec import _SourceBoundBaseWireMethods
from loushang.harness.worker.history._windows_semantic_contracts import (
    _ATTEMPT,
    _DIGEST,
    _LaunchIntentFacts,
    _RecoveryFacts,
    _SourceFacts,
    launch_matches_intent,
)


class _WindowsLaunchIntentBaseMethods(_SourceBoundBaseWireMethods):
    __slots__ = ()
    scope_id: str
    store_id: str
    source_snapshot_digest: str
    retained_intents: tuple[_LaunchIntentFacts, ...]
    intent_attempt_ids: tuple[str, ...]
    record_digest: str
    version: int
    _intent_type: ClassVar[type[_LaunchIntentFacts]]
    _replay_type: ClassVar[Callable[..., object]]

    def __post_init__(self) -> None:
        if (
            type(self.scope_id) is not str
            or not self.scope_id
            or len(self.scope_id) > 128
            or type(self.store_id) is not str
            or not self.store_id
            or len(self.store_id) > 128
            or type(self.source_snapshot_digest) is not str
            or _DIGEST.fullmatch(self.source_snapshot_digest) is None
            or type(self.retained_intents) is not tuple
            or any(
                type(item) is not self._intent_type for item in self.retained_intents
            )
            or tuple(item.attempt_id for item in self.retained_intents)
            != tuple(sorted({item.attempt_id for item in self.retained_intents}))
            or type(self.intent_attempt_ids) is not tuple
            or any(
                type(item) is not str or _ATTEMPT.fullmatch(item) is None
                for item in self.intent_attempt_ids
            )
            or self.intent_attempt_ids != tuple(sorted(set(self.intent_attempt_ids)))
            or any(
                item.attempt_id not in self.intent_attempt_ids
                for item in self.retained_intents
            )
            or type(self.version) is not int
            or self.version != 1
            or type(self.record_digest) is not str
            or self.record_digest
            != sha256(canonical_json_bytes(self._unsigned_dict())).hexdigest()
        ):
            raise ValueError("Windows Worker launch-intent semantic base is invalid")

    @classmethod
    def _from_source_read(cls, source: _SourceFacts, recovery: _RecoveryFacts) -> Self:
        intents = recovery.launch_intents
        if any(type(item) is not cls._intent_type for item in intents):
            raise ValueError("Windows Worker launch-intent history is invalid")
        by_intent = {item.attempt_id: item for item in intents}
        if len(by_intent) != len(intents):
            raise ValueError("Windows Worker launch-intent history is invalid")
        files = {
            item.name: item
            for item in source.files
            if item.name.startswith("worker-launch-intent-")
        }
        expected_names = {
            f"worker-launch-intent-{item.attempt_id}.json" for item in intents
        }
        if set(files) != expected_names:
            raise ValueError("Windows Worker launch-intent source is absent")
        for intent in intents:
            source_file = files[f"worker-launch-intent-{intent.attempt_id}.json"]
            raw = intent.to_bytes()
            if (
                source_file.size != len(raw)
                or source_file.sha256_digest != sha256(raw).hexdigest()
            ):
                raise ValueError("Windows Worker launch-intent source changed")
        recovery_attempts = {item.attempt_id: item for item in recovery.attempts}
        if len(recovery_attempts) != len(recovery.attempts):
            raise ValueError("Windows Worker launch-intent recovery join is invalid")
        for intent in intents:
            attempt = recovery_attempts.get(intent.attempt_id)
            if (
                attempt is None
                or not launch_matches_intent(attempt, intent)
                or attempt.launch_stage_identity != intent.stage_identity
            ):
                raise ValueError(
                    "Windows Worker launch-intent recovery join is invalid"
                )
        retained = tuple(by_intent[key] for key in sorted(by_intent))
        ids = tuple(sorted(by_intent))
        unsigned = {
            "intentAttemptIds": list(ids),
            "retainedIntents": [item.to_dict() for item in retained],
            "scopeId": source.scope_id,
            "sourceSnapshotDigest": source.snapshot_digest,
            "storeId": source.store_id,
            "version": 1,
        }
        return cast(Callable[..., Self], cls)(
            scope_id=source.scope_id,
            store_id=source.store_id,
            source_snapshot_digest=source.snapshot_digest,
            retained_intents=retained,
            intent_attempt_ids=ids,
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )

    def _replay_retained(self, intents: tuple[_LaunchIntentFacts, ...]) -> object:
        if type(intents) is not tuple:
            raise ValueError("Windows Worker launch-intent retained replay is invalid")
        retained = {item.attempt_id: item for item in self.retained_intents}
        ids = set(self.intent_attempt_ids)
        for intent in intents:
            if type(intent) is not self._intent_type or intent.attempt_id in ids:
                raise ValueError(
                    "Windows Worker launch-intent retained replay is invalid"
                )
            ids.add(intent.attempt_id)
            retained[intent.attempt_id] = intent
        return self._replay_type(
            retained_intents=tuple(retained[key] for key in sorted(retained)),
            attempt_ids=frozenset(ids),
        )
