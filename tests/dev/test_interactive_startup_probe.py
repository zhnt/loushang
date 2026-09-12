"""Negative controls for the exploratory embedded frame observer."""

from __future__ import annotations

import sys

import pytest

if sys.platform != "linux":
    pytest.skip("Linux startup pilot", allow_module_level=True)

from tests.coding._interactive_startup_probe import (
    DRAFT,
    FRAME_END,
    ScheduledEdits,
    StartupWitnesses,
    frame_matches,
    wait_for_frame,
)

START = "\x1b[?2026h\x1b[H\x1b[2J"


def test_input_observer_cost_excludes_pre_input_first_frame(monkeypatch):
    from tests.coding import _interactive_startup_probe as module

    times = iter([0.0, 0.1, 1.0, 1.002, 1.003])
    monkeypatch.setattr(module.time, "perf_counter", lambda: next(times))
    witness = StartupWitnesses()
    first = START + "Welcome to Loushang CLI\r\n›\r\nLoading session" + FRAME_END
    witness.observe(first, 1.0)
    assert witness.input_frame_processing_seconds == 0
    witness.input_sent(first)
    witness.observe(first + START + "› " + DRAFT + FRAME_END, 2.0)
    assert witness.max_replay_seconds == pytest.approx(0.1)
    assert witness.max_input_frame_processing_seconds == pytest.approx(0.003)


def test_fixed_edit_observer_does_not_fill_missing_echo_with_later_edit():
    train = ScheduledEdits(lambda _: None, count=3)
    train.rows = [
        dict(token=f"{DRAFT}-{i:03d}", planned=float(i), sent=float(i), echo=None)
        for i in range(3)
    ]
    train.observe(f"› {DRAFT}-000\n\nLoading session", -1.0)
    train.observe(f"› {DRAFT}-000\n\nLoading session", 0.02)
    train.observe(f"› {DRAFT}-002\n\nLoading session", 2.05)
    report = train.report(1.5)
    assert report["missing_count"] == 1
    assert report["rows"][1]["echo"] is None
    assert report["mean_observed_echo_seconds"] == pytest.approx(0.035)
    assert report["spans_ready"]
    assert {
        key: value["count"] for key, value in report["by_observed_ready"].items()
    } == {
        "echo_before_observed_ready": 1,
        "pending_across_observed_ready": 1,
        "sent_after_observed_ready": 1,
    }
    assert not train.report(3.0)["spans_ready"]


def test_fixed_edit_observer_receives_all_coalesced_completed_frames():
    train = ScheduledEdits(lambda _: None, count=2)
    train.rows = [
        dict(token=f"{DRAFT}-{i:03d}", planned=0.0, sent=0.0, echo=None)
        for i in range(2)
    ]
    witness = StartupWitnesses()
    witness.on_frame = train.observe
    witness.observe(
        START
        + f"› {DRAFT}-000\r\n\r\nLoading session"
        + FRAME_END
        + START
        + f"› {DRAFT}-001\r\n\r\nLoading session"
        + FRAME_END,
        1.0,
    )
    assert [row["echo"] for row in train.rows] == [1.0, 1.0]


def test_fixed_sender_does_not_wait_for_echoes():
    writes = []
    train = ScheduledEdits(writes.append, count=3, interval=0.001)
    train.thread.start()
    train.thread.join(3)
    assert not train.thread.is_alive() and train.failure is None
    assert writes == ["00", "01", "02"]
    assert train.report(None)["missing_count"] == 3


def test_cumulative_edits_retain_prefix_evidence_across_wrapped_frame():
    train = ScheduledEdits(lambda _: None, count=2)
    prefix = DRAFT + "0" * (97 - len(DRAFT))
    train.rows = [
        dict(token=prefix, planned=0.0, sent=0.0, echo=None),
        dict(token=prefix + "01", planned=0.1, sent=0.1, echo=None),
    ]
    train.observe("› " + prefix + "\n  01\n\nLoading session", 0.2)
    assert train.last_echo_observed()
    assert train.report(0.05)["missing_count"] == 0


@pytest.mark.parametrize(
    "visible",
    [
        "› G18 draftQ7 00\n\nLoading session",
        "history › G18draftQ700\n› \n\nLoading session",
        "› G18draftQ7\n  00\n\nLoading session",
    ],
)
def test_edit_observer_rejects_spaces_history_and_non_wrapped_regions(visible):
    train = ScheduledEdits(lambda _: None, count=1)
    train.rows = [dict(token=DRAFT + "00", planned=0.0, sent=0.0, echo=None)]
    train.observe(visible, 1.0)
    assert not train.last_echo_observed()


