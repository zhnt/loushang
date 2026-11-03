"""Stable assignment of collected test IDs to CI shards."""

from __future__ import annotations

from hashlib import sha256


def shard_for_nodeid(nodeid: str, shards: int) -> int:
    if shards < 1:
        raise ValueError("shard count must be positive")
    digest = sha256(nodeid.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % shards
