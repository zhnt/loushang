"""Shared identity of one compiled ontology schema."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from loushang.foundation.json import JSONValue, require_json_mapping


@runtime_checkable
class _SchemaIdentitySource(Protocol):
    @property
    def package_id(self) -> str: ...

    @property
    def namespace(self) -> str: ...

    @property
    def version(self) -> object: ...


@dataclass(frozen=True, slots=True)
class SchemaIdentity:
    """Exact package, namespace, and version selected by a runtime contract."""

    package_id: str
    namespace: str
    version: str

    def __post_init__(self) -> None:
        for name in ("package_id", "namespace", "version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")

    @classmethod
    def from_schema(cls, schema: _SchemaIdentitySource) -> SchemaIdentity:
        if not isinstance(schema, _SchemaIdentitySource):
            raise TypeError("schema must be a CompiledOntologySchema")
        return cls(schema.package_id, schema.namespace, str(schema.version))

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "package_id": self.package_id,
            "namespace": self.namespace,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: object) -> SchemaIdentity:
        document = require_json_mapping(value, name="schema identity")
        try:
            return cls(
                package_id=_required_text(document, "package_id"),
                namespace=_required_text(document, "namespace"),
                version=_required_text(document, "version"),
            )
        except KeyError as exc:
            raise ValueError(f"schema identity is missing {exc.args[0]}") from exc


def _required_text(document: dict[str, JSONValue], name: str) -> str:
    value = document[name]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"schema identity {name} must be a non-empty string")
    return value


__all__ = ["SchemaIdentity"]
