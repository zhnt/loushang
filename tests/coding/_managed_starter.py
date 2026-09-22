"""Test starter using the production Linux launcher and canonical managed layout."""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
from time import monotonic, sleep

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.contracts import (
    ManagedInstanceRefV1,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
)
from loushang.apphost.managed.invocation import ManagedChildInvocationV1
from loushang.apphost.managed.lifecycle import ManagedServiceJournalV1
from loushang.apphost.managed.paths import resolve_managed_paths
from loushang.apphost.managed.registry import ManagedRegistryV1
from loushang.hosting.contracts import (
    ProcessLaunchRequest,
    ProcessStderrMode,
    ProcessStdinMode,
    ProcessStdoutMode,
    ProcessStreamSpec,
)
from loushang.hosting.service_process import LinuxServiceProcessV1

root = Path(sys.argv[2])
namespace = ManagedNamespaceV1(str(root / "platform"), os.geteuid(), "a" * 32)
service = ManagedServiceKeyV1("coding", str(root))
reference = ManagedInstanceRefV1(namespace.namespace_key, service.service_id, "d" * 32)
paths = resolve_managed_paths(namespace, service, reference, runtime_root=str(root / "runtime"))
registry = ManagedRegistryV1(Path(paths.registry), namespace)
journal = ManagedServiceJournalV1(registry, namespace, service, Path(paths.lifecycle))
state = journal.read()
parent, child = socket.socketpair()
invocation = ManagedChildInvocationV1(namespace, service, state.handoff.instance,
                                     state.handoff.attempt_id, str(root / "runtime"))
command = json.loads(sys.argv[1]) + [invocation.to_json(), str(child.fileno())]
request = ProcessLaunchRequest(tuple(command), str(root), tuple(os.environ.items()),
                              ProcessStreamSpec(ProcessStdinMode.CLOSED, ProcessStdoutMode.DISCARD, ProcessStderrMode.DISCARD))
owner = LinuxServiceProcessV1(request, child)
identity = owner.spawn()
print(identity.pid, flush=True)  # Retain exact child observation even if registration fails.
late_birth = sys.argv[4] == "late"
if late_birth:
    assert sys.stdin.buffer.read(1) == b"R"
deadline = monotonic() + 5
busy_reported = False
while True:
    try:
        observed = journal.read(deadline=deadline)
        if (observed is None or observed.handoff.instance != state.handoff.instance
                or observed.handoff.attempt_id != state.handoff.attempt_id):
            raise ManagedStorageError("conflict")
        if observed.native_identity == identity:
            break
        journal.register_native(state.handoff.instance, state.handoff.attempt_id, identity, deadline=deadline)
        break
    except ManagedStorageError as error:
        if error.code != "busy" or monotonic() >= deadline:
            raise
        if late_birth and not busy_reported:
            print("registration_busy", flush=True)  # Test-only proof that the competing admission was attempted.
            busy_reported = True
        sleep(0.01)  # Exact durable reobservation; never replay native spawn.
sys.stdin.buffer.read(1)
if sys.argv[3] == "abrupt":
    os._exit(0)
owner.close()
parent.close()
journal.close()
registry.close()
