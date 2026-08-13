from __future__ import annotations

import ast
from pathlib import Path

import loushang.ontology as ontology
import loushang.ontology.facts as ontology_facts
import loushang.ontology.storage as ontology_storage

ONTOLOGY_ROOT = Path("src/loushang/ontology")
LEGACY_FOUNDATION_PREFIXES = ("loushang.observability", "loushang.protocol")
FORBIDDEN_SYSTEM_PREFIXES = (
    "loushang.agent",
    "loushang.ai",
    "loushang.channel",
    "loushang.coding",
    "loushang.harness",
    "loushang.harnesswork",
    "loushang.harnesstui",
    "loushang.method",
    "loushang.resource",
    "loushang.runtime",
    "loushang.tui",
    "loushang.work",
)
REMOVED_COMPATIBILITY_MODULES = (
    "loushang.ontology.core",
    "loushang.ontology.fusion",
    "loushang.ontology.integrations",
    "loushang.ontology.rules",
)
REMOVED_COMPATIBILITY_SOURCES = (
    ONTOLOGY_ROOT / "core",
    ONTOLOGY_ROOT / "fusion",
    ONTOLOGY_ROOT / "integrations",
    ONTOLOGY_ROOT / "rules",
)
REMOVED_PUBLIC_NAMES = (
    "DataFusion",
    "FieldMapping",
    "ObjectStore",
    "Ontology",
    "OntologyStore",
    "OperationalMutationStore",
    "Rule",
    "RuleEngine",
    "SourceMapping",
)


def test_ontology_does_not_import_legacy_foundation_facades() -> None:
    offenders: list[str] = []
    for path in sorted(ONTOLOGY_ROOT.rglob("*.py")):
        for imported in _absolute_imports(path):
            if imported.startswith(LEGACY_FOUNDATION_PREFIXES):
                offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []


def test_ontology_does_not_depend_on_product_or_execution_subsystems() -> None:
    offenders: list[str] = []
    for path in sorted(ONTOLOGY_ROOT.rglob("*.py")):
        for imported in _absolute_imports(path):
            if imported.startswith(FORBIDDEN_SYSTEM_PREFIXES):
                offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []


def test_greenfield_compatibility_sources_are_absent() -> None:
    offenders: list[str] = []
    for path in REMOVED_COMPATIBILITY_SOURCES:
        if path.is_file():
            offenders.append(path.as_posix())
        elif path.is_dir():
            offenders.extend(item.as_posix() for item in path.rglob("*.py"))

    assert offenders == []


def test_public_surface_has_no_direct_mutation_or_compatibility_facades() -> None:
    assert {name for name in REMOVED_PUBLIC_NAMES if hasattr(ontology, name)} == set()
    assert not hasattr(ontology_storage, "SQLiteObjectStore")
    assert hasattr(ontology_storage, "SQLiteFactStore")
    assert hasattr(ontology_storage, "SQLiteProjectionStore")
    assert hasattr(ontology, "ProjectionStore")
    assert hasattr(ontology, "SourceBinding")
    assert hasattr(ontology, "DeploymentProfile")
    assert hasattr(ontology, "IdentityCrosswalkSnapshot")
    assert hasattr(ontology, "IdentityCrosswalkArtifactLock")
    assert hasattr(ontology, "IdentityResolver")
    assert hasattr(ontology, "SourceRecordIdentity")
    assert hasattr(ontology, "SchemaArtifactLock")
    assert hasattr(ontology, "SourceAdapterArtifactLock")
    assert hasattr(ontology, "SourceInstanceSelection")
    assert hasattr(ontology, "MappedSourceInput")
    assert hasattr(ontology, "MappedSourceLink")
    assert hasattr(ontology, "MaterializationCut")
    assert hasattr(ontology, "OntologyPackageArtifact")
    assert hasattr(ontology, "OntologyPackageDependencyLock")
    assert hasattr(ontology, "ActionDefinition")
    assert hasattr(ontology, "ActionRequest")
    assert hasattr(ontology, "ActionPlan")
    assert hasattr(ontology, "ProjectionGuard")
    assert hasattr(ontology, "OperationalOrigin")
    assert hasattr(ontology, "ValueOrigin")
    assert not hasattr(ontology_facts, "MemoryFactStore")


def test_identity_remains_a_leaf_with_only_deployment_validation_consuming_it() -> None:
    identity_root = ONTOLOGY_ROOT / "identity"
    identity_imports: list[str] = []
    identity_consumers: list[str] = []

    for path in sorted(identity_root.rglob("*.py")):
        for imported in _absolute_imports(path):
            if imported.startswith("loushang.ontology") and not imported.startswith(
                "loushang.ontology.identity"
            ):
                identity_imports.append(f"{path.as_posix()} imports {imported}")

    for path in sorted(ONTOLOGY_ROOT.rglob("*.py")):
        if identity_root in path.parents or path == ONTOLOGY_ROOT / "__init__.py":
            continue
        for imported in _absolute_imports(path):
            if imported.startswith("loushang.ontology.identity"):
                identity_consumers.append(f"{path.as_posix()} imports {imported}")

    assert identity_imports == []
    assert identity_consumers == [
        "src/loushang/ontology/deployment/validation.py imports "
        "loushang.ontology.identity"
    ]


