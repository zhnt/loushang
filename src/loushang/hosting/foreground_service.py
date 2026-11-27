"""Native termination handlers and readiness for foreground services."""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import sys
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager


@contextmanager
def foreground_stop_signals(
    stop: Callable[[], None], *, include_interrupt: bool = False,
) -> Iterator[None]:
    if os.name != "posix":
        raise RuntimeError("foreground service signals require POSIX")
    loop = asyncio.get_running_loop()
    signals = (signal.SIGTERM, signal.SIGINT) if include_interrupt else (signal.SIGTERM,)
    with ExitStack() as handlers:
        for signum in signals:
            if not include_interrupt:
                handlers.callback(signal.signal, signum, signal.getsignal(signum))
            loop.add_signal_handler(signum, stop)
            handlers.callback(loop.remove_signal_handler, signum)
        yield


def notify_systemd_ready(notify_socket: str) -> None:
    """Send readiness to the supplied foreground unit socket."""
    if sys.platform != "linux":
        raise RuntimeError("systemd notification requires Linux")
    address = "\0" + notify_socket[1:] if notify_socket.startswith("@") else notify_socket
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notifier:
        notifier.settimeout(1)
        notifier.sendto(b"READY=1", address)
