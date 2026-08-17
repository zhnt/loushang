from __future__ import annotations

import json
import sys

import pytest

from loushang.tui import (
    FakeTerminalPort,
    PlaybackEvent,
    PlaybackHarness,
    PlaybackResult,
    RenderDiagnostics,
    TerminalOperation,
    TerminalSize,
)
from loushang.tui.playback_suite import PlaybackSuite as SuiteFromModule
from tests.coding.tui_support import runner as playback_runner
from tests.coding.tui_support.fakes import SessionCommandPlaybackSession
from tests.coding.tui_support.runner import (
    ScreenPlaybackScenarioSpec,
    ScreenPlaybackSuite,
    run_playback_cli,
    run_playback_scenarios,
)
from tests.coding.tui_support.scenarios.command import COMMAND_ROUTING_SCENARIOS
from tests.coding.tui_support.scenarios.composer import COMPOSER_SCENARIOS
from tests.coding.tui_support.scenarios.lifecycle import LIFECYCLE_SCENARIOS
from tests.coding.tui_support.scenarios.multiagent import MULTIAGENT_SCENARIOS
from tests.coding.tui_support.scenarios.permissions import PERMISSION_SCENARIOS
from tests.coding.tui_support.scenarios.product import PRODUCT_SCENARIOS
from tests.coding.tui_support.scenarios.surface import SURFACE_SCENARIOS
from tests.coding.tui_support.scenarios.terminal import TERMINAL_SCENARIOS
from tests.coding.tui_support.scenarios.transcript import TRANSCRIPT_SCENARIOS


def test_screen_tui_playback_runner_reexports_suite_types_from_playback_suite_module() -> (
    None
):
    assert ScreenPlaybackSuite is SuiteFromModule


def test_screen_tui_playback_runner_help_names_canonical_module(capsys) -> None:
    with pytest.raises(SystemExit, match="0"):
        run_playback_cli(["--help"])

    captured = capsys.readouterr()
    assert "scripts/run_tui_playback.py" in captured.out


def test_screen_tui_playback_fake_session_lists_command_sources() -> None:
    session = SessionCommandPlaybackSession()

    commands = session.list_commands()

    assert [(command.name, command.source) for command in commands] == [
        ("rename", "builtin"),
        ("export", "builtin"),
        ("review", "prompt"),
        ("debugging", "skill"),
    ]


def test_screen_tui_playback_command_scenarios_live_in_command_module() -> None:
    assert [scenario.name for scenario in COMMAND_ROUTING_SCENARIOS] == [
        "local-command",
        "session-rename-command",
        "session-command-error",
        "unknown-slash-prompt",
        "non-executable-session-command",
    ]


def test_screen_tui_playback_composer_scenarios_live_in_composer_module() -> None:
    assert [scenario.name for scenario in COMPOSER_SCENARIOS] == [
        "completion-tab",
        "completion-session-command",
        "completion-navigation-priority",
        "completion-escape-cancel",
        "completion-prefix-refresh",
        "completion-enter-submits-command",
        "history-navigation",
        "bracketed-paste-large-marker",
        "resize-reflow-stable",
        "wide-char-input-cursor",
        "keyboard-shift-enter-newline",
        "editor-key-editing",
        "page-navigation",
        "paste-marker-delete-undo",
        "composer-selection-replace",
        "composer-selection-stress",
    ]


def test_screen_tui_playback_surface_scenarios_live_in_surface_module() -> None:
    assert [scenario.name for scenario in SURFACE_SCENARIOS] == [
        "active-surface",
        "command-palette-select",
        "command-palette-session-command",
        "commands-info-surface",
        "commands-info-session-command",
        "settings-search",
        "model-select",
        "model-select-search",
        "approval-surface",
        "approval-session-surface",
        "approval-reject-surface",
        "approval-abort-surface",
        "approval-persistent-surface",
        "permissions-reopen-revoke-surface",
        "permissions-mode-surface",
        "permissions-full-access-confirmation",
        "dialog-surface",
        "mouse-select-active-surface",
    ]


