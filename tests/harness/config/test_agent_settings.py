from __future__ import annotations

import json
from dataclasses import fields

import pytest


def test_settings_manager_loads_global_and_project_settings_with_project_precedence(
    tmp_path,
) -> None:
    from loushang.harness.config.agent import SettingsManager

    global_settings_path = tmp_path / "global-settings.json"
    project_settings_path = tmp_path / "project-settings.json"

    global_settings_path.write_text(
        json.dumps(
            {
                "default_model": {
                    "provider": "faux",
                    "endpoint_id": "messages",
                    "model_id": "alpha",
                },
                "thinking_level": "minimal",
                "compaction": {
                    "enabled": False,
                    "compact_percent": 75,
                    "reserve_tokens": 2048,
                },
                "session_dir": "/tmp/global-sessions",
                "resource_roots": ["/tmp/global-resources"],
                "package_roots": ["/tmp/global-packages"],
                "plugin_sources": ["/tmp/global-plugins/review-pack"],
                "disabled_skills": ["review"],
                "disabled_plugins": ["legacy-plugin"],
                "keybindings": {
                    "tui.editor.cursorLeft": ["left", "alt+h"],
                    "tui.editor.cursorRight": ["right", "alt+l"],
                },
            }
        ),
        encoding="utf-8",
    )
    project_settings_path.write_text(
        json.dumps(
            {
                "system_prompt": "Use project rules.",
                "compaction": {"keep_recent_tokens": 8192},
                "session_dir": "/tmp/project-sessions",
                "resource_roots": ["/tmp/project-resources"],
            }
        ),
        encoding="utf-8",
    )

    manager = SettingsManager(
        global_settings_path=global_settings_path,
        project_settings_path=project_settings_path,
    )
    settings = manager.get_settings()

    assert settings.default_model is not None
    assert settings.default_model.provider == "faux"
    assert settings.default_model.endpoint_id == "messages"
    assert settings.default_model.model_id == "alpha"
    assert settings.thinking_level == "minimal"
    assert settings.system_prompt == "Use project rules."
    assert settings.compaction.enabled is False
    assert settings.compaction.compact_percent == 75
    assert settings.compaction.reserve_tokens == 2048
    assert settings.compaction.keep_recent_tokens == 8192
    assert settings.session_dir == "/tmp/project-sessions"
    assert settings.resource_roots == ("/tmp/project-resources",)
    assert settings.package_roots == ("/tmp/global-packages",)
    assert settings.plugin_sources == ("/tmp/global-plugins/review-pack",)
    assert settings.disabled_skills == ("review",)
    assert settings.disabled_plugins == ("legacy-plugin",)
    assert settings.keybindings == {
        "tui.editor.cursorLeft": ("left", "alt+h"),
        "tui.editor.cursorRight": ("right", "alt+l"),
    }


def test_settings_manager_loads_method_settings_with_project_precedence(
    tmp_path,
) -> None:
    from loushang.harness.config.agent import MethodSettings, SettingsManager

    global_settings_path = tmp_path / "global-settings.json"
    project_settings_path = tmp_path / "project-settings.json"
    global_settings_path.write_text(
        json.dumps({"method": {"mode": "explicit", "selected_method": "review"}}),
        encoding="utf-8",
    )
    project_settings_path.write_text(
        json.dumps({"method": {"selected_method": "debug"}}),
        encoding="utf-8",
    )

    manager = SettingsManager(
        global_settings_path=global_settings_path,
        project_settings_path=project_settings_path,
    )

    assert manager.get_settings().method == MethodSettings(
        mode="explicit", selected_method="debug"
    )
    assert manager.get_method_settings() == MethodSettings(
        mode="explicit", selected_method="debug"
    )


