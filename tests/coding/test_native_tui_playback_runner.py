from __future__ import annotations

import json
import sys

from loushang.coding.ui import playback_runner
from loushang.coding.ui.playback_runner import (
    NativePlaybackScenarioSpec,
    NativePlaybackSuite,
    run_playback_cli,
    run_playback_scenarios,
)


def test_native_tui_playback_runner_lists_default_scenarios(capsys) -> None:
    exit_code = run_playback_cli(["--list"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "completion-tab" in captured.out
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
    assert "running-follow-up-queued" in captured.out
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


def test_native_tui_playback_runner_runs_lifecycle_scenario(capsys) -> None:
    exit_code = run_playback_cli(["running-steer-queued"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS running-steer-queued" in captured.out
    assert "PASS completion-tab" not in captured.out


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
