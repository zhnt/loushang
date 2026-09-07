from __future__ import annotations

import ast
from pathlib import Path

APPHOST = Path("src/loushang/apphost")
CORE = {
    APPHOST / "__init__.py",
    APPHOST / "_ownership.py",
    APPHOST / "catalog.py",
    APPHOST / "contracts.py",
    APPHOST / "errors.py",
    APPHOST / "router.py",
    APPHOST / "runtime.py",
}
OPTIONAL = {APPHOST / "application.py", APPHOST / "hosted.py"}
ADAPTER = APPHOST / "integrations/harness_session.py"
SCOPE = Path("docs/internals/architecture/apphost/README.md")
CONTRACT = Path("docs/internals/architecture/apphost/contract-model-a0.md")
WORKFLOW = Path(".github/workflows/apphost-quality.yml")


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _imports(path: Path) -> set[str]:
    imports: set[str] = set()
    package = path.parent.relative_to("src").parts
    for node in ast.walk(ast.parse(_source(path), filename=str(path))):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            retained = len(package) - (node.level - 1) if node.level else 0
            base = (
                (*package[:retained], *(node.module or "").split("."))
                if node.level
                else tuple((node.module or "").split("."))
            )
            normalized = tuple(part for part in base if part)
            if normalized:
                imports.add(".".join(normalized))
            imports.update(".".join((*normalized, alias.name)) for alias in node.names)
    return imports


def test_a0_2_core_is_small_stdlib_only_and_optional_integration_is_separate() -> None:
    assert {path for path in APPHOST.glob("*.py")} == CORE | OPTIONAL
    core = "\n".join(_source(path) for path in CORE)
    for forbidden in (
        "loushang.harness",
        "loushang.hosting",
        "loushang.appserver",
        "loushang.appservice",
        "loushang.coding",
        "importlib",
        "entry_points",
        "os.environ",
        "os.getcwd",
        "Path(",
        ".expanduser(",
        "subprocess",
    ):
        assert forbidden not in core
    facade_imports = _imports(APPHOST / "__init__.py")
    assert not any(
        item.startswith("loushang.apphost.integrations") for item in facade_imports
    )
    assert "loushang.apphost.hosted" not in facade_imports
    assert "loushang.apphost.application" not in facade_imports
    assert any(
        item == "loushang.harness" or item.startswith("loushang.harness.")
        for item in _imports(ADAPTER)
    )


def test_a0_2_router_is_lookup_first_and_hands_out_no_execution_capability() -> None:
    source = _source(APPHOST / "router.py")
    tree = ast.parse(source, filename=str(APPHOST / "router.py"))
    create = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_prepare_create"
    )
    calls = [
        ast.unparse(node.func)
        for node in ast.walk(create)
        if isinstance(node, ast.Call)
    ]
    assert calls.index("_call_session") < calls.index("self._catalog._acquire_product")
    assert "_PreparedProductRoute" in source
    assert "PreparedProductRouteV1" in source
    public_create_source = ast.get_source_segment(source, create)
    assert public_create_source is not None
    assert "create_runtime" not in public_create_source
    assert "bind_profile" not in public_create_source
    assert "default_product" not in source
    facade = _source(APPHOST / "__init__.py")
    assert '"PreparedProductRouteV1"' in facade
    catalog = _source(APPHOST / "catalog.py")
    assert "async def _acquire_product(" in catalog
    assert "async def acquire_product(" not in catalog
    friend_consumers = {
        path
        for path in Path("src/loushang").rglob("*.py")
        if "._acquire_product(" in _source(path)
    }
    assert friend_consumers == {APPHOST / "router.py"}
    contracts = ast.parse(_source(APPHOST / "contracts.py"))
    route = next(
        node
        for node in contracts.body
        if isinstance(node, ast.ClassDef) and node.name == "PreparedProductRouteV1"
    )
    members = {
        node.name
        for node in route.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert members == {"descriptor", "generation_id", "binding_key", "close"}


def test_a0_2_catalog_uses_static_exact_pins_and_persistent_retirement() -> None:
    source = _source(APPHOST / "catalog.py")
    for proof in (
        'bind_native_async(registration.admission_source, "acquire_pin")',
        'read_static_property(raw, "identity")',
        "type(identity) is not AdmissionIdentityV1",
        "expected_generation_id",
        "self._retiring",
        "settle_retiring",
        "asyncio.shield",
    ):
        assert proof in source
    assert "self._entry.factory" not in source
    tree = ast.parse(source, filename=str(APPHOST / "catalog.py"))
    legacy_acquire = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_acquire_product"
    )
    legacy_source = ast.get_source_segment(source, legacy_acquire)
    assert legacy_source is not None
    assert "create_runtime" not in legacy_source
    assert "bind_profile" not in legacy_source


