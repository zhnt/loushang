from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from loushang.harness.environment import resolve_platform_home

ResourceScope = Literal["temporary", "project", "user", "package", "built_in"]

STANDARD_RESOURCE_DIRECTORIES = (
    "prompts",
    "skills",
    "extensions",
    "themes",
    "packages",
)
DEFAULT_SCOPE_PRECEDENCE: tuple[ResourceScope, ...] = (
    "temporary",
    "project",
    "user",
    "package",
    "built_in",
)


def resolve_workspace_resource_root(workspace_root: str | Path) -> Path:
    return Path(workspace_root).expanduser().resolve(strict=False) / ".loushang"


def resolve_product_resource_root(
    product: str,
    *,
    platform_home: str | Path | None = None,
) -> Path:
    normalized = product.strip()
    if not normalized or "/" in normalized or "\\" in normalized:
        raise ValueError("product must be a non-empty path segment")
    root = resolve_platform_home() if platform_home is None else Path(platform_home)
    return root.expanduser().resolve(strict=False) / "products" / normalized


def resolve_user_resource_roots(
    additional_roots: Sequence[str | Path] = (),
    *,
    global_base_dir: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    home: str | Path | None = None,
    include_missing_platform_home: bool = False,
) -> tuple[tuple[Path, ...], frozenset[Path]]:
    import os

    platform_home = resolve_platform_home(environ=environ, home=home)
    values = os.environ if environ is None else environ
    roots: list[Path] = []
    if (
        include_missing_platform_home
        or values.get("LOUSHANG_HOME")
        or platform_home.is_dir()
    ):
        roots.append(platform_home)

    explicit: set[Path] = set()
    base = Path(global_base_dir).expanduser() if global_base_dir is not None else None
    for root in additional_roots:
        candidate = Path(root).expanduser()
        if not candidate.is_absolute() and base is not None:
            candidate = base / candidate
        resolved = candidate.resolve(strict=False)
        explicit.add(resolved)
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots), frozenset(explicit)
