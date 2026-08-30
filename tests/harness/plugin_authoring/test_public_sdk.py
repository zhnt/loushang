from __future__ import annotations

from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path

import pytest

import loushang.plugin as plugin_sdk
from loushang.harness.capabilities.contracts import CapabilityRequirement
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.manifest import PluginManifestParser
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
