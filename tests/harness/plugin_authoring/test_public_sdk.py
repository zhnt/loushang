from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
from pathlib import Path

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
    PluginPackageSpec,
    capability_provider,
    capability_requirement,
    package,
    resource,
    skill_action,
    skill_action_effect,
    validate_package,
)
from loushang.plugin.__main__ import main as plugin_cli_main

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
    }.issubset(plugin_sdk.__all__)
    assert not {
        "Approval",
        "Graph",
        "PluginContext",
        "PluginRegistry",
        "RegistrationScope",
        "Sandbox",
    }.intersection(plugin_sdk.__all__)


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
