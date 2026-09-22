"""Local subprocess accounting probe; no application, network or model calls."""

import json
import os
import signal
import sys
from pathlib import Path
from time import monotonic

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.contracts import ManagedNamespaceV1
from loushang.apphost.managed.registry import ManagedRegistryV1
from loushang.apphost.managed.storage_budget import (
    ManagedStorageAllocationV1,
    ManagedStorageBudgetV1,
)

if __name__ == "__main__":
    signal.alarm(15)  # Bound even a parent-side failed barrier in this test child.
    root, home_path, encoded, mode = sys.argv[1:]
    values = json.loads(encoded)
    values["root_identity"] = tuple(values["root_identity"])
    request = ManagedStorageAllocationV1(**values)
    owner = ManagedRegistryV1(Path(root), ManagedNamespaceV1(home_path, os.geteuid(), "a" * 32), defer_open=True)
    try:
        deadline = monotonic() + 10
        owner.open(deadline=deadline, wait_for_lock=True)
        print("ready", flush=True)
        sys.stdin.readline()
        try:
            ManagedStorageBudgetV1(owner).reserve(request, deadline=deadline, wait_for_lock=True)
        except ManagedStorageError as error:
            if error.code != "capacity":
                raise
            print("capacity", flush=True)
        else:
            if mode == "crash":
                os._exit(23)
            print("reserved", flush=True)
    finally:
        owner.close()
