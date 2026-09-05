from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ARCHITECTURE_ROOT = REPOSITORY_ROOT / "docs/internals/architecture"
HOSTING_ROOT = ARCHITECTURE_ROOT / "hosting"
HOSTED_APPLICATION_BOUNDARY = (
    HOSTING_ROOT / "key-designs/hosted-application-support-boundary.md"
)
APPHOST_PLACEMENT = ARCHITECTURE_ROOT / "drafts/apphost-top-level-placement.md"
HOSTING_PLACEMENT = (
    ARCHITECTURE_ROOT / "decisions/ARD-002-hosting-top-level-placement.md"
)
APPSERVICE_BOUNDARY = (
    ARCHITECTURE_ROOT / "drafts/appservice-embedded-tui-hosted-boundary-plan.md"
)
APPSERVICE_REFACTOR = ARCHITECTURE_ROOT / "drafts/application-service-refactor.md"

HOSTING_DOCUMENTS = (
    HOSTING_ROOT / "README.md",
    HOSTING_ROOT / "requirements.md",
    HOSTING_ROOT / "system-context.md",
    HOSTING_ROOT / "component-model.md",
    HOSTING_ROOT / "contract-model-h0.md",
    HOSTING_ROOT / "process-lifetime-host-h1.md",
    HOSTING_ROOT / "process-platform-h2.md",
    HOSTING_ROOT / "inherited-peer-endpoint-h3.md",
    HOSTING_ROOT / "atomic-child-session-h4.md",
    HOSTING_ROOT / "traceability.md",
    HOSTING_ROOT / "validation/component-discovery.md",
    HOSTED_APPLICATION_BOUNDARY,
    HOSTING_PLACEMENT,
)

CURRENT_HARNESS_SEAMS = (
    "src/loushang/harness/workspace/process/types.py",
    "src/loushang/harness/workspace/process/local.py",
    "src/loushang/harness/workspace/process/host.py",
    "src/loushang/harness/tools/process_hosting.py",
    "src/loushang/harness/sandbox/process.py",
    "src/loushang/harness/worker/contracts.py",
    "src/loushang/harness/worker/protocol.py",
    "src/loushang/harness/worker/supervisor.py",
    "src/loushang/harness/worker/journal.py",
)

