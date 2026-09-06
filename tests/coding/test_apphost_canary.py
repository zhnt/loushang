from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

from loushang.coding._apphost_canary_child import main as child_main
from loushang.coding.apphost_canary import (
    CodingAppHostCanaryReportV1,
    CodingAppHostCanaryRequestV1,
    _child_environment,
    run_coding_apphost_canary,
)


def _run(request: CodingAppHostCanaryRequestV1, **kwargs: object) -> Any:
    return asyncio.run(run_coding_apphost_canary(request, **kwargs))


def _request(
    tmp_path: Path,
    operation: str,
    *,
    timeout_seconds: float = 5.0,
) -> CodingAppHostCanaryRequestV1:
    private = tmp_path / "private"
    private.mkdir(mode=0o700, exist_ok=True)
    if os.name == "posix":
        private.chmod(0o700)
    return CodingAppHostCanaryRequestV1(
        operation=cast(Any, operation),
        cwd=tmp_path,
        control_path=private / "control.jsonl",
        timeout_seconds=timeout_seconds,
    )


@pytest.mark.parametrize(
    "_case",
    ("G10-REAL-NATIVE-RUN",),
    ids=("G10-REAL-NATIVE-RUN",),
)
def test_explicit_canary_runs_through_the_native_hosting_backend(
    tmp_path: Path,
    _case: str,
) -> None:
    del _case
    executable = shutil.which("loushang")
    assert executable is not None
    home = tmp_path / "installed-home"
    home.mkdir(mode=0o700)
    environment = dict(os.environ)
    environment["LOUSHANG_HOME"] = str(home)

    def invoke(operation: str, expected_returncode: int = 0) -> dict[str, Any]:
        completed = subprocess.run(
            (
                executable,
                "apphost",
                "canary",
                operation,
                "--format",
                "json",
                "--cwd",
                str(tmp_path),
            ),
            cwd=tmp_path,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert completed.returncode == expected_returncode, completed.stderr
        return cast(dict[str, Any], json.loads(completed.stdout))

    enabled = invoke("enable")
    assert (enabled["state"], enabled["selectionGeneration"]) == ("enabled", 1)
    report = invoke("run")
    assert report["state"] == "ready"
    assert (
        report["hostingBackendId"]
        == {
            "posix": "posix-process-group-v1",
            "nt": "windows-job-v1",
        }[os.name]
    )
    assert report["receiptFingerprint"] is not None
    assert report["attemptFingerprint"] is not None
    assert {"published", "exited", "closed"}.issubset(report["hostingTransitions"])


@pytest.mark.parametrize(
    "_case",
    ("G10-ROLLBACK-BEFORE-RUN",),
    ids=("G10-ROLLBACK-BEFORE-RUN",),
)
def test_missing_or_disabled_control_rejects_before_process_effect(
    tmp_path: Path,
    _case: str,
) -> None:
    del _case
    calls = 0

    def forbidden_host_factory(**kwargs: object) -> Any:
        nonlocal calls
        del kwargs
        calls += 1
        raise AssertionError("Hosting must not be constructed")

    missing = _run(
        _request(tmp_path, "run"),
        process_host_factory=forbidden_host_factory,
    )
    assert (missing.state, missing.code) == (
        "failed",
        "coding_apphost_canary_disabled",
    )
    _run(_request(tmp_path, "enable"))
    disabled = _run(_request(tmp_path, "rollback"))
    assert disabled.state == "disabled"
    rejected = _run(
        _request(tmp_path, "run"),
        process_host_factory=forbidden_host_factory,
    )
    assert rejected.code == "coding_apphost_canary_disabled"
    assert rejected.selection_generation == disabled.selection_generation
    assert calls == 0


@pytest.mark.parametrize(
    "_case",
    ("G10-ENABLE-NEW-GENERATION",),
    ids=("G10-ENABLE-NEW-GENERATION",),
)
def test_rollback_and_reenable_advance_exact_selection_generation(
    tmp_path: Path,
    _case: str,
) -> None:
    del _case
    assert _run(_request(tmp_path, "enable")).selection_generation == 1
    assert _run(_request(tmp_path, "rollback")).selection_generation == 2
    enabled = _run(_request(tmp_path, "enable"))
    assert (enabled.state, enabled.selection_generation) == ("enabled", 3)


@pytest.mark.parametrize(
    "_case",
    ("G10-STATUS-NO-EFFECT",),
    ids=("G10-STATUS-NO-EFFECT",),
)
def test_status_is_read_only_and_constructs_no_host(
    tmp_path: Path,
    _case: str,
) -> None:
    del _case

    def forbidden_host_factory(**kwargs: object) -> Any:
        del kwargs
        raise AssertionError("status must not construct Hosting")

    report = _run(
        _request(tmp_path, "status"),
        process_host_factory=forbidden_host_factory,
    )
    assert report.to_dict() == {
        "attemptFingerprint": None,
        "code": "coding_apphost_canary_unconfigured",
        "hostingBackendId": None,
        "hostingTransitions": [],
        "operation": "status",
        "receiptFingerprint": None,
        "reportVersion": 1,
        "selectionGeneration": 0,
        "state": "unconfigured",
    }


@pytest.mark.parametrize(
    "_case",
    ("G10-NO-FALLBACK",),
    ids=("G10-NO-FALLBACK",),
)
def test_selected_hosting_failure_returns_stable_failure_without_fallback(
    tmp_path: Path,
    _case: str,
) -> None:
    del _case
    _run(_request(tmp_path, "enable"))
    calls = 0

    def failed_host_factory(**kwargs: object) -> Any:
        nonlocal calls
        del kwargs
        calls += 1
        raise RuntimeError("secret cwd and credential")

    report = _run(
        _request(tmp_path, "run"),
        process_host_factory=failed_host_factory,
    )
    assert calls == 1
    assert report.state == "failed"
    assert report.code == "coding_apphost_canary_hosting_unavailable"
    assert "secret" not in json.dumps(report.to_dict())


class _BlockingHost:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.closed = asyncio.Event()

    async def start(self, *args: object, **kwargs: object) -> Any:
        del args, kwargs
        self.entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def close(self) -> None:
        self.closed.set()


@pytest.mark.parametrize(
    "_case",
    ("G10-CANCEL-CLEANUP",),
    ids=("G10-CANCEL-CLEANUP",),
)
def test_cancellation_joins_exact_host_cleanup_and_releases_control_lock(
    tmp_path: Path,
    _case: str,
) -> None:
    del _case

    async def scenario() -> None:
        await run_coding_apphost_canary(_request(tmp_path, "enable"))
        host = _BlockingHost()
        task = asyncio.create_task(
            run_coding_apphost_canary(
                _request(tmp_path, "run"),
                process_host_factory=lambda **_: cast(Any, host),
            )
        )
        await host.entered.wait()
        rollback = asyncio.create_task(
            run_coding_apphost_canary(
                _request(tmp_path, "rollback", timeout_seconds=20.0)
            )
        )
        await asyncio.sleep(0.05)
        assert not rollback.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert host.closed.is_set()
        rolled_back = await asyncio.wait_for(rollback, timeout=2.0)
        assert rolled_back.state == "disabled"

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "_case",
    ("G10-REPORT-REDACTION",),
    ids=("G10-REPORT-REDACTION",),
)
def test_report_schema_is_closed_and_rejects_unbounded_values(_case: str) -> None:
    del _case
    report = CodingAppHostCanaryReportV1(
        operation="run",
        state="ready",
        code="coding_apphost_canary_ready",
        selection_generation=1,
        receipt_fingerprint="a" * 64,
        attempt_fingerprint="b" * 64,
        hosting_backend_id="posix-process-group-v1",
        hosting_transitions=("published", "exited", "closed"),
    )
    assert set(report.to_dict()) == {
        "attemptFingerprint",
        "code",
        "hostingBackendId",
        "hostingTransitions",
        "operation",
        "receiptFingerprint",
        "reportVersion",
        "selectionGeneration",
        "state",
    }
    forbidden = ("cwd", "path", "argv", "environment", "payload", "stderr")
    assert all(name not in json.dumps(report.to_dict()).lower() for name in forbidden)
    with pytest.raises(ValueError):
        CodingAppHostCanaryReportV1(
            operation="run",
            state="ready",
            code="contains spaces",
            selection_generation=1,
        )


