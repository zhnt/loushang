from __future__ import annotations

import ast
import re
from pathlib import Path

from loushang.foundation.platform_paths import PlatformPaths
from loushang.harness.machine_resources.control_plane import (
    resolve_machine_resource_layout,
)

HOSTING_ROOT = Path("docs/internals/architecture/hosting")
DRAFT_ROOT = Path("docs/internals/architecture/drafts")
PLUGIN_ROOT = Path("docs/internals/architecture/harness/plugin")

H6 = HOSTING_ROOT / "managed-launch-preparation-h6.md"
INVENTORY = HOSTING_ROOT / "validation/hosted-product-runtime-v1-inventory.md"
APPHOST_PLACEMENT = DRAFT_ROOT / "apphost-top-level-placement.md"
APPHOST_DISCOVERY = DRAFT_ROOT / "apphost-component-discovery-a0.md"
APPHOST_A0 = DRAFT_ROOT / "apphost-contract-baseline-a0.md"
DELIVERY_PLAN = DRAFT_ROOT / "hosted-product-runtime-v1-plan.md"
PLC9C = PLUGIN_ROOT / "plugin-lifecycle-plc9c0-baseline.md"

HOSTING_SOURCE = Path("src/loushang/hosting")
HARNESS_SOURCE = Path("src/loushang/harness")
WORKER_SOURCE = HARNESS_SOURCE / "worker"
APPHOST_SOURCE = Path("src/loushang/apphost")
APPSERVER_SOURCE = Path("src/loushang/appserver")
APPSERVICE_SOURCE = Path("src/loushang/appservice")

