"""Package, executable, environment, and Git inspection for diagnostics."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution
from importlib.metadata import version as package_version
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RuntimeIdentityProfile:
    """Product labels applied to the shared runtime identity collector."""

    package_name: str
    executable_name: str
    title: str = "runtime source info"
    module_file_field: str | None = None
    related_module_file_fields: Mapping[str, str] | None = None


def collect_profiled_runtime_identity(
    *,
    profile: RuntimeIdentityProfile,
    package_module: object,
    related_modules: Mapping[str, object] | None = None,
    cwd: str | Path | None = None,
    argv0: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Collect identity and project Product-specific display field aliases."""

    identity = collect_runtime_identity(
        package_name=profile.package_name,
        package_module=package_module,
        executable_name=profile.executable_name,
        related_modules=related_modules,
        cwd=cwd,
        argv0=argv0,
        env=env,
    )
    if profile.module_file_field is not None:
        identity[profile.module_file_field] = identity["module_file"]
    related_files = identity.get("related_module_files")
    if isinstance(related_files, Mapping):
        for related_name, field_name in (
            profile.related_module_file_fields or {}
        ).items():
            identity[field_name] = related_files.get(related_name, "")
    return identity


def format_profiled_runtime_identity_text(
    identity: Mapping[str, object],
    *,
    profile: RuntimeIdentityProfile,
) -> str:
    return format_runtime_identity_text(identity, title=profile.title)


