"""Target-aware shell resolution and script-to-argv compilation."""

from __future__ import annotations

import base64
import ntpath
import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from loushang.harness.environment import HostEnvironment, OperatingSystemFamily

ShellKind = Literal["powershell", "bash", "sh", "zsh", "cmd"]
ShellSelectionKind = Literal["auto", "powershell", "bash", "sh", "zsh", "cmd"]
ShellSource = Literal["configured", "program-files", "path", "system"]
ShellTransport = Literal["command", "encoded-command", "stdin"]
PowerShellEdition = Literal["Desktop", "Core"]
ShellResolutionErrorKind = Literal[
    "configured_path_not_absolute",
    "configured_shell_not_found",
    "shell_kind_mismatch",
    "shell_kind_required",
    "shell_unavailable",
    "unsupported_login_shell",
]
ShellCompileErrorKind = Literal["command_too_long", "unsupported_shell"]

_SHELL_KINDS = frozenset({"powershell", "bash", "sh", "zsh", "cmd"})
_WINDOWS_COMMAND_LINE_LIMIT = 30_000
_POWERSHELL_UTF8_PREFIX = """try {
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    [Console]::InputEncoding = $utf8
    [Console]::OutputEncoding = $utf8
    $OutputEncoding = $utf8
} catch {}
$global:LASTEXITCODE = $null
"""
_POWERSHELL_EXIT_SUFFIX = """
$_loushang_exit_code = if ($null -ne $LASTEXITCODE) {
    [int]$LASTEXITCODE
} elseif ($?) {
    0
} else {
    1
}
exit $_loushang_exit_code
"""

PathIsFile = Callable[[str], bool]
WhichExecutable = Callable[[str, str | None], str | None]


@dataclass(frozen=True, slots=True)
class ShellSelection:
    kind: ShellSelectionKind = "auto"
    path: str | None = None
    login: bool = False

    def __post_init__(self) -> None:
        if self.kind != "auto" and self.kind not in _SHELL_KINDS:
            raise ValueError(f"unsupported shell selection: {self.kind!r}")
        if self.path is not None and not self.path.strip():
            raise ValueError("shell path must be a non-empty string or None")
        if not isinstance(self.login, bool):
            raise TypeError("shell login must be a boolean")


@dataclass(frozen=True, slots=True)
class ResolvedShell:
    kind: ShellKind
    executable: str
    flavor: str
    target_id: str
    target_os_family: OperatingSystemFamily
    source: ShellSource
    login: bool = False
    version: str | None = None
    edition: PowerShellEdition | None = None

    def __post_init__(self) -> None:
        if self.kind not in _SHELL_KINDS:
            raise ValueError(f"unsupported resolved shell: {self.kind!r}")
        if not self.target_id:
            raise ValueError("resolved shell target_id must be non-empty")
        if not _target_path_is_absolute(self.executable, self.target_os_family):
            raise ValueError("resolved shell executable must be an absolute target path")
        if self.kind != "powershell" and self.edition is not None:
            raise ValueError("PowerShell edition requires a PowerShell shell")
        if self.kind in {"powershell", "cmd"} and self.login:
            raise ValueError("PowerShell and Cmd do not support login mode")


@dataclass(frozen=True, slots=True)
class ShellLaunch:
    shell: ResolvedShell
    plain_script: str
    transport: ShellTransport
    argv: tuple[str, ...]
    cwd: str
    effective_environment: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not self.plain_script.strip():
            raise ValueError("shell launch script must be non-empty")
        if not self.argv or self.argv[0] != self.shell.executable:
            raise ValueError("shell launch argv must start with the resolved executable")
        if not self.cwd:
            raise ValueError("shell launch cwd must be non-empty")


class ShellResolutionError(RuntimeError):
    def __init__(
        self,
        kind: ShellResolutionErrorKind,
        message: str,
        *,
        attempted_paths: tuple[str, ...] = (),
    ) -> None:
        self.kind = kind
        self.attempted_paths = attempted_paths
        super().__init__(message)


