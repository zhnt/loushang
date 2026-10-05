from __future__ import annotations

import pytest

from loushang.harness.cli.plugin_management import (
    PluginManagementCliProfile,
    bind_plugin_management_cli_commands,
)
from loushang.harness.plugin_management import PluginManagementSourceSnapshotV1
from loushang.harness.plugin_management.read_binding import empty_management_read_ports


class _Source:
    def snapshot(self) -> PluginManagementSourceSnapshotV1:
        return PluginManagementSourceSnapshotV1(owner_revision="test:empty", records=())


def test_command_binding_releases_product_startup_claim_after_publication_failure() -> (
    None
):
    events: list[str] = []
    ports = empty_management_read_ports(_Source())

    class FailingCommandOwner:
        def fenced_product_exists(self):
            return False

        def open_fenced_ports(self):
            pytest.fail("fenced owner must stay unopened")

        def acquire_legacy_startup(self):
            events.append("acquire")
            return lambda: events.append("release")

        def open_legacy_ports(self):
            events.append("open")
            return ports

        def bind_legacy_compatibility(self):
            events.append("bind")

            def publish():
                events.append("publish")
                raise RuntimeError("publication failed")

            return publish

    profile = PluginManagementCliProfile(
        product_id="example",
        installation_scope="workspace",
        scope_id="workspace-1",
        actor_id="example:cli",
        policy_revision="example:1",
    )

    with pytest.raises(RuntimeError, match="publication failed"):
        bind_plugin_management_cli_commands(profile, FailingCommandOwner())

    assert events == ["acquire", "open", "bind", "publish", "release"]
