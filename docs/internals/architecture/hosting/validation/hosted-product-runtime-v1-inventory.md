# Hosted Product Runtime V1 Current Inventory

## Status

- ID: `HOSTED-PRODUCT-V1-INVENTORY`
- Scope: `hosting / AppHost / Harness Worker`
- Parent: `loushang`
- Authority: descriptive — source-backed Current inventory
- Design status: not-applicable
- Implementation status: not-applicable
- Delivery parent: `82df045d`
- Effect: none; this record grants no runtime or activation authority
- Owner: Loushang architecture

## Reading Rule

This is an observed Current inventory for the H6/AppHost/PLC9C5 boundary.
Source and executable tests remain higher authority. Proposed responsibilities
are recorded in the H6 and AppHost documents and must not be read back into
this inventory as implemented facts.

## Implemented Hosting Owners

| Current owner | Exact source | Observed responsibility |
| --- | --- | --- |
| public Contract Model | `src/loushang/hosting/contracts.py`, `src/loushang/hosting/errors.py`, and `src/loushang/hosting/__init__.py` | immutable string-based process/session requests, leases, stable failures, bounded observations, and required/provided ports |
| Process Lifetime Host | `src/loushang/hosting/_process_host.py` and `src/loushang/hosting/_process_backend.py` | capacity, preparation transaction, spawn attachment, streams, exit convergence, termination, and cleanup over a private backend |
| platform process adapters | `src/loushang/hosting/_posix_process.py`, `src/loushang/hosting/_windows_process.py`, and `src/loushang/hosting/_win32_process.py` | POSIX process-group and Windows Job Object creation/ownership mechanics |
| Inherited Peer Endpoint Host | `src/loushang/hosting/_endpoint_host.py`, `src/loushang/hosting/_endpoint_backend.py`, `src/loushang/hosting/_posix_endpoint.py`, and `src/loushang/hosting/_windows_endpoint.py` | bounded anonymous endpoint pair, strict child-side inheritance, raw byte transport, and cleanup |
| Child Session Host | `src/loushang/hosting/_child_session_host.py` | atomic endpoint-plus-process acquisition/publication and joint close |
| private H6.1 launch preparation | `src/loushang/hosting/_launch_preparation.py` | request/profile/closure plus unforgeable attempt binding, opaque capture, final verification, matched-backend spawn, explicit fencing, and ordered cleanup; fake-backed and default-dark only |
| restrained composition | `src/loushang/hosting/runtime.py` | `create_process_host` and `create_child_session_host`; no public backend/plugin registry |

The stable public owners are implemented through H5; H6.1 adds only a private
fake-backed transaction core. They expose no native executable/cwd/containment
material in the public request, preparation lease, or factory.

## Current Harness Preparation And Worker Owners

| Current owner | Exact source | Observed responsibility and limit |
| --- | --- | --- |
| managed Worker binding | `src/loushang/harness/worker/contracts.py` and `src/loushang/harness/worker/launch.py` | validates exact Plugin/runtime identity and captures the executable/cwd before entering the Current managed Process path |
| Linux sealed launch material | `src/loushang/harness/workspace/process/_sealed_executable.py` | private `_SealedProcessExecutable`, `_BoundProcessDirectory`, request subtype, and inherited fd extraction; depends on Linux/POSIX descriptor mechanics |
| Process/Sandbox launch owner | `src/loushang/harness/tools/process_hosting.py` | mandatory authority plus owner-minted managed request and private Process launch composition |
| containment planner | `src/loushang/harness/sandbox/process.py`, `src/loushang/harness/sandbox/runtime.py`, and `src/loushang/harness/sandbox/backends/linux.py` | Sandbox-owner-bound required-containment plan and Linux hosted-process plan |
| Current Process Host | `src/loushang/harness/workspace/process/host.py` and `src/loushang/harness/workspace/process/local.py` | consumes the private contained request and owns current process lifetime |
| Hosting compatibility refusal | `src/loushang/harness/workspace/process/hosting_compat.py` | maps representable requests but explicitly rejects inherited sealed-executable/bound-cwd descriptors |
| H5 Worker adapter | `src/loushang/harness/worker/hosting_adapter.py` | maps one exact Worker request to `ChildSessionRequest` and rechecks caller evidence; cannot manufacture native preparation material |
| H5 owner selector | `src/loushang/harness/worker/owner_selection.py` | explicit typed Current/Hosting route with default `owner="current"`, no environment activation, no same-attempt fallback |
| Worker protocol/lifecycle | `src/loushang/harness/worker/protocol.py`, `src/loushang/harness/worker/supervisor.py`, `src/loushang/harness/worker/journal.py`, and `src/loushang/harness/worker/session.py` | framing, handshake, correlation, heartbeat, restart/fencing, aggregate session, and durable attempt evidence |
| first domain adapter | `src/loushang/harness/worker/capability_query.py` | explicitly enabled read-only Capability query adapter; no Product activation or generation publication route |
| Session discovery contracts | `src/loushang/harness/transcript/discovery.py` and `src/loushang/harness/transcript/session_catalog.py` | canonical/compatibility source identity, stable locator, bounded summaries, aliases/conflicts, and multi-source read model; no generic `product_id` envelope yet |
| Session discovery composition | `src/loushang/harness/transcript/directory.py`, `src/loushang/harness/machine_resources/control_plane.py`, and `src/loushang/coding/cli/__main__.py` | canonical global plus cwd/home compatibility sources are selected at composition; cwd is a query/filter and compatibility roots are not writable authorities |

