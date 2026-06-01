from __future__ import annotations

import json
import sys

from loushang.coding.ui import playback_runner
from loushang.coding.ui.playback_fakes import SessionCommandPlaybackSession
from loushang.coding.ui.playback_runner import (
    NativePlaybackScenarioSpec,
    NativePlaybackSuite,
    run_playback_cli,
    run_playback_scenarios,
)
from loushang.coding.ui.playback_scenarios.command import COMMAND_ROUTING_SCENARIOS
from loushang.coding.ui.playback_scenarios.composer import COMPOSER_SCENARIOS
from loushang.coding.ui.playback_scenarios.lifecycle import LIFECYCLE_SCENARIOS
from loushang.coding.ui.playback_scenarios.surface import SURFACE_SCENARIOS
from loushang.coding.ui.playback_scenarios.terminal import TERMINAL_SCENARIOS
from loushang.coding.ui.playback_scenarios.transcript import TRANSCRIPT_SCENARIOS
from loushang.coding.ui.playback_suite import NativePlaybackSuite as SuiteFromModule


def test_native_tui_playback_runner_reexports_suite_types_from_playback_suite_module() -> None:
    assert NativePlaybackSuite is SuiteFromModule


def test_native_tui_playback_fake_session_lists_command_sources() -> None:
    session = SessionCommandPlaybackSession()

    commands = session.list_commands()

    assert [(command.name, command.source) for command in commands] == [
        ("name", "builtin"),
        ("export", "builtin"),
        ("review", "prompt"),
        ("debugging", "skill"),
    ]


def test_native_tui_playback_command_scenarios_live_in_command_module() -> None:
    assert [scenario.name for scenario in COMMAND_ROUTING_SCENARIOS] == [
        "local-command",
        "session-name-command",
        "session-command-error",
        "unknown-slash-prompt",
        "non-executable-session-command",
    ]


def test_native_tui_playback_composer_scenarios_live_in_composer_module() -> None:
    assert [scenario.name for scenario in COMPOSER_SCENARIOS] == [
        "completion-tab",
        "completion-session-command",
        "completion-navigation-priority",
        "history-navigation",
        "bracketed-paste-large-marker",
        "resize-reflow-stable",
        "wide-char-input-cursor",
        "keyboard-shift-enter-newline",
    ]


def test_native_tui_playback_surface_scenarios_live_in_surface_module() -> None:
    assert [scenario.name for scenario in SURFACE_SCENARIOS] == [
        "active-surface",
        "status-surface",
        "statusline-command",
        "command-palette-select",
        "command-palette-session-command",
        "commands-info-surface",
        "commands-info-session-command",
        "settings-search",
        "model-select",
        "model-select-search",
        "approval-surface",
        "approval-reject-surface",
        "dialog-surface",
        "mouse-select-active-surface",
    ]


def test_native_tui_playback_lifecycle_scenarios_live_in_lifecycle_module() -> None:
    assert [scenario.name for scenario in LIFECYCLE_SCENARIOS] == [
        "idle-escape-clears-draft",
        "running-steer-queued",
        "running-escape-keeps-queued-steer",
        "idle-escape-pops-pending-steer",
        "escape-pending-steer",
        "escape-pending-steer-fifo",
        "escape-pending-steer-preserves-draft",
        "native-loop-ctrl-c-abort-running",
        "running-follow-up-queued",
        "keyboard-alt-enter-follow-up",
    ]


def test_native_tui_playback_terminal_scenarios_live_in_terminal_module() -> None:
    assert [scenario.name for scenario in TERMINAL_SCENARIOS] == [
        "native-loop-split-bracketed-paste",
        "terminal-control-response-hidden",
        "native-loop-terminal-session-cleanup",
        "apple-shift-enter-normalized",
    ]


def test_native_tui_playback_transcript_scenarios_live_in_transcript_module() -> None:
    assert [scenario.name for scenario in TRANSCRIPT_SCENARIOS] == [
        "long-transcript-input",
        "tool-output-preview",
    ]


