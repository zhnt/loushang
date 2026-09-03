from __future__ import annotations

import ast
from pathlib import Path

CONTRACT = Path(
    "docs/internals/architecture/harness/plugin/plugin-lifecycle-plc9a2-contract.md"
)
INVENTORY = Path(
    "docs/internals/architecture/harness/plugin/plugin-lifecycle-plc9-inventory.md"
)
INDEX = Path("docs/internals/architecture/harness/plugin/README.md")
ACTIVATION = Path("src/loushang/harness/resources/packages/product_activation.py")
PRODUCT_CONTRACT = Path("src/loushang/harness/resources/packages/product_contract.py")
PRODUCT_INVENTORY = Path("src/loushang/harness/resources/packages/product_inventory.py")
PRODUCT_LIFECYCLE = Path("src/loushang/harness/resources/packages/product_lifecycle.py")
KERNEL_RECORDS = Path(
    "src/loushang/harness/resources/packages/plugin_lifecycle/records.py"
)
COMPOSITION = Path("src/loushang/harness/resources/packages/product_composition.py")
RETENTION = Path(
    "src/loushang/harness/resources/packages/plugin_lifecycle/product_retention.py"
)
DESIRED = Path("src/loushang/harness/plugin_management/package_product.py")
OPERATIONS = Path("src/loushang/harness/resources/packages/operations.py")
SESSION = Path("src/loushang/harness/resources/packages/session.py")
FACADE = Path("src/loushang/harness/session/facade_optional.py")
CLI = Path("src/loushang/harness/cli/package_lifecycle.py")
RPC = Path("src/loushang/harness/host/rpc/commands/packages.py")
STARTUP = Path("src/loushang/harness/resources/packages/source_resolver.py")
BOOTSTRAP = Path("src/loushang/harness/session/bootstrap_configuration.py")
CONSTRUCTION = Path("src/loushang/harness/session/bootstrap_construction.py")
PRODUCT_SESSION = Path("src/loushang/harness/session/agent_product.py")
CODING_SESSION = Path("src/loushang/coding/session/agent_session.py")
AUTHOR_SDK = Path("src/loushang/plugin/__init__.py")


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _imports(path: Path) -> set[str]:
    return {
        node.module or ""
        for node in ast.walk(ast.parse(_source(path)))
        if isinstance(node, ast.ImportFrom)
    }


def _function_source(path: Path, qualified_name: str) -> str:
    source = _source(path)
    tree = ast.parse(source)
    parents: list[str] = []

    def visit(node: ast.AST) -> str | None:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            parents.append(node.name)
            if ".".join(parents) == qualified_name:
                return ast.get_source_segment(source, node)
            for child in node.body:
                found = visit(child)
                if found is not None:
                    return found
            parents.pop()
            return None
        for child in ast.iter_child_nodes(node):
            found = visit(child)
            if found is not None:
                return found
        return None

    result = visit(tree)
    assert result is not None
    return result


def test_plc9a2_contract_is_indexed_and_inventory_names_every_new_owner() -> None:
    contract = _source(CONTRACT)
    inventory = _source(INVENTORY)
    index = _source(INDEX)

    assert index.count("(plugin-lifecycle-plc9a2-contract.md)") == 1
    for slice_name in ("PLC9A2.0", "PLC9A2.1", "PLC9A2.2"):
        assert slice_name in contract
    for owner in (
        "PackageProductLifecycleActivation",
        "compose_package_product_lifecycle",
        "PluginManagementPackageDesiredStateAdapter",
        "PackageProductRetentionSettlementOwner",
        "PackageOperationsRuntime",
        "PackageSourceResolver.resolve_configured_sources_sync",
        "PackageProductLifecycleExecutionBinding",
        "PackageProductEpochTransactionGuardPort",
        "PackageProductLifecycleInventoryPort",
        "PackageProductLifecycleMode",
        "PackageProductUpdateCheckRequestV1",
        "PackageProductUpdateManifestJournal",
        "PackageProductUpdateManifestReceiptV1",
    ):
        assert owner in inventory
    assert "UI/management-SDK transport bindings" in inventory


def test_plc9a2_product_activation_is_capability_poor_and_pathless() -> None:
    source = _source(ACTIVATION)
    contract = _source(PRODUCT_CONTRACT)
    imports = _imports(ACTIVATION)
    contract_imports = {
        module
        for module in _imports(PRODUCT_CONTRACT)
        if module.startswith("loushang.")
    }

    assert contract_imports == set()
    assert "PackageProductLifecycleEvidenceV1" in contract
    assert not any(
        module.startswith(
            (
                "loushang.coding",
                "loushang.harness.cli",
                "loushang.harness.config",
                "loushang.harness.host",
                "loushang.harness.plugin_management",
            )
        )
        for module in imports
    )
    for forbidden in (
        "PackageMaterializer",
        "PluginRevisionStore",
        "SettingsManager",
        "subprocess",
        "shutil",
        ".unlink(",
        ".rmdir(",
        "rmtree(",
    ):
        assert forbidden not in source
    assert '"path": ""' in contract
    assert "source_locator" not in _function_source(
        PRODUCT_CONTRACT, "PackageProductLifecycleRecordV1.to_dict"
    )
    assert "for recovery in self._recoveries" in source
    assert source.count("self._admit()") == 3


