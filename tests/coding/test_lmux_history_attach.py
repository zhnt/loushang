"""Warm history attach orchestration, not installed performance evidence."""

from contextlib import contextmanager

import pytest

from . import _lmux_product_probe as probe


@pytest.mark.parametrize("fault", [None, "history", "completion", "exit", "close", "read", "native", "member", "workspace"])
def test_history_attach_settles_terminal_before_authenticated_read(tmp_path, monkeypatch, fault):
    from loushang.hosting.service import LinuxServiceIdentityV1

    native = LinuxServiceIdentityV1(123, 100, "12345678-1234-1234-1234-123456789abc", 1000, 4, 5)
    target = {"instanceId": "instance", "serviceId": "service", "muxId": "mux", "members": []}
    events, reads, writes = [], [], []

    class Driver:
        raw_output = ""
        diagnostics = "unexpected terminal exit"

        def read_until(self, predicate, **kwargs):
            phase = ("history", "completion")[len(reads)]
            reads.append(phase)
            if fault == phase:
                raise TimeoutError(phase)

        def write(self, text):
            writes.append(text)

        def wait(self, **kwargs):
            return 1 if fault == "exit" else 0

    @contextmanager
    def terminal(argv, cwd, environment, **kwargs):
        assert argv == [str(tmp_path / "install/bin/lmux"), "attach", "-t", "perf"]
        assert cwd == tmp_path / "elsewhere"
        if fault == "workspace":
            (cwd / "unexpected").mkdir()
        try:
            yield Driver(), None, None
        finally:
            events.append("closed")
            if fault == "close":
                raise OSError("terminal cleanup failed")

    @contextmanager
    def spawn(executable):
        yield {"start": 1.0}

    def observe(environment, expected, identity, *, native_identity):
        assert events == ["closed"] and expected == target and identity == {"session_id": "seed"}
        events.append("read")
        if fault == "read":
            raise OSError("authenticated read failed")
        native_identity.append(object() if fault == "native" else native)
        return {**target, "members": ["different"]} if fault == "member" else target

    monkeypatch.setattr(probe, "observed_terminal", terminal)
    monkeypatch.setattr(probe, "observe_spawn", spawn)
    monkeypatch.setattr(probe, "assert_active_terminal", lambda *args: None)
    monkeypatch.setattr(probe, "managed_history_confirmation", observe)
    report = {"measured_prefix": str(tmp_path / "install")}
    if fault is None:
        clock = iter([4.0, 5.0, 7.0])
        monkeypatch.setattr(probe.time, "perf_counter", lambda: next(clock))
        result = probe._history_attach(tmp_path, report, {}, target, [native], {"session_id": "seed"})
        assert result["history_frame_seconds"] == 3.0
        assert result["history_completion_seconds"] == 2.0
        assert result["detached"] == target
        assert list(report["fixed_product_native"]) == ["history-detached"]
        assert writes == ["/he", "\x7f\x7f\x7f", "\x02d"]
    else:
        with pytest.raises((TimeoutError, OSError, AssertionError)):
            probe._history_attach(tmp_path, report, {}, target, [native], {"session_id": "seed"})
        assert "fixed_product_native" not in report
    assert events.count("closed") == 1
    assert events.count("read") == (0 if fault in {"history", "completion", "exit", "close"} else 1)
    assert writes.count("/he") <= 1 and writes.count("\x02d") <= 1
