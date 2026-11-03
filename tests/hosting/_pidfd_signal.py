"""Test-only exact Linux signal injection; never a numeric-PID fallback."""

import ctypes
import signal


def send_signal(observer, kind):
    send = getattr(signal, "pidfd_send_signal", None)
    if send is not None:
        send(observer._fd, kind)
        return
    # Some uv Python builds omit the wrapper on supporting Linux hosts.
    native = ctypes.CDLL(None, use_errno=True).pidfd_send_signal
    native.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
    native.restype = ctypes.c_int
    if native(observer._fd, kind, None, 0) != 0:
        raise OSError(ctypes.get_errno(), "test pidfd signal failed")