def test_settings_manager_persists_method_settings_updates(tmp_path) -> None:
    from loushang.harness.config.agent import MethodSettings, SettingsManager

    global_settings_path = tmp_path / "global-settings.json"
    project_settings_path = tmp_path / "project-settings.json"
    manager = SettingsManager(
        global_settings_path=global_settings_path,
        project_settings_path=project_settings_path,
    )

    assert manager.get_settings().method == MethodSettings()

    manager.update_settings(
        scope="global",
        method=MethodSettings(mode="explicit", selected_method="review"),
    )
    manager.set_method_settings(MethodSettings(mode="off"), scope="project")

    reloaded = SettingsManager(
        global_settings_path=global_settings_path,
        project_settings_path=project_settings_path,
    )

    assert reloaded.get_global_settings() == {
        "method": {"mode": "explicit", "selected_method": "review"}
    }
    assert reloaded.get_project_settings() == {
        "method": {"mode": "off", "selected_method": None}
    }
    assert reloaded.get_method_settings() == MethodSettings(
        mode="off", selected_method=None
    )


def test_settings_manager_loads_and_persists_sandbox_settings(tmp_path) -> None:
    from loushang.harness.config.agent import SandboxSettings, SettingsManager

    settings_path = tmp_path / "settings.json"
    manager = SettingsManager(global_settings_path=settings_path)

    assert manager.get_sandbox_settings() == SandboxSettings()

    manager.set_sandbox_settings(
        SandboxSettings(enabled=True, requirement="required"),
        scope="global",
    )
    reloaded = SettingsManager(global_settings_path=settings_path)

    assert reloaded.get_global_settings() == {
        "sandbox": {"enabled": True, "requirement": "required"}
    }
    assert reloaded.get_sandbox_settings() == SandboxSettings(
        enabled=True,
        requirement="required",
    )


def test_settings_manager_applies_permission_profiles_at_each_scope(
    tmp_path,
) -> None:
    from loushang.harness.config.agent import SettingsManager

    global_settings_path = tmp_path / "global-settings.json"
    project_settings_path = tmp_path / "project-settings.json"
    manager = SettingsManager(
        global_settings_path=global_settings_path,
        project_settings_path=project_settings_path,
    )

    manager.set_permission_profile("cautious", scope="user")
    assert manager.get_permission_profile_id() == "cautious"
    assert json.loads(global_settings_path.read_text(encoding="utf-8")) == {
        "permissions": {"profile": "cautious"}
    }

    manager.set_permission_profile("standard", scope="project")
    assert manager.get_permission_profile_id() == "standard"
    assert json.loads(project_settings_path.read_text(encoding="utf-8")) == {
        "permissions": {"profile": "standard"}
    }

    manager.set_permission_profile("full_access", scope="session")
    assert manager.get_permission_profile_id() == "full_access"

    manager.set_permission_profile("cautious", scope="user")
    assert manager.get_permission_profile_id() == "full_access"

    reloaded = SettingsManager(
        global_settings_path=global_settings_path,
        project_settings_path=project_settings_path,
    )
    assert reloaded.get_permission_profile_id() == "standard"


def test_settings_manager_enforces_the_managed_permission_ceiling(tmp_path) -> None:
    from loushang.harness.config.agent import SettingsManager
    from loushang.harness.permissions import PermissionProfileCeiling

    manager = SettingsManager(
        global_settings_path=tmp_path / "settings.json",
        permission_profile_ceiling=PermissionProfileCeiling(
            maximum_profile="standard",
            reason="Managed sessions cannot enable Full Access.",
        ),
    )

    with pytest.raises(
        PermissionError,
        match="Managed sessions cannot enable Full Access",
    ):
        manager.set_permission_profile("full_access", scope="session")

    snapshot = manager.get_permission_profile_snapshot()
    full_access = next(
        option
        for option in snapshot.options
        if option.profile.profile_id == "full_access"
    )
    assert full_access.enabled is False
    assert full_access.disabled_reason == (
        "Managed sessions cannot enable Full Access."
    )


