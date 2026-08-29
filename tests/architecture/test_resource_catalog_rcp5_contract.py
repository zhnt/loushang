from __future__ import annotations

import ast
from pathlib import Path

CONTRACT_PATH = Path(
    "docs/internals/architecture/harness/plugin/resource-catalog-rcp5-contract.md"
)
CONSUMER_PATH = Path(
    "src/loushang/harness/resources/_skill_catalog_consumer.py"
)
README_PATH = Path("docs/internals/architecture/harness/plugin/README.md")
SOURCE_ROOT = Path("src/loushang")
CAPABILITY_PROVIDER_PATH = Path(
    "src/loushang/harness/capabilities/resources_provider.py"
)
CAPABILITY_CONSUMER_PATH = Path(
    "src/loushang/harness/capabilities/resources_consumers.py"
)
PUBLIC_SURFACES = (
    Path("src/loushang/harness/resources/__init__.py"),
    Path("src/loushang/harness/__init__.py"),
    Path("src/loushang/coding/__init__.py"),
)
PRIVATE_V3_SYMBOLS = (
    "EffectiveSkillCatalogProjection",
    "RESOURCES_CAPABILITY_DEFINITION_V3",
    "RESOURCES_SKILL_CATALOG_LOAD_REQUIREMENT",
    "ResourceSkillCatalogCapabilityConsumer",
    "SkillCatalogConsumer",
    "SkillCatalogSummary",
)


def test_rcp5_contract_freezes_conservative_order_and_authority() -> None:
    contract = CONTRACT_PATH.read_text(encoding="utf-8")
    readme = README_PATH.read_text(encoding="utf-8")

    assert "A Skill is a Resource, not a Plugin" in contract
    assert "RCP5.1 \u2014 typed read path" in contract
    assert "RCP5.2A \u2014 owner-native status substrate" in contract
    assert "RCP5.2B \u2014 exact-v4 read-only cutover" in contract
    assert "exact-v2 and exact-v3 Graph contracts remain unchanged" in contract
    assert "never a legacy fallback" in contract
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


def test_rcp5_consumer_stays_private_and_default_product_does_not_opt_in() -> None:
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

    assert importers == {CAPABILITY_PROVIDER_PATH, CAPABILITY_CONSUMER_PATH}
    for path in PUBLIC_SURFACES:
        source = path.read_text(encoding="utf-8")
        for symbol in PRIVATE_V3_SYMBOLS:
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
