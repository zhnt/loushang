"""Bounded file consumption shared by observation and verified transfer."""

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from typing import BinaryIO, Literal, Protocol, cast


@contextmanager
def borrowed_binary_stream(
    descriptor: int, mode: Literal["rb", "r+b", "wb"]
) -> Iterator[BinaryIO]:
    """Close the wrapper; its caller retains raw FD custody even on construction failure."""
    with os.fdopen(descriptor, mode, closefd=False) as stream:
        yield cast(BinaryIO, stream)


@contextmanager
def closing_descriptor(descriptor: int) -> Iterator[int]:
    """Close one caller-owned descriptor at the end of its original scope."""
    try:
        yield descriptor
    finally:
        os.close(descriptor)


class FileReadPort(Protocol):
    def read(self, max_bytes: int) -> bytes: ...


class FileWritePort(Protocol):
    def write(self, chunk: bytes) -> object: ...


class FileConsumptionError(OSError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass
class DescriptorReader:
    descriptor: int
    remaining: int | None = None

    def read(self, max_bytes: int) -> bytes:
        if self.remaining is not None:
            if self.remaining == 0:
                return b""
            max_bytes = min(max_bytes, self.remaining)
        chunk = os.read(self.descriptor, max_bytes)
        if self.remaining is not None:
            self.remaining -= len(chunk)
        return chunk


def read_bounded_prefix(
    descriptor: int, maximum: int, *, chunk_size: int = 1024 * 1024
) -> bytes:
    """Read at most maximum+1 bytes; the owner orders overflow vs metadata errors."""
    output = BytesIO()
    consume_file(
        DescriptorReader(descriptor, maximum + 1),
        destination=output,
        max_bytes=maximum + 1,
        chunk_size=chunk_size,
        hash_content=False,
    )
    return output.getvalue()


def consume_file(
    source: FileReadPort,
    *,
    max_bytes: int | Callable[[], int],
    destination: FileWritePort | None = None,
    chunk_size: int = 64 * 1024,
    quota_bytes: int | None = None,
    hash_content: bool = True,
    size_error: Callable[[], Exception] | None = None,
) -> tuple[int, str]:
    digest = sha256() if hash_content else None
    byte_count = 0
    while chunk := source.read(chunk_size):
        if not isinstance(chunk, bytes):
            raise FileConsumptionError("non_bytes")
        byte_count += len(chunk)
        if quota_bytes is not None and byte_count > quota_bytes:
            raise FileConsumptionError("quota")
        if byte_count > (max_bytes if isinstance(max_bytes, int) else max_bytes()):
            raise FileConsumptionError("size") if size_error is None else size_error()
        if digest is not None:
            digest.update(chunk)
        if destination is not None:
            destination.write(chunk)
    return byte_count, "" if digest is None else digest.hexdigest()


def hash_exact_size(descriptor: int, byte_count: int, *, truncated: str) -> str:
    """Digest only the expected bytes; the caller retains its trailer check."""
    consumed, digest = consume_file(
        DescriptorReader(descriptor, byte_count),
        max_bytes=byte_count,
        chunk_size=1024 * 1024,
    )
    if consumed != byte_count:
        raise ValueError(truncated)
    return digest
