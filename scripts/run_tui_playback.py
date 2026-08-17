from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path


def main() -> None:
    """Run the repository-local Coding playback catalog."""

    repository_root = Path(__file__).resolve().parents[1]
    if str(repository_root) not in sys.path:
        sys.path.insert(0, str(repository_root))
    runner = import_module("tests.coding.tui_support.runner")
    runner.main()


if __name__ == "__main__":
    main()
