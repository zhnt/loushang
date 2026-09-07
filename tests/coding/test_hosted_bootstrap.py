from __future__ import annotations

import asyncio

import pytest

from loushang.appserver.protocol.connection_profile import AppConnectionProfileV1
from loushang.coding.cli.hosted import CodingHostedLaunchV1 as LegacyLaunch
from loushang.coding.hosted_bootstrap import (
    CodingHostedLaunchV1,
    create_coding_hosted_attempt,
)


def _launch(root):
    return CodingHostedLaunchV1(
        root,
        root / "applications",
        "coding.default",
        root / "cwd-sessions",
        root / "home-sessions",
    )


def test_G16_BOOTSTRAP_preserves_g14_launch_and_separates_descriptive_profiles(
    tmp_path,
):
    launch = _launch(tmp_path)
    assert LegacyLaunch is CodingHostedLaunchV1
    assert launch.describe()["profile"] == "foreground-stdio/v1"
    assert (
        launch.describe(profile=AppConnectionProfileV1.LOCAL)["profile"]
        == "local-detachable/v1"
    )
    with pytest.raises(ValueError):
        launch.describe(profile="local-detachable/v1")
    assert str(tmp_path) not in repr(launch)
    assert not tuple(tmp_path.iterdir())


def test_G16_BOOTSTRAP_construction_and_unopened_close_do_not_acquire_or_publish(
    tmp_path,
):
    async def scenario():
        attempt = create_coding_hosted_attempt(_launch(tmp_path))
        assert not tuple(tmp_path.iterdir())
        await attempt.close()
        assert not attempt.cleanup_pending
        assert not tuple(tmp_path.iterdir())

    asyncio.run(scenario())
