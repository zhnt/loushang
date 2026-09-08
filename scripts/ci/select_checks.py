"""Select checks from Git changes without importing or installing the product.

The plan is shared by local development and GitHub Actions. Rules are additive;
unknown non-document paths deliberately select the full suite.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def git(*args: str, root: Path = ROOT) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root)


def changed_paths(base: str, head: str, *, root: Path = ROOT) -> list[str]:
    # Treat renames as delete + add, so both the old and new owners are checked.
    data = git("diff", "--name-only", "--no-renames", "-z", base, head, "--", root=root)
    return sorted({os.fsdecode(path) for path in data.split(b"\0") if path})


def local_paths(base: str, *, root: Path = ROOT) -> list[str]:
    ancestor = git("merge-base", base, "HEAD", root=root).decode().strip()
    paths = changed_paths(ancestor, "HEAD", root=root)
    for args in (
        ("diff", "--name-only", "--no-renames", "-z", "HEAD", "--"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    ):
        paths.extend(os.fsdecode(p) for p in git(*args, root=root).split(b"\0") if p)
    return sorted(set(paths))


def make_paths(root: Path = ROOT) -> dict[str, list[str]]:
    text = (root / "Makefile").read_text().replace("\\\n", " ")
    return {
        match[1]: match[2].split()
        for match in re.finditer(r"^(\w+)\s*:=\s*(.*)$", text, re.M)
    }


def select(paths: list[str], *, full: bool = False, root: Path = ROOT) -> dict:
    rules = json.loads((root / "scripts/ci/check-scopes.json").read_text())
    checks = {name: False for name in rules["checks"]}
    reasons: dict[str, list[str]] = {name: [] for name in checks}

    def enable(names: list[str], reason: str) -> None:
        for name in names:
            if name not in checks:
                raise ValueError(f"unknown check {name!r}")
            checks[name] = True
            if reason not in reasons[name]:
                reasons[name].append(reason)

    enable(["docs"], "repository documentation invariants")
    if full:
        enable(list(checks), "explicit full validation")
    variables = make_paths(root)
    for path in sorted(set(paths)):
        if path.startswith("src/") and path.endswith(".py"):
            enable(["architecture"], f"{path}: source dependency facts")
        if (
            path
            == "docs/internals/architecture/generated/current-package-dependencies.md"
        ):
            enable(["architecture"], f"{path}: generated source dependency facts")
            continue
        ordinary_document = not path.startswith("tests/") and (
            path.startswith("docs/")
            or "/" not in path
            or Path(path).name in {"README.md", "AGENTS.md", "TODO.md"}
        )
        if (path.endswith((".md", ".rst")) and ordinary_document) or path in rules[
            "document_files"
        ]:
            enable(["docs"], f"{path}: documentation")
            continue
        matched = False
        for rule in rules["rules"]:
            if any(fnmatch.fnmatchcase(path, pattern) for pattern in rule["paths"]):
                enable(rule["checks"], f"{path}: {rule['reason']}")
                matched = True
        # Reuse the actual coverage inventories instead of copying hundreds of
        # support files into a second, drifting list of path filters.
        for name, variable_names in rules["make_scopes"].items():
            for variable in variable_names:
                if variable not in variables:
                    raise ValueError(f"missing Makefile inventory {variable}")
                if any(
                    path == p or path.startswith(p + "/") for p in variables[variable]
                ):
                    enable([name], f"{path}: {variable}")
                    matched = True
        for covered in variables["HARNESSTUI_TEST_PATHS"]:
            if path == covered or path.startswith(covered + "/"):
                scope = (
                    "coding_ui" if covered.startswith("tests/coding/") else "harnesstui"
                )
                enable([scope], f"{path}: HARNESSTUI_TEST_PATHS")
                matched = True
        if not matched:
            enable(list(checks), f"{path}: unclassified path (full validation)")

    while True:
        before = checks.copy()
        for check, dependencies in rules["check_dependencies"].items():
            if checks[check]:
                enable(dependencies, f"required by {check}")
        if before == checks:
            break
    workflows = {
        name: any(checks[check] for check in scopes)
        for name, scopes in rules["workflows"].items()
    }
    return {
        "version": 1,
        "paths": sorted(set(paths)),
        "checks": checks,
        "workflows": workflows,
        "reasons": reasons,
    }


def event_paths(
    event_name: str, event: dict, *, root: Path = ROOT
) -> tuple[list[str], bool]:
    if event_name in {"schedule", "workflow_dispatch"}:
        return [], True
    if event_name == "pull_request":
        pr = event["pull_request"]
        ancestor = (
            git("merge-base", pr["base"]["sha"], pr["head"]["sha"], root=root)
            .decode()
            .strip()
        )
        return changed_paths(ancestor, pr["head"]["sha"], root=root), False
    if event_name == "push":
        before, after = event["before"], event["after"]
        if before == "0" * 40:
            return [], True
        return changed_paths(before, after, root=root), False
    raise ValueError(f"unsupported event {event_name!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--head")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--event", action="store_true")
    parser.add_argument("--paths", nargs="+")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    full = args.full
    if args.event:
        paths, event_full = event_paths(
            os.environ["GITHUB_EVENT_NAME"],
            json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text()),
        )
        full = full or event_full
    elif args.paths is not None:
        paths = args.paths
    elif args.head:
        paths = changed_paths(args.base, args.head)
    elif full:
        paths = []
    else:
        paths = local_paths(args.base)
    plan = select(paths, full=full)
    if args.output:
        args.output.write_text(json.dumps(plan, indent=2) + "\n")
    print(json.dumps(plan, indent=2))
    if args.event:
        # Never put filenames in output keys or executable shell text.
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
            stream.write("plan=" + json.dumps(plan, separators=(",", ":")) + "\n")
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as stream:
            stream.write("## Selected checks\n\n")
            for check, enabled in plan["checks"].items():
                stream.write(f"- {check}: {'run' if enabled else 'not applicable'}\n")
            stream.write("\nReasons are recorded in the selection job log.\n")


if __name__ == "__main__":
    main()
