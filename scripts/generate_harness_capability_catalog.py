from __future__ import annotations

import argparse
import ast
import difflib
import importlib
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
CATALOG_PATH = (
    ROOT
    / "docs"
    / "internals"
    / "architecture"
    / "harness"
    / "capability-catalog.md"
)

if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from loushang.harness.capabilities.contracts import (  # noqa: E402
    CapabilityDefinition,
    CapabilityRequirement,
)

SymbolRef = str
ConsumerRole = tuple[SymbolRef, tuple[SymbolRef, ...]]


@dataclass(frozen=True)
class CapabilitySeam:
    definition: SymbolRef
    providers: tuple[SymbolRef, ...]
    consumers: tuple[ConsumerRole, ...]
    production_mounts: tuple[SymbolRef, ...] = ()

    @property
    def mount_status(self) -> str:
        return "production-mounted" if self.production_mounts else "source-complete"


SOURCE_BACKED_SEAMS = (
    CapabilitySeam(
        definition=(
            "loushang.harness.capabilities.resources_contracts:"
            "RESOURCES_CAPABILITY_DEFINITION"
        ),
        providers=(
            "loushang.harness.capabilities.resources_provider:"
            "resources_capability_provider_binding",
        ),
        consumers=(
            (
                "loushang.harness.capabilities.resources_consumers:"
                "ResourceActivationCapabilityConsumer",
                (
                    "loushang.harness.capabilities.resources_contracts:"
                    "RESOURCES_ACTIVATION_REQUIREMENT",
                ),
            ),
            (
                "loushang.harness.capabilities.resources_consumers:"
                "ResourcePromptCapabilityConsumer",
                (
                    "loushang.harness.capabilities.resources_contracts:"
                    "RESOURCES_PROMPT_REQUIREMENT",
                ),
            ),
            (
                "loushang.harness.capabilities.resources_consumers:"
                "ResourceToolPackCapabilityConsumer",
                (
                    "loushang.harness.capabilities.resources_contracts:"
                    "RESOURCES_TOOL_PACK_REQUIREMENT",
                ),
            ),
            (
                "loushang.harness.capabilities.resources_consumers:"
                "ResourceCommandPackCapabilityConsumer",
                (
                    "loushang.harness.capabilities.resources_contracts:"
                    "RESOURCES_COMMAND_PACK_REQUIREMENT",
                ),
            ),
        ),
    ),
    CapabilitySeam(
        definition=(
            "loushang.harness.capabilities.workspace_contracts:"
            "WORKSPACE_CAPABILITY_DEFINITION"
        ),
        providers=(
            "loushang.harness.capabilities.workspace_provider:"
            "workspace_capability_provider_binding",
        ),
        consumers=(
            (
                "loushang.harness.capabilities.workspace_tool_consumer:"
                "WorkspaceToolCapabilityConsumer",
                (
                    "loushang.harness.capabilities.workspace_contracts:"
                    "WORKSPACE_TOOL_REQUIREMENT",
                ),
            ),
            (
                "loushang.harness.capabilities.workspace_process_consumer:"
                "WorkspaceProcessCapabilityConsumer",
                (
                    "loushang.harness.capabilities.workspace_contracts:"
                    "WORKSPACE_PROCESS_REQUIREMENT",
                ),
            ),
        ),
    ),
    CapabilitySeam(
        definition=(
            "loushang.harness.capabilities.model_input_contracts:"
            "MODEL_INPUT_CAPABILITY_DEFINITION"
        ),
        providers=(
            "loushang.harness.session.model_call:"
            "build_session_model_call_capability_binding",
        ),
        consumers=(
            (
                "loushang.harness.session.model_call:"
                "SessionModelCallCapabilityConsumer",
                (
                    "loushang.harness.capabilities.model_input_contracts:"
                    "MODEL_INPUT_PREPARATION_REQUIREMENT",
                ),
            ),
        ),
        production_mounts=(
            "loushang.harness.session.agent_product:AgentProductSession",
        ),
    ),
)


