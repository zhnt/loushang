from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, Protocol

from loushang.harness.resources.loader import ResourceLoader
from loushang.harness.resources.types import SkillDescriptor

SettingsScope = Literal["session", "global", "project"]


class SkillSettingsManager(Protocol):
    def get_disabled_skills(self) -> list[str]: ...

    def set_disabled_skills(
        self, names: list[str], *, scope: SettingsScope = "project"
    ) -> None: ...

    def enable_skill(self, name: str, *, scope: SettingsScope = "project") -> None: ...

    def disable_skill(self, name: str, *, scope: SettingsScope = "project") -> None: ...


class SkillLoader:
    """Skill-specific facade over the resource loader skill discovery rules."""

    def __init__(
        self,
        *,
        resource_loader: ResourceLoader | None = None,
        package_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
        disabled_skills: list[str] | tuple[str, ...] | None = None,
        settings_manager: SkillSettingsManager | None = None,
        settings_scope: SettingsScope = "project",
    ) -> None:
        self._resource_loader = resource_loader or ResourceLoader(
            package_roots=package_roots
        )
        self._cwd: Path | None = None
        self._disabled: set[str] = set(disabled_skills or ())
        self._settings_manager = settings_manager
        self._settings_scope = settings_scope

    def discover_skills(self, cwd: str | Path) -> list[SkillDescriptor]:
        self._cwd = Path(cwd)
        self._resource_loader.discover_resources(self._cwd)
        return self.list_enabled_skills()

    def reload_skills(self, cwd: str | Path | None = None) -> list[SkillDescriptor]:
        if cwd is not None:
            return self.discover_skills(cwd)
        if self._cwd is None:
            return self.discover_skills(Path.cwd())
        self._resource_loader.reload_resources(self._cwd)
        return self.list_enabled_skills()

    def load_skill(self, name: str) -> SkillDescriptor:
        skill = self.get_skill(name)
        if skill is None:
            raise KeyError(name)
        return skill

    def get_skill(self, name: str) -> SkillDescriptor | None:
        for skill in self.list_skills():
            if _matches_skill(skill, name):
                return skill
        return None

    def list_skills(self) -> list[SkillDescriptor]:
        snapshot = self._resource_loader.get_resource_snapshot()
        return list(snapshot.active_skill_descriptors)

    def list_enabled_skills(self) -> list[SkillDescriptor]:
        disabled = self._disabled_names()
        return [
            skill
            for skill in self.list_skills()
            if not _is_disabled_skill(skill, disabled)
        ]

    def enable_skill(self, name: str) -> SkillDescriptor:
        skill = self.load_skill(name)
        self._disabled.discard(_skill_key(skill))
        if self._settings_manager is not None:
            next_disabled = [
                disabled_name
                for disabled_name in self._settings_manager.get_disabled_skills()
                if not _matches_skill(skill, disabled_name)
            ]
            self._settings_manager.set_disabled_skills(
                next_disabled, scope=self._settings_scope
            )
        return skill

    def disable_skill(self, name: str) -> SkillDescriptor:
        skill = self.load_skill(name)
        self._disabled.add(_skill_key(skill))
        if self._settings_manager is not None:
            self._settings_manager.disable_skill(skill.name, scope=self._settings_scope)
        return skill

    def _disabled_names(self) -> set[str]:
        disabled = set(self._disabled)
        if self._settings_manager is not None:
            disabled.update(self._settings_manager.get_disabled_skills())
        return disabled


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


def _matches_skill(skill: SkillDescriptor, name: str) -> bool:
    return name in {
        skill.name,
        skill.id,
        skill.canonical_name,
        str(skill.source_path),
    }


def _skill_key(skill: SkillDescriptor) -> str:
    return skill.id or skill.canonical_name or skill.name


def _is_disabled_skill(skill: SkillDescriptor, disabled: set[str]) -> bool:
    return any(
        value in disabled
        for value in (
            skill.name,
            skill.id,
            skill.canonical_name,
            str(skill.source_path),
        )
    )
