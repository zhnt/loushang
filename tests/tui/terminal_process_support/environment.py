from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

_IDENTITY_VARIABLES = {
    "colorterm",
    "ghostty_resources_dir",
    "ghostty_bin_dir",
    "kitty_listen_on",
    "kitty_pid",
    "ssh_client",
    "ssh_connection",
    "ssh_tty",
    "sty",
    "term_program",
    "term_program_version",
    "tmux",
    "wezterm_executable",
    "wezterm_pane",
    "wsl_distro_name",
    "wsl_interop",
    "wt_profile_id",
    "wt_session",
}


def terminal_test_environment(
    repo_root: Path,
    *,
    base: Mapping[str, str] | None = None,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    source = dict(os.environ if base is None else base)
    env = {
        key: value
        for key, value in source.items()
        if key.casefold() not in _IDENTITY_VARIABLES
    }
    _set_case_insensitive(env, "TERM", "xterm-256color")
    _set_case_insensitive(env, "COLORTERM", "truecolor")
    _set_case_insensitive(env, "PYTHONUNBUFFERED", "1")
    existing_pythonpath = _get_case_insensitive(env, "PYTHONPATH")
    pythonpath = str(repo_root / "src")
    if existing_pythonpath:
        pythonpath = f"{pythonpath}{os.pathsep}{existing_pythonpath}"
    _set_case_insensitive(env, "PYTHONPATH", pythonpath)
    for key, value in (extra or {}).items():
        _set_case_insensitive(env, key, value)
    return env


def _get_case_insensitive(env: Mapping[str, str], name: str) -> str | None:
    return next(
        (value for key, value in env.items() if key.casefold() == name.casefold()),
        None,
    )


def _set_case_insensitive(env: dict[str, str], name: str, value: str) -> None:
    for key in tuple(env):
        if key.casefold() == name.casefold():
            del env[key]
    env[name] = value
