from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

import loushang.plugin as plugin_sdk
from loushang.harness.capabilities.contracts import CapabilityRequirement
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.declarations import (
    PluginDeclarationDocument,
    PluginDeclarationDocumentCodec,
)
from loushang.harness.resources.plugins.manifest import (
    PluginManifestError,
    PluginManifestParser,
)
from loushang.plugin import (
    CapabilityProviderSpec,
    PluginPackageArtifact,
    PluginPackageSpec,
    build_coding_data_prompt_wheel,
    build_coding_data_skill_wheel,
    build_coding_data_theme_wheel,
    capability_provider,
    capability_requirement,
    package,
    resource,
    skill_action,
    skill_action_effect,
    validate_package,
    write_coding_data_prompt_wheel,
    write_coding_data_skill_wheel,
    write_package_tree,
)
from loushang.plugin.__main__ import main as plugin_cli_main
from loushang.plugin._coding_data_skill_wheel import _build_resource_wheel

_FIXTURES = Path(__file__).parent / "fixtures"
_AUTHOR_GUIDE = Path(
    "docs/internals/architecture/harness/plugin/plugin-authoring-guide.md"
)


def test_public_sdk_exports_only_data_authoring_and_inert_validation() -> None:
    assert {
        "capability_provider",
        "capability_requirement",
        "package",
        "plugin_definition",
        "resource",
        "validate_package",
        "write_package_tree",
    }.issubset(plugin_sdk.__all__)
    assert not {
        "Approval",
        "Graph",
        "PluginContext",
        "PluginRegistry",
        "RegistrationScope",
        "Sandbox",
    }.intersection(plugin_sdk.__all__)


def test_package_writer_creates_new_tree_and_runs_inert_validation(
    tmp_path: Path,
) -> None:
    spec = package(
        id="org.example.review",
        version="1",
        contributions=(
            resource.skill(contribution_id="review-skill", locator="skills/review"),
        ),
    )
    root = tmp_path / "new-plugin"
    result = write_package_tree(
        root,
        spec,
        content_files={
            "skills/review/SKILL.md": b"# Review\n",
        },
    )

    assert result.valid
    assert result.plugin_id == "org.example.review"
    assert (root / "plugin.json").read_bytes() == spec.read("plugin.json")
    assert (root / "skills/review/SKILL.md").read_bytes() == b"# Review\n"
    with pytest.raises(FileExistsError):
        write_package_tree(root, spec)
    assert (root / "skills/review/SKILL.md").read_bytes() == b"# Review\n"


