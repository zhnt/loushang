"""Source-bound Windows launch intent semantics over existing history records."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import ClassVar, Self, cast

from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.history._base_codec import (
    _BaseWireMethods,
)
from loushang.harness.worker.history._windows_prepared import (
    _record_tuple_field,
    _WindowsPreparedSourceMethods,
)
from loushang.harness.worker.history._windows_semantic_contracts import (
    _ATTEMPT,
    _DIGEST,
    _LaunchIntentFacts,
    _RecoveryFacts,
    _SourceFacts,
    launch_matches_intent,
)


@dataclass(frozen=True, init=False, repr=False, eq=False)
class _WindowsLaunchIntentBaseMethods(_WindowsPreparedSourceMethods):
    __slots__ = ()
    _wire_label = "Windows Worker launch-intent semantic base"
    _wire_lists = ("intentAttemptIds", "retainedIntents")
    _wire_errors: ClassVar[tuple[type[Exception], ...]] = (
        KeyError,
        RecursionError,
        TypeError,
        UnicodeError,
        ValueError,
    )
    _wire_max_bytes = 16 * 1024 * 1024
    scope_id: str
    store_id: str
    source_snapshot_digest: str
    retained_intents: tuple[_LaunchIntentFacts, ...]
    intent_attempt_ids: tuple[str, ...]
    record_digest: str
    version: int = 1
    _intent_type: ClassVar[type[_LaunchIntentFacts]]
    _replay_type: ClassVar[Callable[..., object]]

    @classmethod
    def _bind_record_schema(
        cls, decode_intent: Callable[[bytes], _LaunchIntentFacts]
    ) -> None:
        cls._bind_windows_wire_schema(
            _record_tuple_field(
                "retained_intents",
                lambda item: decode_intent(canonical_json_bytes(item)),
            ),
            RecordField("intent_attempt_ids", decoder=tuple, encoder=list),
        )

    def __post_init__(self) -> None:
        if (
            self._source_identity_invalid()
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


class WindowsLaunchIntentMethods(_BaseWireMethods):
    __slots__ = ()
    _fingerprint_domain: bytes
    attempt_id: str
    stage_identity: tuple[int, int]
    receipt_fingerprint: str
    request_fingerprint: str
    identity_fingerprint: str
    runtime_fingerprint: str
    payload_digest: str
    owner_id: str
    supervisor_epoch: int
    intent_version: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.attempt_id) is not str
            or _ATTEMPT.fullmatch(self.attempt_id) is None
            or type(self.stage_identity) is not tuple
            or (len(self.stage_identity) != 2)
            or any(
                (type(value) is not int or value < 0 for value in self.stage_identity)
            )
            or any(
                (
                    type(value) is not str or _DIGEST.fullmatch(value) is None
                    for value in (
                        self.receipt_fingerprint,
                        self.request_fingerprint,
                        self.identity_fingerprint,
                        self.runtime_fingerprint,
                        self.payload_digest,
                    )
                )
            )
            or (type(self.owner_id) is not str)
            or (not self.owner_id)
            or (len(self.owner_id) > 256)
            or (type(self.supervisor_epoch) is not int)
            or (self.supervisor_epoch < 1)
            or (type(self.intent_version) is not int)
            or (self.intent_version != 1)
        ):
            raise ValueError("Windows Worker launch intent is invalid")

    @property
    def fingerprint(self) -> str:
        return sha256(self._fingerprint_domain + self.to_bytes()).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return self._wire_schema.encode(self, sort_keys=True)

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())
