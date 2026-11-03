"""Bounded test-only failure probe around the actual managed process entry.

Only exception type/code and stack locations are retained, never request data,
locals, tokens or model configuration. No application lifecycle is replaced.
"""

from __future__ import annotations

import json
import os
import sys
import traceback

from loushang.apphost.managed.mux_management import _ManagedMuxFence
from loushang.appservice.runtime import AppServiceV1
from loushang.coding.managed_process import main


def _observe(label, operation):
    async def observed(*args, **kwargs):
        try:
            return await operation(*args, **kwargs)
        except Exception as error:
            record = {"stage": label, "error": type(error).__name__, "code": getattr(error, "code", None),
                      "stack": [(os.path.basename(frame.filename), frame.name, frame.lineno)
                                for frame in traceback.extract_tb(error.__traceback__)[-12:]]}
            descriptor = os.open(sys.argv[4], os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                if os.fstat(descriptor).st_size < 4096:
                    os.write(descriptor, (json.dumps(record) + "\n").encode()[:2048])
            finally:
                os.close(descriptor)
            raise
    return observed


if __name__ == "__main__":
    _ManagedMuxFence._acquire_permission = _observe("native_admission", _ManagedMuxFence._acquire_permission)
    AppServiceV1.create_managed_mux = _observe("create", AppServiceV1.create_managed_mux)
    raise SystemExit(main(sys.argv[1:4]))
