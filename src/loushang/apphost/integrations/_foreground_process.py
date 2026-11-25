"""Exit handling for one foreground AppHost command in its own process."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Callable, Coroutine
from contextlib import redirect_stdout

from loushang.appserver.local_record import LocalRecordError
from loushang.appserver.protocol import AppServiceError


def run_foreground_process(
    operation: Callable[[], Coroutine[object, object, None]],
    pending: Callable[[], bool],
    *,
    reportable_errors: tuple[type[AppServiceError | LocalRecordError], ...],
    interrupted: str,
    failed: str,
    cleanup_incomplete: str,
) -> int:
    """Keep protocol stdout clear and exit nonzero if disposal still owns work."""
    runner = asyncio.Runner()
    status = 0
    with redirect_stdout(sys.stderr):
        try:
            runner.run(operation())
        except KeyboardInterrupt:
            status = 130
            print(interrupted, file=sys.stderr)
        except reportable_errors as error:
            status = 1
            print(error.code.value, file=sys.stderr)
        except Exception:
            status = 1
            print(failed, file=sys.stderr)
        finally:
            if pending():
                print(cleanup_incomplete, file=sys.stderr, flush=True)
                # The parent retains terminate/reap authority. Runner.close()
                # could wait indefinitely for cancellation of the retained task.
                os._exit(status or 1)
            runner.close()
    return status
