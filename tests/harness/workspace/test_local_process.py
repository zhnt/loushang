from __future__ import annotations

import asyncio
import os
import subprocess
import sys

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


def test_posix_spawn_passes_fds_without_mutating_global_inheritability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(*command, **options):
        captured["command"] = command
        captured["options"] = options
        return object()

    def unexpected_set_inheritable(descriptor: int, inheritable: bool) -> None:
        raise AssertionError(
            f"must not change descriptor {descriptor} inheritable={inheritable}"
        )

    monkeypatch.setattr(_local_process, "_is_windows", lambda: False)
    monkeypatch.setattr(
        _local_process.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(
        _local_process.os,
        "set_inheritable",
        unexpected_set_inheritable,
    )

    asyncio.run(
        _local_process.spawn_local_process(
            command=("tool", "--version"),
            cwd="/workspace",
            environment={"PATH": "/bin"},
            pipe_stdin=False,
            inherited_file_descriptors=(11, 12),
        )
    )

    assert captured["command"] == ("tool", "--version")
    options = captured["options"]
    assert isinstance(options, dict)
    assert options["pass_fds"] == (11, 12)


@pytest.mark.skipif(os.name != "posix", reason="POSIX pass_fds behavior")
def test_concurrent_posix_spawns_inherit_only_their_owned_descriptor(
    tmp_path,
) -> None:
    paths = (tmp_path / "first", tmp_path / "second")
    for index, path in enumerate(paths):
        path.write_text(str(index), encoding="utf-8")
    descriptors = tuple(os.open(path, os.O_RDONLY) for path in paths)
    identities = tuple(os.fstat(descriptor) for descriptor in descriptors)
    child = """import os
import sys

own, other, dev, inode = map(int, sys.argv[1:])

def matches(descriptor):
    try:
        value = os.fstat(descriptor)
    except OSError:
        return False
    return (value.st_dev, value.st_ino) == (dev, inode)

print(f"{int(matches(own))}:{int(matches(other))}")
"""

    async def spawn(index: int):
        own = descriptors[index]
        other = descriptors[1 - index]
        identity = identities[index]
        process = await _local_process.spawn_local_process(
            command=(
                sys.executable,
                "-c",
                child,
                str(own),
                str(other),
                str(identity.st_dev),
                str(identity.st_ino),
            ),
            cwd=str(tmp_path),
            environment=dict(os.environ),
            pipe_stdin=False,
            inherited_file_descriptors=(own,),
        )
        stdout, stderr = await process.communicate()
        assert process.returncode == 0, stderr.decode()
        return stdout

    async def scenario() -> tuple[bytes, bytes]:
        first, second = await asyncio.gather(spawn(0), spawn(1))
        return first, second

    try:
        assert all(not os.get_inheritable(item) for item in descriptors)
        outputs = asyncio.run(scenario())
        assert outputs == (b"1:0\n", b"1:0\n")
        assert all(not os.get_inheritable(item) for item in descriptors)
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


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
