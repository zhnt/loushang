from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from loushang.harness.tools.core import ToolDefinition

DiagnosticSeverity = Literal["error", "warning"]


@dataclass(frozen=True)
class ToolContribution:
    definition: ToolDefinition
    enabled: bool = True
    source_info: object | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.definition, ToolDefinition):
            raise TypeError("definition must be a ToolDefinition")
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class ToolPackDefinition:
    name: str
    tools: tuple[str, ...] | list[str] = ()
    includes: tuple[str, ...] | list[str] = ()
    enabled: bool = True
    source_info: object | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("name must be a non-empty string")
        object.__setattr__(self, "tools", _tuple_of_strings(self.tools, "tools"))
        object.__setattr__(self, "includes", _tuple_of_strings(self.includes, "includes"))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class ToolResolutionDiagnostic:
    code: str
    message: str
    severity: DiagnosticSeverity = "error"
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.severity not in {"error", "warning"}:
            raise ValueError("severity must be 'error' or 'warning'")
        object.__setattr__(self, "details", dict(self.details))


@dataclass(frozen=True)
class ToolResolutionResult:
    contributions: tuple[ToolContribution, ...]
    definitions: tuple[ToolDefinition, ...]
    diagnostics: tuple[ToolResolutionDiagnostic, ...] = ()

    @property
    def has_errors(self) -> bool:
        return any(diagnostic.severity == "error" for diagnostic in self.diagnostics)


class ToolResolutionError(ValueError):
    def __init__(self, diagnostics: Iterable[ToolResolutionDiagnostic]) -> None:
        self.diagnostics = tuple(diagnostics)
        message = "; ".join(diagnostic.message for diagnostic in self.diagnostics)
        super().__init__(message or "tool contribution resolution failed")


def resolve_tool_contributions(
    contributions: Iterable[ToolContribution],
    *,
    packs: Iterable[ToolPackDefinition] = (),
    include_packs: Iterable[str] = (),
    disabled_tools: Iterable[str] = (),
    fail_on_errors: bool = True,
) -> ToolResolutionResult:
    contribution_list = tuple(contributions)
    pack_list = tuple(packs)
    disabled_tool_names = set(disabled_tools)
    diagnostics: list[ToolResolutionDiagnostic] = []

    contributions_by_name = _first_contributions_by_name(contribution_list, diagnostics)
    packs_by_name = _first_packs_by_name(pack_list, diagnostics)

    selected_names: list[str] = []
    requested_packs = tuple(include_packs)
    if requested_packs:
        for pack_name in requested_packs:
            _expand_pack(
                pack_name,
                packs_by_name=packs_by_name,
                selected_names=selected_names,
                diagnostics=diagnostics,
            )
    else:
        for candidate in contribution_list:
            _append_unique(selected_names, candidate.definition.name)

    selected_contributions: list[ToolContribution] = []
    for name in selected_names:
        contribution = contributions_by_name.get(name)
        if contribution is None:
            diagnostics.append(
                _diagnostic(
                    "missing_tool",
                    f"Tool {name!r} was referenced but no contribution was registered.",
                    name=name,
                )
            )
            continue
        if not contribution.enabled or name in disabled_tool_names:
            continue
        selected_contributions.append(contribution)

    result = ToolResolutionResult(
        contributions=tuple(selected_contributions),
        definitions=tuple(contribution.definition for contribution in selected_contributions),
        diagnostics=tuple(diagnostics),
    )
    if fail_on_errors and result.has_errors:
        raise ToolResolutionError(result.diagnostics)
    return result


def _tuple_of_strings(value: tuple[str, ...] | list[str], field_name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        raise TypeError(f"{field_name} must be a sequence of strings, not a string")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError(f"{field_name} must contain non-empty strings")
        normalized.append(item)
    return tuple(normalized)


def _first_contributions_by_name(
    contributions: tuple[ToolContribution, ...],
    diagnostics: list[ToolResolutionDiagnostic],
) -> dict[str, ToolContribution]:
    grouped: dict[str, list[ToolContribution]] = {}
    for contribution in contributions:
        grouped.setdefault(contribution.definition.name, []).append(contribution)

    resolved: dict[str, ToolContribution] = {}
    for name, matches in grouped.items():
        resolved[name] = matches[0]
        if len(matches) > 1:
            diagnostics.append(
                _diagnostic(
                    "duplicate_tool",
                    f"Tool {name!r} was contributed more than once.",
                    name=name,
                    sources=[match.source_info for match in matches],
                )
            )
    return resolved


def _first_packs_by_name(
    packs: tuple[ToolPackDefinition, ...],
    diagnostics: list[ToolResolutionDiagnostic],
) -> dict[str, ToolPackDefinition]:
    grouped: dict[str, list[ToolPackDefinition]] = {}
    for pack in packs:
        grouped.setdefault(pack.name, []).append(pack)

    resolved: dict[str, ToolPackDefinition] = {}
    for name, matches in grouped.items():
        resolved[name] = matches[0]
        if len(matches) > 1:
            diagnostics.append(
                _diagnostic(
                    "duplicate_pack",
                    f"Tool pack {name!r} was contributed more than once.",
                    name=name,
                    sources=[match.source_info for match in matches],
                )
            )
    return resolved


def _expand_pack(
    name: str,
    *,
    packs_by_name: Mapping[str, ToolPackDefinition],
    selected_names: list[str],
    diagnostics: list[ToolResolutionDiagnostic],
    stack: tuple[str, ...] = (),
) -> None:
    pack = packs_by_name.get(name)
    if pack is None:
        diagnostics.append(
            _diagnostic(
                "missing_pack",
                f"Tool pack {name!r} was referenced but no pack was registered.",
                name=name,
            )
        )
        return
    if name in stack:
        diagnostics.append(
            _diagnostic(
                "cyclic_pack_include",
                f"Tool pack {name!r} is part of a cyclic include chain.",
                name=name,
                chain=[*stack, name],
            )
        )
        return
    if not pack.enabled:
        return

    next_stack = (*stack, name)
    for include_name in pack.includes:
        _expand_pack(
            include_name,
            packs_by_name=packs_by_name,
            selected_names=selected_names,
            diagnostics=diagnostics,
            stack=next_stack,
        )
    for tool_name in pack.tools:
        _append_unique(selected_names, tool_name)


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _diagnostic(
    code: str,
    message: str,
    *,
    name: str,
    sources: list[object | None] | None = None,
    chain: list[str] | None = None,
) -> ToolResolutionDiagnostic:
    details: dict[str, object] = {"name": name}
    if sources is not None:
        details["sources"] = sources
    if chain is not None:
        details["chain"] = chain
    return ToolResolutionDiagnostic(code=code, message=message, details=details)


__all__ = [
    "DiagnosticSeverity",
    "ToolContribution",
    "ToolPackDefinition",
    "ToolResolutionDiagnostic",
    "ToolResolutionError",
    "ToolResolutionResult",
    "resolve_tool_contributions",
]