## Observed Contract Mismatch

| Boundary | Producer shape | Consumer shape | Current result |
| --- | --- | --- | --- |
| executable/cwd | Harness private request retains native descriptors plus identity | Hosting `ProcessLaunchRequest` contains absolute strings | `hosting_compat` fails closed rather than substitute mutable paths |
| containment | Harness `ProcessContainmentPlan` may rewrite the exact process request and owns semantic evidence | Hosting preparation lease exposes only `request`, `verify_current`, and `close` | lifecycle can be delegated, but native spawn material cannot be consumed |
| inherited resources | Harness Current path extracts private launch descriptors | H6.1 can combine endpoint and opaque preparation inheritance internally | the fake-backed protocol exists, but no Harness or native adapter supplies material |
| Windows required containment | PLC9B includes a purpose-specific AppContainer/Job implementation for legacy restore | Hosting owns generic Job/endpoint mechanics | no accepted managed Worker preparation adapter or parity claim |
| Product activation | PLC9C1--C4 provide declaration, launch, supervisor, and one dark domain adapter | H5 provides an explicit dark Hosting owner | no Product composition selects and publishes the native path |

## AppHost And Hosted Application Absences

- `src/loushang/apphost` is absent.
- `src/loushang/appserver` is absent.
- `src/loushang/appservice` is absent.
- no immutable cross-Product catalog/router or scoped Product Runtime handle
  contract exists;
- no generic Session Identity Envelope is persisted and read before Product
  selection;
- no path-free AppHost port projects the existing Product-neutral Harness
  Session discovery read model together with a pre-routing `product_id`;
- no two-unrelated-Product conformance fixture exists; and
- no production launcher sends a complete foreground AppHost executable to
  Hosting.

The AppHost, AppServer, and AppService architecture drafts are Target inputs,
not evidence of those packages or runtime routes.

## Current-To-Target Delta

| Gap | Target owner | Closure gate |
| --- | --- | --- |
| opaque request-bound native preparation | Hosting Contract/Platform components | implemented privately in H6.1; fake ownership, concurrency/fault, and no-raw-handle gates are retained |
| exact Linux executable/cwd/containment transfer | Hosting platform adapter with caller-owned requirements | H6.2 retained native adversarial oracle |
| exact Windows executable/cwd/containment transfer | Hosting platform adapter with caller-owned requirements | H6.3 retained native adversarial oracle |
| Harness-to-Hosting managed preparation parity | Harness Sandbox/Worker adapter over Hosting | H6.4 independent Current/Hosting parity; still default-dark |
| Product catalog, no-default routing, scoped runtime lifetime | proposed AppHost | A0 contracts and two-unrelated-fake-Product conformance |
| Session pre-routing identity | proposed AppHost schema plus canonical Session persistence/catalog owner | atomic envelope creation/resume/migration tests before Product parsing |
| AppHost cwd/user-global Session projection | adapter over the existing Harness Session discovery/catalog owner | explicit-scope listing, stable source identity, exact alias/conflict behavior, Product envelope, and no-direct-filesystem tests |
| Product/native Worker activation | Product/Harness composition and domain owner | separately reviewed PLC9C5 canary, native gates, recovery, and rollback |
| hosted App protocol and semantics | future AppServer/AppService scopes | separate accepted contracts; not implied by AppHost or Hosting work |

## Retained Fences

The inventory records, rather than relaxes, these Current fences:

- H5 default owner is Current and a selected owner never falls back during an
  attempt;
- sealed-descriptor cases remain rejected by Hosting compatibility;
- PLC9C5 Product activation and platform absence guards remain unchanged;
- AppHost/AppServer/AppService source packages remain absent; and
- Hosting imports no Harness, Product, AppHost, AppServer, or AppService
  package.

Any change that invalidates a row must update this inventory, the owning scope
document, and executable guard in the same delivery slice.
