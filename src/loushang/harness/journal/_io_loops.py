"""Complete a bounded write using an already owned writer."""

from collections.abc import Callable


def write_all(
    write: Callable[[memoryview], int],
    data: bytes | memoryview,
    *,
    message: str,
    error_factory: Callable[[str], BaseException] = OSError,
) -> None:
    remaining = memoryview(data)
    while remaining:
        written = write(remaining)
        if written <= 0:
            raise error_factory(message)
        remaining = remaining[written:]
