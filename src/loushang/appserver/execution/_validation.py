"""Shared execution wire value validation."""

import re

_REASON_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~-]{0,127}\Z")


def _identifier(value: str) -> None:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError("invalid execution identifier")


def _counter(value: object) -> None:
    if type(value) is not int or not 0 <= value <= (1 << 53) - 1:
        raise ValueError("invalid execution counter")
