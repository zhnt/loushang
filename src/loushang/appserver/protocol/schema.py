"""Closed schema metadata for compatibility checks and generated clients."""

from __future__ import annotations

from .model import APP_PROTOCOL_VERSION, AppOperationV1


def operation_names_v1() -> tuple[str, ...]:
    """Return the canonical, stable operation vocabulary."""

    return tuple(operation.value for operation in AppOperationV1)


def schema_fingerprint_material_v1() -> tuple[str, tuple[str, ...]]:
    """Return immutable material used by compatibility fixtures."""

    return APP_PROTOCOL_VERSION, operation_names_v1()


__all__ = ["operation_names_v1", "schema_fingerprint_material_v1"]
