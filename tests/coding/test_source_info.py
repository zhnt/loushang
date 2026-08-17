from __future__ import annotations

from pathlib import Path


def test_executable_source_identity_projects_stable_runtime_details(
    monkeypatch, tmp_path
) -> None:
    import sys

    from loushang.coding.diagnostics.profile import coding_runtime_identity

    monkeypatch.setattr(sys, "executable", "/tmp/python")
    monkeypatch.setattr(sys, "argv", ["/tmp/bin/loushang", "--list-diagnostics"])

    details = coding_runtime_identity(cwd=tmp_path)

    # entrypoint is resolved (symlinks expanded, e.g. /tmp -> /private/tmp on macOS);
    # python_executable and argv0 keep the caller-supplied form.
    assert details["entrypoint"] == str(Path("/tmp/bin/loushang").resolve())
    assert details["python_executable"] == "/tmp/python"
    assert details["argv0"] == "/tmp/bin/loushang"
    assert details["cwd"] == str(tmp_path)
    assert details["package_name"] == "loushang"
    assert isinstance(details["package_version"], str)
    assert isinstance(details["module_file"], str)
    assert isinstance(details["package_root"], str)
    assert isinstance(details["loushang_module_file"], str)
    assert isinstance(details["coding_module_file"], str)
    assert "project_root" in details
    assert "git_branch" in details
    assert "git_commit" in details
    assert "virtual_env" in details
    assert isinstance(details["sys_prefix"], str)
    assert isinstance(details["sys_base_prefix"], str)
    assert details["import_source"] in {
        "editable",
        "installed",
        "source-tree",
        "unknown",
    }
    assert details["install_mode"] in {"editable", "source-tree", "package", "unknown"}


def test_executable_source_identity_marks_path_candidates_active_and_shadowed(
    tmp_path,
) -> None:
    from loushang.coding.diagnostics.profile import coding_runtime_identity

    first_bin = tmp_path / "first" / "bin"
    second_bin = tmp_path / "second" / "bin"
    first_bin.mkdir(parents=True)
    second_bin.mkdir(parents=True)
    first_candidate = first_bin / "loushang"
    second_candidate = second_bin / "loushang"
    first_candidate.write_text("#!/bin/sh\n", encoding="utf-8")
    second_candidate.write_text("#!/bin/sh\n", encoding="utf-8")
    first_candidate.chmod(0o755)
    second_candidate.chmod(0o755)

    details = coding_runtime_identity(
        cwd=tmp_path,
        argv0="loushang",
        env={"PATH": f"{first_bin}:{second_bin}"},
    )

    assert details["entrypoint"] == str(first_candidate)
    assert details["path_candidates"] == [
        {"path": str(first_candidate), "status": "active", "active": True},
        {"path": str(second_candidate), "status": "shadowed", "active": False},
    ]


def test_executable_source_identity_gracefully_degrades_outside_git(tmp_path) -> None:
    from loushang.coding.diagnostics.profile import coding_runtime_identity

    details = coding_runtime_identity(cwd=tmp_path, env={"PATH": ""})

    assert details["project_root"] is None
    assert details["git_branch"] is None
    assert details["git_commit"] is None
    assert details["path_candidates"] == []


def test_source_info_from_resource_descriptor_projects_package_provenance() -> None:
    from loushang.harness.resources.source import source_info_from_resource_descriptor
    from loushang.harness.resources.types import PromptFragmentDescriptor

    descriptor = PromptFragmentDescriptor(
        name="review",
        source_path=Path("/tmp/plugin/prompts/review.md"),
        text="Review carefully.",
        source="package_resource",
        source_kind="external_package",
        source_scope="package",
        source_root=Path("/tmp/plugin/prompts"),
    )

    info = source_info_from_resource_descriptor(descriptor)

    assert info.path == "/tmp/plugin/prompts/review.md"
    assert info.source == "package_resource"
    assert info.scope == "project"
    assert info.origin == "package"
    assert info.base_dir == "/tmp/plugin/prompts"


def test_source_info_from_resource_descriptor_projects_project_local_provenance() -> (
    None
):
    from loushang.harness.resources.source import source_info_from_resource_descriptor
    from loushang.harness.resources.types import SkillDescriptor

    descriptor = SkillDescriptor(
        name="debug",
        source_path=Path("/tmp/project/skills/debug/SKILL.md"),
        content="Debug carefully.",
        source="filesystem",
        source_kind="project_local",
        source_scope="project",
        source_root=Path("/tmp/project/skills"),
    )

    info = source_info_from_resource_descriptor(descriptor)

    assert info.path == "/tmp/project/skills/debug/SKILL.md"
    assert info.source == "filesystem"
    assert info.scope == "project"
    assert info.origin == "top-level"
    assert info.base_dir == "/tmp/project/skills"
