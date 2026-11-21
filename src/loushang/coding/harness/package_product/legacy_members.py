"""Project observed legacy members into their declared snapshot domains."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from pathlib import Path

from loushang.harness.resources.packages.product_pre_b_snapshot import (
    inspect_legacy_product_member_names,
)


def inspect_domain_members(
    root: Path,
    *,
    domains_by_member: Mapping[str, tuple[str, ...]],
    directory_members: Collection[str],
    label: str,
) -> dict[str, tuple[str, ...]]:
    """Inspect the root once, then include each member in its declared domains."""
    names = inspect_legacy_product_member_names(
        root,
        allowed_members=domains_by_member,
        directory_members=directory_members,
        label=label,
    )
    observed_by_domain: dict[str, list[str]] = {}
    for name in sorted(names):
        for domain in domains_by_member[name]:
            observed_by_domain.setdefault(domain, []).append(name)
    return {domain: tuple(members) for domain, members in observed_by_domain.items()}
