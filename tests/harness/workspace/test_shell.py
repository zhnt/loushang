from __future__ import annotations

import asyncio
import base64
import ntpath
import os

import pytest

from loushang.harness.environment import HostEnvironment, LocalHostEnvironmentProbe
from loushang.harness.policy import shell_command_policy_subject
from loushang.harness.workspace.exec import ExecRequest, ExecService
from loushang.harness.workspace.shell import (
    LocalShellResolver,
    ResolvedShell,
    ShellCompileError,
    ShellResolutionError,
    ShellSelection,
    compile_shell_launch,
)


def _windows() -> HostEnvironment:
    return HostEnvironment(
        os_family="windows",
        platform_name="win32",
        architecture="amd64",
    )


def _linux() -> HostEnvironment:
    return HostEnvironment(
        os_family="linux",
        platform_name="linux",
        architecture="x86_64",
    )


def _windows_resolver(
    *,
    files: set[str],
    environ: dict[str, str] | None = None,
    which: dict[str, str] | None = None,
    cwd: str = r"C:\workspace",
) -> LocalShellResolver:
    normalized_files = {ntpath.normcase(ntpath.normpath(path)) for path in files}
    hits = which or {}
    return LocalShellResolver(
        environment=_windows(),
        target_id="windows-local",
        environ=environ or {},
        cwd=cwd,
        path_is_file=lambda path: ntpath.normcase(ntpath.normpath(path))
        in normalized_files,
        which_executable=lambda name, path: hits.get(name),
    )


def test_windows_resolver_prefers_program_files_pwsh() -> None:
    program_pwsh = r"C:\Program Files\PowerShell\7\pwsh.exe"
    path_pwsh = r"C:\Users\dev\scoop\apps\pwsh\current\pwsh.exe"
    resolver = _windows_resolver(
        files={program_pwsh, path_pwsh},
        environ={
            "ProgramFiles": r"C:\Program Files",
            "PATH": r"C:\Users\dev\scoop\shims",
            "SystemRoot": r"C:\Windows",
        },
        which={"pwsh.exe": path_pwsh},
    )

    resolved = resolver.resolve()

    assert resolved.executable == program_pwsh
    assert resolved.kind == "powershell"
    assert resolved.flavor == "pwsh"
    assert resolved.edition == "Core"
    assert resolved.source == "program-files"
    assert resolved.target_id == "windows-local"


def test_windows_resolver_accepts_absolute_path_hit_outside_workspace() -> None:
    path_pwsh = r"C:\Users\dev\scoop\apps\pwsh\current\pwsh.exe"
    resolver = _windows_resolver(
        files={path_pwsh},
        environ={"PATH": r"C:\Users\dev\scoop\shims"},
        which={"pwsh.exe": path_pwsh},
    )

    resolved = resolver.resolve()

    assert resolved.executable == path_pwsh
    assert resolved.source == "path"


def test_windows_resolver_rejects_workspace_path_hit_and_uses_ps51() -> None:
    fake_pwsh = r"C:\workspace\pwsh.exe"
    ps51 = r"D:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    resolver = _windows_resolver(
        files={fake_pwsh, ps51},
        environ={"PATH": r"C:\workspace", "sYsTeMrOoT": r"D:\Windows"},
        which={"pwsh.exe": fake_pwsh},
    )

    resolved = resolver.resolve()

    assert resolved.executable == ps51
    assert resolved.flavor == "windows-powershell"
    assert resolved.version == "5.1"
    assert resolved.edition == "Desktop"
    assert resolved.source == "system"


def test_windows_auto_resolution_does_not_fall_back_to_cmd() -> None:
    cmd = r"C:\Windows\System32\cmd.exe"
    resolver = _windows_resolver(
        files={cmd},
        environ={"SystemRoot": r"C:\Windows"},
    )

    with pytest.raises(ShellResolutionError) as raised:
        resolver.resolve()

    assert raised.value.kind == "shell_unavailable"
    assert cmd not in raised.value.attempted_paths


def test_cmd_and_git_bash_require_explicit_selection() -> None:
    cmd = r"C:\Windows\System32\cmd.exe"
    git_bash = r"C:\Program Files\Git\bin\bash.exe"
    resolver = _windows_resolver(
        files={cmd, git_bash},
        environ={
            "SystemRoot": r"C:\Windows",
            "ProgramFiles": r"C:\Program Files",
        },
    )

    resolved_cmd = resolver.resolve(ShellSelection(kind="cmd"))
    resolved_bash = resolver.resolve(ShellSelection(kind="bash"))

    assert resolved_cmd.executable == cmd
    assert resolved_cmd.flavor == "cmd"
    assert resolved_bash.executable == git_bash
    assert resolved_bash.flavor == "git-bash"


def test_invalid_explicit_shell_fails_without_fallback() -> None:
    ps51 = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    resolver = _windows_resolver(
        files={ps51},
        environ={"SystemRoot": r"C:\Windows"},
    )

    with pytest.raises(ShellResolutionError) as raised:
        resolver.resolve(
            ShellSelection(
                kind="powershell",
                path=r"C:\missing\pwsh.exe",
            )
        )

    assert raised.value.kind == "configured_shell_not_found"
    assert raised.value.attempted_paths == (r"C:\missing\pwsh.exe",)