def test_settings_manager_recovers_from_invalid_sandbox_settings(tmp_path) -> None:
    from loushang.harness.config.agent import SandboxSettings, SettingsManager

    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "thinking_level": "high",
                "sandbox": {"enabled": False, "requirement": "required"},
            }
        ),
        encoding="utf-8",
    )

    manager = SettingsManager(global_settings_path=settings_path)

    assert manager.get_settings().thinking_level == "high"
    assert manager.get_sandbox_settings() == SandboxSettings()
    errors = manager.drain_errors()
    assert len(errors) == 1
    assert "cannot be disabled" in errors[0].message


def test_settings_manager_loads_statusline_settings_with_project_precedence(
    tmp_path,
) -> None:
    from loushang.harness.config.agent import (
        SettingsManager,
        StatusLineControlSettings,
    )

    global_settings_path = tmp_path / "global-settings.json"
    project_settings_path = tmp_path / "project-settings.json"
    global_settings_path.write_text(
        json.dumps(
            {
                "statusline": {
                    "enabled": False,
                    "queue": "true",
                    "style": "muted",
                }
            }
        ),
        encoding="utf-8",
    )
    project_settings_path.write_text(
        json.dumps(
            {
                "statusline": {
                    "model": False,
                    "separator": "dot",
                }
            }
        ),
        encoding="utf-8",
    )

    manager = SettingsManager(
        global_settings_path=global_settings_path,
        project_settings_path=project_settings_path,
    )

    assert manager.get_statusline_settings() == StatusLineControlSettings(
        enabled=False,
        model=False,
        queue="true",
        separator="dot",
        style="muted",
    )
    assert manager.get_settings().statusline == manager.get_statusline_settings()


def test_settings_manager_persists_statusline_settings_updates(tmp_path) -> None:
    from loushang.harness.config.agent import (
        SettingsManager,
        StatusLineControlSettings,
    )

    settings_path = tmp_path / "settings.json"
    manager = SettingsManager(global_settings_path=settings_path)

    manager.set_statusline_settings(
        StatusLineControlSettings(
            enabled=False,
            workspace=False,
            queue="true",
            message="false",
            separator="dot",
            style="plain",
        ),
        scope="global",
    )

    reloaded = SettingsManager(global_settings_path=settings_path)

    assert reloaded.get_global_settings() == {
        "statusline": {
            "enabled": False,
            "model": True,
            "workspace": False,
            "branch": True,
            "session": True,
            "permissions": True,
            "runtime": True,
            "queue": "true",
            "message": "false",
            "separator": "dot",
            "style": "plain",
        }
    }
    assert reloaded.get_statusline_settings() == StatusLineControlSettings(
        enabled=False,
        workspace=False,
        queue="true",
        message="false",
        separator="dot",
        style="plain",
    )


def test_settings_manager_ignores_invalid_statusline_patch_without_dropping_other_settings(
    tmp_path,
) -> None:
    from loushang.harness.config.agent import (
        SettingsManager,
        StatusLineControlSettings,
    )

    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "thinking_level": "high",
                "statusline": {
                    "enabled": False,
                    "queue": "maybe",
                },
            }
        ),
        encoding="utf-8",
    )

    manager = SettingsManager(global_settings_path=settings_path)

    assert manager.get_settings().thinking_level == "high"
    assert manager.get_statusline_settings() == StatusLineControlSettings()
    errors = manager.drain_errors()
    assert len(errors) == 1
    assert errors[0].scope == "global"
    assert "statusline.queue" in errors[0].message


