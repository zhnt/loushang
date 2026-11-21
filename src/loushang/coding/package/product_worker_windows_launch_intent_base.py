"""Typed Windows Worker launch-intent identities at a cutover boundary.

These exact source-bound identities cannot authorize a Product cutover,
substitute for native provisioning evidence, or delete a staged payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from loushang.harness.worker.history._windows_launch_intent_base import (
    _WindowsLaunchIntentBaseMethods,
)

from .product_worker_windows_history_preparation import (
    CodingWindowsWorkerHistoryPreparationV1,
)
from .product_worker_windows_history_sources import (
    CodingWindowsWorkerHistorySemanticReadV1 as CodingWindowsWorkerHistorySemanticReadV1,
)
from .product_worker_windows_launch_intent import (
    CodingWindowsWorkerLaunchIntentError,
    CodingWindowsWorkerLaunchIntentV1,
)


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

    _wire_errors = (
        CodingWindowsWorkerLaunchIntentError,
        *_WindowsLaunchIntentBaseMethods._wire_errors,
    )


__all__ = [
    "CodingWindowsWorkerLaunchIntentReplayV1",
    "CodingWindowsWorkerLaunchIntentSemanticBaseV1",
]


CodingWindowsWorkerLaunchIntentSemanticBaseV1._bind_record_schema(
    lambda raw: CodingWindowsWorkerLaunchIntentV1.from_bytes(raw)
)