def test_explicit_custom_path_requires_kind_and_known_mismatch_fails() -> None:
    wrapper = r"C:\tools\company-shell.exe"
    bash = r"C:\tools\bash.exe"
    resolver = _windows_resolver(files={wrapper, bash})

    with pytest.raises(ShellResolutionError) as missing_kind:
        resolver.resolve(ShellSelection(path=wrapper))
    with pytest.raises(ShellResolutionError) as mismatch:
        resolver.resolve(ShellSelection(kind="powershell", path=bash))

    assert missing_kind.value.kind == "shell_kind_required"
    assert mismatch.value.kind == "shell_kind_mismatch"


def test_explicit_relative_path_is_rejected_before_lookup() -> None:
    resolver = _windows_resolver(files={r"tools\pwsh.exe"})

    with pytest.raises(ShellResolutionError) as raised:
        resolver.resolve(ShellSelection(kind="powershell", path=r"tools\pwsh.exe"))

    assert raised.value.kind == "configured_path_not_absolute"


def test_posix_resolver_preserves_login_selection() -> None:
    resolver = LocalShellResolver(
        environment=_linux(),
        environ={"PATH": "/usr/bin"},
        path_is_file=lambda path: path == "/usr/bin/bash",
        which_executable=lambda name, path: "/usr/bin/bash"
        if name == "bash"
        else None,
    )

    resolved = resolver.resolve(ShellSelection(kind="bash", login=True))
    launch = compile_shell_launch(resolved, "pwd", cwd="/workspace")

    assert resolved.login is True
    assert launch.argv == ("/usr/bin/bash", "-lc", "pwd")


def test_powershell_compiler_uses_plaintext_policy_and_encoded_transport() -> None:
    shell = ResolvedShell(
        kind="powershell",
        executable=r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        flavor="windows-powershell",
        target_id="windows-local",
        target_os_family="windows",
        source="system",
        version="5.1",
        edition="Desktop",
    )

    launch = compile_shell_launch(
        shell,
        "Write-Output '你好'",
        cwd=r"C:\workspace",
        effective_environment=(("Path", "value"),),
    )
    decoded = base64.b64decode(launch.argv[-1]).decode("utf-16le")
    policy_subject = shell_command_policy_subject(
        launch.argv,
        script=launch.plain_script,
        dialect="powershell",
        shell_flavor=launch.shell.flavor,
        cwd=launch.cwd,
    )

    assert launch.argv[:5] == (
        shell.executable,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-EncodedCommand",
    )
    assert launch.transport == "encoded-command"
    assert "UTF8Encoding" in decoded
    assert "Write-Output '你好'" in decoded
    assert "| Microsoft.PowerShell.Core\\Out-Default" in decoded
    assert "$LASTEXITCODE" in decoded
    assert policy_subject.shell_payload == "Write-Output '你好'"
    assert policy_subject.command[-1] != policy_subject.shell_payload
    assert policy_subject.dialect == "powershell"
    assert policy_subject.shell_flavor == "windows-powershell"


def test_windows_compiler_fails_closed_when_command_line_is_too_long() -> None:
    shell = ResolvedShell(
        kind="powershell",
        executable=r"C:\Program Files\PowerShell\7\pwsh.exe",
        flavor="pwsh",
        target_id="windows-local",
        target_os_family="windows",
        source="program-files",
        edition="Core",
    )

    with pytest.raises(ShellCompileError) as raised:
        compile_shell_launch(
            shell,
            "Write-Output '" + ("x" * 1_000) + "'",
            cwd=r"C:\workspace",
            windows_command_line_limit=200,
        )

    assert raised.value.kind == "command_too_long"


def test_non_login_git_bash_compiler_uses_c_not_lc() -> None:
    shell = ResolvedShell(
        kind="bash",
        executable=r"C:\Program Files\Git\bin\bash.exe",
        flavor="git-bash",
        target_id="windows-local",
        target_os_family="windows",
        source="program-files",
    )

    launch = compile_shell_launch(shell, "pwd", cwd=r"C:\workspace")

    assert launch.argv == (shell.executable, "-c", "pwd")


@pytest.mark.skipif(os.name != "nt", reason="requires a native Windows host")
def test_native_windows_shell_executes_utf8_and_preserves_failure_exit_code(
    tmp_path,
) -> None:
    resolver = LocalShellResolver(
        environment=LocalHostEnvironmentProbe().detect(),
        cwd=str(tmp_path),
    )
    shell = resolver.resolve()
    service = ExecService()

    success = compile_shell_launch(
        shell,
        "[Console]::WriteLine('你好')",
        cwd=str(tmp_path),
    )
    success_result = asyncio.run(
        service.execute(ExecRequest(command=success.argv, cwd=str(tmp_path)))
    )
    failure = compile_shell_launch(shell, "throw 'boom'", cwd=str(tmp_path))
    failure_result = asyncio.run(
        service.execute(ExecRequest(command=failure.argv, cwd=str(tmp_path)))
    )

    assert success_result.exit_code == 0
    assert "你好" in success_result.stdout
    assert failure_result.exit_code != 0
