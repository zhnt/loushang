"""Shared CLI skill discovery and listing projection."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from loushang.harness.resources.skills import project_skill_status_summary


class SkillListingError(RuntimeError):
    """Raised when a session does not expose an exact-v4 Skill Catalog."""


def list_skill_records(session: object) -> list[dict[str, object]]:
    """Project every Skill candidate from one exact Catalog capture."""

    getter = getattr(session, "list_skill_statuses", None)
    if not callable(getter):
        raise SkillListingError("Skill Catalog v4 capture is not available.")
    try:
        skills = getter()
    except Exception as error:
        raise SkillListingError(str(error)) from error
    if not isinstance(skills, tuple):
        raise SkillListingError("Skill Catalog returned an invalid response.")
    records: list[dict[str, object]] = []
    for skill in skills:
        projected = project_skill_status_summary(skill)
        if projected is None:
            raise SkillListingError(
                "Skill Catalog returned an invalid status record."
            )
        records.append(projected)
    return records


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
