"""Reviewed test roles, distinct from the historical fast-path file inventory."""
from __future__ import annotations

import ast
import json
from pathlib import Path

CATALOG_FILE = "scripts/ci/test-classification.json"
CATALOG_VERSION = 6
MODULE_CATEGORIES = {"unit", "contract"}
TARGETED_CATEGORIES = {"integration", "platform", "live", "e2e"}
TARGETED_RUNNERS = {"ubuntu-24.04", "macos-15", "windows-2022"}
MODULE_EXTRA_TESTS = {
    "ai": ["tests/protocols", "tests/examples/test_ai_examples.py",
           "tests/examples/test_auth_examples.py"],
    "agent": ["tests/examples/test_agent_examples.py"],
    "coding": ["tests/examples/test_coding_examples.py"],
    "harness": ["tests/examples/test_harness_tool_authoring_example.py",
                "tests/examples/test_harness_document_product_example.py"],
}
_CHECKOUT_ROOT = Path(__file__).resolve().parents[2]
_VALIDATED_CHECKOUT_CATALOG: dict | None = None


def load_catalog(root: Path) -> dict:
    global _VALIDATED_CHECKOUT_CATALOG
    root = root.resolve()
    if root == _CHECKOUT_ROOT and _VALIDATED_CHECKOUT_CATALOG is not None:
        # A CI process sees one immutable checkout. Full validation scans every
        # classified directory and parses targeted test nodes, so reuse it for
        # the many routing examples in that process. Other roots remain
        # uncached because catalog tests intentionally mutate them.
        return _VALIDATED_CHECKOUT_CATALOG
    path = root / CATALOG_FILE
    if not path.exists():
        # During incremental migration, absence retains the complete old route.
        return {
            "version": CATALOG_VERSION,
            "modules": {},
            "targeted_overrides": {},
            "targeted_nodes": {},
        }
    catalog = json.loads(path.read_text())
    if (not isinstance(catalog, dict)
            or catalog.get("version") != CATALOG_VERSION
            or not isinstance(catalog.get("modules"), dict)
            or not isinstance(catalog.get("targeted_overrides", {}), dict)
            or not isinstance(catalog.get("targeted_nodes", {}), dict)):
        raise ValueError("invalid test classification catalog")
    for module, entry in catalog["modules"].items():
        if not module.isidentifier() or not isinstance(entry, dict) or entry.get("complete") is not True:
            raise ValueError(f"unreviewed classified module: {module}")
        files = entry.get("files")
        if not isinstance(files, dict) or not files:
            raise ValueError(f"empty classified module: {module}")
        discovered = {p.relative_to(root).as_posix()
                      for p in (root / "tests" / module).rglob("test_*.py")}
        for extra in MODULE_EXTRA_TESTS.get(module, []):
            extra_path = root / extra
            if not extra_path.exists():
                raise ValueError(f"missing module regression path {extra!r}")
            if extra_path.is_dir():
                discovered.update(p.relative_to(root).as_posix()
                                  for p in extra_path.rglob("test_*.py"))
            else:
                discovered.add(extra)
        if set(files) != discovered:
            raise ValueError(f"test classification incomplete for {module}: "
                             f"missing={sorted(discovered - set(files))}, "
                             f"stale={sorted(set(files) - discovered)}")
        for file, role in files.items():
            if (not isinstance(role, dict)
                    or role.get("category") not in MODULE_CATEGORIES | TARGETED_CATEGORIES
                    or not isinstance(role.get("assertion"), str)
                    or not role["assertion"].strip()):
                raise ValueError(f"invalid reviewed test role: {file}")
            _validate_platforms(file, role)
        if not any(role["category"] in MODULE_CATEGORIES for role in files.values()):
            raise ValueError(f"classified module has no unit or contract tests: {module}")
        fixtures = entry.get("fixtures", {})
        if not isinstance(fixtures, dict):
            raise ValueError(f"invalid fixture inventory: {module}")
        for fixture, role in fixtures.items():
            if (not fixture.startswith(f"tests/{module}/")
                    or ".." in Path(fixture).parts or fixture in files
                    or not (root / fixture).is_file()):
                raise ValueError(f"invalid or missing dedicated fixture: {fixture}")
            if (not isinstance(role, dict)
                    or role.get("category") not in MODULE_CATEGORIES | TARGETED_CATEGORIES
                    or not isinstance(role.get("assertion"), str) or not role["assertion"].strip()):
                raise ValueError(f"invalid dedicated fixture role: {fixture}")
            _validate_platforms(fixture, role)
            consumers = role.get("consumers")
            if (not isinstance(consumers, list) or not consumers
                    or not all(isinstance(consumer, str) for consumer in consumers)
                    or len(set(consumers)) != len(consumers)
                    or set(consumers) - set(files)):
                raise ValueError(f"unreviewed dedicated fixture consumers: {fixture}")
    for module, entry in catalog.get("targeted_overrides", {}).items():
        if (not module.isidentifier() or module in catalog["modules"]
                or not isinstance(entry, dict)):
            raise ValueError(f"invalid partial targeted module: {module}")
        files = entry.get("files")
        if not isinstance(files, dict) or not files:
            raise ValueError(f"empty targeted override: {module}")
        discovered = {
            path.relative_to(root).as_posix()
            for path in (root / "tests" / module).rglob("test_*.py")
        }
        for path, role in files.items():
            if path not in discovered:
                raise ValueError(f"missing targeted override: {path}")
            if (not isinstance(role, dict)
                    or role.get("category") not in TARGETED_CATEGORIES
                    or role.get("category") == "live"
                    or not isinstance(role.get("assertion"), str)
                    or not role["assertion"].strip()):
                raise ValueError(f"invalid targeted override: {path}")
            _validate_platforms(path, role)
    for module, entry in catalog.get("targeted_nodes", {}).items():
        if not module.isidentifier() or not isinstance(entry, dict):
            raise ValueError(f"invalid targeted node module: {module}")
        files = entry.get("files")
        if not isinstance(files, dict) or not files:
            raise ValueError(f"empty targeted nodes: {module}")
        discovered = {
            path.relative_to(root).as_posix()
            for path in (root / "tests" / module).rglob("test_*.py")
        }
        whole_files = catalog.get("targeted_overrides", {}).get(module, {}).get(
            "files", {}
        )
        for path, role in files.items():
            if path not in discovered:
                raise ValueError(f"missing targeted node file: {path}")
            if path in whole_files:
                raise ValueError(f"targeted node overlaps whole-file override: {path}")
            if (not isinstance(role, dict)
                    or role.get("category") not in TARGETED_CATEGORIES - {"live"}
                    or not isinstance(role.get("assertion"), str)
                    or not role["assertion"].strip()):
                raise ValueError(f"invalid targeted nodes: {path}")
            _validate_platforms(path, role)
            nodes = role.get("nodes")
            if (not isinstance(nodes, list) or not nodes
                    or not all(isinstance(node, str) and node for node in nodes)
                    or len(nodes) != len(set(nodes))):
                raise ValueError(f"invalid targeted node list: {path}")
            available = _test_nodes(root / path)
            unknown = set(nodes) - available
            if unknown:
                raise ValueError(f"missing targeted test nodes in {path}: {sorted(unknown)}")
    if root == _CHECKOUT_ROOT:
        _VALIDATED_CHECKOUT_CATALOG = catalog
    return catalog