class ShellCompileError(RuntimeError):
    def __init__(self, kind: ShellCompileErrorKind, message: str) -> None:
        self.kind = kind
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class LocalShellResolver:
    environment: HostEnvironment
    target_id: str = "local"
    environ: Mapping[str, str] | None = None
    cwd: str | None = None
    path_is_file: PathIsFile = os.path.isfile
    which_executable: WhichExecutable = lambda name, path: shutil.which(
        name, path=path
    )

    def resolve(self, selection: ShellSelection | None = None) -> ResolvedShell:
        selected = selection or ShellSelection()
        if not self.target_id:
            raise ValueError("shell resolver target_id must be non-empty")
        if selected.path is not None:
            return self._resolve_configured(selected)
        if selected.login and selected.kind in {"powershell", "cmd"}:
            raise ShellResolutionError(
                "unsupported_login_shell",
                f"{selected.kind} does not support login mode",
            )
        if selected.kind == "auto":
            return self._resolve_default(selected)
        return self._resolve_kind(selected.kind, login=selected.login)

    @property
    def _environment_values(self) -> Mapping[str, str]:
        return os.environ if self.environ is None else self.environ

    def _resolve_configured(self, selection: ShellSelection) -> ResolvedShell:
        assert selection.path is not None
        if not _target_path_is_absolute(
            selection.path,
            self.environment.os_family,
        ):
            raise ShellResolutionError(
                "configured_path_not_absolute",
                f"configured shell path must be absolute: {selection.path}",
                attempted_paths=(selection.path,),
            )
        path = _normalize_target_path(selection.path, self.environment.os_family)
        if not self.path_is_file(path):
            raise ShellResolutionError(
                "configured_shell_not_found",
                f"configured shell does not exist: {path}",
                attempted_paths=(path,),
            )
        inferred = _infer_shell_kind(path)
        if selection.kind == "auto":
            if inferred is None:
                raise ShellResolutionError(
                    "shell_kind_required",
                    "custom shell paths require an explicit shell kind",
                    attempted_paths=(path,),
                )
            kind = inferred
        else:
            kind = selection.kind
            if inferred is not None and inferred != kind:
                raise ShellResolutionError(
                    "shell_kind_mismatch",
                    f"configured shell path looks like {inferred}, not {kind}",
                    attempted_paths=(path,),
                )
        if selection.login and kind in {"powershell", "cmd"}:
            raise ShellResolutionError(
                "unsupported_login_shell",
                f"{kind} does not support login mode",
                attempted_paths=(path,),
            )
        return self._resolved(path, kind, "configured", selection.login)

    def _resolve_default(self, selection: ShellSelection) -> ResolvedShell:
        if self.environment.os_family == "windows":
            return self._resolve_windows_powershell(login=selection.login)
        if self.environment.os_family in {"linux", "macos"}:
            configured = _environment_value(self._environment_values, "SHELL")
            if configured and _infer_shell_kind(configured) in {"bash", "sh", "zsh"}:
                normalized = _normalize_target_path(
                    configured,
                    self.environment.os_family,
                )
                if self.path_is_file(normalized):
                    inferred = _infer_shell_kind(normalized)
                    assert inferred is not None
                    return self._resolved(
                        normalized,
                        inferred,
                        "path",
                        selection.login,
                    )
            for kind in ("bash", "zsh", "sh"):
                hit = self._which(kind)
                if hit is not None:
                    return self._resolved(hit, kind, "path", selection.login)
        raise ShellResolutionError(
            "shell_unavailable",
            f"no supported shell is available for {self.environment.os_family}",
        )

    def _resolve_kind(self, kind: ShellKind, *, login: bool) -> ResolvedShell:
        if kind == "powershell":
            return self._resolve_windows_powershell(login=login)
        if kind == "cmd":
            if self.environment.os_family != "windows":
                raise self._unavailable(kind, ())
            system_root = _environment_value(self._environment_values, "SystemRoot")
            candidate = (
                ntpath.join(system_root, "System32", "cmd.exe")
                if system_root
                else None
            )
            if candidate and self.path_is_file(candidate):
                return self._resolved(candidate, kind, "system", login)
            raise self._unavailable(kind, (candidate,) if candidate else ())
        if self.environment.os_family == "windows" and kind == "bash":
            return self._resolve_windows_git_bash(login=login)
        hit = self._which(f"{kind}.exe" if self.environment.os_family == "windows" else kind)
        if hit is not None:
            return self._resolved(hit, kind, "path", login)
        raise self._unavailable(kind, ())

    def _resolve_windows_powershell(self, *, login: bool) -> ResolvedShell:
        if self.environment.os_family != "windows":
            hit = self._which("pwsh") or self._which("powershell")
            if hit is not None:
                return self._resolved(hit, "powershell", "path", login)
            raise self._unavailable("powershell", ())
        if login:
            raise ShellResolutionError(
                "unsupported_login_shell",
                "powershell does not support login mode",
            )

        attempted: list[str] = []
        program_files = _environment_value(self._environment_values, "ProgramFiles")
        if program_files:
            candidate = ntpath.join(program_files, "PowerShell", "7", "pwsh.exe")
            attempted.append(candidate)
            if self.path_is_file(candidate):
                return self._resolved(candidate, "powershell", "program-files", False)

        path_hit = self._which("pwsh.exe")
        if path_hit is not None:
            attempted.append(path_hit)
            return self._resolved(path_hit, "powershell", "path", False)

        system_root = _environment_value(self._environment_values, "SystemRoot")
        if system_root:
            candidate = ntpath.join(
                system_root,
                "System32",
                "WindowsPowerShell",
                "v1.0",
                "powershell.exe",
            )
            attempted.append(candidate)
            if self.path_is_file(candidate):
                return self._resolved(candidate, "powershell", "system", False)
        raise self._unavailable("powershell", tuple(attempted))

    def _resolve_windows_git_bash(self, *, login: bool) -> ResolvedShell:
        attempted: list[str] = []
        for variable in ("ProgramFiles", "ProgramFiles(x86)"):
            root = _environment_value(self._environment_values, variable)
            if not root:
                continue
            candidate = ntpath.join(root, "Git", "bin", "bash.exe")
            attempted.append(candidate)
            if self.path_is_file(candidate):
                return self._resolved(candidate, "bash", "program-files", login)
        path_hit = self._which("bash.exe")
        if path_hit is not None:
            attempted.append(path_hit)
            return self._resolved(path_hit, "bash", "path", login)
        raise self._unavailable("bash", tuple(attempted))

    def _which(self, name: str) -> str | None:
        search_path = _environment_value(self._environment_values, "PATH")
        hit = self.which_executable(name, search_path)
        if not hit:
            return None
        normalized = _normalize_target_path(hit, self.environment.os_family)
        if not _target_path_is_absolute(normalized, self.environment.os_family):
            return None
        if self._candidate_is_in_cwd(normalized):
            return None
        if not self.path_is_file(normalized):
            return None
        return normalized

    def _candidate_is_in_cwd(self, candidate: str) -> bool:
        if not self.cwd:
            return False
        return _target_path_is_within(
            candidate,
            self.cwd,
            self.environment.os_family,
        )

    def _resolved(
        self,
        executable: str,
        kind: ShellKind,
        source: ShellSource,
        login: bool,
    ) -> ResolvedShell:
        flavor, version, edition = _shell_metadata(executable, kind)
        return ResolvedShell(
            kind=kind,
            executable=_normalize_target_path(
                executable,
                self.environment.os_family,
            ),
            flavor=flavor,
            target_id=self.target_id,
            target_os_family=self.environment.os_family,
            source=source,
            login=login,
            version=version,
            edition=edition,
        )

    @staticmethod
    def _unavailable(
        kind: ShellKind,
        attempted_paths: tuple[str | None, ...],
    ) -> ShellResolutionError:
        return ShellResolutionError(
            "shell_unavailable",
            f"no {kind} shell is available",
            attempted_paths=tuple(path for path in attempted_paths if path),
        )


