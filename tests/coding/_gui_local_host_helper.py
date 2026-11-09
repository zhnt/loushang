"""G1 desktop-only synthetic provider seam; all management uses production owners.

Execute as LOUSHANG_GUI_PYTHON through an explicit test launcher. This file is
not installed or selected by production. It never accepts executable code from
the WebView and never submits a task on the operator's behalf.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from time import monotonic

from loushang.coding.gui_local_host import operate
from loushang.coding.managed_process import coding_managed_process_request


def main():
    if sys.argv[1:] != ["-m", "loushang.coding.gui_local_host"]:
        raise SystemExit("unexpected test helper invocation")
    request = json.loads(sys.stdin.buffer.read(16_384))
    workspace = Path(request["workspace"])

    def factory(invocation, descriptor):
        original = coding_managed_process_request(invocation, descriptor,
            executable=sys.executable, environment=os.environ)
        return replace(original, argv=(sys.executable,
            str(Path(__file__).with_name("_managed_execution_host.py")), *original.argv[3:]))

    result = asyncio.run(operate(request, request_factory=factory))
    with (workspace / "management-audit.jsonl").open("a") as log:
        log.write(json.dumps({"time": monotonic(), "helper_pid": os.getpid(),
            "action": request["action"], **result}) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
