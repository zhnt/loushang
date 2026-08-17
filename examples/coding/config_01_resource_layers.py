from __future__ import annotations

import sys
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

SKILL_USER_REVIEW = """\
---
name: review
description: User-global code review guidelines
---
User-level review skill.
"""

SKILL_USER_SHARED = """\
---
name: shared
description: User-global shared skill
---
User-level shared skill.
"""

SKILL_PKG_REVIEW = """\
---
name: review
description: External package code review guidelines
---
Package-level review skill.
"""

SKILL_PKG_SHARED = """\
---
name: shared
description: External package shared skill
---
Package-level shared skill.
"""

SKILL_PKG_UNIQUE = """\
---
name: package-only
description: Skill only available in external package
---
Package-only skill.
"""

SKILL_PROJECT_REVIEW = """\
---
name: review
description: Project-local code review guidelines
---
Project-level review skill.
"""

SKILL_PROJECT_SHARED = """\
---
name: shared
description: Project-local shared skill
---
Project-level shared skill.
"""

SKILL_PROJECT_UNIQUE = """\
---
name: project-only
description: Skill only available in project
---
Project-only skill.
"""


def _write_skill(root: Path, name: str, content: str) -> None:
    skill_dir = root / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")


def main() -> None:
    with TemporaryDirectory(prefix="loushang-resource-layers-") as tmpdir:
        base = Path(tmpdir)
        user_root = base / "user_home" / ".loushang"
        pkg_root = base / "external_pkg"
        project_root = base / "project"

        # User-global layer
        _write_skill(user_root, "review", SKILL_USER_REVIEW)
        _write_skill(user_root, "shared", SKILL_USER_SHARED)

        # External package layer
        _write_skill(pkg_root, "review", SKILL_PKG_REVIEW)
        _write_skill(pkg_root, "shared", SKILL_PKG_SHARED)
        _write_skill(pkg_root, "package-only", SKILL_PKG_UNIQUE)

        # Project-local layer
        _write_skill(project_root, "review", SKILL_PROJECT_REVIEW)
        _write_skill(project_root, "shared", SKILL_PROJECT_SHARED)
        _write_skill(project_root, "project-only", SKILL_PROJECT_UNIQUE)

        print("=== Flat Resource Architecture: Four-Layer Precedence ===")
        print()
        print("Layer structure:")
        print(f"  User global:  {user_root}/skills/")
        print(f"  External pkg: {pkg_root}/skills/")
        print(f"  Project:      {project_root}/skills/")
        print()

        loader = DefaultResourceLoader(
            package_roots=[pkg_root],
            user_resource_roots=[user_root],
        )
        bundle = loader.discover_resources(project_root)
        snapshot = loader.get_resource_snapshot()

        print("--- Active skills (after precedence resolution) ---")
        for skill in bundle.skills:
            print(f"  {skill.name}: {skill.description} (source_kind={skill.source_kind})")
        print()

        print("--- Resource merge decisions ---")
        for decision in snapshot.merge_decisions:
            if decision.resource_type != "skill":
                continue
            print(f"  logical_id={decision.logical_id}")
            print(f"    winner_id={decision.winner_id}")
            print(f"    winner_source_kind={decision.winner_source_kind}")
            print(f"    reason={decision.reason}")
            print(f"    candidate_source_kinds={decision.candidate_source_kinds}")
        print()

        print("--- Precedence verification ---")
        skill_map = {skill.name: skill for skill in bundle.skills}
        review = skill_map.get("review")
        shared = skill_map.get("shared")
        if review is not None and review.source_kind == "project_local":
            print("  PASS: 'review' resolved to project_local (highest precedence)")
        else:
            print("  FAIL: 'review' should be project_local")
        if shared is not None and shared.source_kind == "project_local":
            print("  PASS: 'shared' resolved to project_local (highest precedence)")
        else:
            print("  FAIL: 'shared' should be project_local")
        if "package-only" in skill_map and skill_map["package-only"].source_kind == "external_package":
            print("  PASS: 'package-only' resolved to external_package (only source)")
        else:
            print("  FAIL: 'package-only' should be external_package")
        if "project-only" in skill_map and skill_map["project-only"].source_kind == "project_local":
            print("  PASS: 'project-only' resolved to project_local (only source)")
        else:
            print("  FAIL: 'project-only' should be project_local")
        print()

        print("--- Source kinds in snapshot ---")
        print(f"  {snapshot.source_kinds}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
