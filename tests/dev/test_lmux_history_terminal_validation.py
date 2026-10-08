"""History starts are line commands; attaches are fully restored TUI owners."""

from pathlib import Path

import pytest

from .test_measure_g18_native import runner


def evidence(restored):
    prefix, workspace = Path("/install"), Path("/workspace")
    child = {"spawns": [], "terminal_settlements": []}
    if restored:
        child["line_terminal_settlements"] = []
    for index in range(2):
        is_line = restored and index == 0
        cwd = workspace if index == 0 else workspace / ("restored-elsewhere" if restored else "elsewhere")
        argv = (["/install/bin/python", "-I", str(runner.inert.ROOT / "tests/coding/_lmux_product_entry.py"),
                 *( ["start", "-t", "perf"] if restored else ["new", "-s", "perf"] )]
                if index == 0 else ["/install/bin/lmux", "attach", "-t", "perf"])
        child["spawns"].append(dict(pid=100 + index, start=1.0 + index * 3, argv=argv, cwd=str(cwd)))
        terminal = dict(pid=100 + index, argv=list(argv), cwd=str(cwd), exit_status=0,
                        termios_restored_at=2.0 + index * 3, settled_at=3.0 + index * 3,
                        reader_settled=True, fallback=False)
        if is_line:
            terminal["presentation"] = "line"
            child["line_terminal_settlements"].append(terminal)
        else:
            terminal.update(cursor_restored=True, bracketed_paste_disabled=True)
            child["terminal_settlements"].append(terminal)
    return child, dict(prefix=prefix, workspace=workspace, restored=restored, earliest=0.5, latest=7.0)


@pytest.mark.parametrize("restored", [False, True])
def test_exact_two_foregrounds(restored):
    child, bounds = evidence(restored)
    terminals = runner.validate_managed_history_terminals(child, **bounds)
    assert [row["pid"] for row in terminals] == [100, 101]


@pytest.mark.parametrize("restored", [False, True])
@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("fault", ["pid", "argv", "cwd", "exit", "boolean-exit", "reader", "fallback",
                                  "time", "out-of-bounds", "extra", "missing"])
def test_each_real_foreground_is_required(restored, index, fault):
    child, bounds = evidence(restored)
    terminals = ([*child["line_terminal_settlements"], *child["terminal_settlements"]]
                 if restored else child["terminal_settlements"])
    row = terminals[index]
    if fault == "pid":
        row["pid"] += 10
    elif fault == "argv":
        row["argv"] = ["wrong-command"]
    elif fault == "cwd":
        row["cwd"] = "/other"
    elif fault in {"exit", "boolean-exit"}:
        row["exit_status"] = 1 if fault == "exit" else False
    elif fault == "reader":
        row["reader_settled"] = False
    elif fault == "fallback":
        row["fallback"] = True
    elif fault == "time":
        row["settled_at"] = float("nan")
    elif fault == "out-of-bounds":
        row["settled_at"] = 8.0
    elif fault == "extra":
        row["accepted"] = True
    else:
        row.pop("termios_restored_at")
    with pytest.raises(ValueError):
        runner.validate_managed_history_terminals(child, **bounds)


@pytest.mark.parametrize("restored", [False, True])
def test_tui_requires_both_mode_restorations(restored):
    for field in ("cursor_restored", "bracketed_paste_disabled"):
        child, bounds = evidence(restored)
        child["terminal_settlements"][-1][field] = False
        with pytest.raises(ValueError):
            runner.validate_managed_history_terminals(child, **bounds)


def test_line_cannot_claim_tui_restoration_or_borrow_tui_receipt():
    child, bounds = evidence(True)
    child["line_terminal_settlements"][0]["cursor_restored"] = True
    with pytest.raises(ValueError):
        runner.validate_managed_history_terminals(child, **bounds)
    child["line_terminal_settlements"] = [child["terminal_settlements"][0]]
    with pytest.raises(ValueError):
        runner.validate_managed_history_terminals(child, **bounds)


@pytest.mark.parametrize("restored", [False, True])
def test_attach_must_follow_original_terminal_settlement(restored):
    child, bounds = evidence(restored)
    child["spawns"][1]["start"] = 2.5
    with pytest.raises(ValueError):
        runner.validate_managed_history_terminals(child, **bounds)