def test_package_artifacts_depend_only_on_schema_and_are_not_runtime_inputs() -> None:
    package_root = ONTOLOGY_ROOT / "package"
    package_imports: list[str] = []
    package_consumers: list[str] = []

    for path in sorted(package_root.rglob("*.py")):
        for imported in _absolute_imports(path):
            if (
                imported.startswith("loushang.ontology")
                and not imported.startswith("loushang.ontology.package")
                and not imported.startswith("loushang.ontology.schema")
            ):
                package_imports.append(f"{path.as_posix()} imports {imported}")

    for path in sorted(ONTOLOGY_ROOT.rglob("*.py")):
        if package_root in path.parents or path == ONTOLOGY_ROOT / "__init__.py":
            continue
        for imported in _absolute_imports(path):
            if imported.startswith("loushang.ontology.package"):
                package_consumers.append(f"{path.as_posix()} imports {imported}")

    assert package_imports == []
    assert package_consumers == []


def test_production_ontology_does_not_import_removed_compatibility_modules() -> None:
    offenders: list[str] = []
    for path in sorted(ONTOLOGY_ROOT.rglob("*.py")):
        for imported in _absolute_imports(path):
            if imported.startswith(REMOVED_COMPATIBILITY_MODULES):
                offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []


def test_ontology_internal_dependency_direction() -> None:
    boundaries = (
        (
            Path("src/loushang/ontology/schema"),
            (
                "loushang.ontology.deployment",
                "loushang.ontology.action",
                "loushang.ontology.facts",
                "loushang.ontology.projection",
                "loushang.ontology.query",
                "loushang.ontology.source",
                "loushang.ontology.storage",
            ),
        ),
        (
            Path("src/loushang/ontology/source"),
            (
                "loushang.ontology.deployment",
                "loushang.ontology.action",
                "loushang.ontology.facts",
                "loushang.ontology.projection",
                "loushang.ontology.query",
                "loushang.ontology.storage",
            ),
        ),
        (
            Path("src/loushang/ontology/query"),
            (
                "loushang.ontology.deployment",
                "loushang.ontology.action",
                "loushang.ontology.facts",
                "loushang.ontology.storage",
            ),
        ),
        (
            Path("src/loushang/ontology/storage"),
            (
                "loushang.ontology.deployment",
                "loushang.ontology.action",
                "loushang.ontology.query",
                "loushang.ontology.rules",
                "loushang.ontology.fusion",
                "loushang.ontology.integrations",
                "loushang.harnesswork",
            ),
        ),
        (
            Path("src/loushang/ontology/facts"),
            (
                "loushang.ontology.deployment",
                "loushang.ontology.action",
                "loushang.ontology.projection",
                "loushang.ontology.query",
                "loushang.ontology.storage",
                "loushang.ontology.rules",
                "loushang.ontology.fusion",
                "loushang.ontology.integrations",
            ),
        ),
        (
            Path("src/loushang/ontology/projection"),
            (
                "loushang.ontology.deployment",
                "loushang.ontology.action",
                "loushang.ontology.query",
                "loushang.ontology.storage",
                "loushang.harnesswork",
            ),
        ),
        (
            Path("src/loushang/ontology/deployment"),
            (
                "loushang.ontology.facts",
                "loushang.ontology.action",
                "loushang.ontology.projection",
                "loushang.ontology.query",
                "loushang.ontology.storage",
            ),
        ),
    )
    offenders: list[str] = []
    for root, forbidden_prefixes in boundaries:
        paths = (root,) if root.is_file() else tuple(sorted(root.rglob("*.py")))
        for path in paths:
            for imported in _absolute_imports(path):
                if imported.startswith(forbidden_prefixes):
                    offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []


def test_action_is_a_pure_upper_layer_without_storage_or_runtime_dependencies() -> None:
    allowed = (
        "loushang.ontology.action",
        "loushang.ontology.deployment",
        "loushang.ontology.facts",
        "loushang.ontology.projection",
        "loushang.ontology.schema",
        "loushang.ontology.source",
    )
    offenders: list[str] = []
    for path in sorted((ONTOLOGY_ROOT / "action").rglob("*.py")):
        for imported in _absolute_imports(path):
            if imported.startswith("loushang.ontology") and not imported.startswith(
                allowed
            ):
                offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []


def test_fact_and_source_contracts_depend_only_on_the_schema_identity_leaf() -> None:
    offenders: list[str] = []
    for root in (ONTOLOGY_ROOT / "facts", ONTOLOGY_ROOT / "source"):
        for path in sorted(root.rglob("*.py")):
            for imported in _absolute_imports(path):
                if imported.startswith("loushang.ontology.schema") and imported != (
                    "loushang.ontology.schema.identity"
                ):
                    offenders.append(f"{path.as_posix()} imports {imported}")

    assert offenders == []

    identity_imports = _absolute_imports(ONTOLOGY_ROOT / "schema" / "identity.py")
    assert {
        imported
        for imported in identity_imports
        if imported.startswith("loushang.ontology")
    } == set()


def test_storage_adapters_do_not_depend_on_each_other() -> None:
    memory_imports = _absolute_imports(ONTOLOGY_ROOT / "storage" / "memory.py")
    sqlite_imports = _absolute_imports(ONTOLOGY_ROOT / "storage" / "sqlite.py")

    assert "loushang.ontology.storage.sqlite" not in memory_imports
    assert "loushang.ontology.storage.memory" not in sqlite_imports


def _absolute_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module)
    return imports