def module_unit_paths(module: str, *, root: Path) -> list[str] | None:
    catalog = load_catalog(root)
    entry = catalog["modules"].get(module)
    if entry:
        return sorted(
            path for path, role in entry["files"].items()
            if role["category"] in MODULE_CATEGORIES
        )
    override = catalog.get("targeted_overrides", {}).get(module)
    if not override:
        return None
    discovered = {
        path.relative_to(root).as_posix()
        for path in (root / "tests" / module).rglob("test_*.py")
    }
    for extra in MODULE_EXTRA_TESTS.get(module, []):
        extra_path = root / extra
        discovered.update(
            path.relative_to(root).as_posix() for path in (
                extra_path.rglob("test_*.py") if extra_path.is_dir() else [extra_path]
            )
        )
    return sorted(discovered - set(override["files"]))


def module_is_fully_classified(module: str, *, root: Path) -> bool:
    return module in load_catalog(root)["modules"]


def module_targeted_nodeids(module: str, *, root: Path) -> list[str]:
    entry = load_catalog(root).get("targeted_nodes", {}).get(module, {})
    return sorted(
        f"{path}::{node}"
        for path, role in entry.get("files", {}).items()
        for node in role["nodes"]
    )


def reviewed_unit_owner(path: str, *, catalog: dict) -> str | None:
    for module, entry in catalog["modules"].items():
        reviewed_file = entry["files"].get(path)
        if (
            reviewed_file is not None
            and reviewed_file["category"] in MODULE_CATEGORIES
        ) or (
            path in entry.get("fixtures", {})
            and entry["fixtures"][path]["category"] in MODULE_CATEGORIES
        ):
            return module
    return None


