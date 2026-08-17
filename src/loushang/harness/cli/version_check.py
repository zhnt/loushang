"""Profile-driven package version checks for Product CLIs."""

from __future__ import annotations

import inspect
import os
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

import httpx

DEFAULT_VERSION_CHECK_TIMEOUT_SECONDS = 10.0
VersionFetcher = Callable[..., object | Awaitable[object]]


@dataclass(frozen=True, slots=True)
class VersionCheckProfile:
    endpoint: str
    user_agent_product: str
    skip_env_vars: tuple[str, ...] = ()
    payload_version_field: str = "version"


@dataclass(frozen=True, slots=True)
class ParsedVersion:
    major: int
    minor: int
    patch: int
    prerelease: str | None = None


def compare_package_versions(left_version: str, right_version: str) -> int | None:
    left = _parse_package_version(left_version)
    right = _parse_package_version(right_version)
    if left is None or right is None:
        return None
    if left.major != right.major:
        return left.major - right.major
    if left.minor != right.minor:
        return left.minor - right.minor
    if left.patch != right.patch:
        return left.patch - right.patch
    if left.prerelease == right.prerelease:
        return 0
    if left.prerelease is None:
        return 1
    if right.prerelease is None:
        return -1
    return (left.prerelease > right.prerelease) - (left.prerelease < right.prerelease)


def is_newer_package_version(candidate_version: str, current_version: str) -> bool:
    comparison = compare_package_versions(candidate_version, current_version)
    if comparison is not None:
        return comparison > 0
    return candidate_version.strip() != current_version.strip()


async def get_latest_package_version(
    current_version: str,
    *,
    profile: VersionCheckProfile,
    timeout_seconds: float = DEFAULT_VERSION_CHECK_TIMEOUT_SECONDS,
    fetcher: VersionFetcher | None = None,
    env: Mapping[str, str] | None = None,
) -> str | None:
    environment = os.environ if env is None else env
    if any(environment.get(name) for name in profile.skip_env_vars):
        return None
    headers = {
        "User-Agent": f"{profile.user_agent_product}/{current_version}",
        "accept": "application/json",
    }
    if fetcher is None:
        payload: object = await _httpx_fetch_version(
            profile.endpoint,
            headers=headers,
            timeout=timeout_seconds,
        )
    else:
        fetched = fetcher(
            profile.endpoint,
            headers=headers,
            timeout=timeout_seconds,
        )
        payload = await fetched if inspect.isawaitable(fetched) else fetched
    if isinstance(payload, str):
        return payload.strip() or None
    if isinstance(payload, Mapping):
        version = payload.get(profile.payload_version_field)
        return version.strip() if isinstance(version, str) and version.strip() else None
    return None


async def check_for_new_package_version(
    current_version: str,
    *,
    profile: VersionCheckProfile,
    timeout_seconds: float = DEFAULT_VERSION_CHECK_TIMEOUT_SECONDS,
    fetcher: VersionFetcher | None = None,
    env: Mapping[str, str] | None = None,
) -> str | None:
    try:
        latest = await get_latest_package_version(
            current_version,
            profile=profile,
            timeout_seconds=timeout_seconds,
            fetcher=fetcher,
            env=env,
        )
    except Exception:
        return None
    if latest and is_newer_package_version(latest, current_version):
        return latest
    return None


async def _httpx_fetch_version(
    url: str,
    *,
    headers: Mapping[str, str],
    timeout: float,
) -> dict[str, object] | None:
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, headers=dict(headers))
    if response.status_code < 200 or response.status_code >= 300:
        return None
    payload = response.json()
    return payload if isinstance(payload, dict) else None


def _parse_package_version(version: str) -> ParsedVersion | None:
    match = re.match(
        r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+.*)?$",
        version.strip(),
    )
    if match is None:
        return None
    return ParsedVersion(
        major=int(match.group(1)),
        minor=int(match.group(2)),
        patch=int(match.group(3)),
        prerelease=match.group(4),
    )


__all__ = [
    "DEFAULT_VERSION_CHECK_TIMEOUT_SECONDS",
    "ParsedVersion",
    "VersionCheckProfile",
    "VersionFetcher",
    "check_for_new_package_version",
    "compare_package_versions",
    "get_latest_package_version",
    "is_newer_package_version",
]