CURRENT_SOURCE_SEAMS = (
    HOSTING_SOURCE / "__init__.py",
    HOSTING_SOURCE / "contracts.py",
    HOSTING_SOURCE / "errors.py",
    HOSTING_SOURCE / "runtime.py",
    HOSTING_SOURCE / "_process_backend.py",
    HOSTING_SOURCE / "_process_host.py",
    HOSTING_SOURCE / "_child_session_host.py",
    HOSTING_SOURCE / "_launch_preparation.py",
    HOSTING_SOURCE / "_posix_launch_preparation.py",
    HOSTING_SOURCE / "_windows_launch_preparation.py",
    HOSTING_SOURCE / "_posix_process.py",
    HOSTING_SOURCE / "_windows_process.py",
    HOSTING_SOURCE / "_win32_process.py",
    HOSTING_SOURCE / "_endpoint_host.py",
    HOSTING_SOURCE / "_endpoint_backend.py",
    HOSTING_SOURCE / "_posix_endpoint.py",
    HOSTING_SOURCE / "_windows_endpoint.py",
    HARNESS_SOURCE / "workspace/process/_sealed_executable.py",
    HARNESS_SOURCE / "workspace/process/hosting_compat.py",
    HARNESS_SOURCE / "workspace/process/host.py",
    HARNESS_SOURCE / "workspace/process/local.py",
    HARNESS_SOURCE / "tools/process_hosting.py",
    HARNESS_SOURCE / "sandbox/process.py",
    HARNESS_SOURCE / "sandbox/runtime.py",
    HARNESS_SOURCE / "sandbox/backends/linux.py",
    WORKER_SOURCE / "contracts.py",
    WORKER_SOURCE / "launch.py",
    WORKER_SOURCE / "hosting_adapter.py",
    WORKER_SOURCE / "owner_selection.py",
    WORKER_SOURCE / "protocol.py",
    WORKER_SOURCE / "supervisor.py",
    WORKER_SOURCE / "journal.py",
    WORKER_SOURCE / "session.py",
    WORKER_SOURCE / "capability_query.py",
    WORKER_SOURCE / "product_activation.py",
    WORKER_SOURCE / "_native_profile_bridge.py",
    HARNESS_SOURCE / "transcript/discovery.py",
    HARNESS_SOURCE / "transcript/session_catalog.py",
    HARNESS_SOURCE / "transcript/directory.py",
    APPHOST_SOURCE / "integrations/harness_session.py",
    APPHOST_SOURCE / "runtime.py",
    APPHOST_SOURCE / "hosted.py",
    APPSERVER_SOURCE / "ports.py",
    HARNESS_SOURCE / "machine_resources/control_plane.py",
    Path("src/loushang/coding/cli/__main__.py"),
    Path("src/loushang/coding/_product_worker_canary.py"),
    Path("src/loushang/coding/apphost_composition.py"),
    Path("src/loushang/coding/apphost_product.py"),
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    marker = f"## {heading}\n"
    assert marker in text
    body = text.split(marker, maxsplit=1)[1]
    return body.split("\n## ", maxsplit=1)[0]


def _status_fields(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    current_name: str | None = None
    for line in _section(_read(path), "Status").splitlines():
        if line.startswith("- "):
            name, value = line[2:].split(":", maxsplit=1)
            fields[name] = value.strip()
            current_name = name
            continue
        if current_name is not None and line.startswith("  "):
            fields[current_name] = f"{fields[current_name]} {line.strip()}"
    for name, value in fields.items():
        normalized = value
        if normalized.startswith("`") and normalized.endswith("`"):
            normalized = normalized[1:-1]
        fields[name] = normalized
    return fields


def _imports(path: Path) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(ast.parse(_read(path), filename=str(path))):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    return imports


def _table_first_column(text: str) -> tuple[str, ...]:
    values: list[str] = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        first = line.strip("|").split("|", maxsplit=1)[0].strip().strip("`")
        if (
            first
            and first not in {"Slice", "Gate", "ID"}
            and not re.fullmatch(r":?-{3,}:?", first)
        ):
            values.append(first)
    return tuple(values)


def _documented_source_paths(text: str) -> set[str]:
    return set(re.findall(r"`(src/loushang/[^`]+\.py)`", text))


def test_baseline_documents_are_status_honest_and_indexed() -> None:
    expected = {
        H6: {
            "ID": "HOST-H6",
            "Scope": "hosting",
            "Parent": "loushang",
            "Authority": "normative accepted design",
            "Design status": "accepted",
            "Implementation status": (
                "implemented — H6.1 through H6.4 remain default-dark; "
                "H6.5b Windows LPAC native mechanics retain one C5.5c Harness "
                "friend consumer and no direct Product consumer"
            ),
            "Activation status": "forbidden; H5 remains default-dark",
        },
        INVENTORY: {
            "ID": "HOSTED-PRODUCT-V1-INVENTORY",
            "Authority": "descriptive — source-backed Current inventory",
            "Design status": "not-applicable",
            "Implementation status": "not-applicable",
            "Effect": "none; this record grants no runtime or activation authority",
        },
        APPHOST_DISCOVERY: {
            "ID": "APPHOST-A0-DISCOVERY",
            "Authority": "descriptive — completed design validation evidence",
            "Design status": "not-applicable",
            "Implementation status": "not-applicable",
        },
        APPHOST_A0: {
            "ID": "APPHOST-A0",
            "Authority": (
                "historical — refined by the canonical A0 Contract Model"
            ),
            "Design status": "accepted and promoted",
            "Implementation status": (
                "implemented through A0.4; A0.5 not started"
            ),
            "Activation status": (
                "default-dark; no production AppHost composition route"
            ),
        },
        DELIVERY_PLAN: {
            "ID": "HOSTED-PRODUCT-RUNTIME-V1",
            "Authority": "normative accepted delivery contract",
            "Design status": "accepted",
            "Implementation status": (
                "implemented — G0H through G9 complete and G9 promoted"
            ),
            "Production activation": "closed",
        },
    }
    for path, fields in expected.items():
        assert path.is_file()
        actual = _status_fields(path)
        for name, value in fields.items():
            assert actual.get(name) == value

    hosting_index = _read(HOSTING_ROOT / "README.md")
    draft_index = _read(DRAFT_ROOT / "README.md")
    plugin_index = _read(PLUGIN_ROOT / "README.md")
    assert hosting_index.count("(managed-launch-preparation-h6.md)") == 1
    assert (
        hosting_index.count(
            "(validation/managed-launch-preparation-h6-harness-parity.md)"
        )
        == 1
    )
    assert (
        hosting_index.count("(validation/hosted-product-runtime-v1-inventory.md)") == 1
    )
    for filename in (
        "apphost-component-discovery-a0.md",
        "apphost-contract-baseline-a0.md",
        "hosted-product-runtime-v1-plan.md",
    ):
        assert draft_index.count(f"({filename})") == 1
    assert "HOST-H6 managed preparation contract" in plugin_index


def test_h6_keeps_authority_outside_and_native_material_opaque() -> None:
    h6 = _read(H6)
    normalized_h6 = " ".join(h6.split())
    responsibility = _section(h6, "Responsibility Boundary")
    contract = _section(h6, "Accepted Contract Properties")

    for statement in (
        "Meaning stays with the caller; mechanism stays with Hosting",
        "An opaque lease crosses the ownership boundary",
        "Preparation is request-bound and one-use",
        "Final verification is adjacent to the effect",
        "Required means fail closed",
        "Evidence does not acquire authority",
        "The five-component model remains stable",
        "The accepted H0--H5 `LaunchPreparationPort` remains caller-owned",
        "H6 adds only a complementary Hosting-owned one-shot capture capability",
        "String placeholder substitution",
        "One spawn has one inheritance manifest",
        "Identity covers the execution closure",
        "Capture is reservation-scoped and bounded",
        "Acquisition attaches before cancellation can land",
        "must not reserve Process/Child Session capacity",
        "Opaque here is an API and ownership property",
        "MINTED -> CAPTURING -> CAPTURED -> VERIFYING -> VERIFIED",
        "The H6.1 matrix includes concurrent double-capture/double-consume",
    ):
        assert statement in normalized_h6
    for owner in (
        "Product/Harness composition",
        "Harness authority owners",
        "Harness Sandbox owner",
        "`HOST-CMP-CONTRACT`",
        "`HOST-CMP-PLATFORM`",
        "`HOST-CMP-PROCESS`",
        "`HOST-CMP-SESSION`",
        "Harness Worker supervisor",
        "exact Harness/domain owner",
    ):
        assert owner in responsibility
    for forbidden in (
        "raw descriptors",
        "handles",
        "mutable paths",
        "Product IDs",
        "Approval records",
        "credentials",
    ):
        assert forbidden.lower() in h6.lower() or forbidden.lower() in contract.lower()

    assert _table_first_column(_section(h6, "Delivery Slices")) == (
        "H6.0",
        "H6.1",
        "H6.2",
        "H6.3",
        "H6.4",
        "H6.5a",
        "H6.5b",
    )
    assert _table_first_column(_section(h6, "Conformance Inventory")) == (
        "H6-BOUND",
        "H6-OPAQUE",
        "H6-ONE-SHOT",
        "H6-STATE",
        "H6-CAPACITY",
        "H6-ATTACH",
        "H6-FINAL-FENCE",
        "H6-INHERITANCE",
        "H6-EXEC-CLOSURE",
        "H6-LOAD-CLOSURE",
        "H6-CLEANUP",
        "H6-POSIX-NATIVE",
        "H6-WINDOWS-NATIVE",
        "H6-HARNESS-PARITY",
        "H6-NO-AUTHORITY",
        "H6-DARK",
    )


def test_apphost_discovery_maps_five_cohesive_components() -> None:
    discovery = _read(APPHOST_DISCOVERY)
    mapping = _section(discovery, "Function-To-Component Mapping")
    refinement = _section(discovery, "Refinement: Split / Merge / Keep")

    assert tuple(
        re.findall(
            r"`AH-F(\d{2})`", _section(discovery, "Candidate Function Inventory")
        )
    ) == tuple(f"{number:02d}" for number in range(1, 20))
    for component in (
        "AppHost Contract Model",
        "Product Catalog And Router",
        "Scoped Runtime Lifecycle",
        "Deployment Profile Composer",
        "Outer Launcher Adapters",
    ):
        assert component in mapping
        assert component in refinement
    for excluded in (
        "AppServer/AppService | split to sibling scopes",
        "Session Store | exclude",
        "Session Discovery/Catalog | keep outside via required port",
        "Plugin Manager/Product builder | exclude",
        "Runtime Resource Owner | reuse, do not wrap as peer component",
    ):
        assert excluded in refinement
    assert (
        "AppHost core -/-> AppServer / Hosting / concrete Product / UI framework"
        in discovery
    )
    assert "AppServer/AppService/Harness/Hosting -/-> AppHost" in discovery


def test_apphost_a0_requires_explicit_identity_and_scoped_lifetimes() -> None:
    baseline = _read(APPHOST_A0)
    placement = _read(APPHOST_PLACEMENT)
    for contract in (
        "Product descriptor",
        "Product factory",
        "Scoped Product Runtime handle",
        "Session Identity Envelope",
        "Profile descriptor/factory/lease",
    ):
        assert contract in _section(baseline, "Contract Boundary")
    for invariant in (
        "Every new/open/resume route states a `product_id`",
        "Unknown, disabled, incompatible, or ambiguous Product identity fails",
        "An envelope selects only among already admitted Product registrations",
        "The catalog is an immutable generation",
        "A canonical live-binding registry owns exactly one scoped Product Runtime",
        "Trusted composition explicitly selects current-directory",
        "Listing and envelope reads have fixed candidate, byte, and schema bounds",
        "Product identity and presentation/deployment profile are orthogonal",
        "AppHost core imports neither AppServer nor Hosting",
        "Python factories and runtime handles never cross a process boundary",
        "AppService aggregate or named-mux count creates no additional AppHost",
        "Legacy Coding and external Codex/Claude-style Session formats",
    ):
        assert invariant in " ".join(
            _section(baseline, "Required Behavioral Invariants").split()
        )
    assert _table_first_column(_section(baseline, "A0 Delivery Slices")) == (
        "A0.0",
        "A0.1",
        "A0.2",
        "A0.3",
        "A0.4",
        "A0.5",
    )
    assert "`loushang.hosting` implements Product-neutral process" in placement
    assert "mechanics through H4; the Harness-owned H5 Worker adapter" in placement
    assert "At that time there was no `loushang.apphost`, `loushang.appserver`, or" in placement
    assert "`loushang.appservice` source package" in placement
    for discovery_root in (
        "current-directory and user-global discovery scopes",
        "AppHost never derives cwd, user home, or `$LOUSHANG_HOME`",
        "reports conflicting envelopes as an ambiguity",
    ):
        assert discovery_root in " ".join(placement.split())
    contract_boundary = " ".join(_section(baseline, "Contract Boundary").split())
    for reuse_contract in (
        "Session identity/catalog required port",
        "existing Harness `SessionDiscoverySource`",
        "It does not create a peer session index",
    ):
        assert reuse_contract in contract_boundary

    assert _table_first_column(
        _section(baseline, "Planned Conformance Inventory")
    ) == (
        "A0-CATALOG",
        "A0-TWO-PRODUCTS",
        "A0-NO-DEFAULT",
        "A0-IDENTITY-NO-AUTHORITY",
        "A0-SESSION-DISCOVERY",
        "A0-SESSION-SCOPE",
        "A0-CATALOG-GENERATION",
        "A0-ADMISSION-PIN",
        "A0-RESUME-PIN",
        "A0-CREATE-IDEMPOTENCY",
        "A0-MIGRATION",
        "A0-MULTI-ATTACH",
        "A0-PROFILE-ORTHOGONAL",
        "A0-IMPORTS",
        "A0-ROLLBACK",
        "A0-SERIALIZED-LAUNCH",
    )


def test_current_inventory_matches_source_and_retained_absences() -> None:
    inventory = _read(INVENTORY)
    for path in CURRENT_SOURCE_SEAMS:
        assert path.is_file(), path
        assert f"`{path.as_posix()}`" in inventory
    assert _documented_source_paths(inventory) == {
        path.as_posix() for path in CURRENT_SOURCE_SEAMS
    }

    assert HOSTING_SOURCE.is_dir()
    assert {
        path.relative_to(APPHOST_SOURCE).as_posix()
        for path in APPHOST_SOURCE.rglob("*.py")
    } == {
        "__init__.py",
        "_ownership.py",
        "catalog.py",
        "contracts.py",
        "errors.py",
        "integrations/__init__.py",
        "integrations/harness_session.py",
        "router.py",
        "runtime.py",
        "hosted.py",
    }
    assert {
        path.relative_to(APPSERVER_SOURCE).as_posix()
        for path in APPSERVER_SOURCE.rglob("*.py")
    } == {"__init__.py", "ports.py"}
    assert not APPSERVICE_SOURCE.exists()

    compatibility = _read(HARNESS_SOURCE / "workspace/process/hosting_compat.py")
    selection = _read(WORKER_SOURCE / "owner_selection.py")
    assert "Hosting v1 cannot transfer the Harness sealed-executable" in compatibility
    assert 'owner: WorkerSessionOwner = "current"' in selection
    assert "os.environ" not in selection
    assert "getenv" not in selection

    current_public_contract = _read(HOSTING_SOURCE / "contracts.py") + _read(
        HOSTING_SOURCE / "__init__.py"
    )
    for h6_runtime_token in (
        "ManagedLaunchPreparation",
        "NativeLaunchMaterial",
        "OpaqueLaunchBinding",
    ):
        assert h6_runtime_token not in current_public_contract

    hosting_imports = {
        imported for path in HOSTING_SOURCE.rglob("*.py") for imported in _imports(path)
    }
    forbidden_hosting_prefixes = (
        "loushang.harness",
        "loushang.coding",
        "loushang.apphost",
        "loushang.appserver",
        "loushang.appservice",
    )
    assert not any(
        imported.startswith(forbidden_hosting_prefixes)
        for imported in hosting_imports
    )

    reverse_apphost_consumers = {
        path
        for path in Path("src/loushang").rglob("*.py")
        if not path.is_relative_to(APPHOST_SOURCE)
        if any(
            imported.startswith("loushang.apphost") for imported in _imports(path)
        )
    }
    assert reverse_apphost_consumers == {
        Path("src/loushang/coding/apphost_composition.py"),
        Path("src/loushang/coding/apphost_product.py")
    }
    retained_fences = " ".join(_section(inventory, "Retained Fences").split())
    for statement in (
        "H5 default owner is Current",
        "PLC9C5 C5.0--C5.5c are implemented",
        "Windows LPAC Product activation is implemented and retained",
            "AppHost G9 remains explicitly selected and dark",
        "Hosting imports no Harness, Product, AppHost, AppServer, or AppService",
    ):
        assert statement in retained_fences


def test_current_session_discovery_roots_preserve_exact_modes(tmp_path: Path) -> None:
    platform_home = tmp_path / "user" / ".loushang"
    paths = PlatformPaths(
        home=platform_home,
        data=platform_home / "data",
        state=platform_home / "state",
        cache=platform_home / "cache",
        runtime=tmp_path / "runtime",
        temporary=tmp_path / "temporary",
    )
    cwd = tmp_path / "project"
    layout = resolve_machine_resource_layout(platform_paths=paths, cwd=cwd)
    sessions = {
        resource.resource_id: resource
        for resource in layout.resources
        if resource.resource_id.startswith("sessions.")
    }

    assert (sessions["sessions.global"].path, sessions["sessions.global"].mode) == (
        platform_home / "data" / "sessions",
        "canonical",
    )
    assert (
        sessions["sessions.cwd_compatibility"].path,
        sessions["sessions.cwd_compatibility"].mode,
    ) == (cwd / ".loushang" / "sessions", "compatibility")
    assert (
        sessions["sessions.home_compatibility"].path,
        sessions["sessions.home_compatibility"].mode,
    ) == (platform_home / "sessions", "compatibility")


def test_delivery_plan_has_parallel_streams_and_one_activation_join() -> None:
    plan = _read(DELIVERY_PLAN)
    normalized = " ".join(plan.split())
    gates = _table_first_column(_section(plan, "Workstreams And Dependency Gates"))
    assert gates == (
        "G0H",
        "G0A",
        "G1",
        "G2L",
        "G2W",
        "G3",
        "G4",
        "G5",
        "G6",
        "G7",
        "G8",
        "G9",
    )
    assert "G2L, G2W, and G3 should proceed in parallel after G1" in normalized
    assert "G4--G6 may proceed in parallel with G1--G3" in normalized
    assert "G0H and G0A are independently accepted gates" in normalized
    assert "G7 is the first Hosting/Harness activation join" in normalized
    assert "G8 now implements the first join between the AppHost and Worker rails" in normalized
    workstreams = _section(plan, "Workstreams And Dependency Gates")
    g7 = next(line for line in workstreams.splitlines() if line.startswith("| G7 |"))
    assert "G2L + G2W + G3" in g7
    assert "G5" not in g7 and "G6" not in g7 and "AppHost" not in g7
    assert "| G8 | AppHost + Product/Harness" in workstreams
    assert "no environment variable, platform auto-detection, or missing" in normalized
    assert "never retry the other owner within one launch attempt" in normalized


def test_current_worker_route_has_one_exact_composition_and_no_fallback() -> None:
    activation_names = {
        "HostingManagedWorkerSessionAdapter",
        "WorkerHostingActivationV1",
        "WorkerSessionOwnerRouter",
    }
    consumers = {
        path
        for path in Path("src/loushang").rglob("*.py")
        if not path.is_relative_to(WORKER_SOURCE)
        and any(name in _read(path) for name in activation_names)
    }
    assert consumers == {Path("src/loushang/coding/_product_worker_canary.py")}

    selection = _read(WORKER_SOURCE / "owner_selection.py")
    assert 'owner: WorkerSessionOwner = "current"' in selection
    router_start = selection.split("    async def start(", maxsplit=1)[1].split(
        "    def _selection_locked", maxsplit=1
    )[0]
    assert router_start.count("return await port.start(") == 1
    assert "except" not in router_start
    assert "_current.start" not in router_start
    assert "_hosting.start" not in router_start
    assert "os.environ" not in selection
    assert "getenv" not in selection


def test_plc9c5_and_h5_activation_fences_are_unchanged() -> None:
    plc9c = _read(PLC9C)
    h6 = _read(H6)
    plan = _read(DELIVERY_PLAN)
    normalized_plc9c = " ".join(plc9c.split())
    assert (
        "Until the owning PLC9C5 C5.1--C5.4 slice intentionally revises each exact"
        in normalized_plc9c
    )
    assert (
        "PLC9C4 -> PLC9C5 C5.0 | remove no runtime guard"
    ) in normalized_plc9c
    assert "C5.0 removes no runtime guard" in " ".join(plan.split())
    assert "they do not revise this activation guard" in normalized_plc9c
    assert "the PLC9C5 Product-activation/platform absence guard remains intact" in h6
    assert "zero runtime activation" in plan
    assert "Production activation: closed" in plan
