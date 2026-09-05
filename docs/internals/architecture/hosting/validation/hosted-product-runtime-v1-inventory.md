# Hosted Product Runtime V1 Current Inventory

## Status

- ID: `HOSTED-PRODUCT-V1-INVENTORY`
- Scope: `hosting / AppHost / Harness Worker`
- Parent: `loushang`
- Authority: descriptive — source-backed Current inventory
- Design status: not-applicable
- Implementation status: not-applicable
- Delivery parent: `c3fca03c`
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
| private H6.2 Linux x86_64 preparation | `src/loushang/hosting/_posix_launch_preparation.py` and `src/loushang/hosting/_posix_process.py` | sealed static launcher/payload, retained cwd, closed invocation/profile identity, exact endpoint-plus-preparation descriptor manifest, and conservative post-effect fencing; private and default-dark |
| private H6.3/C5.3 Windows AMD64 preparation | `src/loushang/hosting/_windows_launch_preparation.py`, `src/loushang/hosting/_windows_process.py`, and `src/loushang/hosting/_win32_process.py` | Hosting-private OS-sourced trusted-payload builder, locked PE/cwd/ancestor identity, fixed restricted token, atomic Job, strict handle list, bounded direct-import mechanics, and exact native settlement; private and default-dark; explicitly rejected as Product required containment |
| restrained composition | `src/loushang/hosting/runtime.py` | `create_process_host` and `create_child_session_host`; no public backend/plugin registry |

The stable public owners are implemented through H5; H6.1 through H6.3 add a
private transaction core and exact Linux/Windows native profiles, and H6.4
preserves that private seam through the Harness Worker adapter. They expose no
native executable/cwd/containment material in the public request, preparation
lease, or factory.

## Current Harness Preparation And Worker Owners

| Current owner | Exact source | Observed responsibility and limit |
| --- | --- | --- |
| managed Worker binding | `src/loushang/harness/worker/contracts.py` and `src/loushang/harness/worker/launch.py` | validates exact Plugin/runtime identity and captures the executable/cwd before entering the Current managed Process path |
| Linux sealed launch material | `src/loushang/harness/workspace/process/_sealed_executable.py` | private `_SealedProcessExecutable`, `_BoundProcessDirectory`, request subtype, and inherited fd extraction; depends on Linux/POSIX descriptor mechanics |
| Process/Sandbox launch owner | `src/loushang/harness/tools/process_hosting.py` | mandatory authority plus owner-minted managed request and private Process launch composition |
| containment planner | `src/loushang/harness/sandbox/process.py`, `src/loushang/harness/sandbox/runtime.py`, and `src/loushang/harness/sandbox/backends/linux.py` | Sandbox-owner-bound required-containment plan and Linux hosted-process plan |
| Current Process Host | `src/loushang/harness/workspace/process/host.py` and `src/loushang/harness/workspace/process/local.py` | consumes the private contained request and owns current process lifetime |
| Hosting compatibility refusal | `src/loushang/harness/workspace/process/hosting_compat.py` | maps representable requests but explicitly rejects inherited sealed-executable/bound-cwd descriptors |
| H5/H6.4 Worker adapter | `src/loushang/harness/worker/hosting_adapter.py` | maps one exact Worker request to `ChildSessionRequest`, rechecks caller evidence, and preserves an injected nominal managed-preparation port; cannot manufacture native preparation material or select a profile |
| H5 owner selector | `src/loushang/harness/worker/owner_selection.py` | explicit typed Current/Hosting route with default `owner="current"`, no environment activation, no same-attempt fallback |
| Worker protocol/lifecycle | `src/loushang/harness/worker/protocol.py`, `src/loushang/harness/worker/supervisor.py`, `src/loushang/harness/worker/journal.py`, and `src/loushang/harness/worker/session.py` | framing, handshake, correlation, heartbeat, restart/fencing, aggregate session, and durable attempt evidence |
| first domain adapter | `src/loushang/harness/worker/capability_query.py` | explicitly enabled read-only Capability query adapter; no Product activation or generation publication route |
| Session discovery contracts | `src/loushang/harness/transcript/discovery.py` and `src/loushang/harness/transcript/session_catalog.py` | canonical/compatibility source identity, stable locator, bounded summaries, aliases/conflicts, and multi-source read model; no generic `product_id` envelope yet |
| optional AppHost/Harness Session integration | `src/loushang/apphost/integrations/harness_session.py` | AppHost-owned optional projection of explicitly injected Harness source identities to path-free migration candidates; seals an unchanged single-descriptor snapshot up to 8 MiB, adopts rejected canonical returns into its own retryable cleanup lifecycle, bounds canonical delegation to eight concurrent calls and refuses new calls while debt remains, never retries a relinquished POSIX fd number after an ambiguous close, derives no roots or second index, remains uncomposed, and fails closed on Windows pending a native retained-handle backend |
| AppHost live binding owner | `src/loushang/apphost/runtime.py` | process-local single-flight Product/runtime binding keyed by canonical Session identity, exact retained catalog generation, per-profile attachment lifetime, admission fencing, retryable dependency-ordered close, and bounded phased shutdown; remains explicitly constructed and uncomposed |
| optional AppHost/AppServer binder | `src/loushang/apphost/hosted.py` | validates one explicitly selected profile as an exact AppServer structural port bundle and preserves the canonical binding identity; owns no listener, protocol, transport, or service semantics |
| AppServer Product ports | `src/loushang/appserver/ports.py` | immutable contract-only identity and Product-supplied Session/projection/work/interaction port bundle; no runtime, listener, protocol, or composition owner |
| Session discovery composition | `src/loushang/harness/transcript/directory.py`, `src/loushang/harness/machine_resources/control_plane.py`, and `src/loushang/coding/cli/__main__.py` | canonical global plus cwd/home compatibility sources are selected at composition; cwd is a query/filter and compatibility roots are not writable authorities |

