"""Fixed Product-owned names for pre-cutover Windows Worker semantic bases."""

from __future__ import annotations

WINDOWS_WORKER_HISTORY_CUTOVER_NAME = "worker-history-cutover-v1.json"

WINDOWS_WORKER_BASE_FILES = (
    ("optIn", "worker-history-base-opt-in-v1.json"),
    ("receipt", "worker-history-base-receipt-v1.json"),
    ("supervisor", "worker-history-base-supervisor-v1.json"),
    ("c5", "worker-history-base-c5-v1.json"),
    ("launchIntent", "worker-history-base-launch-intent-v1.json"),
    ("nativeProvisioning", "worker-history-base-native-provisioning-v1.json"),
)
WINDOWS_WORKER_BASE_NAMES = frozenset(name for _, name in WINDOWS_WORKER_BASE_FILES)
WINDOWS_WORKER_BASE_STAGE_NAMES = frozenset(
    name + ".stage" for name in WINDOWS_WORKER_BASE_NAMES
)


__all__ = [
    "WINDOWS_WORKER_BASE_FILES",
    "WINDOWS_WORKER_BASE_NAMES",
    "WINDOWS_WORKER_BASE_STAGE_NAMES",
]