def test_native_tui_playback_runner_lists_default_scenarios(capsys) -> None:
    exit_code = run_playback_cli(["--list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "completion-tab" in captured.out
    assert "completion-session-command" in captured.out
    assert "completion-navigation-priority" in captured.out
    assert "history-navigation" in captured.out
    assert "idle-escape-clears-draft" in captured.out
    assert "long-transcript-input" in captured.out
    assert "escape-pending-steer" in captured.out
    assert "running-steer-queued" in captured.out
    assert "running-escape-keeps-queued-steer" in captured.out
    assert "idle-escape-pops-pending-steer" in captured.out
    assert "escape-pending-steer-fifo" in captured.out
    assert "escape-pending-steer-preserves-draft" in captured.out
    assert "session-name-command" in captured.out
    assert "session-command-error" in captured.out
    assert "unknown-slash-prompt" in captured.out
    assert "non-executable-session-command" in captured.out
    assert "running-follow-up-queued" in captured.out
    assert "status-surface" in captured.out
    assert "statusline-command" in captured.out
    assert "command-palette-select" in captured.out
    assert "command-palette-session-command" in captured.out
    assert "commands-info-surface" in captured.out
    assert "commands-info-session-command" in captured.out
    assert "settings-search" in captured.out
    assert "model-select" in captured.out
    assert "model-select-search" in captured.out
    assert "approval-surface" in captured.out
    assert "approval-reject-surface" in captured.out
    assert "dialog-surface" in captured.out
    assert "bracketed-paste-large-marker" in captured.out
    assert "tool-output-preview" in captured.out
    assert "resize-reflow-stable" in captured.out
    assert "wide-char-input-cursor" in captured.out
    assert "keyboard-alt-enter-follow-up" in captured.out
    assert "keyboard-shift-enter-newline" in captured.out
    assert "terminal-control-response-hidden" in captured.out
    assert "apple-shift-enter-normalized" in captured.out
    assert "mouse-select-active-surface" in captured.out
    assert "native-loop-split-bracketed-paste" in captured.out
    assert "native-loop-terminal-session-cleanup" in captured.out
    assert "native-loop-ctrl-c-abort-running" in captured.out


def test_native_tui_playback_runner_runs_named_scenario(capsys) -> None:
    exit_code = run_playback_cli(["completion-tab"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS completion-tab" in captured.out
    assert "long-transcript-input" not in captured.out


def test_native_tui_playback_runner_runs_tagged_command_scenarios(capsys) -> None:
    exit_code = run_playback_cli(["--tag", "command"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS session-name-command" in captured.out
    assert "PASS command-palette-session-command" in captured.out
    assert "PASS commands-info-session-command" in captured.out
    assert "PASS model-select" not in captured.out
    assert "PASS long-transcript-input" not in captured.out


def test_native_tui_playback_runner_lists_tagged_command_scenarios(capsys) -> None:
    exit_code = run_playback_cli(["--list", "--tag", "command"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "session-name-command" in captured.out
    assert "command-palette-session-command" in captured.out
    assert "model-select" not in captured.out
    assert "long-transcript-input" not in captured.out


def test_native_tui_playback_runner_runs_completion_session_command_scenario(capsys) -> None:
    exit_code = run_playback_cli(["completion-session-command"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS completion-session-command" in captured.out


def test_native_tui_playback_runner_runs_lifecycle_scenario(capsys) -> None:
    exit_code = run_playback_cli(["running-steer-queued"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS running-steer-queued" in captured.out
    assert "PASS completion-tab" not in captured.out


def test_native_tui_playback_runner_runs_session_name_command_scenario(capsys) -> None:
    exit_code = run_playback_cli(["session-name-command"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS session-name-command" in captured.out


def test_native_tui_playback_runner_runs_session_command_error_scenario(capsys) -> None:
    exit_code = run_playback_cli(["session-command-error"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS session-command-error" in captured.out


def test_native_tui_playback_runner_runs_unknown_slash_prompt_scenario(capsys) -> None:
    exit_code = run_playback_cli(["unknown-slash-prompt"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS unknown-slash-prompt" in captured.out


def test_native_tui_playback_runner_runs_non_executable_session_command_scenario(capsys) -> None:
    exit_code = run_playback_cli(["non-executable-session-command"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS non-executable-session-command" in captured.out


def test_native_tui_playback_runner_runs_settings_search_scenario(capsys) -> None:
    exit_code = run_playback_cli(["settings-search"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS settings-search" in captured.out


def test_native_tui_playback_runner_runs_info_surface_scenarios(capsys) -> None:
    exit_code = run_playback_cli(["status-surface", "commands-info-surface"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS status-surface" in captured.out
    assert "PASS commands-info-surface" in captured.out


def test_native_tui_playback_runner_runs_commands_info_session_command_scenario(capsys) -> None:
    exit_code = run_playback_cli(["commands-info-session-command"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS commands-info-session-command" in captured.out


def test_native_tui_playback_runner_runs_statusline_command_scenario(capsys) -> None:
    exit_code = run_playback_cli(["statusline-command"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS statusline-command" in captured.out


def test_native_tui_playback_runner_runs_command_palette_select_scenario(capsys) -> None:
    exit_code = run_playback_cli(["command-palette-select"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS command-palette-select" in captured.out


def test_native_tui_playback_runner_runs_command_palette_session_command_scenario(capsys) -> None:
    exit_code = run_playback_cli(["command-palette-session-command"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS command-palette-session-command" in captured.out


def test_native_tui_playback_runner_runs_model_select_scenario(capsys) -> None:
    exit_code = run_playback_cli(["model-select"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS model-select" in captured.out


def test_native_tui_playback_runner_runs_model_select_search_scenario(capsys) -> None:
    exit_code = run_playback_cli(["model-select-search"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS model-select-search" in captured.out


def test_native_tui_playback_runner_runs_approval_surface_scenario(capsys) -> None:
    exit_code = run_playback_cli(["approval-surface"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS approval-surface" in captured.out


def test_native_tui_playback_runner_runs_approval_reject_surface_scenario(capsys) -> None:
    exit_code = run_playback_cli(["approval-reject-surface"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS approval-reject-surface" in captured.out


def test_native_tui_playback_runner_runs_dialog_surface_scenario(capsys) -> None:
    exit_code = run_playback_cli(["dialog-surface"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS dialog-surface" in captured.out


def test_native_tui_playback_runner_writes_artifacts(tmp_path, capsys) -> None:
    exit_code = run_playback_cli(["completion-tab", "--artifacts", str(tmp_path), "--include-frames"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS completion-tab" in captured.out
    assert (tmp_path / "completion-tab.jsonl").exists()
    assert (tmp_path / "completion-tab-screen.txt").exists()
    row = json.loads((tmp_path / "completion-tab.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert "visible_lines" in row


def test_native_tui_playback_runner_writes_json_summary(tmp_path, capsys) -> None:
    exit_code = run_playback_cli(["completion-tab", "--json", "--artifacts", str(tmp_path)])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert captured.err == ""
    assert payload == {
        "ok": True,
        "results": [
            {
                "name": "completion-tab",
                "ok": True,
                "error": None,
                "artifacts": [
                    str(tmp_path / "completion-tab.jsonl"),
                    str(tmp_path / "completion-tab-screen.txt"),
                ],
                "elapsed_ms": payload["results"][0]["elapsed_ms"],
            }
        ],
    }
    assert payload["results"][0]["elapsed_ms"] >= 0
    assert "PASS completion-tab" not in captured.out


def test_native_tui_playback_runner_writes_artifacts_for_all_default_scenarios(tmp_path, capsys) -> None:
    exit_code = run_playback_cli(["--artifacts", str(tmp_path), "--include-frames"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS completion-tab" in captured.out
    assert "PASS escape-pending-steer" in captured.out
    assert "PASS running-follow-up-queued" in captured.out
    assert (tmp_path / "completion-tab.jsonl").exists()
    assert (tmp_path / "escape-pending-steer-text.txt").exists()
    assert (tmp_path / "running-steer-queued.jsonl").exists()
    assert (tmp_path / "escape-pending-steer-fifo-text.txt").exists()


def test_native_tui_playback_runner_reports_unknown_scenario(capsys) -> None:
    exit_code = run_playback_cli(["missing-scenario"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Unknown scenario: missing-scenario" in captured.err


def test_native_tui_playback_runner_reports_failed_scenario(tmp_path, capsys) -> None:
    def failing_run() -> None:
        raise AssertionError("forced failure")

    suite = NativePlaybackSuite(
        (
            NativePlaybackScenarioSpec(
                name="forced-failure",
                description="Fails for runner testing.",
                run=failing_run,
            ),
        )
    )

    results = run_playback_scenarios(
        ["forced-failure"],
        suite=suite,
        artifacts_dir=tmp_path,
    )

    assert len(results) == 1
    assert results[0].ok is False
    assert results[0].error == "forced failure"
    assert (tmp_path / "forced-failure-error.txt").read_text(encoding="utf-8") == "forced failure\n"


def test_native_tui_playback_runner_writes_failed_json_summary(tmp_path, capsys) -> None:
    def failing_run() -> None:
        raise AssertionError("forced failure")

    suite = NativePlaybackSuite(
        (
            NativePlaybackScenarioSpec(
                name="forced-failure",
                description="Fails for runner testing.",
                run=failing_run,
            ),
        )
    )

    exit_code = run_playback_cli(
        ["forced-failure", "--json", "--artifacts", str(tmp_path)],
        suite=suite,
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert captured.err == ""
    assert payload["ok"] is False
    assert payload["results"] == [
        {
            "name": "forced-failure",
            "ok": False,
            "elapsed_ms": payload["results"][0]["elapsed_ms"],
            "artifacts": [str(tmp_path / "forced-failure-error.txt")],
            "error": "forced failure",
        }
    ]


def test_native_tui_playback_runner_module_main_exits(monkeypatch) -> None:
    calls = []

    def fake_run_playback_cli(argv=None) -> int:
        calls.append(argv)
        return 7

    monkeypatch.setattr(playback_runner, "run_playback_cli", fake_run_playback_cli)

    try:
        playback_runner.main(["completion-tab"])
    except SystemExit as error:
        assert error.code == 7
    else:
        raise AssertionError("main should raise SystemExit")
    assert calls == [["completion-tab"]]


def test_native_tui_playback_runner_main_uses_process_argv(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["playback-runner", "completion-tab"])

    try:
        playback_runner.main()
    except SystemExit as error:
        assert error.code == 0
    else:
        raise AssertionError("main should raise SystemExit")

    captured = capsys.readouterr()
    assert "PASS completion-tab" in captured.out
    assert "long-transcript-input" not in captured.out


def test_native_tui_playback_runner_main_can_emit_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["playback-runner", "completion-tab", "--json"])

    try:
        playback_runner.main()
    except SystemExit as error:
        assert error.code == 0
    else:
        raise AssertionError("main should raise SystemExit")

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["results"][0]["name"] == "completion-tab"
    assert "PASS completion-tab" not in captured.out