def compile_shell_launch(
    shell: ResolvedShell,
    script: str,
    *,
    cwd: str,
    effective_environment: tuple[tuple[str, str], ...] = (),
    windows_command_line_limit: int = _WINDOWS_COMMAND_LINE_LIMIT,
) -> ShellLaunch:
    if not isinstance(script, str) or not script.strip():
        raise ValueError("shell script must be a non-empty string")
    if not cwd:
        raise ValueError("shell cwd must be non-empty")
    if windows_command_line_limit < 1:
        raise ValueError("windows_command_line_limit must be >= 1")

    argv: tuple[str, ...]
    transport: ShellTransport
    if shell.kind == "powershell":
        compiled_script = _powershell_script(script)
        encoded = base64.b64encode(compiled_script.encode("utf-16le")).decode("ascii")
        argv = (
            shell.executable,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            encoded,
        )
        transport = "encoded-command"
    elif shell.kind == "cmd":
        argv = (shell.executable, "/d", "/s", "/c", script)
        transport = "command"
    elif shell.kind in {"bash", "sh", "zsh"}:
        argv = (shell.executable, "-lc" if shell.login else "-c", script)
        transport = "command"
    else:  # pragma: no cover - ShellKind validation prevents this branch.
        raise ShellCompileError(
            "unsupported_shell",
            f"unsupported shell kind: {shell.kind}",
        )

    if shell.target_os_family == "windows":
        command_line = subprocess.list2cmdline(argv)
        if len(command_line) >= windows_command_line_limit:
            raise ShellCompileError(
                "command_too_long",
                "compiled Windows shell command exceeds the configured safe limit",
            )
    return ShellLaunch(
        shell=shell,
        plain_script=script,
        transport=transport,
        argv=argv,
        cwd=cwd,
        effective_environment=tuple(effective_environment),
    )


