from __future__ import annotations

import ast
import sys
from pathlib import Path

APPHOST_ROOT = Path("src/loushang/apphost")
APPHOST_MODULES = {
    APPHOST_ROOT / "__init__.py",
    APPHOST_ROOT / "_ownership.py",
    APPHOST_ROOT / "catalog.py",
    APPHOST_ROOT / "contracts.py",
    APPHOST_ROOT / "errors.py",
    APPHOST_ROOT / "router.py",
    APPHOST_ROOT / "runtime.py",
}
APPHOST_OPTIONAL_MODULES = {APPHOST_ROOT / "hosted.py"}
HARNESS_SESSION_ADAPTER = Path(
    "src/loushang/apphost/integrations/harness_session.py"
)
SCOPE = Path("docs/internals/architecture/apphost/README.md")
CONTRACT = Path("docs/internals/architecture/apphost/contract-model-a0.md")
ARD = Path(
    "docs/internals/architecture/decisions/ARD-003-apphost-top-level-placement.md"
)
PARENT_DOCS = (
    Path("docs/internals/architecture/README.md"),
    Path("docs/internals/architecture/architecture-overview.md"),
    Path("docs/internals/architecture/subsystem.md"),
    Path("docs/internals/architecture/subsystem-diagram.md"),
    Path("docs/internals/architecture/governance-profile.md"),
    Path("docs/internals/architecture/decisions/README.md"),
    Path("docs/internals/architecture/current-target-gap-ledger.md"),
)
FORBIDDEN_CORE_TERMS = {
    "AppServer",
    "AppService",
    "Coding",
    "Harness",
    "Hosting",
    "ProductHostRuntime",
}


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _resolved_imports_from_source(path: Path, source: str) -> set[str]:
    result: set[str] = set()
    tree = ast.parse(source, filename=str(path))
    package = path.parent.relative_to("src").parts
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                retained = len(package) - (node.level - 1)
                if retained < 0:
                    result.add("<invalid-relative-import>")
                    continue
                base = (*package[:retained], *(node.module or "").split("."))
            else:
                base = tuple((node.module or "").split("."))
            base = tuple(part for part in base if part)
            if base:
                result.add(".".join(base))
            result.update(".".join((*base, alias.name)) for alias in node.names)
    return result


def _resolved_imports(path: Path) -> set[str]:
    return _resolved_imports_from_source(path, _source(path))


def _imports_apphost(path: Path) -> bool:
    return any(
        imported == "loushang.apphost"
        or imported.startswith("loushang.apphost.")
        for imported in _resolved_imports(path)
    )


def test_a0_0_parent_architecture_accepts_apphost_as_a_top_level_scope() -> None:
    ard = _source(ARD)
    scope = _source(SCOPE)
    contract = _source(CONTRACT)

    assert "Design status: accepted" in ard
    assert "AppHost core imports neither AppServer nor Hosting" in contract
    assert "A0.1 performs validation only" in scope
    for path in PARENT_DOCS:
        source = _source(path)
        assert "AppHost" in source, path
    decision_catalog = _source(PARENT_DOCS[5])
    assert "ARD-003-apphost-top-level-placement.md" in decision_catalog


