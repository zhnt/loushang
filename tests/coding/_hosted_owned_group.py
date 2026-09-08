"""Test-only observation of the H2 owned group, not arbitrary fork containment."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def process_groups():
    result = subprocess.run(
        ["/bin/ps", "-axo", "pid=,pgid=,stat="], check=True,
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5,
    )
    if len(result.stdout) > 8 * 1024 * 1024:
        raise RuntimeError("native group table exceeds observation bound")
    table = {}
    for line in result.stdout.splitlines():
        pid, pgid, state = line.split()
        pid, pgid = int(pid), int(pgid)
        if pid < 0 or pgid < 0 or pid in table or len(table) >= 65536:
            raise RuntimeError("invalid native group table")
        table[pid] = (pgid, state)
    # An empty/truncated response cannot stand in for a complete native table.
    if os.getpid() not in table:
        raise RuntimeError("native group table lacks its observer")
    return table


def group_empty(pgid):
    if type(pgid) is not int or pgid <= 1:
        raise ValueError("invalid admitted process group")
    try:
        os.killpg(pgid, 0)  # Observation only; never terminate a historical group.
    except ProcessLookupError:
        pass
    except PermissionError:
        return False
    else:
        return False
    # Darwin signal-zero can omit zombies: require independent full membership.
    return all(group != pgid for group, _ in process_groups().values())


def isolated_git_environment(root, arguments, environment):
    root = Path(root).resolve(strict=True)
    if arguments.count("--workspace") != 1:
        raise ValueError("native fixture requires one explicit workspace")
    workspace = Path(arguments[arguments.index("--workspace") + 1]).resolve(strict=True)
    if not workspace.is_relative_to(root) or not workspace.is_dir():
        raise ValueError("native fixture workspace is outside its private root")
    current = workspace
    while True:
        if os.path.lexists(current / ".git"):
            raise ValueError("native fixture workspace must not contain a Git repository")
        if current == root:
            break
        current = current.parent
    ceiling = str(root.parent)
    if os.pathsep in ceiling:
        raise ValueError("native fixture Git ceiling cannot be represented")
    sealed = {key: value for key, value in environment.items()
              if not key.casefold().startswith("git_")}
    sealed.update({
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CEILING_DIRECTORIES": ceiling,
        # Also protect source identity queries outside the workspace ceiling
        # when the native supplement uses an editable installation.
        "GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "core.fsmonitor",
        "GIT_CONFIG_VALUE_0": "false", "GIT_CONFIG_KEY_1": "core.hooksPath",
        "GIT_CONFIG_VALUE_1": os.devnull,
    })
    return sealed