def test_delayed_sender_start_is_counted_against_external_anchor(monkeypatch):
    from tests.coding import _interactive_startup_probe as module

    train = ScheduledEdits(lambda _: None, count=1, anchor=10.0)
    monkeypatch.setattr(module.time, "perf_counter", lambda: 20.0)
    train._send()
    report = train.report(None)
    assert report["max_pacing_lag_seconds"] == 10.0
    assert not report["sender_schedule_valid"]


def test_sender_write_failure_retains_attempt_and_unsent_count():
    def fail(_):
        raise OSError("injected write failure")

    train = ScheduledEdits(fail, count=3)
    train._send()
    report = train.report(None)
    assert report["attempted_count"] == 1
    assert report["sent_count"] == 0 and report["unsent_count"] == 3
    assert "injected write failure" in report["sender_failure"]
    assert len(report["rows"]) == 1 and report["rows"][0]["echo"] is None


@pytest.mark.parametrize("write_fails", [False, True])
def test_measure_initial_echo_failure_persists_train_and_joins_sender(
    monkeypatch, tmp_path, write_fails
):
    import json
    import termios
    from contextlib import contextmanager
    from pathlib import Path
    from threading import Event

    from tests.coding import _g18_native_probe as native
    from tests.coding import _interactive_startup_probe as module
    from tests.tui import terminal_process_support as terminal

    # The pilot is also executable as a script; its existing child helpers use
    # sibling imports from tests/coding when constructing the private environment.
    monkeypatch.syspath_prepend(str(Path(module.__file__).parent))
    wrote = Event()
    trains = []

    class Train(ScheduledEdits):
        def __init__(self, write, **kwargs):
            super().__init__(write, count=3, interval=0.01, **kwargs)
            trains.append(self)

    class Driver:
        _master_fd = 123
        raw_output = (
            START + "Welcome to Loushang CLI\r\n›\r\nLoading session" + FRAME_END
        )

        def write(self, text):
            if text != DRAFT:
                wrote.set()
                if write_fails:
                    raise OSError("injected sender write failure")

    @contextmanager
    def spawn(*args, **kwargs):
        yield Driver()

    @contextmanager
    def clock(*args):
        yield {"start": 0.0}

    waits = 0

    def wait(driver, predicate, **kwargs):
        nonlocal waits
        waits += 1
        if waits == 1:
            assert predicate(driver.raw_output)
            return driver.raw_output
        assert wrote.wait(1)
        raise TimeoutError("injected initial echo timeout")

    monkeypatch.setattr(module, "ScheduledEdits", Train)
    monkeypatch.setattr(module, "wait_for_frame", wait)
    monkeypatch.setattr(native, "observe_spawn", clock)
    monkeypatch.setattr(terminal, "spawn_terminal_process", spawn)
    monkeypatch.setattr(termios, "tcgetattr", lambda _: [0, 0, 0, 0])
    root = tmp_path / "initial-echo-failure"
    with pytest.raises(TimeoutError, match="initial echo timeout"):
        module.measure(root, Path.cwd(), Path(sys.executable), edit_train=True)
    report = json.loads((root / "report.json").read_text())
    assert report["status"] == "failed"
    assert report["error"] == "injected initial echo timeout"
    assert report["edit_train"]["rows"]
    assert "unsent_count" in report["edit_train"]
    assert all(not train.thread.is_alive() for train in trains)
    if write_fails:
        assert report["edit_train"]["unsent_count"] == 3
        assert "injected sender write failure" in report["edit_train"]["sender_failure"]


def test_frame_predicate_runs_outside_terminal_reader_lock():
    class Driver:
        raw_output = ""
        locked = False

        def read_until(self, predicate, *, timeout):
            assert timeout > 0
            self.locked = True
            try:
                self.raw_output = START + "ready" + FRAME_END
                assert predicate(self.raw_output)
            finally:
                self.locked = False

    driver = Driver()

    def rendered(output):
        assert not driver.locked
        return output.endswith(FRAME_END)

    assert wait_for_frame(driver, rendered, timeout=1) == driver.raw_output


def test_observation_rejects_saturated_terminal_buffer():
    class Driver:
        raw_output = "x" * 1_000_000

    with pytest.raises(ValueError, match="observation bound"):
        wait_for_frame(Driver(), lambda _: True, timeout=1)


def test_readiness_is_recorded_before_echo_without_sequential_wait_bias():
    witness = StartupWitnesses()
    welcome = START + "Welcome to Loushang CLI\r\n›\r\nLoading session" + FRAME_END
    witness.observe(welcome, 1.0)
    witness.input_sent(welcome)
    ready = welcome + START + "›\r\nmodel | idle" + FRAME_END
    witness.observe(ready, 2.0)
    assert witness.ready == 2.0 and witness.echo is None
    echoed = ready + START + "› " + DRAFT + "\r\nmodel | idle" + FRAME_END
    witness.observe(echoed, 3.0)
    witness.observe(echoed, 9.0)
    assert (witness.first_frame, witness.ready, witness.echo) == (1.0, 2.0, 3.0)


