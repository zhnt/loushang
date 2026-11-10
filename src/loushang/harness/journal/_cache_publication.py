"""Atomic byte publication for rebuildable path-based caches."""

import os
import tempfile
from contextlib import suppress
from pathlib import Path


def publish_cache_bytes(
    path: Path,
    payload: bytes,
    *,
    file_mode: int | None = None,
    cleanup_error: type[OSError] = FileNotFoundError,
) -> None:
    """Close the exclusive temporary before replacement; retain original cleanup policy."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            if file_mode is not None:
                os.chmod(stream.name, file_mode)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            with suppress(cleanup_error):
                temporary_path.unlink()
