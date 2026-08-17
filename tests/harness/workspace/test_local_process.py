from __future__ import annotations

import asyncio
import subprocess

import pytest

from loushang.harness.workspace import _local_process


class _FakeProcess:
    pid = 321

    def __init__(self) -> None:
        self.terminate_calls = 0
        self.kill_calls = 0

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1


def test_windows_spawn_uses_hidden_window_without_posix_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(*command, **options):
        captured["command"] = command
        captured["options"] = options
        return object()

    monkeypatch.setattr(_local_process, "_is_windows", lambda: True)
    monkeypatch.setattr(
        _local_process.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    asyncio.run(
        _local_process.spawn_local_process(
            command=("tool.exe", "--version"),
            cwd=r"C:\workspace",
            environment={"Path": "value"},
            pipe_stdin=False,
        )
    )

    assert captured["command"] == ("tool.exe", "--version")
    options = captured["options"]
    assert isinstance(options, dict)
    assert options["creationflags"] == getattr(
        subprocess,
        "CREATE_NO_WINDOW",
        0x08000000,
    )
    assert "start_new_session" not in options


def test_windows_tree_kill_uses_absolute_system_taskkill_and_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    process = _FakeProcess()

    class _Taskkill:
        async def wait(self) -> int:
            captured["waited"] = True
            return 0

    async def fake_create_subprocess_exec(*command, **options):
        captured["command"] = command
        captured["options"] = options
        return _Taskkill()

    monkeypatch.setattr(_local_process, "_is_windows", lambda: True)
    monkeypatch.setattr(
        _local_process.os,
        "environ",
        {"sYsTeMrOoT": r"D:\Windows"},
    )
    monkeypatch.setattr(
        _local_process.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    accepted = asyncio.run(_local_process.kill_local_process_tree(process))

    assert accepted is True
    assert captured["command"] == (
        r"D:\Windows\System32\taskkill.exe",
        "/PID",
        "321",
        "/T",
        "/F",
    )
    assert captured["waited"] is True
    assert process.kill_calls == 0


def test_windows_tree_kill_falls_back_to_root_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess()

    async def failing_create_subprocess_exec(*command, **options):
        del command, options
        raise OSError("taskkill unavailable")

    monkeypatch.setattr(_local_process, "_is_windows", lambda: True)
    monkeypatch.setattr(
        _local_process.os,
        "environ",
        {"SystemRoot": r"C:\Windows"},
    )
    monkeypatch.setattr(
        _local_process.asyncio,
        "create_subprocess_exec",
        failing_create_subprocess_exec,
    )

    accepted = asyncio.run(_local_process.kill_local_process_tree(process))

    assert accepted is False
    assert process.kill_calls == 1
