from __future__ import annotations

import tomllib
from pathlib import Path


def test_package_exposes_loushang_console_script() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["scripts"]["loushang"] == "loushang.coding.cli.__main__:main"
    assert "loushang-ai" not in pyproject["project"]["scripts"]