def test_a0_core_is_standard_library_only_and_has_no_optional_edges() -> None:
    assert {path for path in APPHOST_ROOT.glob("*.py")} == (
        APPHOST_MODULES | APPHOST_OPTIONAL_MODULES
    )
    internal_imports: dict[str, set[str]] = {}
    external_roots: dict[str, set[str]] = {}
    for path in APPHOST_MODULES:
        imports = _resolved_imports(path)
        internal_imports[path.name] = {
            imported
            for imported in imports
            if imported == "loushang.apphost"
            or imported.startswith("loushang.apphost.")
        }
        external_roots[path.name] = {
            imported.partition(".")[0]
            for imported in imports - internal_imports[path.name]
        }
        for imported in imports - internal_imports[path.name]:
            assert imported.partition(".")[0] in sys.stdlib_module_names, (
                path,
                imported,
            )
    _ = {
        "__init__.py": {
            "loushang.apphost.catalog",
            "loushang.apphost.catalog.AppHostCatalogV1",
            "loushang.apphost.contracts",
            "loushang.apphost.contracts.APPHOST_CONTRACT_VERSION",
            "loushang.apphost.contracts.SESSION_IDENTITY_ENVELOPE_VERSION",
            "loushang.apphost.contracts.AdmissionIdentityV1",
            "loushang.apphost.contracts.AdmissionGenerationLeaseV1",
            "loushang.apphost.contracts.AdmissionGenerationSourceV1",
            "loushang.apphost.contracts.AppHostAdmissionSubjectKind",
            "loushang.apphost.contracts.AppHostCatalogInputV1",
            "loushang.apphost.contracts.AppHostComponent",
            "loushang.apphost.contracts.AppHostLifecycleTransition",
            "loushang.apphost.contracts.AppHostObservationSinkV1",
            "loushang.apphost.contracts.AppHostObservationV1",
            "loushang.apphost.contracts.ClaimedSessionCandidateV1",
            "loushang.apphost.contracts.OpenedProductCandidateV1",
            "loushang.apphost.contracts.ProductCandidateValidatorV1",
            "loushang.apphost.contracts.ProductCompatibilityImporterV1",
            "loushang.apphost.contracts.ProductDescriptorV1",
            "loushang.apphost.contracts.ProductFactoryV1",
            "loushang.apphost.contracts.ProductProfileBindingV1",
            "loushang.apphost.contracts.ProductRegistrationV1",
            "loushang.apphost.contracts.ProfileDescriptorV1",
            "loushang.apphost.contracts.ProfileFactoryV1",
            "loushang.apphost.contracts.ProfileLeaseV1",
            "loushang.apphost.contracts.ProfileRegistrationV1",
            "loushang.apphost.contracts.ScopedProductRuntimeV1",
            "loushang.apphost.contracts.SessionBindingKeyV1",
            "loushang.apphost.contracts.SessionCandidateLeaseV1",
            "loushang.apphost.contracts.SessionCandidateMode",
            "loushang.apphost.contracts.SessionCandidateRefV1",
            "loushang.apphost.contracts.SessionCreateIntentV1",
            "loushang.apphost.contracts.SessionCreateRequestV1",
            "loushang.apphost.contracts.SessionDiscoveryScope",
            "loushang.apphost.contracts.SessionIdentityCatalogPortV1",
            "loushang.apphost.contracts.SessionIdentityEnvelopeV1",
            "loushang.apphost.contracts.SessionIdentityProjectionV1",
            "loushang.apphost.errors",
            "loushang.apphost.errors.AppHostError",
            "loushang.apphost.errors.AppHostFailureCategory",
            "loushang.apphost.errors.CleanupIncompleteError",
            "loushang.apphost.errors.GenerationConflictError",
            "loushang.apphost.errors.GenerationRetiredError",
            "loushang.apphost.errors.InvalidAppHostContractError",
            "loushang.apphost.errors.InvalidAppHostContractReason",
            "loushang.apphost.errors.ProductIdentityRequiredError",
            "loushang.apphost.errors.ProductIncompatibleError",
            "loushang.apphost.errors.ProductUnavailableError",
            "loushang.apphost.errors.SessionAmbiguousError",
            "loushang.apphost.errors.SessionCandidateStaleError",
            "loushang.apphost.router",
            "loushang.apphost.router.AppHostRouterV1",
        },
        "catalog.py": {
            "loushang.apphost.contracts",
            "loushang.apphost.contracts.AdmissionGenerationLeaseV1",
            "loushang.apphost.contracts.AdmissionIdentityV1",
            "loushang.apphost.contracts.AppHostCatalogInputV1",
            "loushang.apphost.contracts.ProductRegistrationV1",
            "loushang.apphost.contracts.ProfileRegistrationV1",
            "loushang.apphost.errors",
            "loushang.apphost.errors.CleanupIncompleteError",
            "loushang.apphost.errors.GenerationConflictError",
            "loushang.apphost.errors.GenerationRetiredError",
            "loushang.apphost.errors.ProductIdentityRequiredError",
            "loushang.apphost.errors.ProductUnavailableError",
        },
        "contracts.py": {
            "loushang.apphost.errors",
            "loushang.apphost.errors.AppHostFailureCategory",
            "loushang.apphost.errors.InvalidAppHostContractError",
            "loushang.apphost.errors.InvalidAppHostContractReason",
        },
        "errors.py": set(),
        "router.py": {
            "loushang.apphost.catalog",
            "loushang.apphost.catalog.AppHostCatalogV1",
            "loushang.apphost.contracts",
            "loushang.apphost.contracts.OpenedProductCandidateV1",
            "loushang.apphost.contracts.ProductDescriptorV1",
            "loushang.apphost.contracts.ProductFactoryV1",
            "loushang.apphost.contracts.ProductRegistrationV1",
            "loushang.apphost.contracts.SessionBindingKeyV1",
            "loushang.apphost.contracts.SessionCandidateLeaseV1",
            "loushang.apphost.contracts.SessionCandidateMode",
            "loushang.apphost.contracts.SessionCandidateRefV1",
            "loushang.apphost.contracts.SessionCreateIntentV1",
            "loushang.apphost.contracts.SessionCreateRequestV1",
            "loushang.apphost.contracts.SessionIdentityCatalogPortV1",
            "loushang.apphost.contracts.SessionIdentityEnvelopeV1",
            "loushang.apphost.contracts.SessionIdentityProjectionV1",
            "loushang.apphost.errors",
            "loushang.apphost.errors.AppHostError",
            "loushang.apphost.errors.AppHostFailureCategory",
            "loushang.apphost.errors.ProductIdentityRequiredError",
            "loushang.apphost.errors.ProductIncompatibleError",
            "loushang.apphost.errors.SessionCandidateStaleError",
        },
    }
    _ = {
        "__init__.py": set(),
        "contracts.py": {
            "__future__",
            "dataclasses",
            "enum",
            "inspect",
            "re",
            "typing",
            "unicodedata",
        },
        "errors.py": {"__future__", "enum", "re"},
        "catalog.py": {
            "__future__",
            "asyncio",
            "dataclasses",
            "inspect",
            "typing",
        },
        "router.py": {"__future__", "inspect"},
    }
    public_surface = _source(APPHOST_ROOT / "__init__.py")
    assert all(term not in public_surface for term in FORBIDDEN_CORE_TERMS)