def test_coalesced_frames_keep_earlier_witness_but_latest_visible_state():
    witness = StartupWitnesses()
    first = START + "Welcome to Loushang CLI\r\n›\r\nmodel | idle" + FRAME_END
    latest = START + "›\r\nLoading session" + FRAME_END
    witness.observe(first + latest, 4.0)
    assert witness.first_frame == witness.ready == 4.0
    assert "Loading session" in witness.visible


def test_incremental_frames_equal_full_replay_with_scroll_and_cursor_state():
    from tests.coding._g18_native_probe import _replay_embedded_output

    pieces = (
        START + "\x1b[31mWelcome to Loushang CLI\r\n›" + FRAME_END,
        "\x1b[?2026h\x1b[2;4r\x1b[4;1Htail\r\nnext" + FRAME_END,
        "\x1b[?2026h\x1b[r\x1b[2;1H\x1b[2K› draft" + FRAME_END,
        START + "›\r\nmodel | idle" + FRAME_END,
    )
    witness = StartupWitnesses()
    output = ""
    for index, piece in enumerate(pieces):
        output += piece
        witness.observe(output, float(index))
        expected = _replay_embedded_output(output)
        assert witness._screen == expected
    assert witness.frames == len(pieces)


def test_partial_delimiter_and_pre_input_draft_cannot_manufacture_echo():
    witness = StartupWitnesses()
    old = START + "› " + FRAME_END
    witness.observe(old, 1.0)
    witness.input_sent(old)
    partial = old + START + "› " + DRAFT + FRAME_END[:-1]
    witness.observe(partial, 2.0)
    assert witness.echo is None
    witness.observe(partial + FRAME_END[-1], 3.0)
    assert witness.echo == 3.0
    with pytest.raises(ValueError, match="only be sent once"):
        witness.input_sent(partial)
    with pytest.raises(ValueError, match="retain its prefix"):
        witness.observe("", 4.0)


def test_old_draft_cannot_become_a_new_echo_in_an_unrelated_frame():
    witness = StartupWitnesses()
    old = START + "› " + DRAFT + FRAME_END
    witness.observe(old, 1.0)
    with pytest.raises(ValueError, match="already exists"):
        witness.input_sent(old)
    witness.observe(old + "\x1b[?2026h" + FRAME_END, 2.0)
    assert witness.echo is None


def test_partial_frame_and_kernel_echo_are_not_composer_witnesses():
    assert not frame_matches(DRAFT, DRAFT)
    assert not frame_matches(START + "› " + DRAFT, "› " + DRAFT)
    assert frame_matches(START + "› " + DRAFT + FRAME_END, "› " + DRAFT)


def test_pre_input_idle_is_not_new_frame_evidence():
    old = START + "› \r\nmodel | idle" + FRAME_END
    assert not frame_matches(old + DRAFT, " | idle", after=len(old))


def test_erased_history_is_not_visible_draft():
    old = START + "› " + DRAFT + FRAME_END
    new = START + "› \r\nLoading session" + FRAME_END
    assert not frame_matches(old + new, "› " + DRAFT)
    assert frame_matches(old + new, "Loading session", after=len(old))


def test_status_replaced_by_loading_is_not_ready():
    old = START + "› \r\nmodel | idle" + FRAME_END
    new = START + "› \r\nLoading session" + FRAME_END
    assert not frame_matches(old + new, " | idle")


def test_scroll_region_changes_are_replayed_not_stripped():
    from tests.coding._g18_native_probe import _replay_embedded_output

    screen = _replay_embedded_output("\x1b[2;4r\x1b[4;1Htail\r\nnext")
    assert screen.visible_lines[2].startswith("tail")
    assert screen.visible_lines[3].startswith("next")
    reset = _replay_embedded_output("\x1b[2;4r\x1b[4;1Hx\x1b[rhome")
    assert reset.visible_lines[0].startswith("home")
    assert reset.scroll_top == 0 and reset.scroll_bottom is None


@pytest.mark.parametrize("sequence", ["\x1b[3;2r", "\x1b[1;31r", "\x1b[?3r"])
def test_unknown_scroll_margins_fail_closed(sequence):
    from tests.coding._g18_native_probe import _replay_embedded_output

    with pytest.raises(ValueError, match="scroll margins"):
        _replay_embedded_output(sequence)