def test_screen_tui_playback_lifecycle_scenarios_live_in_lifecycle_module() -> None:
    assert [scenario.name for scenario in LIFECYCLE_SCENARIOS] == [
        "idle-escape-clears-draft",
        "running-steer-queued",
        "running-escape-keeps-queued-steer",
        "idle-escape-pops-pending-steer",
        "escape-pending-steer",
        "escape-pending-steer-fifo",
        "escape-pending-steer-preserves-draft",
        "screen-loop-ctrl-c-abort-running",
        "running-follow-up-queued",
        "keyboard-alt-enter-follow-up",
    ]


def test_screen_tui_playback_multiagent_scenarios_are_layered() -> None:
    assert [scenario.name for scenario in MULTIAGENT_SCENARIOS] == [
        "multiagent-tools",
        "multiagent-messaging",
        "multiagent-followup",
        "multiagent-nested-tree",
        "multiagent-lifecycle",
        "multiagent-quota-recovery",
        "multiagent-parallel-review",
        "multiagent-debate",
        "multiagent-shared-workspace",
        "multiagent-isolated-artifact",
        "multiagent-shared-parallel-writers",
        "multiagent-child-approval",
        "multiagent-concurrent-child-approval",
        "multiagent-render",
    ]


def test_screen_tui_playback_permission_scenarios_are_layered() -> None:
    assert [scenario.name for scenario in PERMISSION_SCENARIOS] == [
        "permission-behavior-matrix",
    ]


