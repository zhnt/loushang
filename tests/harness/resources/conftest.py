from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def symlink_or_skip() -> Callable[..., None]:
    def create(
        link: Path,
        target: str | Path,
        *,
        target_is_directory: bool = False,
    ) -> None:
        try:
            link.symlink_to(target, target_is_directory=target_is_directory)
        except NotImplementedError as exc:
            pytest.skip(f"symbolic links are unavailable: {exc}")
        except OSError as exc:
            if os.name != "nt" or getattr(exc, "winerror", None) != 1314:
                raise
            pytest.skip(f"symbolic link privilege is unavailable: {exc}")

    return create
