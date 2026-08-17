from __future__ import annotations

import asyncio

from loushang.harness.cli.version_check import (
    VersionCheckProfile,
    check_for_new_package_version,
    compare_package_versions,
    is_newer_package_version,
)


def test_version_check_compares_versions_and_uses_product_profile() -> None:
    assert compare_package_versions("v1.2.3", "1.2.2") > 0
    assert compare_package_versions("1.2.3-beta", "1.2.3") < 0
    assert is_newer_package_version("not-semver", "1.2.3") is True

    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def fetcher(*args, **kwargs):
        calls.append((args, kwargs))
        return {"release": "2.0.0"}

    result = asyncio.run(
        check_for_new_package_version(
            "1.0.0",
            profile=VersionCheckProfile(
                endpoint="https://research.example/version",
                user_agent_product="research-agent",
                skip_env_vars=("RESEARCH_OFFLINE",),
                payload_version_field="release",
            ),
            fetcher=fetcher,
            env={},
        )
    )

    assert result == "2.0.0"
    assert calls == [
        (
            ("https://research.example/version",),
            {
                "headers": {
                    "User-Agent": "research-agent/1.0.0",
                    "accept": "application/json",
                },
                "timeout": 10.0,
            },
        )
    ]


def test_version_check_skips_product_offline_environment() -> None:
    called = False

    async def fetcher(*_args, **_kwargs):
        nonlocal called
        called = True
        return "2.0.0"

    result = asyncio.run(
        check_for_new_package_version(
            "1.0.0",
            profile=VersionCheckProfile(
                endpoint="https://design.example/version",
                user_agent_product="design-agent",
                skip_env_vars=("DESIGN_OFFLINE",),
            ),
            fetcher=fetcher,
            env={"DESIGN_OFFLINE": "1"},
        )
    )

    assert result is None
    assert called is False
