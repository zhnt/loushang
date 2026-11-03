from __future__ import annotations

import asyncio

import pytest

from loushang.appserver.protocol.connection_profile import AppConnectionProfileV1
from loushang.coding import hosted_bootstrap
from loushang.coding.cli.hosted import CodingHostedLaunchV1 as LegacyLaunch
from loushang.coding.hosted_bootstrap import (
    CodingHostedLaunchV1,
    create_coding_hosted_attempt,
)
from loushang.coding.hosted_catalog import CodingHostedResumeCatalogV1


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


@pytest.mark.parametrize("platform,owned", [("linux", True), ("darwin", False), ("win32", False)])
def test_hosted_owned_writer_keeps_the_embedded_platform_boundary(
    tmp_path, monkeypatch, platform, owned
):
    async def scenario():
        monkeypatch.setattr(hosted_bootstrap.sys, "platform", platform)
        attempt = create_coding_hosted_attempt(
            _launch(tmp_path), owned_transcripts=True
        )
        sessions = attempt._request.foreground.sessions
        assert isinstance(sessions, CodingHostedResumeCatalogV1) is owned
        if owned:
            assert sessions._owned_factory is not None
        assert (attempt._request.foreground.session_owner is sessions) is owned
        await attempt.close()

    asyncio.run(scenario())
