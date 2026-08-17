from __future__ import annotations


def test_session_settings_controller_returns_defaults_without_manager() -> None:
    from loushang.coding.control import CompactionSettings, RetrySettings
    from loushang.harness.session.settings import SessionSettingsBinding

    controller = SessionSettingsBinding(
        default_compaction=CompactionSettings,
        default_retry=RetrySettings,
    )

    assert controller.get_settings_manager() is None
    assert controller.get_compaction_settings() == CompactionSettings()
    assert controller.get_retry_settings() == RetrySettings()
    assert controller.auto_retry_enabled is controller.get_retry_settings().enabled


def test_session_settings_controller_lazily_creates_manager_for_auto_flags() -> None:
    from loushang.coding.control import SettingsManager
    from loushang.harness.session.settings import SessionSettingsBinding

    controller = SessionSettingsBinding(create_settings_manager=SettingsManager)

    controller.set_auto_retry_enabled(False)
    controller.set_auto_compaction_enabled(False)

    manager = controller.get_settings_manager()
    assert manager is not None
    assert manager.get_retry_settings().enabled is False
    assert manager.get_settings().compaction.enabled is False


def test_session_settings_controller_forwards_permission_profiles() -> None:
    from loushang.coding.control import SettingsManager
    from loushang.harness.session.settings import SessionSettingsBinding

    manager = SettingsManager()
    controller = SessionSettingsBinding(settings_manager=manager)

    assert (
        controller.get_permission_profile_snapshot().effective_profile.profile_id
        == "standard"
    )

    controller.set_permission_profile("cautious", scope="session")

    assert (
        controller.get_permission_profile_snapshot().effective_profile.profile_id
        == "cautious"
    )


def test_session_settings_controller_persists_queue_modes_to_existing_manager(tmp_path) -> None:
    from loushang.coding.control import SettingsManager
    from loushang.harness.session.settings import SessionSettingsBinding

    settings_path = tmp_path / "settings.json"
    controller = SessionSettingsBinding(
        settings_manager=SettingsManager(global_settings_path=settings_path)
    )

    controller.persist_queue_mode("steering", "all")
    controller.persist_queue_mode("follow_up", "all")

    reloaded = SettingsManager(global_settings_path=settings_path)
    assert reloaded.get_settings().steering_mode == "all"
    assert reloaded.get_settings().follow_up_mode == "all"
