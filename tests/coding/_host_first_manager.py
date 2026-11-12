"""Short-lived production management caller with a deterministic Host provider."""
import asyncio
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from loushang.coding.managed_process import coding_managed_process_request
from loushang.coding.managed_service import control_managed_service


def factory(invocation, descriptor):
    original = coding_managed_process_request(invocation, descriptor, executable=sys.executable, environment=os.environ)
    fixture = '_managed_execution_host.py' if sys.argv[1:] == ['stage1'] else '_host_first_execution_host.py'
    return replace(original, argv=(sys.executable, str(Path(__file__).with_name(fixture)), *original.argv[3:]))


if __name__ == "__main__":
    request = json.load(sys.stdin)
    result = asyncio.run(control_managed_service(
        request["action"], request.get("instanceId"), request_factory=factory,
    ))
    print(json.dumps(result))
