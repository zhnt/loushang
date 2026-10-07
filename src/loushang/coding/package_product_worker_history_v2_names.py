"""Fixed Product-owned names for Worker V2 preparation and authority."""

from __future__ import annotations

from .package_product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
)

PREPARATION_INTENT_NAME = "worker-history-v2-preparation.json"
PRODUCT_OWNER_INDEX_NAME = "worker-history-v2-owner.json"
PREPARED_INDEX_NAME = "worker-history-v2-index.candidate.json"


def semantic_base_name(stem: str) -> str:
    if stem not in CODING_WORKER_HISTORY_STREAM_STEMS:
        raise ValueError("Coding Worker V2 stream name is invalid")
    return f"worker-history-v2-{stem}.base.json"


def stream_cutover_name(stem: str) -> str:
    if stem not in CODING_WORKER_HISTORY_STREAM_STEMS:
        raise ValueError("Coding Worker V2 stream name is invalid")
    return f"worker-history-v2-{stem}.cutover.json"


PREPARATION_ARTIFACT_NAMES = (
    PREPARED_INDEX_NAME,
    *(
        name
        for stem in CODING_WORKER_HISTORY_STREAM_STEMS
        for name in (semantic_base_name(stem), stream_cutover_name(stem))
    ),
)
PREPARATION_STATE_NAMES = (PREPARATION_INTENT_NAME, *PREPARATION_ARTIFACT_NAMES)


__all__ = [
    "PREPARATION_ARTIFACT_NAMES",
    "PREPARATION_INTENT_NAME",
    "PREPARATION_STATE_NAMES",
    "PREPARED_INDEX_NAME",
    "PRODUCT_OWNER_INDEX_NAME",
    "semantic_base_name",
    "stream_cutover_name",
]