def test_settings_manager_persists_scoped_updates_and_notifies_subscribers(
    tmp_path,
) -> None:
    from loushang.harness.config.agent import (
        BranchSummarySettings,
        CompactionSettings,
        ImageSettings,
        MarkdownSettings,
        SettingsManager,
        StatusLineControlSettings,
        TerminalSettings,
        ToolSettings,
        WarningSettings,
    )

    global_settings_path = tmp_path / "global-settings.json"
    project_settings_path = tmp_path / "project-settings.json"
    manager = SettingsManager(
        global_settings_path=global_settings_path,
        project_settings_path=project_settings_path,
    )
    seen = []
    manager.subscribe(seen.append)

    manager.update_settings(
        scope="global",
        thinking_level="high",
        steering_mode="all",
        follow_up_mode="all",
        theme="solarized",
        hide_thinking_block=True,
        shell_path="/bin/zsh",
        quiet_startup=True,
        shell_command_prefix="set -e",
        npm_command=("mise", "exec", "node@20", "--", "npm"),
        collapse_changelog=True,
        enable_install_telemetry=False,
        enable_skill_commands=False,
        thinking_budgets={"minimal": 512, "low": 1024, "medium": 2048, "high": 4096},
        compaction=CompactionSettings(
            enabled=False,
            compact_percent=75,
            reserve_tokens=2048,
            keep_recent_tokens=8192,
        ),
        branch_summary=BranchSummarySettings(
            enabled=False, reserve_tokens=4096, skip_prompt=True
        ),
        tools=ToolSettings(
            external_tool_policy="never",
            blocked_tools=("bash",),
            ask_tools=("write",),
            blocked_substrings=("rm -rf",),
            ask_substrings=("git push",),
            blocked_path_substrings=("/etc",),
            ask_path_substrings=(".env",),
            approval_mode="allow",
            approval_reason="trusted headless run",
        ),
        images=ImageSettings(auto_resize=False, block_images=True),
        terminal=TerminalSettings(
            show_images=False,
            image_width_cells=42,
            clear_on_shrink=True,
            show_terminal_progress=True,
        ),
        statusline=StatusLineControlSettings(
            enabled=False, queue="true", style="muted"
        ),
        markdown=MarkdownSettings(code_block_indent="    "),
        warnings=WarningSettings(anthropic_extra_usage=False),
        package_roots=("/tmp/shared-packages",),
        plugin_sources=("/tmp/shared-plugins/review-pack",),
        disabled_skills=("review",),
        disabled_plugins=("debug-pack",),
        keybindings={
            "tui.editor.cursorLeft": ("left", "alt+h"),
            "tui.editor.cursorRight": ("right", "alt+l"),
        },
    )
    manager.enable_skill("review", scope="global")
    manager.disable_skill("debug", scope="global")
    manager.add_plugin_source("/tmp/shared-plugins/debug-pack", scope="global")
    manager.remove_plugin_source("/tmp/shared-plugins/review-pack", scope="global")
    manager.disable_plugin("legacy-pack", scope="global")
    manager.enable_plugin("debug-pack", scope="global")
    manager.update_settings(
        scope="project",
        system_prompt="Project prompt.",
        session_dir="/tmp/project-sessions",
        resource_roots=("/tmp/project-resources",),
    )

    reloaded = SettingsManager(
        global_settings_path=global_settings_path,
        project_settings_path=project_settings_path,
    )

    assert reloaded.get_settings().thinking_level == "high"
    assert reloaded.get_settings().steering_mode == "all"
    assert reloaded.get_settings().follow_up_mode == "all"
    assert reloaded.get_settings().theme == "solarized"
    assert reloaded.get_settings().hide_thinking_block is True
    assert reloaded.get_settings().shell_path == "/bin/zsh"
    assert reloaded.get_settings().quiet_startup is True
    assert reloaded.get_settings().shell_command_prefix == "set -e"
    assert reloaded.get_settings().npm_command == (
        "mise",
        "exec",
        "node@20",
        "--",
        "npm",
    )
    assert reloaded.get_settings().collapse_changelog is True
    assert reloaded.get_settings().enable_install_telemetry is False
    assert reloaded.get_settings().enable_skill_commands is False
    assert reloaded.get_settings().thinking_budgets == {
        "minimal": 512,
        "low": 1024,
        "medium": 2048,
        "high": 4096,
    }
    assert reloaded.get_settings().compaction == CompactionSettings(
        enabled=False, compact_percent=75, reserve_tokens=2048, keep_recent_tokens=8192
    )
    assert reloaded.get_settings().branch_summary == BranchSummarySettings(
        enabled=False, reserve_tokens=4096, skip_prompt=True
    )
    assert reloaded.get_settings().tools == ToolSettings(
        external_tool_policy="never",
        blocked_tools=("bash",),
        ask_tools=("write",),
        blocked_substrings=("rm -rf",),
        ask_substrings=("git push",),
        blocked_path_substrings=("/etc",),
        ask_path_substrings=(".env",),
        approval_mode="allow",
        approval_reason="trusted headless run",
    )
    assert reloaded.get_settings().images == ImageSettings(
        auto_resize=False, block_images=True
    )
    assert reloaded.get_settings().terminal == TerminalSettings(
        show_images=False,
        image_width_cells=42,
        clear_on_shrink=True,
        show_terminal_progress=True,
    )
    assert reloaded.get_settings().statusline == StatusLineControlSettings(
        enabled=False, queue="true", style="muted"
    )
    assert reloaded.get_settings().markdown == MarkdownSettings(
        code_block_indent="    "
    )
    assert reloaded.get_settings().warnings == WarningSettings(
        anthropic_extra_usage=False
    )
    assert reloaded.get_settings().package_roots == ("/tmp/shared-packages",)
    assert reloaded.get_settings().plugin_sources == ("/tmp/shared-plugins/debug-pack",)
    assert reloaded.get_settings().disabled_skills == ("debug",)
    assert reloaded.get_settings().disabled_plugins == ("legacy-pack",)
    assert reloaded.get_keybindings() == {
        "tui.editor.cursorLeft": ("left", "alt+h"),
        "tui.editor.cursorRight": ("right", "alt+l"),
    }
    assert reloaded.get_settings().system_prompt == "Project prompt."
    assert reloaded.get_settings().session_dir == "/tmp/project-sessions"
    assert reloaded.get_settings().resource_roots == ("/tmp/project-resources",)
    assert seen[-1] == manager.get_settings()


