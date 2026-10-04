from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HELPER_DIR = Path(__file__).resolve().parent
if str(_HELPER_DIR) not in sys.path:
    sys.path.insert(0, str(_HELPER_DIR))


@pytest.fixture(autouse=True)
def isolated_coding_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep Product state from prior runs and the developer home out of tests."""

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))


@pytest.fixture
def legacy_coding_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise retained old-route contracts without claiming default B support."""

    from loushang.coding.package_product_runtime import (
        CodingFencedProductApplicationSelection,
    )

    monkeypatch.setattr(
        CodingFencedProductApplicationSelection,
        "factory_for_session",
        lambda self, manager, *, settings_manager=None: None,
    )
