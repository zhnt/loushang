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


def test_rcp5_contract_freezes_conservative_order_and_authority() -> None:
    contract = CONTRACT_PATH.read_text(encoding="utf-8")
    readme = README_PATH.read_text(encoding="utf-8")

    assert "A Skill is a Resource, not a Plugin" in contract
    assert "RCP5.1 \u2014 typed read path" in contract
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
