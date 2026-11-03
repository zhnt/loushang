"""Share immutable import facts across source checks within one test process."""
from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=4096)
def _import_facts(filename: str, source: str) -> tuple[tuple[int | None, str, tuple[str, ...]], ...]:
    facts = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if isinstance(node, ast.Import):
            facts.append((None, "", tuple(alias.name for alias in node.names)))
        elif isinstance(node, ast.ImportFrom):
            facts.append((node.level, node.module or "", tuple(alias.name for alias in node.names)))
    return tuple(facts)


def resolved_imports(path: Path, source: str | None = None, *,
                     include_members: bool = True,
                     reject_invalid_relative: bool = True) -> set[str]:
    # Read content each time: edits remain visible even if timestamps/size repeat.
    # Cache only immutable facts, never a mutable AST or Product/runtime state.
    if source is None:
        source = path.read_text(encoding="utf-8")
    try:
        package = path.parent.relative_to("src").parts
    except ValueError:
        package = path.parent.resolve().relative_to(Path("src").resolve()).parts
    result = set()
    for level, module, names in _import_facts(str(path), source):
        if level is None:
            result.update(names)
            continue
        retained = len(package) - (level - 1) if level else 0
        if level and retained < 0 and reject_invalid_relative:
            result.add("<invalid-relative-import>")
            continue
        base = ((*package[:retained], *module.split(".")) if level
                else tuple(module.split(".")))
        base = tuple(part for part in base if part)
        if base:
            result.add(".".join(base))
        if include_members:
            result.update(".".join((*base, name)) for name in names)
    return result


def imported_modules(path: Path, source: str | None = None) -> set[str]:
    """Return the raw module names declared by import statements.

    Unlike ``resolved_imports``, this preserves the historical behavior of
    source inventory tests: relative import levels are ignored and imported
    members are not expanded.  The shared immutable parse facts still avoid
    reparsing the same source in every architecture contract.
    """
    if source is None:
        source = path.read_text(encoding="utf-8")
    modules: set[str] = set()
    for level, module, names in _import_facts(str(path), source):
        if level is None:
            modules.update(names)
        elif module:
            modules.add(module)
    return modules