def test_settings_manager_package_source_add_remove_uses_package_identity(
    tmp_path,
) -> None:
    from loushang.harness.config.agent import SettingsManager

    settings_path = tmp_path / "settings.json"
    manager = SettingsManager(global_settings_path=settings_path)

    assert (
        manager.add_package_source("pypi:acme-review-pack==1.2.3", scope="global")
        is True
    )
    assert (
        manager.add_package_source("pypi:acme-review-pack==1.3.0", scope="global")
        is False
    )
    assert (
        manager.add_package_source("git:github.com/acme/review-pack@v1", scope="global")
        is True
    )
    assert (
        manager.add_package_source(
            "git+https://github.com/acme/review-pack#main", scope="global"
        )
        is False
    )
    assert [source.source for source in manager.get_package_sources()] == [
        "pypi:acme-review-pack==1.2.3",
        "git:github.com/acme/review-pack@v1",
    ]

    assert (
        manager.remove_package_source("pypi:acme-review-pack==1.3.0", scope="global")
        is True
    )
    assert (
        manager.remove_package_source(
            "git+https://github.com/acme/review-pack#main", scope="global"
        )
        is True
    )
    assert manager.get_package_sources() == []


def test_settings_manager_exposes_standard_control_getters_and_setters(
    tmp_path,
) -> None:
    from loushang.harness.config.agent import SettingsManager

    settings_path = tmp_path / "settings.json"
    manager = SettingsManager(global_settings_path=settings_path)

    manager.set_theme("night")
    manager.set_hide_thinking_block(True)
    manager.set_shell_path("/bin/fish")
    manager.set_quiet_startup(True)
    manager.set_shell_command_prefix("source ~/.profile")
    manager.set_npm_command(("npm", "--silent"))
    manager.set_collapse_changelog(True)
    manager.set_enable_install_telemetry(False)
    manager.set_enable_skill_commands(False)
    manager.set_show_images(False)
    manager.set_image_width_cells(19.8)
    manager.set_clear_on_shrink(True)
    manager.set_show_terminal_progress(True)
    manager.set_image_auto_resize(False)
    manager.set_block_images(True)
    manager.set_enabled_models(["sonnet:high", "haiku:low"])
    manager.set_double_escape_action("fork")
    manager.set_tree_filter_mode("labeled-only")
    manager.set_show_hardware_cursor(True)
    manager.set_editor_padding_x(12)
    manager.set_autocomplete_max_visible(99)
    manager.set_external_tool_policy("required")
    manager.update_settings(
        scope="global",
        branch_summary={"skip_prompt": True},
        markdown={"code_block_indent": "\t"},
    )
    manager.update_settings(scope="global", warnings={"anthropic_extra_usage": False})
    manager.update_settings(
        scope="global",
        thinking_budgets={"low": 1000},
        retry={"provider_max_retry_delay_ms": 7},
    )

    reloaded = SettingsManager(global_settings_path=settings_path)
    settings = reloaded.get_settings()
    assert reloaded.get_theme() == "night"
    assert reloaded.get_hide_thinking_block() is True
    assert reloaded.get_shell_path() == "/bin/fish"
    assert reloaded.get_quiet_startup() is True
    assert reloaded.get_shell_command_prefix() == "source ~/.profile"
    assert reloaded.get_npm_command() == ["npm", "--silent"]
    assert reloaded.get_collapse_changelog() is True
    assert reloaded.get_enable_install_telemetry() is False
    assert reloaded.get_enable_skill_commands() is False
    assert reloaded.get_show_images() is False
    assert reloaded.get_image_width_cells() == 19
    assert reloaded.get_clear_on_shrink() is True
    assert reloaded.get_show_terminal_progress() is True
    assert reloaded.get_image_auto_resize() is False
    assert reloaded.get_block_images() is True
    assert reloaded.get_enabled_models() == ["sonnet:high", "haiku:low"]
    assert reloaded.get_double_escape_action() == "fork"
    assert reloaded.get_tree_filter_mode() == "labeled-only"
    assert reloaded.get_show_hardware_cursor() is True
    assert reloaded.get_editor_padding_x() == 3
    assert reloaded.get_autocomplete_max_visible() == 20
    assert reloaded.get_tool_settings() == settings.tools
    assert reloaded.get_external_tool_policy() == "required"
    assert reloaded.get_thinking_budgets() == {"low": 1000}
    assert reloaded.get_provider_retry_settings()["max_retry_delay_ms"] == 7
    assert reloaded.get_compaction_settings() == settings.compaction
    assert reloaded.get_branch_summary_settings() == settings.branch_summary
    assert reloaded.get_branch_summary_skip_prompt() is True
    assert reloaded.get_image_settings() == settings.images
    assert reloaded.get_terminal_settings() == settings.terminal
    assert reloaded.get_markdown_settings() == settings.markdown
    assert reloaded.get_code_block_indent() == "\t"
    assert reloaded.get_warnings() == settings.warnings


