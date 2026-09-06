"""One-shot private child protocol for the installed AppHost canary."""

from __future__ import annotations

import re
import sys
from collections.abc import Sequence

_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_PROTOCOL = "loushang-apphost-canary/v1"


def main(argv: Sequence[str] | None = None) -> int:
    values = tuple(sys.argv[1:] if argv is None else argv)
    if len(values) != 1 or _NONCE.fullmatch(values[0]) is None:
        return 2
    sys.stdout.write(f"{_PROTOCOL} {values[0]}\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
