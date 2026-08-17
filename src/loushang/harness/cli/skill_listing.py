"""Shared CLI skill discovery and listing projection."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from loushang.harness.resources.skills import project_skill_descriptor


class SkillListingError(RuntimeError):
    """Raised when a session does not expose a skill loader."""


def list_skill_records(session: object) -> list[dict[str, object]]:
    """Discover and project skills from a bound resource session."""

    bundle = getattr(session, "resource_bundle", None)
    skills = getattr(bundle, "skills", None)
    if not isinstance(skills, list):
        loader = getattr(session, "resource_loader", None)
        getter = getattr(loader, "get_skills", None)
        if not callable(getter):
            raise SkillListingError("skill loader is not available.")
        try:
            skills = getter()
        except Exception as error:
            raise SkillListingError(str(error)) from error
    if not isinstance(skills, list):
        raise SkillListingError("skill loader returned an invalid response.")
    return [
        projected
        for skill in skills
        if (projected := project_skill_descriptor(skill)) is not None
    ]


def format_skill_records(
    records: Sequence[Mapping[str, object]],
    output_format: str,
) -> str:
    if output_format == "json":
        return json.dumps(records, ensure_ascii=False) + "\n"
    return "".join(
        f"{skill['name']}\t{skill['source_kind']}\t{skill['path']}\t"
        f"{skill['enabled']}\n"
        for skill in records
    )


__all__ = ["SkillListingError", "format_skill_records", "list_skill_records"]