def collect_runtime_identity(
    *,
    package_name: str,
    package_module: object,
    executable_name: str,
    related_modules: Mapping[str, object] | None = None,
    cwd: str | Path | None = None,
    argv0: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Collect transportable runtime identity without product imports."""

    resolved_env = env if env is not None else os.environ
    resolved_cwd = (
        Path.cwd() if cwd is None else Path(cwd).expanduser().resolve(strict=False)
    )
    resolved_argv0 = argv0 if argv0 is not None else _argv0()
    entrypoint = resolve_entrypoint(resolved_argv0, resolved_env)
    module_file = module_file_path(package_module)
    git_info = git_identity(resolved_cwd)
    source_git_info = _source_git_identity(module_file)
    is_virtual_env = sys.prefix != sys.base_prefix
    related_files = {
        name: module_file_path(module)
        for name, module in (related_modules or {}).items()
    }
    return {
        "entrypoint": entrypoint,
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "argv0": resolved_argv0,
        "cwd": path_text(resolved_cwd),
        "package_name": package_name,
        "package_version": installed_package_version(package_name),
        "module_file": module_file,
        "package_root": package_root_from_module_file(module_file),
        "source_project_root": source_git_info["project_root"],
        "source_git_branch": source_git_info["git_branch"],
        "source_git_commit": source_git_info["git_commit"],
        "source_git_dirty": source_git_info["git_dirty"],
        "related_module_files": related_files,
        "project_root": git_info["project_root"],
        "git_branch": git_info["git_branch"],
        "git_commit": git_info["git_commit"],
        "git_dirty": git_info["git_dirty"],
        "virtual_env": resolved_env.get("VIRTUAL_ENV"),
        "sys_prefix": sys.prefix,
        "sys_base_prefix": sys.base_prefix,
        "is_virtual_env": is_virtual_env,
        "launch_mode": detect_launch_mode(
            argv0=resolved_argv0,
            entrypoint=entrypoint,
            executable_name=executable_name,
            is_virtual_env=is_virtual_env,
        ),
        "path_candidates": executable_path_candidates(
            resolved_env,
            executable_name,
            entrypoint=entrypoint,
        ),
        "import_source": import_source(package_name, module_file),
        "install_mode": install_mode(package_name, module_file),
    }


def format_runtime_identity_text(
    identity: Mapping[str, object],
    *,
    title: str = "runtime source info",
) -> str:
    """Render the stable common source-identity fields for human diagnostics."""

    lines = [title]
    for key in (
        "entrypoint",
        "python_executable",
        "python_version",
        "module_file",
        "package_root",
        "source_project_root",
        "source_git_branch",
        "source_git_commit",
        "source_git_dirty",
        "project_root",
        "git_branch",
        "git_commit",
        "git_dirty",
        "cwd",
        "virtual_env",
        "sys_prefix",
        "sys_base_prefix",
        "package_version",
        "install_mode",
        "launch_mode",
    ):
        lines.append(f"{key}: {display_value(identity.get(key))}")

    lines.append("path_candidates:")
    candidates = identity.get("path_candidates")
    if isinstance(candidates, list) and candidates:
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            lines.append(
                f"  - {display_value(candidate.get('path'))} "
                f"[{display_value(candidate.get('status'))}]"
            )
    else:
        lines.append("  <none>")
    return "\n".join(lines)


def path_text(path: str | Path | object) -> str:
    if isinstance(path, Path):
        return path.as_posix()
    if isinstance(path, str):
        return path
    return str(path)


def module_file_path(module: object) -> str:
    raw_path = getattr(module, "__file__", None)
    if not raw_path:
        return ""
    return Path(str(raw_path)).expanduser().resolve(strict=False).as_posix()


def package_root_from_module_file(module_file: str) -> str | None:
    if not module_file:
        return None
    path = Path(module_file)
    if path.name == "__init__.py":
        return path.parent.parent.as_posix()
    return path.parent.as_posix()


def installed_package_version(package_name: str, *, fallback: str = "0.1.0") -> str:
    try:
        return package_version(package_name)
    except PackageNotFoundError:
        return fallback


def import_source(package_name: str, module_file: str) -> str:
    if distribution_is_editable(package_name):
        return "editable"
    if module_file_is_source_tree(module_file):
        return "source-tree"
    if module_file_is_installed(module_file):
        return "installed"
    return "unknown"


def install_mode(package_name: str, module_file: str) -> str:
    if distribution_is_editable(package_name):
        return "editable"
    if module_file_is_source_tree(module_file):
        return "source-tree"
    if module_file_is_installed(module_file):
        return "package"
    return "unknown"


def distribution_is_editable(package_name: str) -> bool:
    try:
        direct_url = distribution(package_name).read_text("direct_url.json")
    except PackageNotFoundError:
        return False
    if not direct_url:
        return False
    try:
        payload = json.loads(direct_url)
    except json.JSONDecodeError:
        return False
    directory_info = payload.get("dir_info") if isinstance(payload, dict) else None
    return isinstance(directory_info, dict) and directory_info.get("editable") is True


def module_file_is_source_tree(module_file: str) -> bool:
    return bool(module_file) and any(
        parent.name == "src" for parent in Path(module_file).parents
    )


def module_file_is_installed(module_file: str) -> bool:
    return bool(module_file) and any(
        parent.name in {"site-packages", "dist-packages"}
        for parent in Path(module_file).parents
    )


def resolve_entrypoint(argv0: str, env: Mapping[str, str]) -> str | None:
    if not argv0:
        return None
    if looks_like_path(argv0):
        return Path(argv0).expanduser().resolve(strict=False).as_posix()
    resolved = shutil.which(argv0, path=env.get("PATH"))
    if resolved:
        return Path(resolved).expanduser().resolve(strict=False).as_posix()
    return argv0


def executable_path_candidates(
    env: Mapping[str, str],
    executable_name: str,
    *,
    entrypoint: str | None = None,
) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    seen: set[str] = set()
    active_path = _active_executable_path(entrypoint, executable_name)
    if active_path is not None:
        candidates.append(
            {
                "path": active_path,
                "status": "active",
                "active": True,
            }
        )
        seen.add(active_path)
    candidate_names = _executable_candidate_names(env, executable_name)
    for directory in os.get_exec_path(dict(env)):
        for candidate_name in candidate_names:
            candidate = Path(directory or ".") / candidate_name
            if not candidate.is_file() or not os.access(candidate, os.X_OK):
                continue
            path = candidate.expanduser().resolve(strict=False).as_posix()
            if path in seen:
                continue
            seen.add(path)
            candidates.append(
                {
                    "path": path,
                    "status": "shadowed",
                    "active": False,
                }
            )
    return candidates


def _active_executable_path(
    entrypoint: str | None,
    executable_name: str,
) -> str | None:
    if entrypoint is None or not looks_like_path(entrypoint):
        return None
    name = Path(entrypoint).name.lower()
    executable_names = {executable_name.lower(), f"{executable_name.lower()}.exe"}
    if name not in executable_names:
        return None
    return Path(entrypoint).expanduser().resolve(strict=False).as_posix()


def _executable_candidate_names(
    env: Mapping[str, str],
    executable_name: str,
) -> tuple[str, ...]:
    names = [executable_name]
    if Path(executable_name).suffix:
        return tuple(names)
    raw_extensions = env.get("PATHEXT", "")
    separator = ";" if ";" in raw_extensions else os.pathsep
    for raw_extension in raw_extensions.split(separator):
        extension = raw_extension.strip()
        if not extension:
            continue
        if not extension.startswith("."):
            extension = f".{extension}"
        candidate = f"{executable_name}{extension}"
        if candidate not in names:
            names.append(candidate)
    return tuple(names)


def git_identity(cwd: Path) -> dict[str, str | bool | None]:
    project_root = _run_git(cwd, "rev-parse", "--show-toplevel")
    if project_root is None:
        return {
            "project_root": None,
            "git_branch": None,
            "git_commit": None,
            "git_dirty": None,
        }
    branch = _run_git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    return {
        "project_root": project_root,
        "git_branch": None if branch == "HEAD" else branch,
        "git_commit": _run_git(cwd, "rev-parse", "HEAD"),
        "git_dirty": _git_worktree_dirty(cwd),
    }


def _source_git_identity(module_file: str) -> dict[str, str | bool | None]:
    if not module_file or module_file_is_installed(module_file):
        return {
            "project_root": None,
            "git_branch": None,
            "git_commit": None,
            "git_dirty": None,
        }
    return git_identity(Path(module_file).parent)


def detect_launch_mode(
    *,
    argv0: str,
    entrypoint: str | None,
    executable_name: str,
    is_virtual_env: bool,
) -> str:
    candidate = entrypoint or argv0
    name = Path(candidate).name.lower() if candidate else ""
    executable_names = {executable_name.lower(), f"{executable_name.lower()}.exe"}
    if name in executable_names:
        return "virtualenv-console-script" if is_virtual_env else "console-script"
    if name == "__main__.py":
        return "python-module"
    return "direct"


def display_value(value: object) -> str:
    return "<unknown>" if value is None or value == "" else str(value)


def _argv0() -> str:
    return sys.argv[0] if sys.argv else ""


def _run_git(cwd: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", cwd.as_posix(), *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    return output or None


def _git_worktree_dirty(cwd: Path) -> bool | None:
    try:
        result = subprocess.run(
            ["git", "-C", cwd.as_posix(), "status", "--porcelain"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def looks_like_path(value: str) -> bool:
    return os.sep in value or (os.altsep is not None and os.altsep in value)


__all__ = [
    "RuntimeIdentityProfile",
    "collect_profiled_runtime_identity",
    "collect_runtime_identity",
    "format_profiled_runtime_identity_text",
    "format_runtime_identity_text",
    "module_file_path",
]
