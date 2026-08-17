from __future__ import annotations

from collections.abc import Mapping

from loushang.harness.cli.version_check import (
    DEFAULT_VERSION_CHECK_TIMEOUT_SECONDS,
    VersionCheckProfile,
    VersionFetcher,
    check_for_new_package_version,
)

LATEST_VERSION_URL = "https://loushang.ai/api/latest-version"
LOUSHANG_VERSION_CHECK_PROFILE = VersionCheckProfile(
    endpoint=LATEST_VERSION_URL,
    user_agent_product="loushang-coding",
    skip_env_vars=(
        "LOUSHANG_SKIP_VERSION_CHECK",
        "LOUSHANG_OFFLINE",
        "PI_OFFLINE",
    ),
)


async def check_for_new_loushang_version(
    current_version: str,
    *,
    timeout_seconds: float = DEFAULT_VERSION_CHECK_TIMEOUT_SECONDS,
    fetcher: VersionFetcher | None = None,
    env: Mapping[str, str] | None = None,
) -> str | None:
    return await check_for_new_package_version(
        current_version,
        profile=LOUSHANG_VERSION_CHECK_PROFILE,
        timeout_seconds=timeout_seconds,
        fetcher=fetcher,
        env=env,
    )


__all__ = [
    "DEFAULT_VERSION_CHECK_TIMEOUT_SECONDS",
    "LATEST_VERSION_URL",
    "LOUSHANG_VERSION_CHECK_PROFILE",
    "check_for_new_loushang_version",
]
