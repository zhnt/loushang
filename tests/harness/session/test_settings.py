from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.config.agent import CompactionSettings
from loushang.harness.session.settings import SessionSettingsBinding


@dataclass
class _Snapshot:
    compaction: CompactionSettings


class _SettingsManager:
    def __init__(self) -> None:
        self.snapshot = _Snapshot(compaction=CompactionSettings())

    def get_settings(self) -> _Snapshot:
        return self.snapshot

    def get_retry_settings(self) -> object:
        return object()

    def update_settings(self, *, scope: str, compaction: CompactionSettings) -> None:
        assert scope == "session"
        self.snapshot = _Snapshot(compaction=compaction)


def test_settings_binding_materializes_only_the_changed_policy_field() -> None:
    manager = _SettingsManager()
    binding = SessionSettingsBinding(
        create_settings_manager=lambda: manager,
        default_compaction=CompactionSettings,
    )

    assert binding.get_compaction_policy_override() is None

    binding.set_auto_compaction_enabled(False)

    assert binding.get_compaction_policy_override() == CompactionSettings(
        enabled=False,
    )