def test_optional_adapter_is_dark_with_only_reviewed_g8_through_g12_consumers() -> (
    None
):
    apphost_consumers = {
        path
        for path in Path("src/loushang").rglob("*.py")
        if not path.is_relative_to(APPHOST)
        and any(
            item == "loushang.apphost" or item.startswith("loushang.apphost.")
            for item in _imports(path)
        )
    }
    assert apphost_consumers == {
        Path("src/loushang/coding/apphost_canary.py"),
        Path("src/loushang/coding/apphost_composition.py"),
        Path("src/loushang/coding/apphost_product.py"),
        Path("src/loushang/coding/appservice_adapter.py"),
        Path("src/loushang/coding/hosted_application.py"),
    }
    adapter_consumers = {
        path
        for path in Path("src/loushang").rglob("*.py")
        if path != ADAPTER
        and any(
            item == "loushang.apphost.integrations.harness_session"
            or item.startswith("loushang.apphost.integrations.harness_session.")
            for item in _imports(path)
        )
    }
    assert adapter_consumers == set()


def test_optional_adapter_pins_owner_descriptor_without_deriving_roots() -> None:
    source = _source(ADAPTER)
    for proof in (
        "self._runtime.list_discovered_session_summaries()",
        "self._scope_by_source.get(discovery.locator.source_id)",
        "os.O_NOFOLLOW",
        "dir_fd=parent",
        "os.fstat(descriptor)",
        "_conversation_id(snapshot)",
        "_native_descriptor_supported()",
        "_read_sealed_snapshot(descriptor, before)",
        "HARNESS_SESSION_SNAPSHOT_MAX_BYTES_V1",
    ):
        assert proof in source
    for forbidden in (
        "agent_transcript_file_lock",
        ".loushang",
        "LOUSHANG_HOME",
        "getcwd",
        "expanduser",
        "rglob",
        ".glob(",
        "os.environ",
        "Path(reference",
        "Path(candidate",
    ):
        assert forbidden not in source


def test_optional_adapter_owns_rejected_returns_and_fences_its_lifecycle() -> None:
    source = _source(ADAPTER)
    tree = ast.parse(source, filename=str(ADAPTER))
    validate = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_validate_canonical_candidate"
    )
    validate_source = ast.get_source_segment(source, validate)
    assert validate_source is not None
    adoption = validate_source.index("cleanup.adopt(group)")
    close_binding = validate_source.index("owner.bind_close()")
    projection = validate_source.index('read_static_property(value, "projection")')
    assert adoption < close_binding < projection
    for proof in (
        "async def settle_pending_cleanup(self)",
        "async def close(self)",
        "self._closed = True",
        "await self._drained.wait()",
        "await self._cleanup.settle_all()",
        "if self._closed:",
        "raise GenerationRetiredError()",
    ):
        assert proof in source


def test_optional_adapter_bounds_and_predrains_canonical_delegation() -> None:
    source = _source(ADAPTER)
    assert "HARNESS_SESSION_MAX_ACTIVE_CANONICAL_OPS_V1 = 8" in source
    assert source.count("await self._begin_canonical_provider_call()") == 4
    assert source.count("await _call_optional(") == 4
    tree = ast.parse(source, filename=str(ADAPTER))
    begin = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_begin_canonical_provider_call"
    )
    begin_source = ast.get_source_segment(source, begin)
    assert begin_source is not None
    drain = begin_source.index("await self._cleanup.settle_all()")
    pending = begin_source.index("if self._cleanup.has_pending:")
    reserve = begin_source.index("self._canonical_active += 1")
    assert drain < pending < reserve


def test_optional_adapter_relinquishes_posix_fd_before_ambiguous_close() -> None:
    source = _source(ADAPTER)
    tree = ast.parse(source, filename=str(ADAPTER))
    owner = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "_DescriptorOwner"
    )
    close = next(
        node
        for node in owner.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "close"
    )
    close_source = ast.get_source_segment(source, close)
    assert close_source is not None
    assert close_source.index("self._descriptor = -1") < close_source.index(
        "os.close(descriptor)"
    )
    assert close_source.index("self._closed = True") < close_source.index(
        "os.close(descriptor)"
    )


def test_windows_native_fail_closed_workflow_is_verified_and_retained() -> None:
    source = _source(WORKFLOW)
    for proof in (
        "runs-on: windows-2022",
        "-k windows_native_backend_is_explicitly_fail_closed",
        "--junitxml=.artifacts/apphost-harness-windows.xml",
        "scripts/dev/verify_pytest_xml.py .artifacts/apphost-harness-windows.xml",
        "if-no-files-found: error",
    ):
        assert proof in source


def test_a0_2_docs_remain_recorded_inside_the_default_dark_a0_4_scope() -> None:
    scope = _source(SCOPE)
    contract = _source(CONTRACT)
    assert "A0.2 adds:" in scope
    assert "A0.2 Catalog And Router" in contract
    assert "read-only idempotency" in contract
    assert "A0.3 Live Binding And Embedded Profile" in contract
    assert "A0.4 Hosted Binder" in contract
    assert "registered in the adapter's private" in contract
    assert "never retries that integer" in contract
    assert "capped by `HARNESS_SESSION_MAX_ACTIVE_CANONICAL_OPS_V1`" in contract
    assert "The one installed explicit factory may" in scope
    assert "only after an exact typed Hosting activation request" in scope
