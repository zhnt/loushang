"""Compare product source volume against a frozen Git revision (read only).

This is a local accounting aid, not a CI gate. Review still establishes that
changes consolidate responsibilities without moving or dropping functionality.
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import tarfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS = "src/loushang/harness/"
PRODUCT_ROOTS = (
    "src/",
    "gui/src/",
    "gui/src-tauri/src/",
    "gui/contracts/generated/",
)
SOURCE_SUFFIXES = frozenset(
    {
        ".py",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".rs",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".css",
        ".html",
        ".sh",
        ".go",
        ".java",
        ".kt",
        ".swift",
    }
)


def git(*arguments: str) -> bytes:
    return subprocess.check_output(["git", *arguments], cwd=ROOT)


def is_source(path: str) -> bool:
    return path.startswith(PRODUCT_ROOTS) and Path(path).suffix in SOURCE_SUFFIXES


def baseline_counts(revision: str) -> dict[str, int]:
    archive = git("archive", "--format=tar", revision, *PRODUCT_ROOTS)
    counts = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as files:
        for member in files:
            if member.isfile() and is_source(member.name):
                stream = files.extractfile(member)
                assert stream is not None
                counts[member.name] = len(stream.read().splitlines())
    return counts


def working_counts() -> dict[str, int]:
    paths = (
        git(
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            *PRODUCT_ROOTS,
        )
        .decode()
        .split("\0")
    )
    return {
        path: len((ROOT / path).read_bytes().splitlines())
        for path in set(paths)
        if is_source(path) and (ROOT / path).is_file()
    }


def report(revision: str) -> dict[str, object]:
    before = baseline_counts(revision)
    after = working_counts()
    modules: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    outside_growth = 0
    for path in before.keys() | after.keys():
        old, new = before.get(path, 0), after.get(path, 0)
        if path.startswith(HARNESS):
            module = path.removeprefix(HARNESS).split("/")[0]
            module = "(root)" if module.endswith(".py") else module
            modules[module][0] += old
            modules[module][1] += new
        else:
            outside_growth += max(0, new - old)
    old_harness = sum(old for old, _ in modules.values())
    new_harness = sum(new for _, new in modules.values())
    return {
        "baseline_commit": git("rev-parse", revision).decode().strip(),
        "working_head": git("rev-parse", "HEAD").decode().strip(),
        "includes_uncommitted_source": True,
        "product_roots": PRODUCT_ROOTS,
        "source_suffixes": sorted(SOURCE_SUFFIXES),
        "harness_before": old_harness,
        "harness_after": new_harness,
        "harness_net_deleted": old_harness - new_harness,
        "outside_harness_added_lines_debited": outside_growth,
        "effective_net_deleted": old_harness - new_harness - outside_growth,
        "product_before": sum(before.values()),
        "product_after": sum(after.values()),
        "product_net_deleted": sum(before.values()) - sum(after.values()),
        "modules": {
            name: {"before": old, "after": new, "net_deleted": old - new}
            for name, (old, new) in sorted(modules.items())
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    print(json.dumps(report(parser.parse_args().baseline), indent=2) + "\n", end="")
