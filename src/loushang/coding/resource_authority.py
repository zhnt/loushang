"""Coding product choices for initial resource authority."""

from __future__ import annotations

from typing import Literal

ResourceAuthorityMode = Literal["catalog_required", "legacy_explicit"]
RESOURCE_AUTHORITY_MODES: tuple[ResourceAuthorityMode, ...] = (
    "catalog_required",
    "legacy_explicit",
)

__all__ = ["RESOURCE_AUTHORITY_MODES", "ResourceAuthorityMode"]
