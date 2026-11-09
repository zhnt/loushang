"""Opt-in G1 human-operated Tauri acceptance; never starts a Host for the GUI.

The operator uses the GUI's management controls. This observer only releases
synthetic model gates, opens GUI B after GUI A exits, and performs final cleanup.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import mkdtemp
from time import monotonic, sleep

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path(mkdtemp(prefix="loushang-g1-desktop-"))


def main():
    # Managed storage rejects group-writable ancestors. Repository directories
    # can legitimately be shared, so keep private acceptance storage in /tmp.
    workspace = EVIDENCE / "workspace"
    workspace.mkdir(mode=0o700)
    (workspace / "desktop-acceptance").touch()
    (workspace / "desktop-scenario-v2").touch()
    launcher = EVIDENCE / "python-test-provider"
    launcher.write_text(f"#!{sys.executable}\nimport runpy\nrunpy.run_path({str(Path(__file__).with_name('_gui_local_host_helper.py'))!r}, run_name='__main__')\n")
    launcher.chmod(0o700)
    environment = {**os.environ, "LOUSHANG_GUI_PYTHON": str(launcher),
        "LOUSHANG_HOME": str(EVIDENCE / "home"), "LOUSHANG_RUNTIME_DIR": str(EVIDENCE / "runtime"),
        "LOUSHANG_TMPDIR": str(EVIDENCE / "temporary"), "XDG_CONFIG_HOME": str(EVIDENCE / "gui-config"),
        "XDG_DATA_HOME": str(EVIDENCE / "gui-data"), "XDG_CACHE_HOME": str(EVIDENCE / "gui-cache")}
    evidence = {"workspace": str(workspace), "observer_pid": os.getpid(), "guis": [], "milestones": []}

    def save(kind, **facts):
        evidence["milestones"].append({"kind": kind, "time": monotonic(), **facts})
        (EVIDENCE / "desktop.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False))
        print(json.dumps({"kind": kind, **facts}), flush=True)

    def events():
        path = workspace / "execution-audit.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def manage(action, instance=None):
        request = {"action": action, "workspace": str(workspace)}
        if instance is not None:
            request["instanceId"] = instance
        result = subprocess.run([str(launcher), "-m", "loushang.coding.gui_local_host"],
            input=json.dumps(request), capture_output=True, text=True, env=environment, timeout=90)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    with (EVIDENCE / "gui.log").open("w") as log:
        def launch():
            process = subprocess.Popen([str(ROOT / "gui/src-tauri/target/debug/harness-gui")],
                cwd=workspace, env=environment, stdout=log, stderr=log)
            evidence["guis"].append(process.pid)
            return process

        gui = launch()
        save("gui_a_launched", pid=gui.pid, evidence=str(EVIDENCE))
        second = False
        original_host = None
        deadline = monotonic() + 1800
        try:
            while monotonic() < deadline:
                audit = events()
                entered = [item for item in audit if item["kind"] == "model_entered"]
                if entered and original_host is None:
                    original_host = entered[0]["pid"]
                    save("first_host_observed", pid=original_host)
                for item in entered:
                    # Keep the second original execution held across GUI exit;
                    # keep the third for the user's confirmed Host stop.
                    if (item["pid"] != original_host or item["number"] not in {2, 3}) and monotonic() - item["time"] >= 3:
                        (workspace / f"release-{item['number']}").touch()
                if gui.poll() is not None:
                    save("gui_exited", pid=gui.pid, exit_code=gui.returncode)
                    if second:
                        break
                    task = next((item for item in entered if item["pid"] == original_host and item["number"] == 2), None)
                    assert task is not None, "GUI A exited before the held task"
                    assert not any(item["kind"] in {"model_returned", "model_cancelled"} and item.get("number") == 2 for item in audit)
                    sleep(2)
                    host = manage("status")
                    assert host["state"] == "running" and host["pid"] == original_host
                    save("host_survived_gui_exit", **host)
                    (workspace / "release-2").touch()
                    gui = launch()
                    second = True
                    save("gui_b_launched", pid=gui.pid)
                sleep(0.1)
            else:
                raise TimeoutError("manual G1 acceptance timed out")
        finally:
            host = manage("status")
            if host.get("instanceId") and host["state"] != "not_running":
                stopped = manage("stop", host["instanceId"])
                assert stopped.get("cleanlyStopped"), stopped
                save("final_managed_stop", **stopped)
            if gui.poll() is None:
                gui.terminate()
                gui.wait(timeout=15)
            save("observer_finished")


if __name__ == "__main__":
    main()