def load_catalog_entries() -> tuple[tuple[CapabilitySeam, CapabilityDefinition], ...]:
    discovered = _discover_definition_refs()
    declared = frozenset(seam.definition for seam in SOURCE_BACKED_SEAMS)
    if discovered != declared:
        raise RuntimeError(
            "Capability catalog coverage mismatch; "
            f"missing={sorted(discovered - declared)!r}, "
            f"stale={sorted(declared - discovered)!r}"
        )

    loaded: list[tuple[CapabilitySeam, CapabilityDefinition]] = []
    capability_ids: set[str] = set()
    for seam in SOURCE_BACKED_SEAMS:
        definition = _resolve(seam.definition)
        if not isinstance(definition, CapabilityDefinition):
            raise TypeError(f"catalog Definition has wrong type: {_label(seam.definition)}")
        if definition.capability_id in capability_ids:
            raise RuntimeError(
                f"duplicate catalog Capability id: {definition.capability_id}"
            )
        capability_ids.add(definition.capability_id)
        _validate_providers(seam)
        _validate_consumers(seam, definition)
        _validate_production_mounts(seam)
        loaded.append((seam, definition))
    return tuple(sorted(loaded, key=lambda item: item[1].capability_id))


def render_catalog() -> str:
    rows = [_render_row(seam, definition) for seam, definition in load_catalog_entries()]
    return "\n".join(
        (
            "<!-- Generated by scripts/generate_harness_capability_catalog.py; "
            "do not edit by hand. -->",
            "",
            "# Harness Capability Catalog",
            "",
            "Status: generated source projection.",
            "",
            "This catalog lists only source-backed, role-complete Capability seams. It "
            "is a read-only documentation projection, not a runtime registry, selection "
            "authority, or service locator. The accepted future Capability budget "
            "remains defined by [Capability Dependency And Mount Lifecycle]"
            "(capability-dependency-and-mount-lifecycle.md).",
            "",
            "A Capability appears here only after its Definition, Provider, requirement,",
            "and Consumer symbols all exist in source. `source-complete` does not imply",
            "that a Product mounts the seam. `production-mounted` requires a declared",
            "production composition reference that resolves to a callable source symbol.",
            "Mounted Providers use the",
            "existing `RuntimeCapabilityGraphBinder`; owner-scoped live contributions",
            "use `RegistrationScope`.",
            "",
            "Regenerate with:",
            "",
            "```bash",
            ".venv/bin/python scripts/generate_harness_capability_catalog.py",
            "```",
            "",
            "Verify without writing with `--check`.",
            "",
            "## Source-Backed Capability Seams",
            "",
            "| Capability | Mount status | Contract | Lifecycle | Facets | Definition | "
            "Provider | Consumer requirements | Consumer |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            *rows,
            "",
            "## Coverage Boundary",
            "",
            "`harness.session`, `coding.lsp`, and `coding.arch` remain accepted rollout "
            "targets, but they are deliberately absent from the "
            "table until each has a complete source-backed Definition / Provider /",
            "Consumer seam. Fine-grained Runtime Profile slots and individual Tools,",
            "hooks, resources, and Extension contributions do not become top-level",
            "Capability nodes.",
            "",
        )
    )


def _render_row(seam: CapabilitySeam, definition: CapabilityDefinition) -> str:
    provider_text = "<br>".join(f"`{_label(item)}`" for item in seam.providers)
    requirement_text = "<br>".join(
        f"`{_label(requirement)}`"
        for _consumer, requirements in seam.consumers
        for requirement in requirements
    )
    consumer_text = "<br>".join(
        f"`{_label(consumer)}`" for consumer, _requirements in seam.consumers
    )
    facets = "<br>".join(f"`{facet}`" for facet in definition.facets)
    lifecycle = (
        f"`{definition.scope}` / `{definition.refresh_boundary}` / "
        f"`{definition.phase}`"
    )
    mount_status = f"`{seam.mount_status}`"
    if seam.production_mounts:
        mount_status += "<br>" + "<br>".join(
            f"`{_label(item)}`" for item in seam.production_mounts
        )
    return (
        f"| `{definition.capability_id}` | {mount_status} | "
        f"v{definition.contract_version} / "
        f"`{definition.owner_id}` | {lifecycle} | {facets} | "
        f"`{_label(seam.definition)}` | {provider_text} | {requirement_text} | "
        f"{consumer_text} |"
    )


def _validate_production_mounts(seam: CapabilitySeam) -> None:
    for reference in seam.production_mounts:
        mounted_by = _resolve(reference)
        if not callable(mounted_by):
            raise TypeError(
                f"catalog production mount is not callable: {_label(reference)}"
            )


