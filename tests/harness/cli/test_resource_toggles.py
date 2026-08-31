from __future__ import annotations

import pytest

from loushang.harness.cli import (
    PluginManagementCliBinding,
    ResourceToggleError,
    ResourceToggleRequest,
    agent_resource_toggle_request,
    apply_resource_toggles,
)
from loushang.harness.plugin_management import (
    PluginDesiredStateLedger,
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginManagementApplicationPorts,
    PluginManagementCommandApplication,
    PluginManagementCommandV1,
    PluginManagementReadModelProjector,
    PluginManagementService,
    PluginPackageRevisionRefV1,
)


class _Settings:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def enable_skill(self, name: str, *, scope: str) -> None:
        self.calls.append(("enable_skill", f"{name}:{scope}"))

    def add_plugin_source(self, source: str, *, scope: str) -> bool:
        self.calls.append(("add_plugin_source", f"{source}:{scope}"))
        return True


def test_agent_resource_flags_project_optional_request() -> None:
    from types import SimpleNamespace

    request = agent_resource_toggle_request(
        SimpleNamespace(
            enable_skills=("review",),
            disable_skills=(),
            add_plugin_sources=(),
            remove_plugin_sources=(),
            enable_plugins=(),
            disable_plugins=(),
        )
    )

    assert request == ResourceToggleRequest(enable_skills=("review",))


def test_resource_toggles_return_ordered_messages_and_use_injected_policy() -> None:
    settings = _Settings()

    result = apply_resource_toggles(
        settings,
        ResourceToggleRequest(
            enable_skills=("review",),
            add_plugin_sources=("https://example.test/plugin",),
        ),
        evaluate_plugin_source=lambda source: None,
        is_remote_plugin_source=lambda source: source.startswith("https://"),
    )

    assert result.messages == (
        "enabled skill\treview",
        "added remote plugin source\thttps://example.test/plugin",
    )
    assert settings.calls[0] == ("enable_skill", "review:project")


def test_resource_toggles_preserve_messages_before_policy_failure() -> None:
    settings = _Settings()
    with pytest.raises(ResourceToggleError) as raised:
        apply_resource_toggles(
            settings,
            ResourceToggleRequest(
                enable_skills=("review",),
                add_plugin_sources=("denied",),
            ),
            evaluate_plugin_source=lambda source: "denied by policy",
        )

    assert raised.value.messages == ("enabled skill\treview",)


def test_plugin_toggle_uses_management_command_without_settings_mutator(
    tmp_path,
) -> None:
    desired, service, binding = _management(tmp_path)
    _install(service)
    settings = _Settings()

    disabled = apply_resource_toggles(
        settings,
        ResourceToggleRequest(disable_plugins=("review-pack",)),
        plugin_management=binding,
    )
    repeated = apply_resource_toggles(
        settings,
        ResourceToggleRequest(disable_plugins=("review-pack",)),
        plugin_management=binding,
    )
    enabled = apply_resource_toggles(
        settings,
        ResourceToggleRequest(enable_plugins=("review-pack",)),
        plugin_management=binding,
    )

    assert disabled.messages == ("disabled plugin\treview-pack",)
    assert repeated.messages == ("disabled plugin\treview-pack",)
    assert enabled.messages == ("enabled plugin\treview-pack",)
    assert settings.calls == []
    assert desired.snapshot().installation(_key()).selection.desired_state == (
        "installed_enabled"
    )
    assert len(desired.transitions()) == 4


def test_plugin_toggle_refuses_unmigrated_installation_without_legacy_write(
    tmp_path,
) -> None:
    _desired, _service, binding = _management(tmp_path)
    settings = _Settings()

    with pytest.raises(ResourceToggleError) as raised:
        apply_resource_toggles(
            settings,
            ResourceToggleRequest(disable_plugins=("review-pack",)),
            plugin_management=binding,
        )

    assert raised.value.code == "plugin_enablement_migration_required"
    assert settings.calls == []


def _management(tmp_path):
    desired = PluginDesiredStateLedger(tmp_path / "desired.jsonl")
    service = PluginManagementService(
        desired_state=desired,
        operation_journal_path=tmp_path / "operations.jsonl",
    )
    binding = PluginManagementCliBinding(
        ports=PluginManagementApplicationPorts(
            commands=PluginManagementCommandApplication(service),
            queries=PluginManagementReadModelProjector(
                desired_state=desired,
                operations=service,
            ),
        ),
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace-1",
        actor_id="cli",
        policy_revision="cli-v1",
    )
    return desired, service, binding


def _install(service: PluginManagementService) -> None:
    installed = service.submit(
        PluginManagementCommandV1(
            action="install",
            mutation=PluginDesiredStateMutationV1(
                operation_id="install",
                idempotency_key="install",
                expected_inventory_revision=0,
                installation_key=_key(),
                desired_state="installed_disabled",
                package_revision=_package(),
                actor_id="test",
                policy_revision="test",
            ),
        )
    )
    assert installed.result is not None
    enabled = service.submit(
        PluginManagementCommandV1(
            action="enable",
            mutation=PluginDesiredStateMutationV1(
                operation_id="enable",
                idempotency_key="enable",
                expected_inventory_revision=1,
                installation_key=_key(),
                desired_state="installed_enabled",
                package_revision=None,
                actor_id="test",
                policy_revision="test",
            ),
        )
    )
    assert enabled.result is not None


def _key() -> PluginInstallationKeyV1:
    return PluginInstallationKeyV1(
        product_id="coding",
        installation_scope="workspace",
        scope_id="workspace-1",
        plugin_id="review-pack",
    )


def _package() -> PluginPackageRevisionRefV1:
    return PluginPackageRevisionRefV1(
        plugin_id="review-pack",
        plugin_version="1",
        package_content_digest="1" * 64,
        dependency_lock_digest="2" * 64,
        package_source_identity="local:/review-pack",
    )
