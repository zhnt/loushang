from __future__ import annotations

from loushang.harnesstui.status.line import StatusLineSettings
from loushang.harnesstui.status.snapshot import StatusSnapshot


def test_status_snapshot_preserves_neutral_status_facts() -> None:
    snapshot = StatusSnapshot(
        model_label="moonshot/kimi-for-coding",
        cwd="/repo",
        branch="main",
        session_label="abcd",
        thinking_level="high",
        running=True,
        statusline_visible=False,
    )

    assert snapshot.model_label == "moonshot/kimi-for-coding"
    assert snapshot.cwd == "/repo"
    assert snapshot.branch == "main"
    assert snapshot.session_label == "abcd"
    assert snapshot.thinking_level == "high"
    assert snapshot.running is True
    assert snapshot.statusline_visible is False
    assert snapshot.statusline_settings == StatusLineSettings()
