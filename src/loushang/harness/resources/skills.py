from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def project_skill_descriptor(skill: object) -> dict[str, object] | None:
    """Project a skill descriptor for resource listings.

    The projection contains only resource identity, provenance, activation
    state, and diagnostics.  Product CLIs may choose how to render it, but do
    not need to duplicate the object-shape normalization.
    """

    name = _safe_skill_getattr(skill, "name", None)
    if not isinstance(name, str) or not name:
        return None
    source_path = _safe_skill_getattr(skill, "source_path", None)
    source_root = _safe_skill_getattr(skill, "source_root", None)
    raw_diagnostics = _safe_skill_getattr(skill, "diagnostics", ())
    diagnostic_values = (
        raw_diagnostics if isinstance(raw_diagnostics, list | tuple) else ()
    )
    diagnostics = [
        normalized
        for diagnostic in diagnostic_values
        if (normalized := project_skill_diagnostic(diagnostic)) is not None
    ]
    return {
        "name": name,
        "id": _safe_skill_getattr(skill, "id", "") or "",
        "canonical_name": _safe_skill_getattr(skill, "canonical_name", "") or "",
        "description": _safe_skill_getattr(skill, "description", "") or "",
        "path": _safe_skill_string(source_path),
        "source_kind": _safe_skill_getattr(skill, "source_kind", "") or "",
        "source_scope": _safe_skill_getattr(skill, "source_scope", "") or "",
        "source": _safe_skill_getattr(skill, "source", "") or "",
        "source_root": _safe_skill_string(source_root)
        if source_root is not None
        else "",
        "disable_model_invocation": bool(
            _safe_skill_getattr(skill, "disable_model_invocation", False)
        ),
        "enabled": bool(_safe_skill_getattr(skill, "enabled", True)),
        "diagnostics": diagnostics,
    }


def project_skill_status_summary(skill: object) -> dict[str, object] | None:
    """Project one exact Catalog status record for Product listings."""

    name = _safe_skill_getattr(skill, "name", None)
    status = _safe_skill_getattr(skill, "status", None)
    if not isinstance(name, str) or not name or not isinstance(status, str):
        return None
    source_path = _safe_skill_getattr(skill, "source_path", None)
    source_root = _safe_skill_getattr(skill, "source_root", None)
    raw_diagnostics = _safe_skill_getattr(skill, "diagnostics", ())
    diagnostic_values = (
        raw_diagnostics if isinstance(raw_diagnostics, list | tuple) else ()
    )
    diagnostics = [
        projected
        for diagnostic in diagnostic_values
        if (
            projected := _project_skill_status_diagnostic(diagnostic)
        )
        is not None
    ]
    declared_model_invocable = bool(
        _safe_skill_getattr(skill, "declared_model_invocable", False)
    )
    effective = bool(_safe_skill_getattr(skill, "effective", False))
    return {
        "name": name,
        "id": _safe_skill_getattr(skill, "id", "") or "",
        "canonical_name": (
            _safe_skill_getattr(skill, "canonical_name", "") or ""
        ),
        "description": _safe_skill_getattr(skill, "description", "") or "",
        "path": _safe_skill_string(source_path),
        "source_kind": _safe_skill_getattr(skill, "source_kind", "") or "",
        "source_scope": _safe_skill_getattr(skill, "source_scope", "") or "",
        "source": _safe_skill_getattr(skill, "source", "") or "",
        "source_root": (
            _safe_skill_string(source_root) if source_root is not None else ""
        ),
        "disable_model_invocation": not declared_model_invocable,
        "enabled": effective,
        "declared_enabled": bool(
            _safe_skill_getattr(skill, "declared_enabled", False)
        ),
        "declared_model_invocable": declared_model_invocable,
        "effective": effective,
        "primary": bool(_safe_skill_getattr(skill, "primary", False)),
        "model_invocable": bool(
            _safe_skill_getattr(skill, "model_invocable", False)
        ),
        "status": status,
        "status_reason": (
            _safe_skill_getattr(skill, "status_reason", "") or ""
        ),
        "diagnostics": diagnostics,
    }


def _project_skill_status_diagnostic(
    diagnostic: object,
) -> dict[str, object] | None:
    code = _safe_skill_getattr(diagnostic, "code", None)
    if not isinstance(code, str) or not code:
        return None
    raw_details = _safe_skill_getattr(diagnostic, "details", ())
    details = (
        dict(raw_details)
        if isinstance(raw_details, tuple)
        and all(
            isinstance(item, tuple)
            and len(item) == 2
            and isinstance(item[0], str)
            and isinstance(item[1], str)
            for item in raw_details
        )
        else {}
    )
    return {
        "code": code,
        "reason": _safe_skill_getattr(diagnostic, "reason", "") or "",
        "source_id": _safe_skill_getattr(diagnostic, "source_id", None),
        "details": details,
    }


def project_skill_diagnostic(diagnostic: object) -> dict[str, object] | None:
    """Project one resource diagnostic nested in a skill listing."""

    code = _safe_skill_getattr(diagnostic, "code", None)
    if not isinstance(code, str) or not code:
        return None
    raw_details = _safe_skill_getattr(diagnostic, "details", {})
    details = raw_details if isinstance(raw_details, Mapping) else {}
    metadata = details.get("metadata")
    return {
        "code": code,
        "message": _safe_skill_getattr(diagnostic, "message", "") or "",
        "path": _safe_skill_string(
            _safe_skill_getattr(diagnostic, "source_path", "")
        ),
        "resource_type": details.get("resource_type"),
        "source_kind": details.get("source_kind"),
        "metadata": _json_safe_skill_value(metadata if metadata is not None else {}),
    }


def _safe_skill_getattr(target: object, name: str, default: object) -> object:
    try:
        return getattr(target, name)
    except Exception:
        return default


def _safe_skill_string(value: object) -> str:
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        try:
            return repr(value)
        except Exception:
            return ""


def _json_safe_skill_value(value: Any) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {
            _safe_skill_string(key): _json_safe_skill_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe_skill_value(item) for item in value]
    return _safe_skill_string(value)


__all__ = [
    "project_skill_descriptor",
    "project_skill_diagnostic",
    "project_skill_status_summary",
]
