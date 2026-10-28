"""Trusted bounded check process. Run from a protected task package, not a model command."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from contextlib import suppress
from pathlib import Path


def terminate_group(child):
    """Settle descendants even after the immediate command process has exited."""
    if child is not None:
        with suppress(ProcessLookupError):
            os.killpg(child.pid, signal.SIGKILL)
        child.wait()


def main():
    request = json.load(sys.stdin)
    package = Path(request["package"])
    content = package.read_bytes()
    if hashlib.sha256(content).hexdigest() != request["package_sha256"]:
        raise ValueError("task package changed")
    config = json.loads(content)
    for name, digest in config["protected"].items():
        if hashlib.sha256((package.parent / name).read_bytes()).hexdigest() != digest:
            raise ValueError("protected verifier input changed")
    root = Path(config["workspace"])
    before = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in config["allowed_files"]
    }
    if before != request["inventory"]:
        raise ValueError("candidate changed before verification")
    mode = request["check"]
    selectors = config["check_selectors"]
    groups = [("contract", [str(package.parent / "test_contract.py")])]
    if mode != "all":
        groups.append((mode, selectors[mode]))
    else:
        groups.append(("regression", selectors["regression"]))
    environment = dict(os.environ)
    environment.update(PYTHONPATH=str(root / "src"), PYTHONDONTWRITEBYTECODE="1")
    child = None

    def stop(signum, frame):
        terminate_group(child)
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    checks = []
    with tempfile.TemporaryDirectory(
        prefix="repo-goal-check-", dir=config["temporary_root"]
    ) as temp:
        environment["PYTHONPYCACHEPREFIX"] = str(Path(temp) / "pycache")
        for label, paths in groups:
            xml = Path(temp) / (label + ".xml")
            command = [
                config["python"],
                "-m",
                "pytest",
                *paths,
                "-q",
                "--import-mode=importlib",
                "--tb=short",
                "-m",
                "not live",
                "-p",
                "no:cacheprovider",
                "--basetemp",
                str(Path(temp) / label),
                "--junitxml",
                str(xml),
            ]
            if label != "contract":
                command.append("--skip-host-runtime")
            try:
                child = subprocess.Popen(
                    command,
                    cwd=root,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                output, _ = child.communicate(timeout=config["check_timeout_seconds"])
            except subprocess.TimeoutExpired:
                terminate_group(child)
                child.communicate()
                raise RuntimeError("repository check timed out") from None
            finally:
                terminate_group(child)
            cases = (
                list(ET.parse(xml).getroot().iter("testcase")) if xml.exists() else []
            )
            failed = [
                case.get("classname", "") + ":" + case.get("name", "")
                for case in cases
                if case.find("failure") is not None
            ]
            errors = [
                case.get("classname", "") + ":" + case.get("name", "")
                for case in cases
                if case.find("error") is not None
            ]
            skipped = sum(case.find("skipped") is not None for case in cases)
            checks.append(
                {
                    "name": label,
                    "exit_code": child.returncode,
                    "collected": len(cases),
                    "failed": failed,
                    "errors": errors,
                    "skipped": skipped,
                    "output": output.decode(errors="replace"),
                }
            )
    after = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in config["allowed_files"]
    }
    result = {
        "version": 1,
        "identity": request["identity"],
        "package_sha256": request["package_sha256"],
        "inventory": before,
        "current": before == after,
        "check": mode,
        "results": checks,
    }
    print(json.dumps(result, sort_keys=True), flush=True)
    return (
        0
        if before == after
        and all(
            c["exit_code"] == 0
            and c["collected"] > c["skipped"]
            and not c["failed"]
            and not c["errors"]
            for c in checks
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