def test_settings_manager_transport_setting_is_removed() -> None:
    from loushang.harness.config.agent import ControlConfig, SettingsManager

    manager = SettingsManager()

    assert "transport" not in {field.name for field in fields(ControlConfig)}
    assert not hasattr(manager, "get_transport")
    assert not hasattr(manager, "set_transport")
    with pytest.raises(TypeError, match="transport"):
        manager.update_settings(transport="websocket")  # type: ignore[call-arg]

    manager.apply_overrides({"transport": "websocket"})
    assert not hasattr(manager.get_settings(), "transport")
    errors = manager.drain_errors()
    assert len(errors) == 1
    assert errors[0].scope == "session"
    assert "transport setting has been removed" in errors[0].message


def test_settings_manager_reports_persisted_removed_transport_setting(tmp_path) -> None:
    from loushang.harness.config.agent import SettingsManager

    global_settings_path = tmp_path / "global-settings.json"
    global_settings_path.write_text(
        json.dumps({"transport": "websocket", "theme": "night"}),
        encoding="utf-8",
    )

    manager = SettingsManager(global_settings_path=global_settings_path)

    assert manager.get_settings().theme == "night"
    assert not hasattr(manager.get_settings(), "transport")
    assert manager.get_global_settings() == {
        "transport": "websocket",
        "theme": "night",
    }
    errors = manager.drain_errors()
    assert len(errors) == 1
    assert errors[0].scope == "global"
    assert "transport setting has been removed" in errors[0].message

    manager.reload()
    errors = manager.drain_errors()
    assert len(errors) == 1
    assert errors[0].scope == "global"
    assert "transport setting has been removed" in errors[0].message


