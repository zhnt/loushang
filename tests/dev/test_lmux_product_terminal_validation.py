"""Pure terminal/stop receipt checks; no claim of native authentication."""

import pytest

from .test_measure_g18_native import runner


def sample(tmp_path, scenario):
    prefix, workspace = tmp_path / "install", tmp_path / scenario
    spawns, terminals = [], []
    for index in range(2 if scenario == "interrupt" else 1):
        cwd = workspace if index == 0 else workspace / "elsewhere"
        argv = ([str(prefix / "bin/python"), "-I", str(runner.inert.ROOT / "tests/coding/_lmux_product_entry.py"), "new", "-s", "perf"]
                if index == 0 else [str(prefix / "bin/lmux"), "attach", "-t", "perf"])
        spawns.append({"pid": 100 + index, "start": 2.0 + index * 4, "argv": argv, "cwd": str(cwd)})
        terminals.append({"pid": 100 + index, "argv": argv, "cwd": str(cwd), "exit_status": 0,
                          "termios_restored_at": 3.0 + index * 4, "settled_at": 4.0 + index * 4,
                          "cursor_restored": True, "bracketed_paste_disabled": True,
                          "reader_settled": True, "fallback": False})
    child = {"status": "observed", "valid": False, "measured_prefix": str(prefix),
             "workspace": str(workspace), "started_at": 1.0, "finished_at": 13.0,
             "spawns": spawns, "terminal_settlements": terminals,
             "fixed_product_stop": {"started_at": 10.0, "observed_at": 11.0,
                                    "local_owner_settled_at": 12.0, "service_id": "b" * 64,
                                    "result": {"status": "stopped", "instanceId": "a" * 32}}}
    return child, dict(prefix=prefix, workspace=workspace, instance="a" * 32, service="b" * 64)


@pytest.mark.parametrize("scenario", ["reply", "approval", "interrupt"])
@pytest.mark.parametrize("fault", [None, "missing", "extra", "pid", "cwd", "argv", "exit", "bool-exit",
                                  "cursor", "paste", "reader", "fallback", "overlap", "nan",
                                  "early-stop", "late-close", "wrong-instance", "wrong-service",
                                  "self-outer", "failed", "cleanup-debt"])
def test_every_actual_terminal_and_exact_stop_must_match(tmp_path, scenario, fault):
    child, parameters = sample(tmp_path, scenario)
    terminal, stop = child["terminal_settlements"][-1], child["fixed_product_stop"]
    if fault == "missing":
        child["terminal_settlements"].pop()
    elif fault == "extra":
        child["terminal_settlements"].append(dict(terminal))
    elif fault == "pid":
        terminal["pid"] = 999
    elif fault == "cwd":
        terminal["cwd"] = str(tmp_path)
    elif fault == "argv":
        child["spawns"][0]["argv"] = ["arbitrary-entry"]
    elif fault in {"exit", "bool-exit"}:
        terminal["exit_status"] = 1 if fault == "exit" else False
    elif fault in {"cursor", "paste", "reader"}:
        terminal[{"cursor": "cursor_restored", "paste": "bracketed_paste_disabled", "reader": "reader_settled"}[fault]] = False
    elif fault == "fallback":
        terminal["fallback"] = True
    elif fault == "overlap":
        child["spawns"][-1]["start"] = 0.5
    elif fault == "nan":
        terminal["settled_at"] = float("nan")
    elif fault == "early-stop":
        stop["started_at"] = 0.5
    elif fault == "late-close":
        stop["local_owner_settled_at"] = 14.0
    elif fault == "wrong-instance":
        stop["result"]["instanceId"] = "c" * 32
    elif fault == "wrong-service":
        stop["service_id"] = "c" * 64
    elif fault == "self-outer":
        stop["outer_owner_settled_at"] = 13.0
    elif fault == "failed":
        child["status"] = "failed"
    elif fault == "cleanup-debt":
        child["fixed_product_cleanup_failure"] = {"type": "TimeoutError"}
    if fault is None:
        runner.validate_managed_product_terminals(child, scenario, **parameters)
    else:
        with pytest.raises(ValueError):
            runner.validate_managed_product_terminals(child, scenario, **parameters)