def test_generic_validation_does_not_claim_product_admission_or_use(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec = package(
        id="org.example.review",
        version="1",
        contributions=(
            resource.skill(contribution_id="review-skill", locator="skills/review"),
        ),
    )
    root = tmp_path / "generic-plugin"
    write_package_tree(
        root, spec, content_files={"skills/review/SKILL.md": b"# Review\n"}
    )
    assert plugin_cli_main(["validate", str(root)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["valid"] is True
    assert report["pluginId"] == "org.example.review"
    assert report["productAdmission"] == "not_checked"
    assert report["productSelection"] == "not_checked"
    assert report["productUse"] == "not_checked"


def test_package_writer_rejects_escape_and_collisions_before_creating_tree(
    tmp_path: Path,
) -> None:
    spec = package(
        id="org.example.review",
        version="1",
        contributions=(
            resource.skill(contribution_id="review-skill", locator="skills/review"),
        ),
    )
    root = tmp_path / "new-plugin"
    with pytest.raises(ValueError, match="canonical contained relative path"):
        write_package_tree(root, spec, content_files={"../escape": b"bad"})
    with pytest.raises(ValueError, match="repeats file"):
        write_package_tree(root, spec, content_files={"plugin.json": b"bad"})
    with pytest.raises(ValueError, match="file and directory paths conflict"):
        write_package_tree(
            root,
            spec,
            content_files={
                "skills": b"bad",
                "skills/review/SKILL.md": b"# Review\n",
            },
        )
    with pytest.raises(ValueError, match="canonical contained relative path"):
        write_package_tree(
            root,
            PluginPackageSpec(
                plugin_id="org.example.review",
                version="1",
                artifacts=(PluginPackageArtifact("/escape", b"bad"),),
            ),
        )
    assert not root.exists()
    assert not (tmp_path / "escape").exists()


def test_public_coding_data_skill_recipe_is_deterministic_and_product_shaped(
    tmp_path: Path,
) -> None:
    arguments = {
        "plugin_id": "reviewpack",
        "version": "1",
        "contribution_id": "review-skill",
        "skill_name": "review",
        "skill_document": b"---\nname: review\ndescription: Review files\n---\n# Review\n",
    }
    wheel = build_coding_data_skill_wheel(**arguments)
    assert wheel == build_coding_data_skill_wheel(**arguments)
    with ZipFile(BytesIO(wheel)) as archive:
        assert set(archive.namelist()) == {
            "reviewpack/plugin.json",
            "reviewpack/declarations/resources.json",
            "reviewpack/skills/review/SKILL.md",
            "reviewpack-1.dist-info/METADATA",
            "reviewpack-1.dist-info/WHEEL",
            "reviewpack-1.dist-info/RECORD",
        }
    path = write_coding_data_skill_wheel(tmp_path, **arguments)
    assert path.read_bytes() == wheel
    with pytest.raises(FileExistsError):
        write_coding_data_skill_wheel(tmp_path, **arguments)
    assert path.read_bytes() == wheel


def test_public_coding_data_prompt_recipe_is_deterministic_and_product_shaped(
    tmp_path: Path,
) -> None:
    arguments = {
        "plugin_id": "promptpack",
        "version": "1",
        "contribution_id": "review-prompt",
        "prompt_name": "review",
        "prompt_document": b"# Review\nCheck the change carefully.\n",
    }
    wheel = build_coding_data_prompt_wheel(**arguments)
    assert wheel == build_coding_data_prompt_wheel(**arguments)
    with ZipFile(BytesIO(wheel)) as archive:
        assert set(archive.namelist()) == {
            "promptpack/plugin.json",
            "promptpack/declarations/resources.json",
            "promptpack/prompts/review.md",
            "promptpack-1.dist-info/METADATA",
            "promptpack-1.dist-info/WHEEL",
            "promptpack-1.dist-info/RECORD",
        }
    path = write_coding_data_prompt_wheel(tmp_path, **arguments)
    assert path.read_bytes() == wheel
    with pytest.raises(FileExistsError):
        write_coding_data_prompt_wheel(tmp_path, **arguments)


def test_coding_data_skill_recipe_rejects_generic_sdk_identity_and_oversize() -> None:
    arguments = {
        "plugin_id": "reviewpack",
        "version": "1",
        "contribution_id": "review-skill",
        "skill_name": "review",
        "skill_document": b"# Review\n",
    }
    with pytest.raises(ValueError, match="simple lowercase ASCII"):
        build_coding_data_skill_wheel(
            **{**arguments, "plugin_id": "org.example.review"}
        )
    with pytest.raises(ValueError, match="filename exceeds Product limit"):
        build_coding_data_skill_wheel(**{**arguments, "plugin_id": "a" * 170})
    with pytest.raises(ValueError, match="extracted tree"):
        build_coding_data_skill_wheel(
            **{**arguments, "skill_document": b"x" * (1024 * 1024)}
        )


def test_coding_data_skill_cli_builds_new_artifact_from_skill_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skill_root = tmp_path / "skills" / "review"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review files\n---\n# Review\n",
        encoding="utf-8",
    )
    args = [
        "build-coding-skill",
        str(skill_root / "SKILL.md"),
        "--plugin-id",
        "reviewpack",
        "--version",
        "1",
        "--output-dir",
        str(tmp_path / "dist"),
    ]
    assert plugin_cli_main(args) == 0
    report = json.loads(capsys.readouterr().out)
    wheel = tmp_path / "dist" / "reviewpack-1-py3-none-any.whl"
    assert report == {
        "artifactPath": str(wheel),
        "artifactSha256": sha256(wheel.read_bytes()).hexdigest(),
        "disposableSmoke": "not_checked",
        "profile": "coding-data-skill-v1",
        "productAdmission": "not_checked",
        "productSelection": "not_checked",
        "productUse": "not_checked",
        "sha256": sha256(wheel.read_bytes()).hexdigest(),
        "sourcePath": str(skill_root / "SKILL.md"),
        "targetInstallCommand": [
            "loushang",
            "--install-package",
            str(wheel),
            "--package-scope",
            "project",
        ],
        "validationCommand": ["loushang-plugin", "validate-coding-wheel", str(wheel)],
        "validationDiagnostics": [],
        "validationResult": "passed",
    }
    with pytest.raises(SystemExit, match="2"):
        plugin_cli_main(args)
    assert wheel.read_bytes() == build_coding_data_skill_wheel(
        plugin_id="reviewpack",
        version="1",
        contribution_id="review-skill",
        skill_name="review",
        skill_document=(skill_root / "SKILL.md").read_bytes(),
    )
    linked_skill = skill_root / "LINK.md"
    try:
        linked_skill.symlink_to(skill_root / "SKILL.md")
    except OSError:
        pytest.skip("Symlinks are unavailable on this host")
    with pytest.raises(SystemExit, match="2"):
        plugin_cli_main(
            [
                "build-coding-skill",
                str(linked_skill),
                "--plugin-id",
                "reviewpack",
                "--version",
                "2",
                "--output-dir",
                str(tmp_path / "dist"),
            ]
        )
    assert not (tmp_path / "dist" / "reviewpack-2-py3-none-any.whl").exists()


def test_coding_data_prompt_cli_builds_new_artifact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    prompt = tmp_path / "prompts" / "review.md"
    prompt.parent.mkdir()
    prompt.write_text("# Review\nCheck the change carefully.\n", encoding="utf-8")
    args = [
        "build-coding-prompt",
        str(prompt),
        "--plugin-id",
        "promptpack",
        "--version",
        "1",
        "--output-dir",
        str(tmp_path / "dist"),
    ]
    assert plugin_cli_main(args) == 0
    report = json.loads(capsys.readouterr().out)
    wheel = tmp_path / "dist" / "promptpack-1-py3-none-any.whl"
    assert report == {
        "artifactPath": str(wheel),
        "artifactSha256": sha256(wheel.read_bytes()).hexdigest(),
        "disposableSmoke": "not_checked",
        "profile": "coding-data-prompt-v1",
        "productAdmission": "not_checked",
        "productSelection": "not_checked",
        "productUse": "not_checked",
        "sha256": sha256(wheel.read_bytes()).hexdigest(),
        "sourcePath": str(prompt),
        "targetInstallCommand": [
            "loushang",
            "--install-package",
            str(wheel),
            "--package-scope",
            "project",
        ],
        "validationCommand": ["loushang-plugin", "validate-coding-wheel", str(wheel)],
        "validationDiagnostics": [],
        "validationResult": "passed",
    }
    assert wheel.read_bytes() == build_coding_data_prompt_wheel(
        plugin_id="promptpack",
        version="1",
        contribution_id="review-prompt",
        prompt_name="review",
        prompt_document=prompt.read_bytes(),
    )
    with pytest.raises(SystemExit, match="2"):
        plugin_cli_main(args)


@pytest.mark.parametrize("kind", ["skill", "prompt"])
def test_coding_data_wheel_cli_validates_built_artifact_without_product_admission(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    root = tmp_path / kind
    assert plugin_cli_main([f"init-coding-{kind}", str(root)]) == 0
    scaffold = json.loads(capsys.readouterr().out)
    assert plugin_cli_main(scaffold["buildCommand"][1:]) == 0
    built = json.loads(capsys.readouterr().out)

    assert plugin_cli_main(["validate-coding-wheel", built["artifactPath"]]) == 0
    validated = json.loads(capsys.readouterr().out)
    assert validated["valid"] is True
    assert validated["artifactPath"] == built["artifactPath"]
    assert validated["sha256"] == built["sha256"]
    assert validated["profile"] == f"coding-data-{kind}-v1"
    assert validated["pluginId"] == kind
    assert validated["productAdmission"] == "not_checked"
    assert validated["productSelection"] == "not_checked"
    assert validated["productUse"] == "not_checked"
    artifact = Path(built["artifactPath"])
    changed = bytearray(artifact.read_bytes())
    changed[0] ^= 1
    artifact.write_bytes(changed)
    assert plugin_cli_main(["validate-coding-wheel", str(artifact)]) == 1
    rejected = json.loads(capsys.readouterr().out)
    assert rejected["valid"] is False
    assert rejected["sha256"] != built["sha256"]


def test_coding_data_wheel_cli_rejects_non_wheel_and_unsupported_kind(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skill = build_coding_data_skill_wheel(
        plugin_id="reviewpack",
        version="1",
        contribution_id="review-skill",
        skill_name="review",
        skill_document=b"---\nname: review\ndescription: Review files\n---\n# Review\n",
    )
    wheel = tmp_path / "reviewpack-1-py3-none-any.whl"
    wheel.write_bytes(skill)
    linked = tmp_path / "linked-1-py3-none-any.whl"
    linked.symlink_to(wheel)
    for invalid in (tmp_path, linked):
        assert plugin_cli_main(["validate-coding-wheel", str(invalid)]) == 1
        assert json.loads(capsys.readouterr().out)["valid"] is False

    theme = build_coding_data_theme_wheel(
        plugin_id="themepack",
        version="1",
        contribution_id="dusk-theme",
        theme_name="dusk",
        theme_document=b'{"schemaVersion":1,"tokens":{"welcome.title":{"color":"red"}}}',
    )
    theme_path = tmp_path / "themepack-1-py3-none-any.whl"
    theme_path.write_bytes(theme)
    assert plugin_cli_main(["validate-coding-wheel", str(theme_path)]) == 1
    rejected = json.loads(capsys.readouterr().out)
    assert rejected["valid"] is False
    assert rejected["diagnostics"][0]["code"] == "coding_data_wheel_profile_unsupported"

    misplaced = _build_resource_wheel(
        plugin_id="reviewpack",
        version="2",
        resource_spec=resource.skill(
            contribution_id="review-skill", locator="other/review"
        ),
        body_path="other/review/SKILL.md",
        body=b"# Review\n",
    )
    misplaced_path = tmp_path / "reviewpack-2-py3-none-any.whl"
    misplaced_path.write_bytes(misplaced)
    assert plugin_cli_main(["validate-coding-wheel", str(misplaced_path)]) == 1
    rejected = json.loads(capsys.readouterr().out)
    assert rejected["diagnostics"][0]["code"] == "coding_data_wheel_profile_unsupported"


@pytest.mark.parametrize(
    ("kind", "relative_source", "build_command"),
    [
        ("skill", "skills/review/SKILL.md", "build-coding-skill"),
        ("prompt", "prompts/review.md", "build-coding-prompt"),
        ("theme", "themes/review.json", "build-coding-theme"),
    ],
)
def test_coding_data_scaffold_produces_buildable_source_without_replacement(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    kind: str,
    relative_source: str,
    build_command: str,
) -> None:
    root = tmp_path / "reviewpack"
    assert (
        plugin_cli_main(
            [
                f"init-coding-{kind}",
                str(root),
                "--resource-name",
                "review",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    source = root / relative_source
    assert report["sourcePath"] == str(source)
    assert report["profile"] == f"coding-data-{kind}-v1"
    assert report["productAdmission"] == "not_checked"
    assert report["productSelection"] == "not_checked"
    assert report["productUse"] == "not_checked"
    assert report["buildCommand"][:2] == ["loushang-plugin", build_command]
    assert report["smokeCommand"][:2] == [
        "loushang-coding-plugin-smoke",
        str(root / "dist" / "reviewpack-1-py3-none-any.whl"),
    ]
    assert source.is_file()
    if kind == "theme":
        assert json.loads(source.read_text(encoding="utf-8"))["tokens"][
            "welcome.title"
        ] == {
            "color": "red",
            "bold": True,
        }
    else:
        assert "review" in source.read_text(encoding="utf-8")
    assert plugin_cli_main(report["buildCommand"][1:]) == 0
    built = json.loads(capsys.readouterr().out)
    assert Path(built["artifactPath"]).is_file()
    assert report["smokeCommand"][1] == built["artifactPath"]
    original = source.read_bytes()
    with pytest.raises(SystemExit, match="2"):
        plugin_cli_main([f"init-coding-{kind}", str(root)])
    assert source.read_bytes() == original
    with pytest.raises(SystemExit, match="2"):
        plugin_cli_main(
            [f"init-coding-{kind}", str(tmp_path / "invalid"), "--resource-name", "BAD"]
        )
    assert not (tmp_path / "invalid").exists()


def test_public_capability_helpers_are_frozen_and_use_canonical_requirement() -> None:
    requirement = capability_requirement(
        capability="harness.workspace",
        facets=("read",),
        contract=1,
    )
    provider = capability_provider(
        contribution_id="echo-provider",
        capability="example.echo",
        provider_id="org.example.echo/default",
        implementation_version=1,
        contract=(1, 2),
        facets=("echo",),
        requirements=(requirement,),
        factory="definition.py:create_provider",
        disposer=None,
    )

    assert type(requirement) is CapabilityRequirement
    assert isinstance(provider, CapabilityProviderSpec)
    assert provider.compatible_contract.minimum == 1
    assert provider.compatible_contract.maximum == 2
    with pytest.raises(FrozenInstanceError):
        provider.provider_id = "changed"  # type: ignore[misc]


def test_author_guide_separates_author_sdk_from_exact_provider_runtime_abi() -> None:
    guide = _AUTHOR_GUIDE.read_text(encoding="utf-8")
    definition_source = guide.split("```python\n", 1)[1].split("\n```", 1)[0]
    provider_source = guide.split("```python\n", 2)[2].split("\n```", 1)[0]

    assert "from loushang.plugin import" in definition_source
    assert 'factory="provider.py:create_provider"' in definition_source
    assert "loushang.plugin.provider_runtime" not in definition_source
    assert "from loushang.plugin.provider_runtime import" in provider_source
    assert "loushang.harness" not in provider_source
    assert "from loushang.plugin import" not in provider_source


def test_package_compiler_emits_runtime_ir_and_one_skill_resource_document(
    tmp_path: Path,
) -> None:
    script = b"print('review')\n"
    action = skill_action(
        id="review",
        script="scripts/review.py",
        script_digest=sha256(script).hexdigest(),
        runtime="python",
        argv=("--check",),
        effects=(skill_action_effect(kind="filesystem.read", target="workspace"),),
    )
    skill = resource.skill(
        contribution_id="review-skill",
        locator="skills/review",
        actions=(action,),
    )
    compiled = package(
        id="org.example.review",
        version="1.0.0",
        contributions=(skill,),
    )
    assert isinstance(compiled, PluginPackageSpec)
    assert tuple(item.path for item in compiled.artifacts) == (
        "plugin.json",
        "declarations/resources.json",
        "skills/review/actions.json",
    )
    manifest = StrictPluginJsonCodec.decode_bytes(compiled.read("plugin.json"))
    assert manifest["engine"] == {
        "apiVersion": 1,
        "declarationIrVersion": 2,
        "requiredFeatures": [
            "declaration-document-v1",
            "managed-skill-action-v1",
            "resource-item-v1",
        ],
    }

    for artifact in compiled.artifacts:
        target = tmp_path / artifact.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(artifact.content)
    skill_dir = tmp_path / "skills" / "review"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("# Review\n", encoding="utf-8")
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "review.py").write_bytes(script)

    assert PluginManifestParser().parse(tmp_path).manifest.name == "org.example.review"
    result = validate_package(tmp_path)
    assert result.valid
    assert result.diagnostics == ()


def test_validation_is_inert_and_engine_versions_are_explicit() -> None:
    compatible = validate_package(_FIXTURES / "sdk_v1_ir2")
    incompatible = validate_package(_FIXTURES / "sdk_v0_ir1")

    assert compatible.valid
    assert compatible.engine_api_version == 1
    assert compatible.declaration_ir_version == 2
    assert {item.code for item in incompatible.diagnostics} == {
        "unsupported_plugin_declaration_ir_version",
        "unsupported_plugin_engine_api_version",
        "unsupported_plugin_manifest_version",
    }
    with pytest.raises(PluginManifestError) as caught:
        PluginManifestParser().parse(_FIXTURES / "sdk_v0_ir1")
    assert caught.value.code == "unsupported_plugin_manifest_version"


def test_runtime_and_public_validator_share_fail_closed_engine_negotiation(
    tmp_path: Path,
) -> None:
    skill = resource.skill(
        contribution_id="review-skill",
        locator="skills/review",
    )
    compiled = package(
        id="org.example.review",
        version="1",
        contributions=(skill,),
    )
    manifest = StrictPluginJsonCodec.decode_bytes(compiled.read("plugin.json"))
    assert isinstance(manifest, dict)
    engine = manifest["engine"]
    assert isinstance(engine, dict)
    engine["requiredFeatures"] = ["future-engine-v9"]
    (tmp_path / "plugin.json").write_bytes(StrictPluginJsonCodec.encode(manifest))
    (tmp_path / "definition.py").write_text("def declare(plugin): pass\n")

    result = validate_package(tmp_path)
    with pytest.raises(PluginManifestError) as caught:
        PluginManifestParser().parse(tmp_path)

    assert {item.code for item in result.diagnostics} == {
        "unsupported_plugin_engine_feature"
    }
    assert caught.value.code == "unsupported_plugin_engine_feature"

    missing_root = tmp_path / "missing-feature"
    missing_root.mkdir()
    for artifact in compiled.artifacts:
        target = missing_root / artifact.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(artifact.content)
    missing_manifest = StrictPluginJsonCodec.decode_bytes(compiled.read("plugin.json"))
    assert isinstance(missing_manifest, dict)
    missing_engine = missing_manifest["engine"]
    assert isinstance(missing_engine, dict)
    missing_engine["requiredFeatures"] = ["declaration-document-v1"]
    (missing_root / "plugin.json").write_bytes(
        StrictPluginJsonCodec.encode(missing_manifest)
    )
    missing_result = validate_package(missing_root)
    with pytest.raises(PluginManifestError) as missing_caught:
        PluginManifestParser().parse(missing_root)
    assert {item.code for item in missing_result.diagnostics} == {
        "plugin_engine_feature_declaration_incomplete"
    }
    assert missing_caught.value.code == "plugin_engine_feature_declaration_incomplete"


def test_validation_rejects_known_but_unused_engine_features(tmp_path: Path) -> None:
    skill = resource.skill(
        contribution_id="review-skill",
        locator="skills/review",
    )
    compiled = package(
        id="org.example.review",
        version="1",
        contributions=(skill,),
    )
    for artifact in compiled.artifacts:
        target = tmp_path / artifact.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(artifact.content)
    skill_root = tmp_path / "skills" / "review"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text("# Review\n")
    manifest_path = tmp_path / "plugin.json"
    manifest = StrictPluginJsonCodec.decode_bytes(manifest_path.read_bytes())
    assert isinstance(manifest, dict)
    engine = manifest["engine"]
    assert isinstance(engine, dict)
    features = engine["requiredFeatures"]
    assert isinstance(features, list)
    engine["requiredFeatures"] = sorted([*features, "catalog-consumer-v1"])
    manifest_path.write_bytes(StrictPluginJsonCodec.encode(manifest))

    result = validate_package(tmp_path)
    with pytest.raises(PluginManifestError) as caught:
        PluginManifestParser().parse(tmp_path)

    assert {item.code for item in result.diagnostics} == {
        "plugin_engine_feature_declaration_extraneous"
    }
    assert caught.value.code == "plugin_engine_feature_declaration_extraneous"


def test_stable_action_feature_is_required_by_runtime_and_public_validation(
    tmp_path: Path,
) -> None:
    script = b"print('review')\n"
    declaration = skill_action(
        id="review",
        script="scripts/review.py",
        script_digest=sha256(script).hexdigest(),
        runtime="python",
    )
    compiled = package(
        id="org.example.action-feature",
        version="1",
        contributions=(
            resource.skill(
                contribution_id="review-skill",
                locator="skills/review",
                actions=(declaration,),
            ),
        ),
    )
    for artifact in compiled.artifacts:
        target = tmp_path / artifact.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(artifact.content)
    skill_root = tmp_path / "skills" / "review"
    (skill_root / "SKILL.md").write_text("# Review\n", encoding="utf-8")
    scripts = skill_root / "scripts"
    scripts.mkdir()
    (scripts / "review.py").write_bytes(script)
    manifest_path = tmp_path / "plugin.json"
    manifest = StrictPluginJsonCodec.decode_bytes(manifest_path.read_bytes())
    assert isinstance(manifest, dict)
    engine = manifest["engine"]
    assert isinstance(engine, dict)
    features = engine["requiredFeatures"]
    assert isinstance(features, list)
    engine["requiredFeatures"] = [
        item for item in features if item != "managed-skill-action-v1"
    ]
    manifest_path.write_bytes(StrictPluginJsonCodec.encode(manifest))

    result = validate_package(tmp_path)
    with pytest.raises(PluginManifestError) as caught:
        PluginManifestParser().parse(tmp_path)

    assert {item.code for item in result.diagnostics} == {
        "plugin_engine_feature_declaration_incomplete"
    }
    assert caught.value.code == "plugin_engine_feature_declaration_incomplete"


def test_legacy_manifest_cannot_retain_managed_action_marker(
    tmp_path: Path,
) -> None:
    script = b"print('legacy bypass')\n"
    declaration = skill_action(
        id="review",
        script="scripts/review.py",
        script_digest=sha256(script).hexdigest(),
        runtime="python",
    )
    compiled = package(
        id="org.example.legacy-action-marker",
        version="1",
        contributions=(
            resource.skill(
                contribution_id="review-skill",
                locator="skills/review",
                actions=(declaration,),
            ),
        ),
    )
    for artifact in compiled.artifacts:
        target = tmp_path / artifact.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(artifact.content)
    skill_root = tmp_path / "skills" / "review"
    (skill_root / "SKILL.md").write_text("# Review\n", encoding="utf-8")
    scripts = skill_root / "scripts"
    scripts.mkdir()
    (scripts / "review.py").write_bytes(script)

    manifest_path = tmp_path / "plugin.json"
    manifest = StrictPluginJsonCodec.decode_bytes(manifest_path.read_bytes())
    assert isinstance(manifest, dict)
    manifest.pop("manifestVersion")
    manifest.pop("engine")
    manifest_path.write_bytes(StrictPluginJsonCodec.encode(manifest))

    result = validate_package(tmp_path)
    with pytest.raises(PluginManifestError) as caught:
        PluginManifestParser().parse(tmp_path)

    assert {item.code for item in result.diagnostics} == {
        "plugin_engine_contract_missing"
    }
    assert caught.value.code == "plugin_engine_contract_missing"


def test_validation_rejects_oversized_manifest_before_json_decode(
    tmp_path: Path,
) -> None:
    (tmp_path / "plugin.json").write_bytes(b"x" * (1_048_576 + 1))

    result = validate_package(tmp_path)
    with pytest.raises(PluginManifestError) as caught:
        PluginManifestParser().parse(tmp_path)

    assert {item.code for item in result.diagnostics} == {"plugin_manifest_too_large"}
    assert caught.value.code == "contained_file_too_large"


def test_validation_rejects_declarations_not_reserved_by_manifest(
    tmp_path: Path,
) -> None:
    skill = resource.skill(
        contribution_id="review-skill",
        locator="skills/review",
    )
    compiled = package(
        id="org.example.review",
        version="1",
        contributions=(skill,),
    )
    for artifact in compiled.artifacts:
        target = tmp_path / artifact.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(artifact.content)
    skill_root = tmp_path / "skills" / "review"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text("# Review\n")
    document_path = tmp_path / "declarations" / "resources.json"
    document = PluginDeclarationDocumentCodec.decode_bytes(document_path.read_bytes())
    [declaration] = document.declarations
    extra = replace(declaration, contribution_id="zzz-extra-skill")
    document_path.write_bytes(
        PluginDeclarationDocumentCodec.encode_bytes(
            PluginDeclarationDocument(declarations=(declaration, extra))
        )
    )
    result = validate_package(tmp_path)

    assert "plugin_declaration_reservation_mismatch" in {
        item.code for item in result.diagnostics
    }


def test_execution_conformance_is_a_separate_explicit_command(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider = capability_provider(
        contribution_id="echo-provider",
        capability="example.echo",
        provider_id="org.example.echo/default",
        implementation_version=1,
        contract=1,
        facets=("echo",),
        factory="definition.py:create_provider",
        disposer=None,
    )
    compiled = package(
        id="org.example.echo",
        version="1",
        contributions=(provider,),
    )
    for artifact in compiled.artifacts:
        target = tmp_path / artifact.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(artifact.content)
    (tmp_path / "definition.py").write_text(
        "from pathlib import Path\n"
        "Path(__file__).with_name('executed').write_text('yes')\n"
        "def declare(plugin): pass\n",
        encoding="utf-8",
    )
    marker = tmp_path / "executed"

    assert plugin_cli_main(("validate", str(tmp_path))) == 0
    assert not marker.exists()
    with pytest.raises(SystemExit) as captured:
        plugin_cli_main(("conformance", str(tmp_path)))
    assert captured.value.code == 2
    assert not marker.exists()

    assert plugin_cli_main(("conformance", str(tmp_path), "--approve-execution")) == 0
    assert marker.read_text(encoding="utf-8") == "yes"
    capsys.readouterr()


@pytest.mark.parametrize(
    "package_name",
    ("coding_base", "coding_lsp_default", "coding_arch_default"),
)
def test_production_plugin_packages_satisfy_stable_engine_contract(
    package_name: str,
) -> None:
    root = Path("src/loushang/coding/_plugins") / package_name

    result = validate_package(root)

    assert result.valid, result.diagnostics
