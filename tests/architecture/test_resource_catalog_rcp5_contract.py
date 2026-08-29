from __future__ import annotations

import ast
from pathlib import Path

CONTRACT_PATH = Path(
    "docs/internals/architecture/harness/plugin/resource-catalog-rcp5-contract.md"
)
CONSUMER_PATH = Path(
    "src/loushang/harness/resources/_skill_catalog_consumer.py"
)
STATUS_PROJECTION_PATH = Path(
    "src/loushang/harness/resources/_skill_catalog_status.py"
)
README_PATH = Path("docs/internals/architecture/harness/plugin/README.md")
SOURCE_ROOT = Path("src/loushang")
CAPABILITY_PROVIDER_PATH = Path(
    "src/loushang/harness/capabilities/resources_provider.py"
)
CAPABILITY_CONSUMER_PATH = Path(
    "src/loushang/harness/capabilities/resources_consumers.py"
)
CAPABILITY_CONTRACT_PATH = Path(
    "src/loushang/harness/capabilities/resources_contracts.py"
)
AGENT_PRODUCT_PATH = Path("src/loushang/harness/session/agent_product.py")
COMPOSITION_RUNTIME_PATH = Path(
    "src/loushang/harness/capabilities/composition_runtime.py"
)
PROMPT_PREFLIGHT_PATH = Path(
    "src/loushang/harness/capabilities/prompt_preflight.py"
)
COMMAND_SOURCE_PATH = Path("src/loushang/harness/session/command_sources.py")
REQUEST_EVIDENCE_PATH = Path(
    "src/loushang/harness/session/request_evidence.py"
)
CATALOG_PROJECTION_PATH = Path(
    "src/loushang/harness/resources/_catalog_projection.py"
)
EXTENSION_CATALOG_SOURCE_PATH = Path(
    "src/loushang/harness/resources/_catalog_extension_source.py"
)
EXTENSION_RESOURCE_OWNER_PATH = Path(
    "src/loushang/harness/extensions/resources.py"
)
LEGACY_SKILL_BODY_PATH = Path(
    "src/loushang/harness/resources/_legacy_skill_body.py"
)
METHOD_LOADER_PATH = Path("src/loushang/method/loader.py")
CODING_CLI_PATH = Path("src/loushang/coding/cli/__main__.py")
PUBLIC_SURFACES = (
    Path("src/loushang/harness/resources/__init__.py"),
    Path("src/loushang/harness/__init__.py"),
    Path("src/loushang/coding/__init__.py"),
)
PRIVATE_SKILL_SYMBOLS = (
    "EffectiveSkillCatalogProjection",
    "RESOURCES_CAPABILITY_DEFINITION_V3",
    "RESOURCES_CAPABILITY_DEFINITION_V4",
    "RESOURCES_SKILL_CATALOG_LOAD_REQUIREMENT",
    "RESOURCES_SKILL_STATUS_CATALOG_LOAD_REQUIREMENT",
    "ResourceSkillCatalogCapabilityConsumer",
    "ResourceSkillStatusCatalogCapabilityConsumer",
    "SkillCandidateStatus",
    "SkillCatalogConsumer",
    "SkillCatalogStatusProjectionError",
    "SkillCatalogSummary",
    "SkillCatalogStatusProjection",
    "SkillCatalogStatusSummary",
    "build_skill_catalog_status_projection",
)


