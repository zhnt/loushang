"""Compatibility exports for machine-local path resolution."""

from loushang.foundation.platform_paths import (
    PlatformPaths,
    resolve_platform_home,
    resolve_platform_paths,
)

__all__ = ["PlatformPaths", "resolve_platform_home", "resolve_platform_paths"]
