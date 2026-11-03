"""Fresh scenario sequencing only; not a substitute for installed evidence."""

import stat
import sys

import pytest

from . import _lmux_product_probe as probe

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed measurement composition")


def test_fresh_scenarios_project_distinct_platform_and_runtime_roots(tmp_path, monkeypatch):
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "ambient-platform"))
    monkeypatch.setenv("LOUSHANG_RUNTIME_DIR", str(tmp_path / "ambient-runtime"))
    environments = [probe._terminal_environment(tmp_path / name)
                    for name in ("reply", "approval", "interrupt")]
    for name, environment in zip(("reply", "approval", "interrupt"), environments, strict=True):
        assert environment["LOUSHANG_HOME"] == str(tmp_path / name / "platform")
        assert environment["LOUSHANG_RUNTIME_DIR"] == str(tmp_path / name / "runtime")
    assert len({item["LOUSHANG_HOME"] for item in environments}) == 3
    assert len({item["LOUSHANG_RUNTIME_DIR"] for item in environments}) == 3
    assert list(tmp_path.iterdir()) == []  # Projection alone must not create state.


@pytest.mark.parametrize("failure", [None, "reply", "approval", "interrupt"])
def test_first_use_runs_fresh_scenarios_in_order_and_stops_after_failure(tmp_path, monkeypatch, failure):
    calls = []

    def scenario(root, report, **options):
        name = root.name
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
        assert report["valid"] is False and report["status"] == "running"
        assert report["measured_prefix"] == "fixed-install"
        assert options == ({"tool_approval": True} if name == "approval" else
                           {"delayed_final": True, "interrupt_next_turn": True} if name == "interrupt" else {})
        calls.append(name)
        if name == failure:
            raise RuntimeError("original owner cleanup failed")
        timing = {"actions": {"fixed_entry_through_visible_reply" if name == "reply" else "next_reply":
                              {"started_at": 1.0, "finished_at": 3.0}},
                  "spawn_through_visible_reply_seconds" if name == "reply" else "next_reply_seconds": 2.0}
        key = {"reply": "fixed_product_first_reply", "approval": "fixed_product_tool_approval",
               "interrupt": "fixed_product_interrupt_next_turn"}[name]
        report[key] = {"next_turn": timing} if name == "interrupt" else timing

    monkeypatch.setattr(probe, "first_reply", scenario)
    report = {"measured_prefix": "fixed-install", "valid": False}
    if failure:
        with pytest.raises(RuntimeError):
            probe.first_use(tmp_path, report)
        assert calls == ["reply", "approval", "interrupt"][:["reply", "approval", "interrupt"].index(failure) + 1]
        assert report["fixed_product_scenarios"][failure]["status"] == "failed"
    else:
        probe.first_use(tmp_path, report)
        assert calls == ["reply", "approval", "interrupt"]
        assert report["fixed_product_scenarios"]["reply"]["milestones"] == {
            "fixed_entry_through_visible_reply_seconds": 2.0,
        }
        previous = 0.0
        for child in report["fixed_product_scenarios"].values():
            assert previous <= child["started_at"] <= child["finished_at"]
            previous = child["finished_at"]
    assert report["valid"] is False
    assert all(child["valid"] is False for child in report["fixed_product_scenarios"].values())