def test_rcp5_contract_freezes_conservative_order_and_authority() -> None:
    contract = CONTRACT_PATH.read_text(encoding="utf-8")
    normalized_contract = " ".join(contract.split())
    readme = README_PATH.read_text(encoding="utf-8")

    assert "A Skill is a Resource, not a Plugin" in contract
    assert "RCP5.1 \u2014 typed read path" in contract
    assert "RCP5.2A \u2014 owner-native status substrate" in contract
    assert "RCP5.2B \u2014 exact-v4 read-only cutover" in contract
    assert "exact-v2 and exact-v3 Graph contracts remain unchanged" in contract
    assert "never a legacy fallback" in contract
    assert "RCP5.2B default ingress is complete" in contract
    assert "admitted initial Resource Catalog" in normalized_contract
    assert "forbidden silent legacy fallback" in contract
    assert "RCP5.2B default ingress authority" in contract
    assert "RCP5.3A — exact asynchronous body preflight" in contract
    assert "RCP5.3B — request-bound durable evidence" in contract
    assert "RCP5.3C — eager-body sink deletion" in contract
    assert "`catalog_required` is the public default" in contract
    assert "`legacy_explicit` is a caller-selected compatibility boundary" in contract
    assert "input-sensitive or exception-driven `auto` mode" in contract
    assert "The mode is Product policy, not a ResourceLoader type test" in contract
    assert "Raw `package_roots` and non-Plugin `package_sources`" in contract
    assert "RCP5.5 \u2014 peer deletion" in contract
    assert "Production cutover starts only after" in contract
    assert "Only then is PLC6" in contract
    assert readme.count("resource-catalog-rcp5-contract.md") == 1


def test_rcp5_typed_consumer_has_no_legacy_or_product_dependency() -> None:
    source = CONSUMER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(CONSUMER_PATH))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert not imported_modules & {
        "loushang.coding",
        "loushang.harness.resources.loader",
        "loushang.harness.resources.skills",
        "loushang.harness.resources._loader_pipeline",
        "loushang.harness.resources._loader_precedence",
        "loushang.harness.resources._loader_resolution",
    }
    assert "ResourceBundle" not in source
    assert "SkillLoader" not in source


def test_rcp5_consumer_stays_private_and_product_uses_only_exact_v4() -> None:
    target = "loushang.harness.resources._skill_catalog_consumer"
    importers: set[Path] = set()
    for path in SOURCE_ROOT.rglob("*.py"):
        if path == CONSUMER_PATH:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        } | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        if target in imported:
            importers.add(path)

    assert importers == {
        CAPABILITY_PROVIDER_PATH,
        CAPABILITY_CONSUMER_PATH,
        AGENT_PRODUCT_PATH,
        REQUEST_EVIDENCE_PATH,
    }
    for path in PUBLIC_SURFACES:
        source = path.read_text(encoding="utf-8")
        for symbol in PRIVATE_SKILL_SYMBOLS:
            assert symbol not in source

    v3_opt_in_mentions = {
        path
        for path in SOURCE_ROOT.rglob("*.py")
        if "enable_skill_catalog_v3"
        in path.read_text(encoding="utf-8")
    }
    assert v3_opt_in_mentions == {CAPABILITY_PROVIDER_PATH}
    provider_source = CAPABILITY_PROVIDER_PATH.read_text(encoding="utf-8")
    assert "enable_skill_catalog_v3: bool = False" in provider_source
    v4_opt_in_mentions = {
        path
        for path in SOURCE_ROOT.rglob("*.py")
        if "enable_skill_catalog_v4"
        in path.read_text(encoding="utf-8")
    }
    assert v4_opt_in_mentions == {CAPABILITY_PROVIDER_PATH, AGENT_PRODUCT_PATH}
    product_source = AGENT_PRODUCT_PATH.read_text(encoding="utf-8")
    assert "RESOURCES_SKILL_STATUS_CATALOG_LOAD_REQUIREMENT" in product_source
    assert "RESOURCES_SKILL_CATALOG_LOAD_REQUIREMENT" not in product_source


