"""Typed Windows Worker launch-intent identities at a cutover boundary.

These exact source-bound identities cannot authorize a Product cutover,
substitute for native provisioning evidence, or delete a staged payload.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1,
)
from .package_product_worker_windows_launch_intent import (
    CodingWindowsWorkerLaunchIntentError,
    CodingWindowsWorkerLaunchIntentV1,
)

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
_MAX_BASE_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerLaunchIntentSemanticBaseV1:
    scope_id: str
    store_id: str
    source_snapshot_digest: str
    retained_intents: tuple[CodingWindowsWorkerLaunchIntentV1, ...]
    intent_attempt_ids: tuple[str, ...]
    record_digest: str
    version: int = 1

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
                type(item) is not CodingWindowsWorkerLaunchIntentV1
                for item in self.retained_intents
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

    def _unsigned_dict(self) -> dict[str, object]:
        return {
            "intentAttemptIds": list(self.intent_attempt_ids),
            "retainedIntents": [item.to_dict() for item in self.retained_intents],
            "scopeId": self.scope_id,
            "sourceSnapshotDigest": self.source_snapshot_digest,
            "storeId": self.store_id,
            "version": self.version,
        }

    def to_bytes(self) -> bytes:
        raw = canonical_json_bytes(
            {**self._unsigned_dict(), "recordDigest": self.record_digest}
        )
        if len(raw) > _MAX_BASE_BYTES:
            raise ValueError(
                "Windows Worker launch-intent semantic base exceeds capacity"
            )
        return raw

    @classmethod
    def from_bytes(cls, raw: bytes) -> CodingWindowsWorkerLaunchIntentSemanticBaseV1:
        if type(raw) is not bytes or not raw or len(raw) > _MAX_BASE_BYTES:
            raise ValueError("Windows Worker launch-intent semantic base is invalid")
        try:
            value = json.loads(raw)
            if (
                type(value) is not dict
                or set(value)
                != {
                    "intentAttemptIds",
                    "retainedIntents",
                    "scopeId",
                    "sourceSnapshotDigest",
                    "storeId",
                    "recordDigest",
                    "version",
                }
                or type(value["intentAttemptIds"]) is not list
                or type(value["retainedIntents"]) is not list
            ):
                raise ValueError(
                    "Windows Worker launch-intent semantic base is invalid"
                )
            base = cls(
                scope_id=value["scopeId"],
                store_id=value["storeId"],
                source_snapshot_digest=value["sourceSnapshotDigest"],
                retained_intents=tuple(
                    CodingWindowsWorkerLaunchIntentV1.from_bytes(
                        canonical_json_bytes(item)
                    )
                    for item in value["retainedIntents"]
                ),
                intent_attempt_ids=tuple(value["intentAttemptIds"]),
                record_digest=value["recordDigest"],
                version=value["version"],
            )
            if base.to_bytes() != raw:
                raise ValueError(
                    "Windows Worker launch-intent semantic base is invalid"
                )
            return base
        except (
            CodingWindowsWorkerLaunchIntentError,
            KeyError,
            RecursionError,
            TypeError,
            UnicodeError,
            ValueError,
        ) as exc:
            raise ValueError(
                "Windows Worker launch-intent semantic base is invalid"
            ) from exc

    @classmethod
    def from_semantic_read(
        cls,
        prepared: CodingWindowsWorkerHistoryPreparationV1,
        semantic: CodingWindowsWorkerHistorySemanticReadV1,
    ) -> CodingWindowsWorkerLaunchIntentSemanticBaseV1:
        if type(prepared) is not CodingWindowsWorkerHistoryPreparationV1:
            raise ValueError("Windows Worker launch-intent preparation is invalid")
        prepared.require_semantic_read(semantic)
        source = semantic.source_snapshot
        recovery = semantic.offline_recovery
        intents = recovery.launch_intents
        if any(type(item) is not CodingWindowsWorkerLaunchIntentV1 for item in intents):
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
                or attempt.launch_request_fingerprint != intent.request_fingerprint
                or attempt.launch_receipt_fingerprint != intent.receipt_fingerprint
                or attempt.launch_identity_fingerprint != intent.identity_fingerprint
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
        return cls(
            scope_id=source.scope_id,
            store_id=source.store_id,
            source_snapshot_digest=source.snapshot_digest,
            retained_intents=retained,
            intent_attempt_ids=ids,
            record_digest=sha256(canonical_json_bytes(unsigned)).hexdigest(),
        )

    def replay(
        self, intents: tuple[CodingWindowsWorkerLaunchIntentV1, ...]
    ) -> CodingWindowsWorkerLaunchIntentReplayV1:
        if type(intents) is not tuple:
            raise ValueError("Windows Worker launch-intent retained replay is invalid")
        retained = {item.attempt_id: item for item in self.retained_intents}
        ids = set(self.intent_attempt_ids)
        for intent in intents:
            if (
                type(intent) is not CodingWindowsWorkerLaunchIntentV1
                or intent.attempt_id in ids
            ):
                raise ValueError(
                    "Windows Worker launch-intent retained replay is invalid"
                )
            ids.add(intent.attempt_id)
            retained[intent.attempt_id] = intent
        return CodingWindowsWorkerLaunchIntentReplayV1(
            retained_intents=tuple(retained[key] for key in sorted(retained)),
            attempt_ids=frozenset(ids),
        )


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerLaunchIntentReplayV1:
    retained_intents: tuple[CodingWindowsWorkerLaunchIntentV1, ...]
    attempt_ids: frozenset[str]


__all__ = [
    "CodingWindowsWorkerLaunchIntentReplayV1",
    "CodingWindowsWorkerLaunchIntentSemanticBaseV1",
]