def test_screen_tui_playback_runs_permission_behavior_matrix(tmp_path) -> None:
    results = run_playback_scenarios(
        ["permission-behavior-matrix"],
        artifacts_dir=tmp_path,
    )

    assert [result.ok for result in results] == [True]
    rows = [
        json.loads(line)
        for line in (tmp_path / "permission-behavior-matrix-events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert any(
        row["layer"] == "behavior"
        and row["data"]["name"] == "child-delegated-ceiling"
        and row["data"]["outcome"] == "contained"
        for row in rows
    )
    assert any(
        row["layer"] == "gateway"
        and row["event"] == "tool_execution_failed"
        and row["data"]["phase"] == "pre_execution"
        for row in rows
    )


def test_screen_tui_playback_runs_multiagent_topology_matrix(tmp_path) -> None:
    names = [
        "multiagent-followup",
        "multiagent-nested-tree",
        "multiagent-lifecycle",
        "multiagent-quota-recovery",
        "multiagent-parallel-review",
        "multiagent-debate",
        "multiagent-shared-workspace",
        "multiagent-isolated-artifact",
        "multiagent-shared-parallel-writers",
    ]

    results = run_playback_scenarios(
        names,
        artifacts_dir=tmp_path,
    )

    assert [result.ok for result in results] == [True] * len(names)
    for name in names:
        rows = [
            json.loads(line)
            for line in (tmp_path / f"{name}-events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert any(row["layer"] == "topology" for row in rows)


def test_screen_tui_playback_runner_writes_layered_multiagent_diagnostics(
    tmp_path,
) -> None:
    results = run_playback_scenarios(
        [
            "multiagent-tools",
            "multiagent-messaging",
            "multiagent-render",
        ],
        artifacts_dir=tmp_path,
        include_frames=True,
    )

    assert [result.ok for result in results] == [True, True, True]
    messaging_rows = [
        json.loads(line)
        for line in (tmp_path / "multiagent-messaging-events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    classifications = [
        row
        for row in messaging_rows
        if row["event"] == "completion.classified"
    ]
    assert classifications == [
        {
            "sequence": 29,
            "layer": "projection",
            "event": "completion.classified",
            "data": {
                "expected_channel": "system_mailbox",
                "actual_channel": "system_mailbox",
                "editable": False,
                "triggers_queue_preview": False,
                "verdict": "correct_input_boundary",
            },
        }
    ]
    render_rows = [
        json.loads(line)
        for line in (tmp_path / "multiagent-render-render.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert render_rows
    render_events = [
        json.loads(line)
        for line in (tmp_path / "multiagent-render-events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    queue_syncs = [row for row in render_events if row["event"] == "queue.synced"]
    assert len(queue_syncs) == 3
    assert all(row["data"]["pending_followups"] == [] for row in queue_syncs)
    assert all(row["data"]["pending_steers"] == [] for row in queue_syncs)
    final_screen = (tmp_path / "multiagent-render-screen.txt").read_text(
        encoding="utf-8"
    )
    assert "Queued follow-up inputs" not in final_screen
    assert "queued=" not in final_screen
    assert "/root/random-1 completed (round 1)." not in final_screen
    assert "/root/random-2 completed (round 1)." not in final_screen
    assert "/root/random-3 completed (round 1)." not in final_screen


def test_screen_tui_playback_product_scenarios_live_in_product_module() -> None:
    assert [scenario.name for scenario in PRODUCT_SCENARIOS] == [
        "product-composed-interaction",
        "product-streaming-control-flow",
    ]


def test_screen_tui_playback_terminal_scenarios_live_in_terminal_module() -> None:
    assert [scenario.name for scenario in TERMINAL_SCENARIOS] == [
        "screen-loop-split-bracketed-paste",
        "terminal-control-response-hidden",
        "screen-loop-terminal-session-cleanup",
        "apple-shift-enter-normalized",
    ]


def test_screen_tui_playback_transcript_scenarios_live_in_transcript_module() -> None:
    assert [scenario.name for scenario in TRANSCRIPT_SCENARIOS] == [
        "long-transcript-input",
        "tool-output-preview",
        "transcript-reader-modal",
        "transcript-reader-copy-command",
        "transcript-reader-live-draft",
        "transcript-reader-render-modes",
        "transcript-reader-search",
    ]


def test_screen_tui_playback_runner_lists_default_scenarios(capsys) -> None:
    exit_code = run_playback_cli(["--list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "completion-tab" in captured.out
    assert "completion-session-command" in captured.out
    assert "completion-navigation-priority" in captured.out
    assert "completion-escape-cancel" in captured.out
    assert "completion-prefix-refresh" in captured.out
    assert "completion-enter-submits-command" in captured.out
    assert "history-navigation" in captured.out
    assert "idle-escape-clears-draft" in captured.out
    assert "long-transcript-input" in captured.out
    assert "transcript-reader-modal" in captured.out
    assert "transcript-reader-copy-command" in captured.out
    assert "transcript-reader-live-draft" in captured.out
    assert "transcript-reader-render-modes" in captured.out
    assert "transcript-reader-search" in captured.out
    assert "escape-pending-steer" in captured.out
    assert "running-steer-queued" in captured.out
    assert "running-escape-keeps-queued-steer" in captured.out
    assert "idle-escape-pops-pending-steer" in captured.out
    assert "escape-pending-steer-fifo" in captured.out
    assert "escape-pending-steer-preserves-draft" in captured.out
    assert "session-rename-command" in captured.out
    assert "session-command-error" in captured.out
    assert "unknown-slash-prompt" in captured.out
    assert "non-executable-session-command" in captured.out
    assert "running-follow-up-queued" in captured.out
    assert "command-palette-select" in captured.out
    assert "command-palette-session-command" in captured.out
    assert "commands-info-surface" in captured.out
    assert "commands-info-session-command" in captured.out
    assert "settings-search" in captured.out
    assert "model-select" in captured.out
    assert "model-select-search" in captured.out
    assert "approval-surface" in captured.out
    assert "approval-session-surface" in captured.out
    assert "approval-reject-surface" in captured.out
    assert "approval-abort-surface" in captured.out
    assert "approval-persistent-surface" in captured.out
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
    assert "screen-loop-split-bracketed-paste" in captured.out
    assert "screen-loop-terminal-session-cleanup" in captured.out
    assert "screen-loop-ctrl-c-abort-running" in captured.out
    assert "product-composed-interaction" in captured.out
    assert "product-streaming-control-flow" in captured.out
    assert "multiagent-tools" in captured.out
    assert "multiagent-messaging" in captured.out
    assert "multiagent-render" in captured.out


def test_screen_tui_playback_runner_runs_named_scenario(capsys) -> None:
    exit_code = run_playback_cli(["completion-tab"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS completion-tab" in captured.out
    assert "long-transcript-input" not in captured.out


def test_screen_tui_playback_runner_runs_child_approval_scenario(capsys) -> None:
    exit_code = run_playback_cli(["multiagent-child-approval"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS multiagent-child-approval" in captured.out


def test_screen_tui_playback_runner_runs_concurrent_child_approval_scenario(
    capsys,
) -> None:
    exit_code = run_playback_cli(["multiagent-concurrent-child-approval"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS multiagent-concurrent-child-approval" in captured.out


def test_screen_tui_playback_runner_runs_tagged_command_scenarios(capsys) -> None:
    exit_code = run_playback_cli(["--tag", "command"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS session-rename-command" in captured.out
    assert "PASS command-palette-session-command" in captured.out
    assert "PASS commands-info-session-command" in captured.out
    assert "PASS model-select" not in captured.out
    assert "PASS long-transcript-input" not in captured.out


@pytest.mark.tui_render_contract
def test_screen_tui_playback_runner_runs_tagged_product_scenarios(capsys) -> None:
    exit_code = run_playback_cli(["--tag", "product"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS product-composed-interaction" in captured.out
    assert "PASS product-streaming-control-flow" in captured.out
    assert "PASS completion-tab" not in captured.out


def test_screen_tui_playback_runner_lists_tagged_command_scenarios(capsys) -> None:
    exit_code = run_playback_cli(["--list", "--tag", "command"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "session-rename-command" in captured.out
    assert "command-palette-session-command" in captured.out
    assert "model-select" not in captured.out
    assert "long-transcript-input" not in captured.out


def test_screen_tui_playback_runner_runs_completion_session_command_scenario(
    capsys,
) -> None:
    exit_code = run_playback_cli(["completion-session-command"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS completion-session-command" in captured.out


def test_screen_tui_playback_runner_runs_completion_detail_scenarios(capsys) -> None:
    exit_code = run_playback_cli(
        [
            "completion-escape-cancel",
            "completion-prefix-refresh",
            "completion-enter-submits-command",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS completion-escape-cancel" in captured.out
    assert "PASS completion-prefix-refresh" in captured.out
    assert "PASS completion-enter-submits-command" in captured.out


def test_screen_tui_playback_runner_runs_composer_selection_scenario(capsys) -> None:
    exit_code = run_playback_cli(["composer-selection-replace"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS composer-selection-replace" in captured.out


def test_screen_tui_playback_runner_runs_composer_selection_stress_scenario(
    capsys,
) -> None:
    exit_code = run_playback_cli(["composer-selection-stress"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS composer-selection-stress" in captured.out


def test_screen_tui_playback_runner_runs_transcript_reader_scenario(capsys) -> None:
    exit_code = run_playback_cli(["transcript-reader-modal"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS transcript-reader-modal" in captured.out


def test_screen_tui_playback_runner_runs_transcript_reader_copy_scenario(
    capsys,
) -> None:
    exit_code = run_playback_cli(["transcript-reader-copy-command"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS transcript-reader-copy-command" in captured.out


def test_screen_tui_playback_runner_runs_transcript_reader_live_draft_scenario(
    capsys,
) -> None:
    exit_code = run_playback_cli(["transcript-reader-live-draft"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS transcript-reader-live-draft" in captured.out


def test_screen_tui_playback_runner_runs_transcript_reader_render_modes_scenario(
    capsys,
) -> None:
    exit_code = run_playback_cli(["transcript-reader-render-modes"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS transcript-reader-render-modes" in captured.out


def test_screen_tui_playback_runner_runs_transcript_reader_search_scenario(
    capsys,
) -> None:
    exit_code = run_playback_cli(["transcript-reader-search"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS transcript-reader-search" in captured.out


def test_screen_tui_playback_runner_runs_product_composed_interaction_scenario(
    capsys,
) -> None:
    exit_code = run_playback_cli(["product-composed-interaction"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS product-composed-interaction" in captured.out


def test_screen_tui_playback_runner_runs_product_streaming_control_flow_scenario(
    capsys,
) -> None:
    exit_code = run_playback_cli(["product-streaming-control-flow"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS product-streaming-control-flow" in captured.out


def test_screen_tui_playback_runner_runs_lifecycle_scenario(capsys) -> None:
    exit_code = run_playback_cli(["running-steer-queued"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS running-steer-queued" in captured.out
    assert "PASS completion-tab" not in captured.out


def test_screen_tui_playback_runner_runs_session_name_command_scenario(capsys) -> None:
    exit_code = run_playback_cli(["session-rename-command"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS session-rename-command" in captured.out


def test_screen_tui_playback_runner_runs_session_command_error_scenario(capsys) -> None:
    exit_code = run_playback_cli(["session-command-error"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS session-command-error" in captured.out


def test_screen_tui_playback_runner_runs_unknown_slash_prompt_scenario(capsys) -> None:
    exit_code = run_playback_cli(["unknown-slash-prompt"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS unknown-slash-prompt" in captured.out


def test_screen_tui_playback_runner_runs_non_executable_session_command_scenario(
    capsys,
) -> None:
    exit_code = run_playback_cli(["non-executable-session-command"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS non-executable-session-command" in captured.out


def test_screen_tui_playback_runner_runs_settings_search_scenario(capsys) -> None:
    exit_code = run_playback_cli(["settings-search"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS settings-search" in captured.out


def test_screen_tui_playback_runner_runs_info_surface_scenarios(capsys) -> None:
    exit_code = run_playback_cli(["commands-info-surface"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS commands-info-surface" in captured.out


def test_screen_tui_playback_runner_runs_commands_info_session_command_scenario(
    capsys,
) -> None:
    exit_code = run_playback_cli(["commands-info-session-command"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS commands-info-session-command" in captured.out


def test_screen_tui_playback_runner_runs_command_palette_select_scenario(
    capsys,
) -> None:
    exit_code = run_playback_cli(["command-palette-select"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS command-palette-select" in captured.out


def test_screen_tui_playback_runner_runs_command_palette_session_command_scenario(
    capsys,
) -> None:
    exit_code = run_playback_cli(["command-palette-session-command"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS command-palette-session-command" in captured.out


def test_screen_tui_playback_runner_runs_model_select_scenario(capsys) -> None:
    exit_code = run_playback_cli(["model-select"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS model-select" in captured.out


def test_screen_tui_playback_runner_runs_model_select_search_scenario(capsys) -> None:
    exit_code = run_playback_cli(["model-select-search"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS model-select-search" in captured.out


def test_screen_tui_playback_runner_runs_approval_surface_scenario(capsys) -> None:
    exit_code = run_playback_cli(["approval-surface"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS approval-surface" in captured.out


def test_screen_tui_playback_runner_runs_approval_session_surface_scenario(
    capsys,
) -> None:
    exit_code = run_playback_cli(["approval-session-surface"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS approval-session-surface" in captured.out


def test_screen_tui_playback_runner_runs_approval_reject_surface_scenario(
    capsys,
) -> None:
    exit_code = run_playback_cli(["approval-reject-surface"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS approval-reject-surface" in captured.out


def test_screen_tui_playback_runner_runs_approval_abort_surface_scenario(
    capsys,
) -> None:
    exit_code = run_playback_cli(["approval-abort-surface"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS approval-abort-surface" in captured.out


def test_screen_tui_playback_runner_runs_approval_persistent_surface_scenario(
    capsys,
) -> None:
    exit_code = run_playback_cli(["approval-persistent-surface"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS approval-persistent-surface" in captured.out


def test_screen_tui_playback_runner_runs_dialog_surface_scenario(capsys) -> None:
    exit_code = run_playback_cli(["dialog-surface"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS dialog-surface" in captured.out


def test_screen_tui_playback_runner_writes_artifacts(tmp_path, capsys) -> None:
    exit_code = run_playback_cli(
        ["completion-tab", "--artifacts", str(tmp_path), "--include-frames"]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS completion-tab" in captured.out
    assert (tmp_path / "completion-tab.jsonl").exists()
    assert (tmp_path / "completion-tab-screen.txt").exists()
    row = json.loads(
        (tmp_path / "completion-tab.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert "visible_lines" in row


def test_screen_tui_playback_runner_writes_json_summary(tmp_path, capsys) -> None:
    exit_code = run_playback_cli(
        ["completion-tab", "--json", "--artifacts", str(tmp_path)]
    )

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
                    str(tmp_path / "completion-tab-terminal.txt"),
                ],
                "elapsed_ms": payload["results"][0]["elapsed_ms"],
            }
        ],
    }
    assert payload["results"][0]["elapsed_ms"] >= 0
    assert "PASS completion-tab" not in captured.out


def test_screen_tui_playback_runner_writes_artifacts_for_all_default_scenarios(
    tmp_path, capsys
) -> None:
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


def test_screen_tui_playback_runner_reports_unknown_scenario(capsys) -> None:
    exit_code = run_playback_cli(["missing-scenario"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Unknown scenario: missing-scenario" in captured.err


def test_screen_tui_playback_runner_reports_failed_scenario(tmp_path, capsys) -> None:
    def failing_run() -> None:
        raise AssertionError("forced failure")

    suite = ScreenPlaybackSuite(
        (
            ScreenPlaybackScenarioSpec(
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
    assert (tmp_path / "forced-failure-error.txt").read_text(
        encoding="utf-8"
    ) == "forced failure\n"


def test_screen_tui_playback_runner_writes_review_artifacts_for_playback_failure(
    tmp_path,
) -> None:
    def failing_run() -> None:
        result = _single_frame_result("reviewable failure frame")
        error = AssertionError("forced review failure")
        error.playback_result = result
        raise error

    suite = ScreenPlaybackSuite(
        (
            ScreenPlaybackScenarioSpec(
                name="forced-review-failure",
                description="Fails after producing playback frames.",
                run=failing_run,
            ),
        )
    )

    results = run_playback_scenarios(
        ["forced-review-failure"],
        suite=suite,
        artifacts_dir=tmp_path,
        include_frames=True,
    )

    assert len(results) == 1
    assert results[0].ok is False
    assert results[0].error == "forced review failure"
    assert [path.name for path in results[0].artifacts] == [
        "forced-review-failure-error.txt",
        "forced-review-failure.jsonl",
        "forced-review-failure-screen.txt",
        "forced-review-failure-terminal.txt",
    ]
    assert "forced review failure" in (
        tmp_path / "forced-review-failure-error.txt"
    ).read_text(encoding="utf-8")
    assert "reviewable failure frame" in (
        tmp_path / "forced-review-failure-screen.txt"
    ).read_text(encoding="utf-8")
    row = json.loads(
        (tmp_path / "forced-review-failure.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert row["visible_lines"][0] == "reviewable failure frame"
    assert row["serialized_output"] == "reviewable failure frame"


def test_screen_tui_playback_runner_writes_failed_json_summary(
    tmp_path, capsys
) -> None:
    def failing_run() -> None:
        raise AssertionError("forced failure")

    suite = ScreenPlaybackSuite(
        (
            ScreenPlaybackScenarioSpec(
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


def test_screen_tui_playback_runner_module_main_exits(monkeypatch) -> None:
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


def test_screen_tui_playback_runner_main_uses_process_argv(monkeypatch, capsys) -> None:
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


def test_screen_tui_playback_runner_main_can_emit_json(monkeypatch, capsys) -> None:
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


def _single_frame_result(text: str) -> PlaybackResult:
    def render(
        _event: PlaybackEvent,
        _size: TerminalSize,
        _previous: RenderDiagnostics | None,
    ) -> RenderDiagnostics:
        return RenderDiagnostics(
            current_logical_lines=(text,),
            changed_line_range=(0, 0),
            logical_cursor_row=0,
            hardware_cursor_row=0,
            operations=(TerminalOperation.write(text),),
        )

    port = FakeTerminalPort(size=TerminalSize(columns=80, rows=4))
    harness = PlaybackHarness(render=render, port=port)
    return PlaybackResult(steps=harness.play([PlaybackEvent("render")]), port=port)