## Observed Contract Mismatch

| Boundary | Producer shape | Consumer shape | Current result |
| --- | --- | --- | --- |
| executable/cwd | Harness private request retains native descriptors plus identity | Hosting `ProcessLaunchRequest` contains absolute strings | `hosting_compat` fails closed rather than substitute mutable paths |
| containment | Harness `ProcessContainmentPlan` may rewrite the exact process request and owns semantic evidence | Hosting's public preparation lease exposes only `request`, `verify_current`, and `close`; H6 adds a private managed capture | C5.2 supplies one default-dark Linux contained-profile adapter through the H6.4 seam; no Product composition selects it |
| inherited resources | Harness Current path extracts private launch descriptors | H6.1 combines endpoint and opaque preparation inheritance internally; H6.2/H6.3 supply exact platform-private material | H6.4 can preserve an injected managed port, but no composition currently supplies either native profile for a Worker |
| Windows required containment | PLC9B includes a purpose-specific AppContainer/Job implementation for legacy restore | Hosting H6.3 owns one narrower restricted-token/locked-PE profile | the managed semantic bridge exists, but no AppContainer equivalence, eligible Worker profile supplier, or native parity claim exists |
| Product activation | PLC9C1--C4 provide declaration, launch, supervisor, and one dark domain adapter | H5 provides an explicit dark Hosting owner | no Product composition selects and publishes the native path |

## AppHost And Hosted Application State

AppHost A0.4 now supplies immutable standard-library contracts, admitted
catalog generations, explicit candidate routing, one process-local live-binding
registry, embedded profile attachments, and an optional contract-only AppServer
port binder. There is still:

- no AppHost production composition or launcher;
- no AppServer listener, transport, protocol, or application-service runtime;
- `src/loushang/appservice` is absent.
- the generic Session Identity Envelope contract is not yet persisted or read
  before Product selection;
- the optional AppHost-owned Harness integration exposes current JSONL only as explicit migration
  candidates; no canonical envelope persistence owner is composed;
- no production launcher sends a complete foreground AppHost executable to
  Hosting.

The accepted AppHost architecture now has executable A0.3/A0.4 lifecycle and
wiring evidence. AppServer runtime and AppService remain Target boundaries,
not implemented routes.

## Current-To-Target Delta

| Gap | Target owner | Closure gate |
| --- | --- | --- |
| opaque request-bound native preparation | Hosting Contract/Platform components | implemented privately in H6.1; fake ownership, concurrency/fault, and no-raw-handle gates are retained |
| exact Linux executable/cwd/containment transfer | Hosting platform adapter with caller-owned requirements | implemented for the private static-closure profiles; H6.2 retained native adversarial oracle remains green |
| exact Windows executable/cwd/containment transfer | Hosting platform adapter with caller-owned requirements | implemented for one private restricted-token/direct-import PE mechanics profile; the non-skippable H6.3 native adversarial oracle must remain green |
| Harness-to-Hosting managed preparation parity | Harness Sandbox/Worker adapter over Hosting | H6.4 fake-backed public/managed semantic and cleanup parity; native Worker compatibility remains absent and default stays Current |
| Product catalog, no-default routing, scoped runtime lifetime | AppHost | implemented through A0.3: the Router-private admission seam feeds one canonical live binding, exact generation retention, per-profile attachments, and bounded retryable shutdown; production composition remains absent |
| Session pre-routing identity | AppHost schema plus canonical Session persistence/catalog owner | A0.2 fake owner proves atomic creation/recovery; real canonical envelope persistence remains uncomposed |
| AppHost cwd/user-global Session projection | AppHost-owned optional integration over the existing Harness Session discovery/catalog owner | A0.2 proves explicit source binding, stable source identity, alias/conflict, an unchanged bounded descriptor read sealed into immutable bytes, no token-to-path behavior, and Windows fail-closed semantics |
| Product/native Worker activation | Product/Harness composition and domain owner | separately reviewed PLC9C5 canary, native gates, recovery, and rollback |
| hosted App protocol and semantics | future AppServer/AppService scopes | A0.4 supplies only the optional exact port-bundle binder and contract package; listener, transport, protocol, service semantics, and production composition remain separate |

## Retained Fences

The inventory records, rather than relaxes, these Current fences:

- H5 default owner is Current and a selected owner never falls back during an
  attempt;
- sealed-descriptor cases remain rejected by Hosting compatibility;
- PLC9C5 C5.0 design/inventory, C5.1 receipt/lifecycle, C5.2 Linux profile,
  and C5.3 Windows mechanics/rejection are implemented, but Product activation
  and unsupported-platform guards remain unchanged;
- AppHost A0.4 remains explicitly constructed and dark: its core runtime owns
  live bindings, while optional Harness Session and AppServer port adapters stay
  outside the core facade; AppServer contains contracts only, AppService remains
  absent, and no production composition imports either optional adapter; and
- Hosting imports no Harness, Product, AppHost, AppServer, or AppService
  package.

Any change that invalidates a row must update this inventory, the owning scope
document, and executable guard in the same delivery slice.
