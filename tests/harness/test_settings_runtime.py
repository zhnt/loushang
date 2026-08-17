from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.config import (
    ConfigFieldSpec,
    ConfigLayer,
    LayeredConfig,
    SchemaConfigCodec,
    ScopedConfigRuntime,
    SettingsRuntime,
)


@dataclass(frozen=True)
class _Settings:
    enabled: bool = False


def _runtime() -> SettingsRuntime[_Settings]:
    codec = SchemaConfigCodec(
        default_factory=_Settings,
        fields=(ConfigFieldSpec("enabled"),),
    )
    return SettingsRuntime(
        ScopedConfigRuntime(
            LayeredConfig(
                codec=codec,
                layers=(ConfigLayer("global"), ConfigLayer("session")),
            )
        )
    )


def test_settings_runtime_delegates_scopes_and_changes() -> None:
    runtime = _runtime()
    seen: list[_Settings] = []
    runtime.subscribe(seen.append)

    change = runtime.update("session", {"enabled": True})

    assert change.operation == "update"
    assert runtime.value.enabled is True
    assert runtime.scope("session").patch == {"enabled": True}
    assert seen == [_Settings(enabled=True)]


def test_settings_runtime_exposes_layer_paths_and_issue_drain() -> None:
    runtime = _runtime()

    assert runtime.global_base_dir is None
    assert runtime.project_base_dir is None
    assert runtime.drain_issues() == ()
