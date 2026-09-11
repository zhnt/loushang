"""Console/module entrypoint; application policy lives in its own module."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from loushang.coding.cli.application import run_cli


def __getattr__(name: str) -> Any:
    # Historical helper reads remain available; application owns their injection.
    if name.startswith("__"):
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from loushang.coding.cli import application

    return getattr(application, name)


def main(argv: list[str] | tuple[str, ...] | None = None) -> int:
    try:
        return asyncio.run(run_cli(sys.argv[1:] if argv is None else argv))
    except KeyboardInterrupt:
        sys.stderr.write("Interrupted.\n")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
