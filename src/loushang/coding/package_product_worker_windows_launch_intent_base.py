"""Typed Windows Worker launch-intent identities at a cutover boundary.

These exact source-bound identities cannot authorize a Product cutover,
substitute for native provisioning evidence, or delete a staged payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.history._base_codec import (
    _unchanged,
)
from loushang.harness.worker.history._windows_launch_intent_base import (
    _WindowsLaunchIntentBaseMethods,
)

from .package_product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .package_product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1 as CodingWindowsWorkerHistorySemanticReadV1,
)
from .package_product_worker_windows_launch_intent import (
    CodingWindowsWorkerLaunchIntentError,
    CodingWindowsWorkerLaunchIntentV1,
)

_MAX_BASE_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerLaunchIntentReplayV1:
    retained_intents: tuple[CodingWindowsWorkerLaunchIntentV1, ...]
    attempt_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class CodingWindowsWorkerLaunchIntentSemanticBaseV1(_WindowsLaunchIntentBaseMethods):
    _preparation_type = CodingWindowsWorkerHistoryPreparationV1
    _preparation_label = "launch-intent"
    _intent_type = CodingWindowsWorkerLaunchIntentV1
    _replay_type = CodingWindowsWorkerLaunchIntentReplayV1

    retained_intents: tuple[CodingWindowsWorkerLaunchIntentV1, ...]

    def replay(
        self, intents: tuple[CodingWindowsWorkerLaunchIntentV1, ...]
    ) -> CodingWindowsWorkerLaunchIntentReplayV1:
        return cast(
            CodingWindowsWorkerLaunchIntentReplayV1, self._replay_retained(intents)
        )

    _wire_label = "Windows Worker launch-intent semantic base"
    _wire_lists = ("intentAttemptIds", "retainedIntents")
    _wire_errors = (
        CodingWindowsWorkerLaunchIntentError,
        KeyError,
        RecursionError,
        TypeError,
        UnicodeError,
        ValueError,
    )

    @classmethod
    def _wire_maximum(cls) -> int:
        return _MAX_BASE_BYTES


__all__ = [
    "CodingWindowsWorkerLaunchIntentReplayV1",
    "CodingWindowsWorkerLaunchIntentSemanticBaseV1",
]


CodingWindowsWorkerLaunchIntentSemanticBaseV1._bind_wire_schema(
    RecordSchema.for_dataclass(
        CodingWindowsWorkerLaunchIntentSemanticBaseV1,
        _unchanged,
        RecordField(
            "retained_intents",
            decoder=lambda xs: tuple(
                (
                    CodingWindowsWorkerLaunchIntentV1.from_bytes(
                        canonical_json_bytes(item)
                    )
                    for item in xs
                )
            ),
            encoder=lambda values: [value.to_dict() for value in values],
        ),
        RecordField("intent_attempt_ids", decoder=tuple, encoder=list),
    )
)