def test_plc9a2_freezes_atomic_admission_guard_and_inventory_owners() -> None:
    lifecycle = _source(PRODUCT_LIFECYCLE)
    inventory = _source(PRODUCT_INVENTORY)
    records = _source(KERNEL_RECORDS)

    route = _function_source(ACTIVATION, "PackageProductLifecycleActivation.route")
    query = _function_source(
        ACTIVATION,
        "PackageProductLifecycleActivation.execute_guarded_query",
    )
    guarded = _function_source(
        ACTIVATION,
        "PackageProductLifecycleActivation._route_guarded",
    )
    assert route.index("with guard:") < route.index("self._admit()") < route.index(
        "self._route_guarded("
    )
    assert query.index("with guard:") < query.index("self._admit()") < query.index(
        "await query()"
    )
    assert "receipt.request.admission_request_id" in guarded
    assert guarded.index("bind_runtime_admission(") < guarded.index(
        "self._router.route("
    )
    assert (
        "runtime_admission_request_id=("
        in guarded
    )
    assert "resolution_environment_fingerprint=sha256" not in guarded
    assert "PACKAGE_LIFECYCLE_REQUEST_VERSION = 1" in records
    assert "PACKAGE_LIFECYCLE_REQUEST_V2_VERSION = 2" in records
    assert "class PackageLifecycleIngressRequestV2(" in records
    assert "class PackageLifecycleRequestV2(" in records
    assert "decode_package_lifecycle_request(" in records
    assert '"runtimeAdmissionRequestId"' in records
    assert "PackageProductLifecycleExecutionBinding" in lifecycle
    assert "self._transaction.owner_binding_id != self._owner_binding_id" in lifecycle
    assert "self.ingress.runtime_admission_request_id" in lifecycle
    assert "self.admission.request.admission_request_id" in lifecycle
    assert "_PackageProductAdmissionJournal" not in lifecycle

    update_all = _function_source(OPERATIONS, "PackageOperationsRuntime.update_all")
    check = _function_source(SESSION, "SessionPackageController.check_package_updates")
    for body in (update_all, check):
        assert "inventory.binding_id != lifecycle.binding_id" in body
        assert "execute_guarded_query" in body
    assert "inventory.bind_update_targets(" in update_all
    assert "PackageProductUpdateManifestReceiptV1.create(" in update_all
    assert "receipt != expected_receipt" in update_all
    assert "class PackageProductUpdateManifestJournal:" in inventory
    assert '"bindingId": self.binding_id' in inventory
    assert "item.binding_id != self._binding_id" in inventory
    assert "_assert_private_storage(self._path)" in inventory
    assert 'JournalLoadPolicy(partial_tail="repair")' in inventory
    assert inventory.count("append_jsonl_record(") == 1
    for forbidden in ("source_locator", "credential_reference", "target.source"):
        assert forbidden not in inventory
    assert "PackageProductLifecycleMode = Literal[\"legacy\", \"dark\", \"enforced\"]" in (
        _source(PRODUCT_CONTRACT)
    )
    assert "package_product_update_manifest_conflict" in inventory
    assert "PackageProductUpdateCheckRequestV1(" in check
    assert "inventory.check_updates(request=request)" in check
    rpc = _source(RPC)
    contract = _source(PRODUCT_CONTRACT)
    assert "PACKAGE_PRODUCT_LIFECYCLE_FAILURE_CODES = frozenset(" in contract
    assert "self.failure_code not in PACKAGE_PRODUCT_LIFECYCLE_FAILURE_CODES" in (
        contract
    )
    assert "_validate_product_update_checks(result)" in rpc
    assert "_validate_product_lifecycle_records(" in rpc
    assert "_ProductPackageOperationError" in rpc
    assert 'item.get("kind") == "plugin_package"' in rpc
    assert 'item["name"] != expected_name' in rpc


def test_plc9a2_transports_depend_on_the_product_contract_not_owner_internals() -> None:
    consumers = (
        OPERATIONS,
        SESSION,
        FACADE,
        CLI,
        RPC,
        STARTUP,
        BOOTSTRAP,
        CONSTRUCTION,
        PRODUCT_SESSION,
        CODING_SESSION,
    )

    for path in consumers:
        imports = _imports(path)
        assert "loushang.harness.resources.packages.product_contract" in imports
        assert not any(
            module.startswith(
                (
                    "loushang.harness.resources.packages.plugin_lifecycle",
                    "loushang.harness.resources.packages.product_activation",
                    "loushang.harness.resources.packages.product_lifecycle",
                )
            )
            for module in imports
        ), path


