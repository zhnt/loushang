"""Authoritative source precedence and stable ordering for resource candidates."""

from __future__ import annotations

from loushang.harness.resources._loader_types import DescriptorT
from loushang.harness.resources.types import ResourceSourceKind

_SOURCE_PRIORITY: dict[ResourceSourceKind, int] = {
    "temporary": -1,
    "project_local": 0,
    "user_global": 1,
    "external_package": 2,
    "built_in": 3,
}


def _source_precedence_rank(source_kind: ResourceSourceKind) -> int:
    return _SOURCE_PRIORITY[source_kind]


def _candidate_sort_key(descriptor: DescriptorT) -> tuple[int, int, str, str]:
    return (
        _source_precedence_rank(descriptor.source_kind),
        descriptor.source_root_order,
        descriptor.canonical_name or descriptor.name,
        descriptor.source_path.as_posix(),
    )


def _winner_sort_key(descriptor: DescriptorT) -> tuple[int, int, str, str]:
    return _candidate_sort_key(descriptor)
