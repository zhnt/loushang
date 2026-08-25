from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.ai.model import Capabilities, Model
from loushang.coding._resource_catalog_shadow import (
    CodingResourceCatalogShadowAdmissionError,
    build_coding_initial_resource_catalog_shadow_adapter,
)
from loushang.coding.bootstrap import _create_agent_session, create_services
from loushang.coding.control import SettingsManager
from loushang.coding.session_manager import SessionManager
from loushang.harness.resources._catalog_input_receipt import (
    ResourceCatalogInputReceipt,
)


def _model() -> Model:
    return Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128_000,
            max_tokens=4096,
        ),
    )


def _receipt(tmp_path: Path) -> ResourceCatalogInputReceipt:
    user_root = tmp_path / "user"
    project_root = tmp_path / "project"
    user_root.mkdir(exist_ok=True)
    project_root.mkdir(exist_ok=True)
    return ResourceCatalogInputReceipt(
        cwd=project_root,
        project_resource_root=project_root,
        project_context_roots=(tmp_path, project_root),
        package_roots=(),
        user_resource_roots=(user_root,),
        explicit_user_resource_roots=frozenset({user_root}),
        additional_extension_paths=(),
        additional_skill_paths=(),
        additional_prompt_template_paths=(),
        additional_theme_paths=(),
        no_extensions=False,
        no_skills=False,
        no_prompt_templates=False,
        no_themes=False,
        no_context_files=False,
        built_in_resource_packages=("loushang.coding.resources",),
        context_file_names=("AGENTS.md", "CLAUDE.md"),
    )


def test_coding_shadow_maps_one_receipt_without_bundle_inference(
    tmp_path: Path,
) -> None:
    adapter = build_coding_initial_resource_catalog_shadow_adapter(_receipt(tmp_path))

    selection = adapter.selection
    assert selection.product_policy_revision == "coding-resource-catalog-shadow-v1"
    assert [item.handle_id for item in selection.native_roots] == [
        "coding-user-0",
        "coding-project-context-0",
        "coding-project-context-1",
        "coding-project-standard",
    ]
    assert [item.root_kind for item in selection.native_roots] == [
        "combined",
        "context",
        "context",
        "standard",
    ]
    assert [item.source_root_order for item in selection.native_roots] == [
        0,
        0,
        1,
        0,
    ]
    assert len(selection.embedded_collections) == 1
    embedded = selection.embedded_collections[0]
    assert embedded.collection_id == "coding-built-in-0"
    assert embedded.embedded_revision.startswith("sha256:")
    assert selection.context_file_names == ("AGENTS.md", "CLAUDE.md")


def test_coding_shadow_preserves_disabled_context_as_standard_roots(
    tmp_path: Path,
) -> None:
    receipt = replace(
        _receipt(tmp_path),
        project_context_roots=(),
        no_context_files=True,
    )

    selection = build_coding_initial_resource_catalog_shadow_adapter(receipt).selection

    assert [item.handle_id for item in selection.native_roots] == [
        "coding-user-0",
        "coding-project-standard",
    ]
    assert [item.root_kind for item in selection.native_roots] == [
        "standard",
        "standard",
    ]


@pytest.mark.parametrize(
    ("change", "disabled_skills", "reason"),
    (
        ({"package_roots": (Path("/package"),)}, (), "package_sources"),
        (
            {"additional_skill_paths": (Path("skill"),)},
            (),
            "temporary_sources",
        ),
        ({"no_skills": True}, (), "resource_kind_switches"),
        ({}, ("review",), "disabled_skills"),
    ),
)
def test_coding_shadow_rejects_inputs_not_covered_by_the_thin_slice(
    tmp_path: Path,
    change: dict[str, object],
    disabled_skills: tuple[str, ...],
    reason: str,
) -> None:
    receipt = replace(_receipt(tmp_path), **change)

    with pytest.raises(CodingResourceCatalogShadowAdmissionError) as captured:
        build_coding_initial_resource_catalog_shadow_adapter(
            receipt,
            disabled_skills=disabled_skills,
        )

    assert reason in captured.value.reasons


def test_coding_initial_catalog_shadow_publishes_project_context_and_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        project_root = tmp_path / "project"
        skill_root = project_root / "skills" / "review"
        skill_root.mkdir(parents=True)
        (project_root / "AGENTS.md").write_text("Project guidance", encoding="utf-8")
        (skill_root / "SKILL.md").write_text(
            "---\nname: review\ndescription: Review code\n---\nReview carefully.\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "missing-home"))
        services = create_services(
            settings_manager=SettingsManager(
                global_settings_path=tmp_path / "global-settings.json",
                project_settings_path=tmp_path / "project-settings.json",
            )
        )
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(project_root),
            persist=False,
        )
        session = _create_agent_session(
            session_manager=manager,
            services=services,
            model=_model(),
            enable_initial_resource_catalog_shadow=True,
        )
        bootstrap = session._initial_resource_catalog_bootstrap
        assert bootstrap is not None
        resource_candidate = session._staged_resource_candidate
        assert resource_candidate is not None
        try:
            await session.prepare_model_call_runtime()

            assert bootstrap.state == "published"
            assert resource_candidate.ownership_state == "graph_owned"
            assert session._resource_catalog_snapshot is not None
            assert session.resource_bundle is not None
            assert [skill.name for skill in session.resource_bundle.skills] == [
                "review"
            ]
            assert [
                descriptor.text
                for descriptor in session.resource_bundle.prompt_descriptors
            ] == ["Project guidance"]
        finally:
            await session.dispose()
        assert resource_candidate.ownership_state == "disposed"
        assert session._capability_graph_runtime.is_closed is True
        assert session._capability_graph_runtime.has_pending_retirements is False

    asyncio.run(scenario())
