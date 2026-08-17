from __future__ import annotations

import asyncio
import sys
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
while not (REPO_ROOT / "src").exists() and REPO_ROOT.parent != REPO_ROOT:
    REPO_ROOT = REPO_ROOT.parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from loushang.coding.resource_runtime import (
    CodingResourceLoader as DefaultResourceLoader,
)
from loushang.coding.resource_runtime import CodingSkillLoader as SkillLoader

SKILL_REVIEW_PKG = """\
---
name: review
description: Package-level code review guidelines
---
This is the EXTERNAL PACKAGE version of the review skill.
It provides generic review guidelines.
"""

SKILL_REVIEW_PROJECT = """\
---
name: review
description: Project-specific code review guidelines
---
This is the PROJECT-LOCAL version of the review skill.
It enforces project-specific style rules.
"""

SKILL_TEST_PROJECT = """\
---
name: test
description: Generate unit tests for the given code
---
Write comprehensive unit tests covering edge cases.
"""


async def main() -> None:
    with TemporaryDirectory(prefix="loushang-skill-precedence-") as tmpdir:
        base = Path(tmpdir)
        pkg_dir = base / "external_pkg"
        project_dir = base / "project"

        # External package skill
        (pkg_dir / "skills" / "review").mkdir(parents=True)
        (pkg_dir / "skills" / "review" / "SKILL.md").write_text(SKILL_REVIEW_PKG, encoding="utf-8")

        # Project-local skills (review overrides package; test is unique)
        (project_dir / "skills" / "review").mkdir(parents=True)
        (project_dir / "skills" / "test").mkdir(parents=True)
        (project_dir / "skills" / "review" / "SKILL.md").write_text(SKILL_REVIEW_PROJECT, encoding="utf-8")
        (project_dir / "skills" / "test" / "SKILL.md").write_text(SKILL_TEST_PROJECT, encoding="utf-8")

        print("=== Skill Precedence: project_local > external_package > built_in ===")
        print(f"Package root: {pkg_dir}")
        print(f"Project root: {project_dir}")
        print()

        resource_loader = DefaultResourceLoader(package_roots=[pkg_dir])
        loader = SkillLoader(resource_loader=resource_loader)
        loader.discover_skills(project_dir)

        print("--- Active skills after discovery ---")
        for skill in loader.list_enabled_skills():
            print(f"  {skill.name}: {skill.description} (source_kind={skill.source_kind})")
        print()

        snapshot = resource_loader.get_resource_snapshot()
        print(f"--- Resource merge decisions ({len(snapshot.merge_decisions)}) ---")
        for decision in snapshot.merge_decisions:
            if decision.resource_type == "skill":
                print(f"  logical_id={decision.logical_id}")
                print(f"    winner_id={decision.winner_id}")
                print(f"    winner_source_kind={decision.winner_source_kind}")
                print(f"    candidates={decision.candidate_ids}")
                print(f"    candidate_source_kinds={decision.candidate_source_kinds}")
                print(f"    reason={decision.reason}")
        print()

        print(f"--- Resource diagnostics ({len(snapshot.diagnostics)}) ---")
        for diagnostic in snapshot.diagnostics:
            if diagnostic.details.get("resource_type") == "skill":
                print(f"  [{diagnostic.code}] {diagnostic.message}")
                metadata = diagnostic.details.get("metadata")
                if isinstance(metadata, Mapping):
                    for key, value in sorted(metadata.items()):
                        print(f"    {key}={value}")
        print()

        print("--- Same-precedence collision demo ---")
        # Create two external packages with the same skill name
        pkg_a = base / "pkg_a"
        pkg_b = base / "pkg_b"
        (pkg_a / "skills" / "audit").mkdir(parents=True)
        (pkg_b / "skills" / "audit").mkdir(parents=True)
        (pkg_a / "skills" / "audit" / "SKILL.md").write_text(
            "---\nname: audit\ndescription: Audit from package A\n---\nPackage A audit rules.\n",
            encoding="utf-8",
        )
        (pkg_b / "skills" / "audit" / "SKILL.md").write_text(
            "---\nname: audit\ndescription: Audit from package B\n---\nPackage B audit rules.\n",
            encoding="utf-8",
        )

        collision_loader = DefaultResourceLoader(package_roots=[pkg_a, pkg_b])
        collision_loader.discover_resources(project_dir)
        collision_snapshot = collision_loader.get_resource_snapshot()

        active_audit = [s for s in collision_snapshot.active_skill_descriptors if s.name == "audit"]
        print(f"  Active 'audit' skills after same-precedence collision: {len(active_audit)} (expected: 0)")

        for decision in collision_snapshot.merge_decisions:
            if decision.resource_type == "skill" and "audit" in decision.logical_id:
                print(f"  Merge decision: logical_id={decision.logical_id}, winner_id={decision.winner_id}, reason={decision.reason}")

        for diagnostic in collision_snapshot.diagnostics:
            resource_id = diagnostic.details.get("resource_id")
            if (
                diagnostic.details.get("resource_type") == "skill"
                and isinstance(resource_id, str)
                and "audit" in resource_id
            ):
                print(f"  Diagnostic: [{diagnostic.code}] {diagnostic.message}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