def test_child_protocol_accepts_only_one_exact_nonce(
    capsys: pytest.CaptureFixture[str],
) -> None:
    nonce = "a" * 32
    assert child_main((nonce,)) == 0
    assert capsys.readouterr().out == f"loushang-apphost-canary/v1 {nonce}\n"
    assert child_main(()) == 2
    assert child_main((nonce, "extra")) == 2
    assert child_main(("A" * 32,)) == 2


def test_child_environment_is_generated_from_a_minimal_noncredential_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-cross")
    monkeypatch.setenv("PYTHONPATH", "/must/not/cross")
    monkeypatch.setenv("PATH", "/must/not/cross")
    environment = dict(_child_environment())
    assert environment["PYTHONIOENCODING"] == "utf-8"
    assert environment["PYTHONUTF8"] == "1"
    assert {"AWS_SECRET_ACCESS_KEY", "PYTHONPATH", "PATH"}.isdisjoint(environment)
    assert set(environment) <= {
        "PYTHONIOENCODING",
        "PYTHONUTF8",
        "SYSTEMROOT",
        "WINDIR",
    }


@pytest.mark.parametrize(
    "_case",
    ("G10-EPHEMERAL-NO-SESSION-IO",),
    ids=("G10-EPHEMERAL-NO-SESSION-IO",),
)
def test_native_canary_leaves_user_session_roots_untouched(
    tmp_path: Path,
    _case: str,
) -> None:
    del _case
    cwd_sessions = tmp_path / ".loushang" / "sessions"
    global_sessions = tmp_path / "data" / "sessions"
    cwd_sessions.mkdir(parents=True)
    global_sessions.mkdir(parents=True)
    (cwd_sessions / "cwd-sentinel.jsonl").write_text("cwd", encoding="utf-8")
    (global_sessions / "global-sentinel.jsonl").write_text("global", encoding="utf-8")

    def snapshot(root: Path) -> tuple[tuple[str, bytes | None], ...]:
        return tuple(
            (
                path.relative_to(root).as_posix(),
                path.read_bytes() if path.is_file() else None,
            )
            for path in sorted(root.rglob("*"))
        )

    before = (snapshot(cwd_sessions), snapshot(global_sessions))

    _run(_request(tmp_path, "enable"))
    report = _run(_request(tmp_path, "run"))

    assert report.succeeded
    after = (snapshot(cwd_sessions), snapshot(global_sessions))
    assert after == before