def targeted_node_owner(path: str, *, catalog: dict) -> str | None:
    for module, entry in catalog.get("targeted_nodes", {}).items():
        if path in entry["files"]:
            return module
    return None


def targeted_test_cases(path: str, *, catalog: dict) -> list[tuple[str, dict]]:
    """Return directly runnable reviewed tests affected by a targeted change."""
    cases: list[tuple[str, dict]] = []
    for entry in catalog["modules"].values():
        role = entry["files"].get(path)
        if role is not None and role["category"] in TARGETED_CATEGORIES - {"live"}:
            cases.append((path, role))
        fixture = entry.get("fixtures", {}).get(path)
        if fixture is None or fixture["category"] not in TARGETED_CATEGORIES - {"live"}:
            continue
        for consumer in fixture["consumers"]:
            consumer_role = entry["files"][consumer]
            if consumer_role["category"] not in TARGETED_CATEGORIES - {"live"}:
                raise ValueError(f"targeted fixture has non-targeted consumer: {path}")
            cases.append((consumer, consumer_role))
    for entry in catalog.get("targeted_overrides", {}).values():
        role = entry["files"].get(path)
        if role is not None:
            cases.append((path, role))
    for entry in catalog.get("targeted_nodes", {}).values():
        role = entry["files"].get(path)
        if role is not None:
            cases.extend((f"{path}::{node}", role) for node in role["nodes"])
    return cases


def all_targeted_test_cases(*, catalog: dict) -> list[tuple[str, dict]]:
    """Return every offline targeted owner for explicit full validation."""
    cases: list[tuple[str, dict]] = []
    for entry in catalog["modules"].values():
        cases.extend(
            (path, role)
            for path, role in entry["files"].items()
            if role["category"] in TARGETED_CATEGORIES - {"live"}
        )
    for entry in catalog.get("targeted_overrides", {}).values():
        cases.extend(entry["files"].items())
    for entry in catalog.get("targeted_nodes", {}).values():
        for path, role in entry["files"].items():
            cases.extend((f"{path}::{node}", role) for node in role["nodes"])
    return sorted(cases, key=lambda case: case[0])


def _test_nodes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    nodes: set[str] = set()
    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name.startswith("test_"):
                nodes.add(item.name)
        elif isinstance(item, ast.ClassDef):
            for child in item.body:
                if (isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name.startswith("test_")):
                    nodes.add(f"{item.name}::{child.name}")
    return nodes


def _validate_platforms(path: str, role: dict) -> None:
    category = role["category"]
    platforms = role.get("platforms")
    if category in TARGETED_CATEGORIES - {"live"}:
        if (not isinstance(platforms, list) or not platforms
                or not all(isinstance(platform, str) for platform in platforms)
                or len(platforms) != len(set(platforms))
                or set(platforms) - TARGETED_RUNNERS):
            raise ValueError(f"invalid targeted test platforms: {path}")
    elif platforms is not None:
        raise ValueError(f"non-targeted test declares platforms: {path}")
