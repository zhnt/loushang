from __future__ import annotations

from pathlib import Path

import pytest

from loushang.coding._base_plugin import (
    CodingBasePluginAssemblyError,
    coding_base_plugin_root,
    prepare_coding_base_plugin_assembly,
)
from loushang.coding.composition_sets import resolve_coding_composition_set
from loushang.coding.prompt import CODING_STANDARD_SYSTEM_PROMPT_FRAGMENT
from loushang.coding.resource_runtime import CodingPackageMaterializer
from loushang.harness.plugin_authoring.consumer_pack import (
    CommandPackDeclarationPayload,
    ToolPackDeclarationPayload,
)
from loushang.harness.plugin_authoring.resource_item import (
    ResourceItemDeclarationPayload,
)
from loushang.harness.session.product_composition_assembly import (
    assemble_product_composition,
)


def _materializer(tmp_path: Path) -> CodingPackageMaterializer:
    return CodingPackageMaterializer(
        install_root=tmp_path / "installed",
        plugin_revision_root=tmp_path / "revisions",
    )


def test_checked_in_base_package_is_data_only_and_matches_product_catalogs(
    tmp_path: Path,
) -> None:
    assembly = prepare_coding_base_plugin_assembly(
        resolve_coding_composition_set("coding-standard"),
        session_id="package-shape",
        package_materializer=_materializer(tmp_path),
    )
    try:
        assert assembly.package.manifest.name == "coding.base"
        assert assembly.package.dependency_lock.python_distributions == ()
        assert not (coding_base_plugin_root() / "definition.py").exists()
        assert (coding_base_plugin_root() / "prompts" / "standard.md").read_text(
            encoding="utf-8"
        ) == CODING_STANDARD_SYSTEM_PROMPT_FRAGMENT

        candidates = {
            item.declaration.contribution_id: item
            for item in assembly.selection.candidates
        }
        assert tuple(candidates) == (
            "coding.builtin",
            "coding.standard",
            "prompt-standard",
            "skill-standard",
        )
        tools = ToolPackDeclarationPayload.from_candidate(candidates["coding.builtin"])
        commands = CommandPackDeclarationPayload.from_candidate(
            candidates["coding.standard"]
        )
        prompt = ResourceItemDeclarationPayload.from_candidate(
            candidates["prompt-standard"]
        )
        skill = ResourceItemDeclarationPayload.from_candidate(
            candidates["skill-standard"]
        )
        assert tools.item_ids == (
            "bash",
            "edit",
            "find",
            "grep",
            "ls",
            "read",
            "write",
        )
        assert commands.item_ids == (
            "branch",
            "changelog",
            "clone",
            "compact",
            "copy",
            "delete",
            "export",
            "extensions",
            "fork",
            "import",
            "new",
            "reload",
            "rename",
            "resume",
            "session",
            "tools",
            "tree",
        )
        assert (prompt.resource_kind, prompt.locator) == (
            "prompt",
            "prompts/standard.md",
        )
        assert (skill.resource_kind, skill.locator) == (
            "skill",
            "skills/standard/SKILL.md",
        )
        assert (
            coding_base_plugin_root() / skill.locator
        ).read_text(encoding="utf-8").startswith("---\nname: standard\n")
    finally:
        assembly.close()


def test_base_assembly_compiles_all_four_exact_owner_admissions(
    tmp_path: Path,
) -> None:
    composition_set = resolve_coding_composition_set("coding-standard")
    assembly = prepare_coding_base_plugin_assembly(
        composition_set,
        session_id="owner-admission",
        package_materializer=_materializer(tmp_path),
    )
    try:
        compilation = assemble_product_composition(
            assembly.composition_request,
            evaluated_at=10,
        )

        assert assembly.scope_id == "session:owner-admission"
        assert assembly.composition_set_fingerprint == composition_set.fingerprint
        assert {
            (item.owner_id, item.contribution_kind)
            for item in compilation.resource_admissions
        } == {
            ("resources.prompt", "resource_item"),
            ("resources.skill", "resource_item"),
        }
        assert {
            (item.owner_id, item.contribution_kind)
            for item in compilation.catalog_admissions
        } == {
            ("commands.session", "command_pack"),
            ("tools.workspace", "tool_pack"),
        }
        assert compilation.consumer_requirements.mandatory_roots == (
            "harness.model_input",
        )
        assert compilation.consumer_requirements.roots == (
            "harness.model_input",
            "harness.workspace",
        )
        [requirement] = compilation.consumer_requirements.entries
        assert requirement.plugin_id == "coding.base"
        assert requirement.contribution_id == "coding.builtin"
        assert requirement.requirement.capability == "harness.workspace"
    finally:
        handle = assembly.package.revision_handle
        assert handle.closed is False
        assembly.close()
        assert handle.closed is True
        assembly.close()


def test_minimal_set_cannot_prepare_a_hidden_base_package(tmp_path: Path) -> None:
    with pytest.raises(CodingBasePluginAssemblyError) as captured:
        prepare_coding_base_plugin_assembly(
            resolve_coding_composition_set("coding-minimal"),
            session_id="minimal",
            package_materializer=_materializer(tmp_path),
        )

    assert captured.value.code == "coding_base_not_requested"
