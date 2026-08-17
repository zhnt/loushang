"""Stable diagnostics emitted by ontology schema compilation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SchemaDiagnostic:
    """One deterministic schema error."""

    code: str
    path: str
    message: str


class SchemaCompilationError(ValueError):
    """Raised when a draft cannot produce a compiled schema snapshot."""

    def __init__(self, diagnostics: tuple[SchemaDiagnostic, ...]) -> None:
        if not diagnostics:
            raise ValueError("SchemaCompilationError requires at least one diagnostic")
        self.diagnostics = diagnostics
        rendered = "; ".join(
            f"[{item.code}] {item.path}: {item.message}" for item in diagnostics
        )
        super().__init__(rendered)


__all__ = ["SchemaCompilationError", "SchemaDiagnostic"]
