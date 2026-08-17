from __future__ import annotations

import inspect
from collections.abc import Mapping, MutableMapping

_SDK_AUTH_HEADER_NAMES = {
    "authorization": "Authorization",
    "x-api-key": "X-Api-Key",
}


def canonicalize_sdk_headers(headers: Mapping[str, str]) -> dict[str, str]:
    canonicalized: dict[str, str] = {}
    for key, value in headers.items():
        set_header_case_insensitive(
            canonicalized,
            _SDK_AUTH_HEADER_NAMES.get(key.casefold(), key),
            value,
        )
    return canonicalized


def get_header_case_insensitive(
    headers: Mapping[str, str],
    name: str,
) -> str | None:
    target = name.casefold()
    for key, value in headers.items():
        if key.casefold() == target:
            return value
    return None


def set_header_case_insensitive(
    headers: MutableMapping[str, str],
    name: str,
    value: str,
) -> None:
    target = name.casefold()
    for key in tuple(headers):
        if key.casefold() == target:
            del headers[key]
    headers[name] = value


async def close_provider_stream(stream: object) -> None:
    for name in ("aclose", "close"):
        close = getattr(stream, name, None)
        if not callable(close):
            continue
        result = close()
        if inspect.isawaitable(result):
            await result
        return
