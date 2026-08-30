"""Strict package-local symbol locator shared by executable Plugin owners."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import cast

from loushang.harness.resources.plugins.declarations import (
    PluginContributionExecutionModel,
    PluginDeclarationCodecError,
)
from loushang.harness.resources.plugins.locators import (
    canonical_plugin_python_path,
    canonical_plugin_symbol,
)

PLUGIN_SYMBOL_REFERENCE_VERSION = 2


@dataclass(frozen=True, slots=True)
class PluginSymbolReference:
    """Package-internal symbol locator; the Host attaches revision identity."""

    path: str
    symbol: str
    execution_model: PluginContributionExecutionModel
    symbol_reference_version: int = PLUGIN_SYMBOL_REFERENCE_VERSION

    def __post_init__(self) -> None:
        try:
            path = canonical_plugin_python_path(self.path)
        except ValueError as exc:
            raise ValueError(
                "Plugin symbol path must be a contained relative Python path"
            ) from exc
        canonical_plugin_symbol(self.symbol)
        if self.execution_model != "in_process":
            raise ValueError("Unsupported Plugin symbol execution model")
        if self.symbol_reference_version != PLUGIN_SYMBOL_REFERENCE_VERSION:
            raise ValueError("Unsupported Plugin symbol reference version")
        object.__setattr__(self, "path", path.as_posix())

    @property
    def relative_path(self) -> PurePosixPath:
        return PurePosixPath(self.path)

    def to_dict(self) -> dict[str, object]:
        return {
            "executionModel": self.execution_model,
            "path": self.path,
            "symbol": self.symbol,
            "symbolReferenceVersion": self.symbol_reference_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginSymbolReference:
        if not isinstance(value, dict):
            raise PluginDeclarationCodecError(
                "Plugin symbol reference must be an object",
                code="plugin_declaration_field_type_mismatch",
            )
        version = value.get("symbolReferenceVersion")
        if version is None:
            raise PluginDeclarationCodecError(
                "Plugin symbol reference version is missing",
                code="unsupported_plugin_symbol_reference_version",
            )
        if not isinstance(version, int) or isinstance(version, bool):
            raise PluginDeclarationCodecError(
                "Plugin symbol reference version must be an integer",
                code="plugin_declaration_field_type_mismatch",
            )
        if version != PLUGIN_SYMBOL_REFERENCE_VERSION:
            raise PluginDeclarationCodecError(
                "Unsupported Plugin symbol reference version",
                code="unsupported_plugin_symbol_reference_version",
            )
        if set(value) != {
            "executionModel",
            "path",
            "symbol",
            "symbolReferenceVersion",
        }:
            raise PluginDeclarationCodecError(
                "Plugin symbol reference fields do not match the supported format",
                code="plugin_declaration_exact_field_mismatch",
            )
        path = value["path"]
        symbol = value["symbol"]
        execution_model = value["executionModel"]
        if not all(isinstance(item, str) for item in (path, symbol, execution_model)):
            raise PluginDeclarationCodecError(
                "Plugin symbol reference fields must be strings",
                code="plugin_declaration_field_type_mismatch",
            )
        assert isinstance(path, str)
        assert isinstance(symbol, str)
        assert isinstance(execution_model, str)
        if execution_model != "in_process":
            raise PluginDeclarationCodecError(
                "Unsupported Plugin symbol execution model",
                code="unsupported_plugin_contribution_execution_model",
            )
        try:
            return cls(
                path=path,
                symbol=symbol,
                execution_model=cast(
                    PluginContributionExecutionModel,
                    execution_model,
                ),
                symbol_reference_version=version,
            )
        except (TypeError, ValueError) as exc:
            raise PluginDeclarationCodecError(
                f"Invalid Plugin symbol reference: {exc}",
                code="plugin_declaration_field_value_mismatch",
            ) from exc


__all__ = ["PLUGIN_SYMBOL_REFERENCE_VERSION", "PluginSymbolReference"]