def test_settings_patch_preserves_omitted_null_and_package_wire_contract() -> None:
    from loushang.harness.config.agent._settings_patch import (
        AgentSettingsUpdate,
        build_settings_patch,
    )

    assert build_settings_patch(AgentSettingsUpdate()) == {}
    assert build_settings_patch(
        AgentSettingsUpdate(
            theme=None,
            enabled_models=None,
            package_sources=("/tmp/shared-package",),
        )
    ) == {
        "theme": None,
        "enabled_models": None,
        "packages": ["/tmp/shared-package"],
    }


def test_prepare_override_patch_drops_removed_keys_without_rewriting_storage() -> None:
    from loushang.harness.config.agent._settings_patch import prepare_override_patch

    patch, messages = prepare_override_patch(
        {"transport": "websocket", "theme": "night"}
    )

    assert patch == {"theme": "night"}
    assert messages == (
        "transport setting has been removed; use provider/contrib-specific configuration instead",
    )


def test_settings_manager_control_getters_apply_standard_defaults_and_bounds(
    tmp_path, monkeypatch
) -> None:
    from loushang.harness.config.agent import SettingsManager

    monkeypatch.delenv("PI_HARDWARE_CURSOR", raising=False)
    manager = SettingsManager(global_settings_path=tmp_path / "settings.json")

    assert manager.get_enabled_models() is None
    assert manager.get_double_escape_action() == "tree"
    assert manager.get_tree_filter_mode() == "default"
    assert manager.get_show_hardware_cursor() is False
    assert manager.get_editor_padding_x() == 0
    assert manager.get_autocomplete_max_visible() == 5

    manager.set_enabled_models(None)
    manager.set_double_escape_action("none")
    manager.set_tree_filter_mode("all")
    manager.set_show_hardware_cursor(False)
    manager.set_editor_padding_x(-10)
    manager.set_autocomplete_max_visible(1)

    assert manager.get_enabled_models() is None
    assert manager.get_double_escape_action() == "none"
    assert manager.get_tree_filter_mode() == "all"
    assert manager.get_show_hardware_cursor() is False
    assert manager.get_editor_padding_x() == 0
    assert manager.get_autocomplete_max_visible() == 3


def test_settings_manager_exposes_resource_and_package_source_getters_and_setters(
    tmp_path,
) -> None:
    from loushang.harness.config.agent import SettingsManager
    from loushang.harness.resources.packages.source import PackageSourceConfig

    manager = SettingsManager(global_settings_path=tmp_path / "settings.json")

    manager.set_resource_roots(["resources/a", "resources/b"])
    manager.set_package_roots(["packages/review"])
    manager.set_package_sources(
        [
            PackageSourceConfig(
                source="https://packages.example.invalid/review-pack.git",
                prompts=("review.md",),
                skills=(),
            )
        ]
    )
    manager.set_plugin_sources(["plugins/debug"])
    manager.set_disabled_skills(["skill-a"])
    manager.set_disabled_plugins(["plugin-a"])

    reloaded = SettingsManager(global_settings_path=tmp_path / "settings.json")

    assert reloaded.get_resource_roots() == ["resources/a", "resources/b"]
    assert reloaded.get_package_roots() == ["packages/review"]
    assert reloaded.get_package_sources() == [
        PackageSourceConfig(
            source="https://packages.example.invalid/review-pack.git",
            prompts=("review.md",),
            skills=(),
        )
    ]
    assert reloaded.get_plugin_sources() == ["plugins/debug"]
    assert reloaded.get_disabled_skills() == ["skill-a"]
    assert reloaded.get_disabled_plugins() == ["plugin-a"]

    roots = reloaded.get_package_roots()
    roots.append("mutated")
    assert reloaded.get_package_roots() == ["packages/review"]


