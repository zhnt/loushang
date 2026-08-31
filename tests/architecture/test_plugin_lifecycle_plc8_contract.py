from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

import loushang.plugin as plugin_sdk
from loushang.harness.workspace.process import ProcessLaunchRequest

CONTRACT = Path(
    "docs/internals/architecture/harness/plugin/"
    "plugin-lifecycle-plc8-contract.md"
)
GUIDE = Path(
    "docs/internals/architecture/harness/plugin/plugin-authoring-guide.md"
)
README = Path("docs/internals/architecture/harness/plugin/README.md")
VALIDATION = Path("src/loushang/plugin/_validation.py")
CONFORMANCE = Path("src/loushang/plugin/_conformance.py")
ACTION_RUNTIME = Path("src/loushang/harness/tools/skill_actions.py")
PROCESS_RUNTIME = Path("src/loushang/harness/tools/process_hosting.py")
SKILL_CONSUMER = Path(
    "src/loushang/harness/resources/_skill_catalog_consumer.py"
)
ACTION_AUTHORITY = Path(
    "src/loushang/harness/resources/_skill_action_authority.py"
)
RESOURCE_OWNER_GENERATION = Path(
    "src/loushang/harness/resource_catalog/generation.py"
)
RESOURCE_PROVIDER = Path(
    "src/loushang/harness/capabilities/resources_provider.py"
)
AGENT_PRODUCT = Path("src/loushang/harness/session/agent_product.py")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }


def test_plc8_contract_and_author_guide_are_canonical_entries() -> None:
    contract = CONTRACT.read_text(encoding="utf-8")
    guide = GUIDE.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")

    assert "manifestVersion` | `1" in contract
    assert "engine.declarationIrVersion` | `2" in contract
    assert "CatalogManagedSkillAction" in contract
    assert "public four-field `ProcessLaunchRequest` remains unchanged" in contract
    assert "loushang-plugin validate" in guide
    assert "--approve-execution" in guide
    assert readme.count("plugin-lifecycle-plc8-contract.md") == 1
    assert readme.count("plugin-authoring-guide.md") == 1


def test_public_sdk_has_no_owner_authority_exports() -> None:
    forbidden = {
        "Approval",
        "Graph",
        "PluginContext",
        "PluginRegistry",
        "RegistrationScope",
        "Sandbox",
        "Session",
    }
    assert not forbidden.intersection(plugin_sdk.__all__)
    assert {
        "capability_provider",
        "capability_requirement",
        "package",
        "plugin_definition",
        "resource",
        "skill_action",
        "validate_package",
    }.issubset(plugin_sdk.__all__)


def test_validation_is_inert_and_conformance_is_explicitly_gated() -> None:
    validation_imports = _imports(VALIDATION)
    validation_source = VALIDATION.read_text(encoding="utf-8")
    conformance_source = CONFORMANCE.read_text(encoding="utf-8")

    assert not validation_imports & {"importlib", "runpy", "subprocess"}
    assert "eval(" not in validation_source
    assert "exec(" not in validation_source
    assert "run_execution_conformance" not in validation_source
    assert conformance_source.index("execution_approved is not True") < (
        conformance_source.index("runpy.run_path")
    )


def test_managed_action_consumes_catalog_facts_and_existing_host_authorities() -> None:
    action_source = ACTION_RUNTIME.read_text(encoding="utf-8")
    process_source = PROCESS_RUNTIME.read_text(encoding="utf-8")
    consumer_source = SKILL_CONSUMER.read_text(encoding="utf-8")
    authority_source = ACTION_AUTHORITY.read_text(encoding="utf-8")
    owner_source = RESOURCE_OWNER_GENERATION.read_text(encoding="utf-8")
    provider_source = RESOURCE_PROVIDER.read_text(encoding="utf-8")
    product_source = AGENT_PRODUCT.read_text(encoding="utf-8")

    assert "CatalogManagedSkillAction" in action_source
    assert "SkillCatalogConsumer" not in action_source
    assert "catalogSnapshotFingerprint" in action_source
    assert "type(launcher) is not ScopeBoundProcessLauncher" in action_source
    assert "subprocess" not in action_source
    assert "_managed_process_launch_request" in action_source
    assert "_start_managed" in action_source
    assert "_ManagedProcessLaunchRequest" in process_source
    assert "pre_start_validator" in process_source
    assert "_sealed_executable" in action_source
    assert not any(
        name.startswith("loushang.harness.sandbox")
        for name in _imports(PROCESS_RUNTIME)
    )
    assert "capture_managed_actions" in consumer_source
    assert "_mint_catalog_managed_skill_action" not in consumer_source
    assert "_CatalogActionOwnerSeal" in consumer_source
    assert "_register_catalog_managed_skill_action" in consumer_source
    assert "_from_resource_owner" in consumer_source
    assert "owner-constructed Skill consumer" in consumer_source
    assert "_owner_constructing" not in consumer_source
    assert "_prepare_managed_action_owner" not in consumer_source
    assert "_install_managed_action_owner" not in consumer_source
    assert "_REGISTRATIONS" in authority_source
    assert "_CatalogActionOwnerSnapshot" in authority_source
    assert "_CatalogActionOwnerLiveness" in authority_source
    assert "SkillCatalogConsumer" not in authority_source
    assert "resource_catalog.generation" not in authority_source
    assert "sys.modules" not in authority_source
    assert "_skill_action_owner_registrations" not in authority_source
    assert "_managed_action_owner_identity" not in authority_source
    assert "_managed_action_owner_capability" not in authority_source
    assert "consumer_ref" not in authority_source
    assert "_construct_skill_catalog_consumer" in owner_source
    assert "_skill_action_owner_registrations" not in owner_source
    assert "_new_catalog_action_owner_generation_lifecycle" in owner_source
    assert "_prepare_catalog_action_owner_binding" in owner_source
    assert "skill_consumer=skill_consumer" in provider_source
    assert product_source.count(
        "self._skill_catalog_consumer = skill_catalog.skill_consumer"
    ) == 2
    assert "SkillCatalogConsumer(skill_catalog)" not in product_source


def test_public_process_request_contract_is_not_widened_for_skill_actions() -> None:
    assert {field.name for field in fields(ProcessLaunchRequest)} == {
        "command",
        "cwd",
        "effective_environment",
        "stream_stderr",
    }


def test_production_definitions_use_the_public_author_namespace() -> None:
    for path in (
        Path("src/loushang/coding/_plugins/coding_lsp_default/definition.py"),
        Path("src/loushang/coding/_plugins/coding_arch_default/definition.py"),
    ):
        imports = _imports(path)
        assert "loushang.plugin" in imports
        assert "loushang.harness.plugin_authoring.builder" not in imports