def test_plc9a2_keeps_desired_and_retention_owners_separate() -> None:
    composition = _source(COMPOSITION)
    desired = _source(DESIRED)
    retention = _source(RETENTION)

    assert "PackageProductLifecycleRouter(" in composition
    assert "PackageRetentionHandoffRecovery" in composition
    assert "PluginManagementCommandV1(" in desired
    assert 'action="install"' in desired
    assert 'desired_state="installed_disabled"' in desired
    assert "PluginDesiredStateLedger(" not in desired
    assert "PluginManagementService(" not in desired
    assert "PackageTransactionPinJournal" in retention
    assert 'state="released"' in retention
    for forbidden in (
        "PluginRevisionStore",
        "PackageMaterializer",
        "shutil",
        ".unlink(",
        ".rmdir(",
        "rmtree(",
    ):
        assert forbidden not in retention


def test_plc9a2_all_single_source_operations_route_before_legacy_effects() -> None:
    for method in (
        "PackageOperationsRuntime.materialize",
        "PackageOperationsRuntime.install",
        "PackageOperationsRuntime.update",
        "PackageOperationsRuntime.remove",
        "PackageOperationsRuntime.uninstall",
        "PackageOperationsRuntime.uninstall_sync",
    ):
        body = _function_source(OPERATIONS, method)
        assert body.index("self._route_product(") < min(
            (
                body.find(effect)
                for effect in (
                    "self._require_materializer(",
                    "self._materialize_legacy(",
                    "self._remove_legacy(",
                    "self._refresh_settings_mutation(",
                    "self._refresh_settings_mutation_sync(",
                )
                if effect in body
            ),
            default=len(body),
        )


def test_plc9a2_transports_and_startup_use_one_typed_lifecycle_seam() -> None:
    session = _source(SESSION)
    facade = _source(FACADE)
    cli = _source(CLI)
    rpc = _source(RPC)
    startup = _source(STARTUP)

    assert "async def execute_package_lifecycle(" in session
    assert "async def execute_package_lifecycle(" in facade
    assert 'entrypoint="cli"' in cli
    assert 'entrypoint="rpc"' in rpc
    assert 'entrypoint="startup"' in startup
    assert cli.index('getattr(session, "execute_package_lifecycle"') < cli.index(
        "_require_method("
    )
    assert rpc.index('getattr(session, "execute_package_lifecycle"') < rpc.index(
        "method_names = {"
    )
    assert "for owner in (self._runtime, session)" not in _function_source(
        RPC, "_DynamicPackageCapabilities._invoke_lifecycle"
    )
    for method in (
        "_DynamicPackageCapabilities._invoke_lifecycle",
        "_DynamicPackageCapabilities._invoke_collection",
    ):
        body = _function_source(RPC, method)
        assert body.index("self._product_owner(session)") < body.index(
            "if callable(executor)"
            if method.endswith("_invoke_lifecycle")
            else "if callable(collection)"
        )
    product_owner = _function_source(
        RPC,
        "_DynamicPackageCapabilities._product_owner",
    )
    assert "if session_binding is None:" in product_owner
    assert "runtime_binding is not None" in product_owner
    assert "return session" in product_owner
    startup_route = _function_source(
        STARTUP, "PackageSourceResolver._materialize_startup_source"
    )
    assert startup_route.index("lifecycle.route(") < startup_route.index(
        "self.materializer.materialize_remote_source_sync(source)",
        startup_route.index("lifecycle.route("),
    )


def test_plc9a2_product_binding_is_explicit_at_bootstrap_and_session() -> None:
    bootstrap = _source(BOOTSTRAP)
    product_session = _source(PRODUCT_SESSION)

    assert "package_product_lifecycle: PackageProductLifecycleOperationPort | None" in (
        bootstrap
    )
    assert "product_lifecycle=request.package_product_lifecycle" in bootstrap
    assert "package_product_lifecycle: PackageProductLifecycleOperationPort | None" in (
        product_session
    )
    assert "product_lifecycle=package_product_lifecycle" in product_session


def test_plc9a2_does_not_widen_the_public_author_sdk() -> None:
    author_sdk = _source(AUTHOR_SDK)
    for symbol in (
        "PackageProductLifecycleActivation",
        "PackageProductLifecycleIntentV1",
        "PackageProductLifecycleOperationPort",
        "PluginManagementPackageDesiredStateAdapter",
        "PackageProductRetentionSettlementOwner",
    ):
        assert symbol not in author_sdk