def test_rcp52_status_projection_stays_with_the_resource_owner() -> None:
    target = "loushang.harness.resources._skill_catalog_status"
    importers: set[Path] = set()
    for path in SOURCE_ROOT.rglob("*.py"):
        if path == STATUS_PROJECTION_PATH:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        } | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        if target in imported:
            importers.add(path)

    assert importers == {
        Path("src/loushang/harness/capabilities/resources_consumers.py"),
        Path("src/loushang/harness/capabilities/resources_provider.py"),
        Path("src/loushang/harness/resource_catalog/generation.py"),
        Path("src/loushang/harness/resource_catalog/shadow.py"),
        Path("src/loushang/harness/resources/_skill_catalog_consumer.py"),
        AGENT_PRODUCT_PATH,
    }
    source = STATUS_PROJECTION_PATH.read_text(encoding="utf-8")
    assert ".content" not in source
    assert ".metadata" not in source
    assert ".opaque_locator" not in source

    contracts = CAPABILITY_CONTRACT_PATH.read_text(encoding="utf-8")
    provider = CAPABILITY_PROVIDER_PATH.read_text(encoding="utf-8")
    consumer = CAPABILITY_CONSUMER_PATH.read_text(encoding="utf-8")
    composition = COMPOSITION_RUNTIME_PATH.read_text(encoding="utf-8")
    assert "RESOURCES_CAPABILITY_DEFINITION_V4" in contracts
    assert "RESOURCES_SKILL_STATUS_CATALOG_LOAD_REQUIREMENT" in contracts
    assert "skill_status_projection" in provider
    assert "skill_status_projection" in consumer
    assert "def _resource_skill_status_projection" in composition
    assert "def resource_skill_status_projection" not in composition


def test_rcp53a_catalog_body_preflight_uses_only_the_typed_async_loader() -> None:
    prompt_source = PROMPT_PREFLIGHT_PATH.read_text(encoding="utf-8")
    command_source = COMMAND_SOURCE_PATH.read_text(encoding="utf-8")
    product_source = AGENT_PRODUCT_PATH.read_text(encoding="utf-8")
    product_tree = ast.parse(product_source, filename=str(AGENT_PRODUCT_PATH))
    loader = next(
        node
        for node in ast.walk(product_tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_load_effective_skill_body"
    )
    loader_source = ast.unparse(loader)

    assert "load_skill_body" in prompt_source
    assert "loaded_skills" in prompt_source
    assert "SkillBodyLoadRequiresAsyncError" in prompt_source
    assert "await preflight_user_input_async" in command_source
    assert "load_skill_body=self._skill_body_loader()" in command_source
    assert "consumer.get_effective_skill" in loader_source
    assert "consumer.load_handle" in loader_source
    assert "await consumer.load" in loader_source
    assert "resource_bundle" not in loader_source
    assert "source_path" not in loader_source


def test_rcp53c_catalog_projection_and_consumers_are_body_free() -> None:
    prompt_source = PROMPT_PREFLIGHT_PATH.read_text(encoding="utf-8")
    command_source = COMMAND_SOURCE_PATH.read_text(encoding="utf-8")
    projection_source = CATALOG_PROJECTION_PATH.read_text(encoding="utf-8")
    extension_source = EXTENSION_CATALOG_SOURCE_PATH.read_text(encoding="utf-8")
    extension_owner = EXTENSION_RESOURCE_OWNER_PATH.read_text(encoding="utf-8")
    method_loader = METHOD_LOADER_PATH.read_text(encoding="utf-8")
    coding_cli = CODING_CLI_PATH.read_text(encoding="utf-8")

    assert "skill.content" not in prompt_source
    assert 'getattr(skill, "content"' not in command_source
    assert "allow_legacy_skill_body" in prompt_source
    assert "skill_body_authority" in command_source
    assert "loushang.resource-catalog-projection-descriptor/v2" in projection_source
    assert "content=None" in projection_source
    assert 'if key != "body"' in projection_source
    assert "skill_bodies" in extension_source
    assert "body = route.skill_bodies[index]" in extension_source
    assert "skill.content.encode" in extension_owner
    assert 'skill_authority: Literal["none", "legacy_explicit"] = "none"' in (
        method_loader
    )
    assert "skill_body_authority: ResourceSkillBodyAuthority | None = None" in (
        command_source
    )
    assert 'ResourceSkillBodyAuthority = Literal["catalog_required", "legacy_explicit"]' in (
        command_source
    )
    assert "_coding_method_loader(args)" in coding_cli

    legacy_target = "loushang.harness.resources._legacy_skill_body"
    legacy_importers = {
        path
        for path in SOURCE_ROOT.rglob("*.py")
        if path != LEGACY_SKILL_BODY_PATH
        and legacy_target in path.read_text(encoding="utf-8")
    }
    assert legacy_importers == {
        PROMPT_PREFLIGHT_PATH,
        Path("src/loushang/harness/commands/resources.py"),
    }
