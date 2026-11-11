"""Short-lived production management caller with a deterministic Host provider."""
import asyncio
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from loushang.coding.gui_local_host import operate
from loushang.coding.managed_process import coding_managed_process_request


def factory(invocation, descriptor):
    original = coding_managed_process_request(invocation, descriptor, executable=sys.executable, environment=os.environ)
    return replace(original, argv=(sys.executable, str(Path(__file__).with_name('_host_first_execution_host.py')), *original.argv[3:]))


print(json.dumps(asyncio.run(operate(json.load(sys.stdin), request_factory=factory))))