def test_settings_manager_initial_config_preserves_package_sources() -> None:
    from loushang.harness.config.agent import ControlConfig, SettingsManager
    from loushang.harness.resources.packages.source import PackageSourceConfig

    source = PackageSourceConfig(
        source="https://packages.example.invalid/review-pack.git",
        prompts=("review.md",),
        skills=(),
    )

    manager = SettingsManager(ControlConfig(package_sources=(source,)))

    assert manager.get_package_sources() == [source]


def test_settings_manager_exposes_scope_patch_snapshots(tmp_path) -> None:
    from loushang.harness.config.agent import SettingsManager

    global_settings_path = tmp_path / "global-settings.json"
    project_settings_path = tmp_path / "project-settings.json"
    global_settings_path.write_text(
        json.dumps({"thinking_level": "minimal"}), encoding="utf-8"
    )
    project_settings_path.write_text(
        json.dumps({"system_prompt": "Project prompt."}), encoding="utf-8"
    )

    manager = SettingsManager(
        global_settings_path=global_settings_path,
        project_settings_path=project_settings_path,
    )
    manager.update_settings(scope="session", resource_roots=("/tmp/session-resources",))

    global_patch = manager.get_global_settings()
    project_patch = manager.get_project_settings()
    session_patch = manager.get_session_settings()
    global_patch["thinking_level"] = "mutated"
    project_patch["system_prompt"] = "mutated"
    session_patch["resource_roots"].append("/tmp/mutated")

    assert manager.get_global_settings() == {"thinking_level": "minimal"}
    assert manager.get_project_settings() == {"system_prompt": "Project prompt."}
    assert manager.get_session_settings() == {
        "resource_roots": ["/tmp/session-resources"]
    }


def test_settings_manager_records_load_errors_without_failing_startup(tmp_path) -> None:
    from loushang.harness.config.agent import SettingsManager

    global_settings_path = tmp_path / "global-settings.json"
    project_settings_path = tmp_path / "project-settings.json"
    global_settings_path.write_text("{not-json", encoding="utf-8")
    project_settings_path.write_text(
        json.dumps({"thinking_level": "high"}), encoding="utf-8"
    )

    manager = SettingsManager(
        global_settings_path=global_settings_path,
        project_settings_path=project_settings_path,
    )

    assert manager.get_settings().thinking_level == "high"
    errors = manager.drain_errors()
    assert len(errors) == 1
    assert errors[0].scope == "global"
    assert "Expecting property name" in errors[0].message
    assert manager.drain_errors() == []


def test_settings_manager_reload_preserves_previous_scope_when_reload_fails(
    tmp_path,
) -> None:
    from loushang.harness.config.agent import SettingsManager

    project_settings_path = tmp_path / "project-settings.json"
    project_settings_path.write_text(
        json.dumps({"system_prompt": "before"}), encoding="utf-8"
    )
    manager = SettingsManager(project_settings_path=project_settings_path)

    project_settings_path.write_text("{not-json", encoding="utf-8")
    manager.reload()

    assert manager.get_settings().system_prompt == "before"
    errors = manager.drain_errors()
    assert len(errors) == 1
    assert errors[0].scope == "project"