def _powershell_script(script: str) -> str:
    return (
        f"{_POWERSHELL_UTF8_PREFIX}& {{\n{script}\n}} "
        "| Microsoft.PowerShell.Core\\Out-Default\n"
        f"{_POWERSHELL_EXIT_SUFFIX}"
    )


def _infer_shell_kind(path: str) -> ShellKind | None:
    name = ntpath.basename(path.replace("/", "\\")).casefold()
    if name in {"pwsh", "pwsh.exe", "powershell", "powershell.exe"}:
        return "powershell"
    if name in {"bash", "bash.exe"}:
        return "bash"
    if name in {"sh", "sh.exe"}:
        return "sh"
    if name in {"zsh", "zsh.exe"}:
        return "zsh"
    if name in {"cmd", "cmd.exe"}:
        return "cmd"
    return None


def _shell_metadata(
    executable: str,
    kind: ShellKind,
) -> tuple[str, str | None, PowerShellEdition | None]:
    name = ntpath.basename(executable.replace("/", "\\")).casefold()
    if kind == "powershell" and name in {"powershell", "powershell.exe"}:
        return "windows-powershell", "5.1", "Desktop"
    if kind == "powershell":
        return "pwsh", None, "Core"
    if kind == "bash" and executable.casefold().replace("/", "\\").endswith(
        "\\git\\bin\\bash.exe"
    ):
        return "git-bash", None, None
    return kind, None, None


def _environment_value(environment: Mapping[str, str], name: str) -> str | None:
    folded = name.casefold()
    for key, value in environment.items():
        if key.casefold() == folded:
            return value
    return None


def _normalize_target_path(path: str, os_family: OperatingSystemFamily) -> str:
    if os_family == "windows":
        return ntpath.normpath(path)
    return os.path.abspath(path)


def _target_path_is_absolute(
    path: str,
    os_family: OperatingSystemFamily,
) -> bool:
    return ntpath.isabs(path) if os_family == "windows" else os.path.isabs(path)


def _target_path_is_within(
    path: str,
    parent: str,
    os_family: OperatingSystemFamily,
) -> bool:
    path_module = ntpath if os_family == "windows" else os.path
    normalized_path = path_module.normcase(path_module.abspath(path))
    normalized_parent = path_module.normcase(path_module.abspath(parent))
    try:
        return path_module.commonpath((normalized_path, normalized_parent)) == normalized_parent
    except ValueError:
        return False


__all__ = [
    "LocalShellResolver",
    "PowerShellEdition",
    "ResolvedShell",
    "ShellCompileError",
    "ShellCompileErrorKind",
    "ShellKind",
    "ShellLaunch",
    "ShellResolutionError",
    "ShellResolutionErrorKind",
    "ShellSelection",
    "ShellSelectionKind",
    "ShellSource",
    "ShellTransport",
    "compile_shell_launch",
]
