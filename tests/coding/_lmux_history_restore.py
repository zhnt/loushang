"""Restart a seeded service under the original retained evidence process."""

import json
import time
from dataclasses import asdict
from pathlib import Path

from loushang.appserver.protocol import SessionIdentityV1, SessionScopeV1
from loushang.tui.cell_width import strip_control_sequences

from . import _lmux_product_probe as probe
from ._lmux_history_canonical import read_history


def restore_history(root, report):
    """Old and new generations have distinct receipts and stop attempts."""
    old = {"measured_prefix": report["measured_prefix"], "valid": False, "status": "running"}
    new = {"measured_prefix": report["measured_prefix"], "valid": False, "status": "not-started"}
    report["history_generations"] = {"old": old, "new": new}
    probe.first_reply(root, old, history=True)
    old["status"] = "observed"
    prior = old["fixed_product_history"]
    target = old["fixed_product_target"]
    assert prior["stop"] == {"status": "stopped", "instanceId": target["instanceId"]}
    assert old["fixed_product_stop"]["result"] == prior["stop"]
    identity = prior["seed"]["history_identity"]
    canonical_read = prior["canonical_read"]
    assert old["fixed_product_stop"]["local_owner_settled_at"] <= canonical_read["started_at"]
    assert canonical_read["started_at"] <= canonical_read["completed_at"]
    new["status"] = "running"
    _restart(root, new, target, old["fixed_product_native"]["stop"], identity,
             canonical_read["completed_at"], prior["canonical"])
    new["status"] = "observed"
    report["fixed_product_history_restore"] = new["restored_history"]
    report["spawns"] = [*old["spawns"], *new["spawns"]]


def _restart(root, report, old_target, old_native, identity, old_completed_at, old_canonical):
    prefix = Path(report["measured_prefix"])
    environment = probe._terminal_environment(root)
    environment.pop("LOUSHANG_TMPDIR", None)
    argv = [str(prefix / "bin/python"), "-I", str(Path(__file__).with_name("_lmux_product_entry.py")),
            "start", "-t", "perf"]
    target, native = None, []
    attempted = stopped = False
    primary = None
    try:
        with probe.observe_spawn(argv[0]) as spawned, probe.observed_terminal(
            argv, root, environment, failure_report=report,
            line_settlements=report.setdefault("line_terminal_settlements", []),
        ) as (driver, _master, _original):
            report.setdefault("spawns", []).append(spawned)
            assert spawned["start"] >= old_completed_at
            assert driver.wait(timeout=45) == 0, driver.diagnostics
        # start is a line-oriented command, not a TUI: the original context
        # still proves termios/reader settlement without inventing mode toggles.
        rows = [json.loads(line) for line in strip_control_sequences(driver.raw_output).splitlines() if line.strip()]
        assert len(rows) == 1 and rows[0]["status"] == "service_ready"
        ready = rows[0]
        report["start_command"] = {"started_at": spawned["start"], "settled_at": time.perf_counter(),
                                   "result": ready, "exit_status": 0}
        candidates = []
        candidate = probe.managed_read_observation(environment, "first-member", native_identity=candidates)
        assert len(candidates) == 1
        assert candidate["serviceId"] == old_target["serviceId"] == ready["serviceId"]
        assert candidate["instanceId"] == ready["instanceId"] != old_target["instanceId"]
        assert asdict(candidates[0]) != old_native
        # Only the fully checked new generation is eligible for exact stop.
        # Name/ready mismatches remain the original outer owner's responsibility.
        target, native = candidate, candidates
        report["fixed_product_target"] = dict(target)
        report["authenticated_at"] = time.perf_counter()
        probe._record_native(report, "restored", native[0])
        attached = probe._history_attach(root, report, environment, target, native, identity,
                                         directory="restored-elsewhere")
        attempted = True
        result = probe._stop_generation(root, report, environment, target, native[0])
        stopped = True
        restored_identity = {**identity, "scope": SessionScopeV1(identity["scope"])}
        canonical_read = {}
        canonical = read_history(Path(environment["LOUSHANG_HOME"]) / "data/sessions",
                                 SessionIdentityV1(**restored_identity), root, receipt=canonical_read)
        assert canonical == old_canonical
        finished = attached["actions"]["history_frame"]["finished_at"]
        report["restored_history"] = {"attach": attached, "canonical": canonical, "stop": result,
            "canonical_read": canonical_read,
            "restored_history_frame_seconds": finished - spawned["start"],
            "action": {"started_at": spawned["start"], "finished_at": finished}}
    except BaseException as error:
        primary = error
        report.update(status="failed", failure=type(error).__name__)
        raise
    finally:
        if not stopped:
            try:
                if attempted or target is None or len(native) != 1:
                    raise RuntimeError("restart exact stop unavailable; original outer owner must settle")
                attempted = True
                probe._stop_generation(root, report, environment, target, native[0])
            except BaseException as cleanup:
                report["cleanup_failure"] = type(cleanup).__name__
                if primary is None:
                    raise
                primary.add_note("restart cleanup failed: " + type(cleanup).__name__)
