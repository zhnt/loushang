"""Compatibility import for the neutral contained-file capture substrate."""

from loushang.harness.resources._safe_files import (
    CapturedRegularFile,
    ContainedFileCaptureError,
    capture_contained_regular_file,
)

__all__ = [
    "CapturedRegularFile",
    "ContainedFileCaptureError",
    "capture_contained_regular_file",
]