def _validate_providers(seam: CapabilitySeam) -> None:
    if not seam.providers:
        raise RuntimeError(f"Capability has no Provider: {_label(seam.definition)}")
    definition_symbol = _parts(seam.definition)[1]
    for provider in seam.providers:
        if not callable(_resolve(provider)):
            raise TypeError(f"catalog Provider is not callable: {_label(provider)}")
        tree = _parse_source(provider)
        provider_call = any(
            isinstance(node, ast.Call)
            and _call_name(node.func) == "CapabilityBundleProvider"
            and _mentions(node, definition_symbol)
            for node in ast.walk(tree)
        )
        if not provider_call:
            raise RuntimeError(
                f"catalog Provider does not construct {definition_symbol}: "
                f"{_label(provider)}"
            )


def _validate_consumers(
    seam: CapabilitySeam,
    definition: CapabilityDefinition,
) -> None:
    if not seam.consumers:
        raise RuntimeError(f"Capability has no Consumer: {_label(seam.definition)}")
    for consumer, requirements in seam.consumers:
        if not callable(_resolve(consumer)):
            raise TypeError(f"catalog Consumer is not callable: {_label(consumer)}")
        if not requirements:
            raise RuntimeError(f"catalog Consumer has no requirement: {_label(consumer)}")
        tree = _parse_source(consumer)
        for reference in requirements:
            requirement = _resolve(reference)
            if not isinstance(requirement, CapabilityRequirement):
                raise TypeError(f"catalog requirement has wrong type: {_label(reference)}")
            if requirement.capability != definition.capability_id:
                raise RuntimeError(
                    f"{_label(reference)} targets {requirement.capability}, expected "
                    f"{definition.capability_id}"
                )
            if not _mentions(tree, _parts(reference)[1]):
                raise RuntimeError(
                    f"catalog Consumer does not use {_label(reference)}: "
                    f"{_label(consumer)}"
                )


def _discover_definition_refs() -> frozenset[SymbolRef]:
    discovered: set[SymbolRef] = set()
    for path in SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module = ".".join(path.relative_to(SOURCE_ROOT).with_suffix("").parts)
        call_names = {"CapabilityDefinition"}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                call_names.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "CapabilityDefinition"
                )

        calls = {
            id(node): node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _call_name(node.func) in call_names
        }
        declared: set[int] = set()
        for node in tree.body:
            if isinstance(node, ast.Assign):
                value, targets = node.value, tuple(node.targets)
            elif isinstance(node, ast.AnnAssign):
                value, targets = node.value, (node.target,)
            else:
                continue
            if not isinstance(value, ast.Call) or _call_name(value.func) not in call_names:
                continue
            declared.add(id(value))
            discovered.update(
                f"{module}:{target.id}" for target in targets if isinstance(target, ast.Name)
            )
        if undeclared := calls.keys() - declared:
            lines = sorted(calls[identity].lineno for identity in undeclared)
            raise RuntimeError(
                "CapabilityDefinition must be a named module-level declaration: "
                f"{path.relative_to(ROOT)}:{lines}"
            )
    return frozenset(discovered)


def _parts(reference: SymbolRef) -> tuple[str, str]:
    module, separator, symbol = reference.partition(":")
    if not separator or not module or not symbol:
        raise ValueError(f"invalid catalog symbol reference: {reference!r}")
    return module, symbol


def _source_path(reference: SymbolRef) -> Path:
    module, _symbol = _parts(reference)
    return SOURCE_ROOT.joinpath(*module.split(".")).with_suffix(".py")


def _label(reference: SymbolRef) -> str:
    path = _source_path(reference).relative_to(ROOT)
    return f"{path}::{_parts(reference)[1]}"


def _resolve(reference: SymbolRef) -> object:
    module, symbol = _parts(reference)
    try:
        return getattr(importlib.import_module(module), symbol)
    except AttributeError as error:
        raise RuntimeError(f"missing catalog symbol: {_label(reference)}") from error


def _parse_source(reference: SymbolRef) -> ast.Module:
    path = _source_path(reference)
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _mentions(tree: ast.AST, symbol: str) -> bool:
    return any(isinstance(node, ast.Name) and node.id == symbol for node in ast.walk(tree))


def _check(rendered: str) -> int:
    current = CATALOG_PATH.read_text(encoding="utf-8") if CATALOG_PATH.exists() else ""
    if current == rendered:
        return 0
    print(
        "\n".join(
            difflib.unified_diff(
                current.splitlines(),
                rendered.splitlines(),
                fromfile=str(CATALOG_PATH.relative_to(ROOT)),
                tofile="generated",
                lineterm="",
            )
        )
    )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Harness Capability catalog")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the committed catalog differs from source",
    )
    args = parser.parse_args()
    rendered = render_catalog()
    if args.check:
        return _check(rendered)
    CATALOG_PATH.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
