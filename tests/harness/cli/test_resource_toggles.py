from __future__ import annotations

import pytest

from loushang.harness.cli import (
    ResourceToggleError,
    ResourceToggleRequest,
    agent_resource_toggle_request,
    apply_resource_toggles,
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