def test_a0_1_public_all_exactly_matches_the_frozen_facade_bindings() -> None:
    tree = ast.parse(
        _source(APPHOST_ROOT / "__init__.py"),
        filename=str(APPHOST_ROOT / "__init__.py"),
    )
    imported = {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        )
    )
    exported = ast.literal_eval(assignment.value)
    assert isinstance(exported, list)
    assert len(exported) == len(set(exported))
    assert set(exported) == imported


def test_a0_slices_add_runtime_and_hosted_but_no_launcher() -> None:
    names = {path.name for path in APPHOST_ROOT.iterdir()}
    assert {"catalog.py", "router.py", "runtime.py", "hosted.py"} <= names
    for forbidden in ("profiles.py", "launcher.py"):
        assert forbidden not in names

    all_core_source = "\n".join(_source(path) for path in sorted(APPHOST_MODULES))
    for ambient_effect in (
        "os.environ",
        "os.getcwd",
        ".expanduser(",
        ".resolve(",
        "Path(",
        "open(",
        "subprocess",
        "importlib",
        "entry_points",
    ):
        assert ambient_effect not in all_core_source


def test_a0_1_create_and_profile_boundaries_preserve_owner_authority() -> None:
    tree = ast.parse(
        _source(APPHOST_ROOT / "contracts.py"),
        filename=str(APPHOST_ROOT / "contracts.py"),
    )
    classes = {
        node.name: node for node in tree.body if isinstance(node, ast.ClassDef)
    }
    catalog_port = classes["SessionIdentityCatalogPortV1"]
    catalog_methods = {
        node.name
        for node in catalog_port.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {"find_created_candidate", "create_candidate"} <= catalog_methods
    create_request = classes["SessionCreateRequestV1"]
    create_fields = {
        node.target.id
        for node in create_request.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert create_fields == {
        "product_id",
        "creator_scope_id",
        "operation_id",
        "contract_version",
    }
    create_intent = classes["SessionCreateIntentV1"]
    intent_fields = {
        node.target.id
        for node in create_intent.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert intent_fields == {
        "request",
        "product_compatibility_id",
        "contract_version",
    }
    contract = _source(CONTRACT)
    normalized_contract = " ".join(contract.split())
    assert "Commit-before-return cancellation or crash" in normalized_contract
    assert "same exact candidate/revision" in normalized_contract
    admission_source = classes["AdmissionGenerationSourceV1"]
    admission_members = {
        node.name
        for node in admission_source.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert admission_members == {"acquire_pin"}
    admission_identity = classes["AdmissionIdentityV1"]
    identity_fields = {
        node.target.id
        for node in admission_identity.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert identity_fields == {"generation_id", "subject_kind", "subject_id"}
    assert "match generation, subject kind," in normalized_contract
    profile_binding = classes["ProductProfileBindingV1"]
    profile_members = {
        node.name
        for node in profile_binding.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert profile_members == {"binding_key", "opaque_binding"}
    assert "close" not in profile_members


def test_a0_1_has_only_the_reviewed_default_dark_product_consumers() -> None:
    consumers = {
        path
        for path in Path("src/loushang").rglob("*.py")
        if not path.is_relative_to(APPHOST_ROOT) and _imports_apphost(path)
    }
    assert consumers == {
        Path("src/loushang/coding/apphost_composition.py"),
        Path("src/loushang/coding/apphost_product.py"),
    }
    reverse_adapter_consumers = {
        path
        for path in Path("src/loushang").rglob("*.py")
        if path != HARNESS_SESSION_ADAPTER
        and any(
            imported == "loushang.apphost.integrations.harness_session"
            or imported.startswith(
                "loushang.apphost.integrations.harness_session."
            )
            for imported in _resolved_imports(path)
        )
    }
    assert reverse_adapter_consumers == set()


def test_apphost_import_guard_covers_parent_alias_and_relative_forms() -> None:
    facade = Path("src/loushang/__init__.py")
    nested = Path("src/loushang/coding/__init__.py")
    assert "loushang.apphost" in _resolved_imports_from_source(
        facade, "from loushang import apphost"
    )
    assert "loushang.apphost" in _resolved_imports_from_source(
        facade, "from . import apphost"
    )
    assert "loushang.apphost" in _resolved_imports_from_source(
        nested, "from .. import apphost"
    )
    assert "loushang.hosting" in _resolved_imports_from_source(
        APPHOST_ROOT / "contracts.py", "from ..hosting import ProcessHost"
    )


def test_a0_1_observation_schema_has_no_open_payload_or_path() -> None:
    tree = ast.parse(
        _source(APPHOST_ROOT / "contracts.py"),
        filename=str(APPHOST_ROOT / "contracts.py"),
    )
    observation = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AppHostObservationV1"
    )
    fields = {
        node.target.id
        for node in observation.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert fields == {
        "component",
        "transition",
        "generation_id",
        "product_id",
        "profile_id",
        "session_id",
        "failure",
    }
    assert not fields.intersection(
        {"payload", "details", "path", "environment", "message", "metadata"}
    )
