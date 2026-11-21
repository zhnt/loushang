from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    """Give native Transcript fixtures private ancestors on disk."""
    with TemporaryDirectory(prefix=".loushang-transcript-test-", dir=Path.home()) as directory:
        yield Path(directory).resolve()
