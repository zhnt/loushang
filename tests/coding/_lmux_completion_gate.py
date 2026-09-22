"""Single-use, private test control; never a production authorization channel."""
from __future__ import annotations

import asyncio
import math
import os
import re
import stat
from pathlib import Path


def _path(root: Path, instance: str, nonce: str) -> Path:
    if any(re.fullmatch(r"[0-9a-f]{32}", value) is None for value in (instance, nonce)):
        raise ValueError("invalid completion gate identity")
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077 or root.resolve() != root:
        raise ValueError("completion gate requires a private original test directory")
    return root / f"release-{instance}-{nonce}"


def release(root: Path, instance: str, nonce: str) -> None:
    path = _path(root, instance, nonce)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(f"{instance}:{nonce}".encode("ascii"))


class CompletionGate:
    def __init__(self, root: Path, instance: str, *, timeout: float = 90):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("invalid completion gate deadline")
        self.root, self.instance, self.timeout = root, instance, timeout
        self.claimed: set[str] = set()

    async def __call__(self, nonce: str) -> None:
        path = _path(self.root, self.instance, nonce)
        if nonce in self.claimed:
            raise ValueError("completion gate already consumed")
        self.claimed.add(nonce)
        expected = f"{self.instance}:{nonce}".encode("ascii")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout
        async with asyncio.timeout_at(deadline):
            while True:
                try:
                    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                except FileNotFoundError:
                    await asyncio.sleep(0.01)
                    continue
                with os.fdopen(fd, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_nlink != 1:
                        raise ValueError("invalid completion release file")
                    payload = stream.read(len(expected) + 1)
                # The exclusive release file can be observed before its writer
                # closes. Incomplete bytes never release; the same deadline applies.
                if len(payload) < len(expected) and expected.startswith(payload):
                    await asyncio.sleep(0.01)
                    continue
                if payload != expected:
                    raise ValueError("completion release identity mismatch")
                if loop.time() >= deadline:
                    raise TimeoutError("completion release arrived after deadline")
                return