COMPONENT_IDS = (
    "HOST-CMP-CONTRACT",
    "HOST-CMP-PROCESS",
    "HOST-CMP-ENDPOINT",
    "HOST-CMP-SESSION",
    "HOST-CMP-PLATFORM",
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
    started = False
    for line in _section(_read(path), "Status").splitlines():
        if not started:
            if not line.startswith("- "):
                continue
            started = True
        elif not line:
            break
        if not line.startswith("- "):
            continue
        assert ":" in line, f"malformed Status field in {path}: {line!r}"
        name, value = line[2:].split(":", maxsplit=1)
        assert name not in fields, f"duplicate Status field {name!r} in {path}"
        normalized = value.strip()
        if normalized.startswith("`") and normalized.endswith("`"):
            normalized = normalized[1:-1]
        fields[name] = normalized
    return fields


def _table_rows(text: str, headers: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    lines = text.splitlines()
    expected_header = "| " + " | ".join(headers) + " |"
    start = lines.index(expected_header)
    separator = tuple(cell.strip() for cell in lines[start + 1].strip("|").split("|"))
    assert len(separator) == len(headers)
    assert all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator)

    rows: list[tuple[str, ...]] = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
        assert len(cells) == len(headers), line
        rows.append(cells)
    return tuple(rows)


def _assert_mapping_contains(actual: dict[str, str], expected: dict[str, str]) -> None:
    for key, value in expected.items():
        assert actual.get(key) == value


def _numbered_steps(text: str, heading: str) -> tuple[str, ...]:
    section = _section(text, heading)
    matches = tuple(re.finditer(r"(?ms)^(\d+)\. (.*?)(?=^\d+\. |\n\n)", section))
    assert tuple(int(match.group(1)) for match in matches) == tuple(
        range(1, len(matches) + 1)
    )
    return tuple(" ".join(match.group(2).split()) for match in matches)


def test_hosting_design_package_is_complete_and_h0_is_accepted() -> None:
    for path in HOSTING_DOCUMENTS:
        assert path.is_file(), path.relative_to(REPOSITORY_ROOT)

    expected_authority = {
        HOSTING_ROOT / "README.md": "normative — accepted top-level Architecture Scope",
        HOSTING_ROOT / "requirements.md": "normative — accepted requirements",
        HOSTING_ROOT / "system-context.md": (
            "normative — accepted black-box context and boundary"
        ),
        HOSTING_ROOT / "component-model.md": ("normative — accepted component model"),
        HOSTING_ROOT / "contract-model-h0.md": (
            "normative — accepted H0 public contract"
        ),
        HOSTING_ROOT / "process-lifetime-host-h1.md": (
            "normative — implemented H1 internal runtime specification"
        ),
        HOSTING_ROOT / "process-platform-h2.md": (
            "normative — accepted H2 process-platform specification"
        ),
        HOSTING_ROOT / "inherited-peer-endpoint-h3.md": (
            "normative — accepted H3 endpoint specification"
        ),
        HOSTING_ROOT / "atomic-child-session-h4.md": (
            "normative — accepted H4 child-session specification"
        ),
        HOSTING_ROOT / "traceability.md": ("normative — accepted design traceability"),
        HOSTING_PLACEMENT: "normative — accepted cross-scope Hosting placement decision",
    }
    for path, authority in expected_authority.items():
        _assert_mapping_contains(
            _status_fields(path),
            {
                "Scope": "hosting",
                "Parent": "loushang",
                "Authority": authority,
                "Design status": "accepted",
                "Implementation status": (
                    "implemented"
                    if path
                    in {
                        HOSTING_ROOT / "contract-model-h0.md",
                        HOSTING_ROOT / "process-lifetime-host-h1.md",
                        HOSTING_ROOT / "process-platform-h2.md",
                        HOSTING_ROOT / "inherited-peer-endpoint-h3.md",
                        HOSTING_ROOT / "atomic-child-session-h4.md",
                    }
                    else "partial"
                ),
            },
        )

    _assert_mapping_contains(
        _status_fields(HOSTED_APPLICATION_BOUNDARY),
        {
            "Scope": "hosting",
            "Parent": "loushang",
            "Authority": "normative proposed design",
            "Design status": "proposed",
            "Implementation status": "not-started",
        },
    )

    _assert_mapping_contains(
        _status_fields(HOSTING_ROOT / "validation/component-discovery.md"),
        {
            "Scope": "hosting",
            "Parent": "loushang",
            "Authority": "descriptive — design validation input",
            "Design status": "not-applicable",
            "Implementation status": "not-applicable",
        },
    )
    _assert_mapping_contains(
        _status_fields(APPHOST_PLACEMENT),
        {
            "ID": "APPHOST-DP-TOP-LEVEL",
            "Scope": "Loushang",
            "Parent": "none",
            "Authority": "historical — superseded by accepted ARD-003",
            "Design status": "superseded",
            "Implementation status": "not-applicable — see canonical AppHost scope",
        },
    )
    _assert_mapping_contains(
        _status_fields(APPSERVICE_BOUNDARY),
        {
            "ID": "APP-DP-HOSTED-BOUNDARY",
            "Scope": "AppService / application host",
            "Parent": "Loushang",
            "Authority": "normative target proposal",
            "Design status": "proposed",
            "Implementation status": "not-started",
        },
    )
    _assert_mapping_contains(
        _status_fields(APPSERVICE_REFACTOR),
        {
            "ID": "APP-DP-SERVICE-REFACTOR",
            "Scope": "AppServer / AppService",
            "Parent": "Loushang",
            "Authority": "normative target proposal",
            "Design status": "proposed",
            "Implementation status": "partial",
        },
    )

    overview = _read(HOSTING_ROOT / "README.md")
    assert "H1 adds a private, fake-backed Process Lifetime Host" in " ".join(
        _section(overview, "Current").split()
    )
    assert "The accepted Target implements `loushang.hosting`" in _section(
        overview, "Target"
    )
    assert "## Current-To-Target Gaps" in overview

    apphost = _read(APPHOST_PLACEMENT)
    for heading in ("Current", "Accepted target", "Explicit delta"):
        assert f"### {heading}" in _section(apphost, "Current, Target, And Delta")


def test_hosting_parent_catalog_promotes_hosting_and_apphost() -> None:
    catalog = _read(ARCHITECTURE_ROOT / "README.md")
    scope_tree = _section(catalog, "Architecture Scope Tree")

    assert "- [Hosting](hosting/README.md)" in scope_tree
    assert "- [AppHost](apphost/README.md)" in scope_tree
    assert "Proposed top-level placements under design" not in scope_tree


def test_hosting_component_set_and_dependency_direction_are_explicit() -> None:
    overview = _read(HOSTING_ROOT / "README.md")
    component_model = _read(HOSTING_ROOT / "component-model.md")
    boundary = _read(HOSTING_ROOT / "system-context.md")

    component_rows = _table_rows(
        _section(component_model, "Component Map"),
        ("ID", "Component", "Owns", "Does not own"),
    )
    assert {row[0].strip("`"): row[1] for row in component_rows} == {
        "HOST-CMP-CONTRACT": "Hosting Contract Model",
        "HOST-CMP-PROCESS": "Process Lifetime Host",
        "HOST-CMP-ENDPOINT": "Inherited Peer Endpoint Host",
        "HOST-CMP-SESSION": "Child Session Host",
        "HOST-CMP-PLATFORM": "Platform Adapter Set",
    }
    assert set(COMPONENT_IDS) == {row[0].strip("`") for row in component_rows}
    for component_id in COMPONENT_IDS:
        assert component_id in overview

    assert (
        "loushang.harness -> loushang.hosting     # Current dark H2c dependency"
        in overview
    )
    assert "loushang.hosting -> loushang.harness     # forbidden" in overview
    authority_rows = dict(
        _table_rows(
            _section(boundary, "Authority And Trust Boundary"),
            ("Fact or decision", "Sole owner"),
        )
    )
    assert authority_rows["action allowed/approved/authorized"] == (
        "Harness Policy, Approval, Authorization"
    )
    assert authority_rows["containment required and active"] == (
        "Harness Sandbox owner"
    )
    assert authority_rows["exact OS process created/exited/reclaimed"] == (
        "Hosting Process Lifetime Host"
    )
    assert (
        "### Child Session Hosting Port" in boundary
        and "| Worker handshaken/healthy/fenced | Harness Worker protocol/supervisor |"
        in boundary
    )


def test_hosted_application_responsibilities_and_dependencies_are_separated() -> None:
    hosting_boundary = _read(HOSTED_APPLICATION_BOUNDARY)
    apphost_placement = _read(APPHOST_PLACEMENT)
    appservice_boundary = _read(APPSERVICE_BOUNDARY)
    refactor = _read(APPSERVICE_REFACTOR)

    assert (
        "This Hosting child design specifies only Hosting's black-box "
        "relationship" in hosting_boundary
    )
    assert (
        "AppServer, AppService, Product packages, and UI packages are not Hosting\nconsumers."
        in hosting_boundary
    )
    assert "AppServer -X-> Hosting" in apphost_placement
    assert "Product identity and delivery profile are orthogonal" in apphost_placement
    assert "### Multi-Aggregate Hosted Cardinality" in apphost_placement
    assert (
        "Aggregate count never creates another\nAppHost, AppServer listener, "
        "application `RunLease`, or process-level\n`RuntimeResourceOwner`"
        in apphost_placement
    )
    assert (
        "AppHost does not import an aggregate type, index its selector names"
        in apphost_placement
    )
    assert (
        "`loushang.harnesswork` is the canonical shared durable\n"
        "Work subsystem" in apphost_placement
    )
    assert (
        "`loushang.work` is only its forwarding\ncompatibility facade"
        in apphost_placement
    )
    assert "**Session Identity Envelope**" in apphost_placement
    assert "ProductIdentityRequired" in apphost_placement
    assert "external supervisor\n  -> complete foreground AppHost executable" in (
        apphost_placement
    )
    assert "  -/-> Hosting library" in apphost_placement
    assert "controller process\n  AppHost launcher" in apphost_placement
    assert "immutable executable + argv/env/profile/state references" in (
        apphost_placement
    )
    assert "target process\n  AppHost runtime/bootstrap" in apphost_placement
    assert "exposes one process-level\nreadiness and stop boundary" in (
        apphost_placement
    )
    shutdown_steps = _numbered_steps(apphost_placement, "Graceful Shutdown Protocol")
    assert shutdown_steps == (
        "mark the process `stopping`; atomically fence the active catalog "
        "generation, new bootstrap, Product resolution, live-binding attachment, "
        "and profile activation;",
        "tell AppServer to stop accepting connections and reject new request "
        "admission;",
        "tell AppServer to stop reading new frames and freeze/report connection "
        "state; it does not drain writers yet and does not decide logical detach;",
        "tell AppService to reject new Sessions, perform the sole logical detach, "
        "settle or interrupt admitted work by explicit Product policy, clean up "
        "interactions, close logical attachments, and request release through each "
        "Session-scoped Product binding's sole idempotent close port;",
        "ensure AppHost releases all remaining Product Runtime handles and admitted "
        "presentation-profile leases, then wait for dependent attachment/runtime "
        "pins to drain;",
        "close the catalog generation and every catalog-owned Product/OEM "
        "admission pin exactly once; borrowed registration sources remain owned "
        "by outer composition;",
        "drain-or-abort AppServer writers within the remaining deadline, then close "
        "transports, listener, and connection records;",
        "close the process's one `RuntimeResourceOwner` only when all dependent "
        "runtime, profile, catalog, and admission leases settled; that owner alone "
        "revokes projections, drains admitted operations, and closes its ArtifactStore "
        "and `RunLease` as one transaction; and",
        "publish `stopped` readiness and let the foreground process exit.",
    )
    assert "A phase failure is recorded but\ndoes not skip later cleanup phases" in (
        apphost_placement
    )
    assert "One monotonic deadline bounds the\nsequence" in apphost_placement
    assert "kill the owned process tree" in apphost_placement
    assert "A direct foreground AppHost force-closes its remaining local\nhandles" in (
        apphost_placement
    )
    assert "$LOUSHANG_HOME/data/sessions` authority" in apphost_placement
    assert "$LOUSHANG_HOME/data/session-assets/<session-id>`" in apphost_placement
    assert (
        "Each process resolves or receives exactly one admitted, immutable\n"
        "`PlatformPaths` at its outer composition root" in apphost_placement
    )
    assert (
        "only normalized, serialized, policy-admitted overrides,\n"
        "profile identifiers, and state references cross between them"
        in apphost_placement
    )
    assert "retains\n  at most one `RuntimeResourceOwner`" in apphost_placement
    assert "does not imply another application `RunLease`" in apphost_placement
    assert (
        "compatibility discovery/import inputs, never peer writable authorities"
        in apphost_placement
    )
    for owner_row in (
        "| unsubmitted image/prompt draft | active client/input-router draft owner |",
        "| submitted image bytes | Harness Session Blob authority |",
        "| logs, traces, diagnostics | producing observability service |",
        "| AppServer listener and transport scratch | AppServer transport |",
        "| service-instance record | future Hosting Service Instance Controller |",
    ):
        assert owner_row in apphost_placement

    responsibility_rows = {
        row[0]: (row[1], row[2])
        for row in _table_rows(
            _section(apphost_placement, "Cross-Scope Dependency And Responsibility"),
            ("Scope", "Owns", "Explicitly does not own"),
        )
    }
    assert set(responsibility_rows) == {
        "AppHost",
        "AppServer",
        "AppService",
        "Product outer integration",
        "Hosting",
        "presentation profile",
    }
    assert "AppService construction" in responsibility_rows["AppServer"][1]
    assert "logical attachment/mailbox/detach" in responsibility_rows["AppService"][0]

    resource_rows = {
        row[0]: (row[1], row[2])
        for row in _table_rows(
            _section(apphost_placement, "Machine-Resource Composition"),
            ("Resource concern", "Lifecycle owner", "Placement/composition rule"),
        )
    }
    assert resource_rows == {
        "platform roots and run-lease primitive": (
            "Foundation",
            "pure `PlatformPaths` plus Product-neutral `RuntimeScope`/`RunLease`; "
            "no Product or storage semantics",
        ),
        "shared configuration and Resource discovery": (
            "Harness configuration/resources",
            "project `.loushang` is reviewable declaration; private generated state "
            "is user-global; Product admits policy and content",
        ),
        "application-run artifacts and machine inventory": (
            "Harness `RuntimeResourceOwner`",
            "one effectful owner per application process; it alone owns the "
            "ArtifactStore/RunLease transaction and revocable projections",
        ),
        "durable Session transcripts": (
            "Harness conversation/transcript owner selected by Product",
            "canonical writable default is `$LOUSHANG_HOME/data/sessions`; "
            "compatibility roots are discovery/import inputs only",
        ),
        "durable Session Blob objects": (
            "Harness Session Blob authority",
            "canonical writable layout is "
            "`$LOUSHANG_HOME/data/session-assets/<session-id>` with immutable "
            "objects and manifest",
        ),
        "clipboard/image capture or upload": (
            "active presentation-client adapter",
            "Native TUI is Current; GUI/WebUI own browser/OS selection without "
            "transferring storage to AppHost/AppServer/Hosting",
        ),
        "unsubmitted image/prompt draft": (
            "active client/input-router draft owner",
            "bounded private client/run-local draft, removed on submit/cancel/disposal",
        ),
        "submitted image bytes": (
            "Harness Session Blob authority",
            "validate and promote before a pathless durable reference enters the "
            "transcript",
        ),
        "logs, traces, diagnostics": (
            "producing observability service",
            "bounded-retention state subdirectory; not Session content and not "
            "Hosting policy",
        ),
        "AppServer listener and transport scratch": (
            "AppServer transport",
            "listener under runtime root, atomic scratch under temporary root, one "
            "transport cleanup owner",
        ),
        "AppService live registry and snapshots": (
            "AppService",
            "live application state; durable recovery remains an explicit "
            "Product/store operation",
        ),
        "service-instance record": (
            "future Hosting Service Instance Controller",
            "narrow injected state subdirectory containing mechanism facts only; "
            "retire removes it only after the exact process tree is confirmed "
            "reaped, and cleanup failure leaves conservative residue",
        ),
    }
    assert "AppService -X-> Hosting" in appservice_boundary
    assert "Coding UI -X-> HarnessGUI / HarnessWebUI" in appservice_boundary
    assert "Harnesstui -X-> Coding" in appservice_boundary
    assert "appserver.service -X-> Hosting" in refactor
    assert "### Multi-Session Coordination Aggregates" in refactor
    assert "There is no global cross-Session revision" in refactor
    assert "per-stream sub-budgets" in refactor
    assert "### Multi-Session Coordination Aggregate" in appservice_boundary
    assert "There is no global cross-Session instant or cursor" in (appservice_boundary)
    assert "one connection to at most one active aggregate" in appservice_boundary
    assert "attempts every aggregate-owned membership, subscription, presenter" in (
        appservice_boundary
    )
    assert "never directly closes the canonical AppHost Session runtime binding" in (
        appservice_boundary
    )
    assert (
        "application aggregate identity, membership, attachment/controller state"
        in hosting_boundary
    )
    assert (
        "Running one or many application coordination aggregates does not change"
        in hosting_boundary
    )
    assert (
        "AppServer and all its subpackages must not import any Hosting package"
        in refactor
    )
    assert (
        "AppHost is the\ncomposition root: it constructs AppService, injects it "
        "into AppServer" in appservice_boundary
    )


def test_rejected_boundary_phrases_do_not_reappear() -> None:
    documents = tuple(
        _read(path)
        for path in (
            HOSTED_APPLICATION_BOUNDARY,
            APPHOST_PLACEMENT,
            APPSERVICE_BOUNDARY,
            APPSERVICE_REFACTOR,
        )
    )

    rejected_claims = (
        "AppServer daemon adapter",
        "daemon-owned hosted Session",
        "Coding / Work / PPT / Design",
        "CodingTUI / Harnesstui",
        "foreground AppServer can use Hosting",
        "foreground AppServer process hosting",
        "AppHost launcher OR external supervisor",
        "AppServer -/-> hosting.service",
        "appserver -X-> hosting.service",
        "AppServer denial of `hosting.service`",
        "construction and orderly close of one AppService",
        "AppServer | Hosted server/connection runtime that constructs AppService",
        "connection.py      # attachment",
        "each Harness application/Session run",
        "Every hosted application/Session run",
        "kill the exact process",
        "durable Session transcript and blobs |",
    )
    for text in documents:
        for claim in rejected_claims:
            assert claim not in text


def test_hosting_traceability_covers_every_requirement_exactly_once() -> None:
    requirements = _read(HOSTING_ROOT / "requirements.md")
    requirement_ids = tuple(
        re.findall(r"^### (HOST-(?:FR|QR)-\d{3}) — ", requirements, re.M)
    )
    trace_rows = _table_rows(
        _section(_read(HOSTING_ROOT / "traceability.md"), "Requirement Traceability"),
        (
            "Requirement",
            "Primary design owner",
            "Boundary/design evidence",
            "Executable evidence / remaining gate",
        ),
    )
    traced_ids = tuple(row[0].strip("`") for row in trace_rows)
    primary_owners = {row[0].strip("`"): row[1].strip("`") for row in trace_rows}

    assert len(requirement_ids) == len(set(requirement_ids)) == 12
    assert traced_ids == requirement_ids
    assert trace_rows == (
        (
            "`HOST-FR-001`",
            "`HOST-CMP-CONTRACT`",
            "requirements; H0 Contract Model",
            "H0 request validation and no-ambient-environment contract tests",
        ),
        (
            "`HOST-FR-002`",
            "`HOST-CMP-PROCESS`",
            "Process Lifetime Host; failure interaction",
            "H1 fake lifecycle matrix and H2 real process-tree conformance",
        ),
        (
            "`HOST-FR-003`",
            "`HOST-CMP-ENDPOINT`",
            "Inherited Peer Endpoint Host; physical context",
            "POSIX/Windows handle allowlist, peer closure, and leak tests",
        ),
        (
            "`HOST-FR-004`",
            "`HOST-CMP-SESSION`",
            "Child Session Host; H4 atomic transaction",
            "H4 failure matrix at every acquisition/publication boundary",
        ),
        (
            "`HOST-FR-005`",
            "`HOST-CMP-CONTRACT`",
            "authority table; H0 observation boundary",
            "H0 closed-schema, bounded-ID, and no-security-claim tests",
        ),
        (
            "`HOST-FR-006`",
            "`HOST-CMP-PLATFORM`",
            "explicit platform boundary",
            "H2 exact backend selection, atomic ownership, and unsupported-platform tests",
        ),
        (
            "`HOST-QR-001`",
            "Process, Endpoint, Session",
            "lifecycle invariants",
            "H1/H3 owner tests plus H4 joint close, cancellation, and cleanup-debt cases",
        ),
        (
            "`HOST-QR-002`",
            "Process, Endpoint, Session",
            "requirements and component interfaces",
            "H1/H3 resource bounds plus H4 aggregate capacity and factory-bound validation",
        ),
        (
            "`HOST-QR-003`",
            "Session, Platform Adapter",
            "trust boundary",
            "inherited-handle and effective-environment adversarial tests",
        ),
        (
            "`HOST-QR-004`",
            "scope/composition root",
            "[ARD-002: Hosting Top-Level Placement]"
            "(../decisions/ARD-002-hosting-top-level-placement.md) and dependency view",
            "H0 top-level standard-library-only and public-surface gates",
        ),
        (
            "`HOST-QR-005`",
            "all components",
            "discovery/refinement",
            "H1 fake process/clock/failure seams; later real conformance remains",
        ),
        (
            "`HOST-QR-006`",
            "`HOST-CMP-PLATFORM`",
            "open validation questions",
            "separate POSIX and Windows conformance manifests",
        ),
    )
    assert primary_owners == {
        "HOST-FR-001": "HOST-CMP-CONTRACT",
        "HOST-FR-002": "HOST-CMP-PROCESS",
        "HOST-FR-003": "HOST-CMP-ENDPOINT",
        "HOST-FR-004": "HOST-CMP-SESSION",
        "HOST-FR-005": "HOST-CMP-CONTRACT",
        "HOST-FR-006": "HOST-CMP-PLATFORM",
        "HOST-QR-001": "Process, Endpoint, Session",
        "HOST-QR-002": "Process, Endpoint, Session",
        "HOST-QR-003": "Session, Platform Adapter",
        "HOST-QR-004": "scope/composition root",
        "HOST-QR-005": "all components",
        "HOST-QR-006": "HOST-CMP-PLATFORM",
    }
    qr004 = next(row for row in trace_rows if row[0] == "`HOST-QR-004`")
    assert (
        "[ARD-002: Hosting Top-Level Placement]"
        "(../decisions/ARD-002-hosting-top-level-placement.md)" in (qr004[2])
    )


def test_hosting_discovery_is_grounded_in_current_harness_facts() -> None:
    discovery = _read(HOSTING_ROOT / "validation/component-discovery.md")

    for relative_path in CURRENT_HARNESS_SEAMS:
        assert (REPOSITORY_ROOT / relative_path).is_file(), relative_path

    for current_owner in (
        "harness.workspace.process",
        "harness.tools.process_hosting",
        "harness.sandbox.process",
        "harness.worker",
    ):
        assert current_owner in discovery


def test_hosting_and_apphost_contracts_keep_future_runtime_packages_dark() -> None:
    assert (REPOSITORY_ROOT / "src/loushang/hosting").is_dir()
    apphost = REPOSITORY_ROOT / "src/loushang/apphost"
    assert {
        path.relative_to(apphost).as_posix() for path in apphost.rglob("*.py")
    } == {
        "__init__.py",
        "_ownership.py",
        "catalog.py",
        "contracts.py",
        "errors.py",
        "integrations/__init__.py",
        "integrations/harness_session.py",
        "router.py",
    }
    assert not (REPOSITORY_ROOT / "src/loushang/appserver").exists()

    overview = _read(HOSTING_ROOT / "README.md")
    decision = _read(HOSTING_PLACEMENT)
    assert "Implementation status: partial" in overview
    assert "This decision is accepted for phased implementation." in decision
    assert "H0 updates the Loushang AOD" in decision
    assert "extraction alone cannot remove PLC9C default-dark" in decision
