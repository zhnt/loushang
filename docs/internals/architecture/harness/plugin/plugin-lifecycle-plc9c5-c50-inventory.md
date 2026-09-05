# PLC9C5 Current Product/Native Worker Inventory

## Status

- ID: `PLC9C5-C5.0-INVENTORY`
- Scope: `Product / Harness Worker / Hosting / Session`
- Parent: `PLC9C5-C5.0`
- Authority: descriptive — source-backed Current inventory
- Design status: not-applicable
- Implementation status: not-applicable
- Observation base: C5.2 implementation candidate based on `cda62364`
- Effect: none; this inventory grants no runtime or activation authority
- Owner: Harness Worker architecture

## Reading Rule

This inventory records Current facts at the observation base and the exact C5.1
and C5.2 transitions. Source and executable tests remain higher authority.
Names owned by C5.3--C5.4 remain proposals. A source row records the narrow seam needed to
reason about C5; it does not transfer authority to Product or Plugin management.

## Exact Current Source Set

| ID | Exact source | Current fact | C5 disposition |
| --- | --- | --- | --- |
| `C5-CUR-DECL` | `src/loushang/harness/resources/plugins/declarations.py` and `src/loushang/harness/resources/plugins/selection.py` | versioned inert `local_worker` declaration/selection exists for `capability_provider`; declared required/optional and exact Worker configuration are data only | retain; Product must rejoin the exact selected reservation and immutable revision before a receipt and cannot downgrade declared requiredness |
| `C5-CUR-PRODUCT-CORE` | `src/loushang/harness/session/bootstrap_construction.py` and `src/loushang/harness/session/agent_product.py` | one Product-bound Agent Session construction path exists; it owns Product callbacks and final Session assembly but has no Worker activation input | reuse as the shared canary-capable construction boundary; do not put activation in presenters |
| `C5-CUR-CODING-PRODUCT` | `src/loushang/coding/bootstrap.py` and `src/loushang/coding/cli/__main__.py` | Coding supplies an explicit `product_id` and converges ordinary Agent/TUI/RPC/channel/plain/workflow modes through one runtime builder; early-dispatch workspace/LSP/multiagent routes are separate | first Product evidence only; C5.4 must inventory exact canary-capable callers and keep every excluded route dark |
| `C5-CUR-PACKAGE-PRODUCT` | `src/loushang/harness/resources/packages/product_contract.py`, `src/loushang/harness/resources/packages/product_runtime.py`, `src/loushang/harness/resources/packages/product_activation.py`, and `src/loushang/harness/resources/packages/product_composition.py` | PLC9A2 owns Package lifecycle routing for CLI/RPC/Session/startup/operations; it is not a generic Product catalog and contains no Worker authority | retain as Product composition precedent; do not extend its Package-specific receipt into Worker activation |
| `C5-CUR-SESSION-PROFILE` | `src/loushang/harness/transcript/runtime_profile.py` and `src/loushang/coding/session_manager.py` | Coding persists a Product-bound runtime profile and refuses foreign Product profile snapshots on restore | reuse for the Coding-specific G7 resume row after locator selection; do not claim generic AppHost pre-routing identity |
| `C5-CUR-SESSION-DISCOVERY` | `src/loushang/harness/transcript/discovery.py`, `src/loushang/harness/transcript/directory.py`, `src/loushang/harness/transcript/session_catalog.py`, and `src/loushang/harness/machine_resources/control_plane.py` | canonical global plus cwd/home compatibility sources have stable source/locator, alias/conflict, and read-only projection semantics | retain; discovery selects a candidate and grants no Worker/Product authority |
| `C5-CUR-WORKER-PUBLIC` | `src/loushang/harness/worker/__init__.py` | public Worker contracts export launch/session/supervisor, owner selection, H6.4 adapter, C4 query-adapter mechanics, exactly three C5.1 policy/receipt/authority contracts, and the single C5.2 `ProductWorkerNativeProfilePort` | freeze the exact Current `__all__`; private coordinator/cleanup/status/bridge/platform types remain unexported |
| `C5-C51-RECEIPT-LIFECYCLE` | `src/loushang/harness/worker/product_activation.py` | strict pathless policy/receipt codec, statically bound synchronous Product-owned freshness gate, coordinator-wide callback reentry fence, deterministic CAS aggregate, closed monotonic attempt phases, sticky active registry, exact publication/retirement, durable restart policy plus pinned evidence-authority identity/fingerprint, two-phase retryable kill latch, retryable idempotent gate release, trusted cleanup settlement/debt, and exact registered-orphan no-effect recovery exist without a production consumer | retain as Product-neutral internal C5.1 aggregate; evidence authority is construction-pinned and record APIs accept only opaque witnesses; C5.2 may inject Linux native evidence but cannot add Product composition |
| `C5-C52-LINUX-NATIVE` | `src/loushang/harness/worker/_native_profile_bridge.py` | one request-bound, single-use, pathless Linux contained-profile capability rejoins the C5.1 receipt to the exact Worker request, binds the static launcher digest and containment-profile digest, rejects WSL/unknown/non-x86 before lazily loading the two accepted private H6 POSIX symbols, and records policy/execution closure fingerprints | implemented and default-dark; no Product composition constructs it, Windows dispatch is absent, and Hosting retains all raw native material |
| `C5-CUR-WORKER-IDENTITY` | `src/loushang/harness/worker/contracts.py` | launch identity binds Plugin revision/contribution/Product/scope/generation/attempt; runtime binding captures executable digest and generic filesystem stat identity | retain; C5 receipt must bind this identity, while Windows native identity remains a separate gap |
| `C5-CUR-CURRENT-LAUNCH` | `src/loushang/harness/worker/launch.py` and `src/loushang/harness/sandbox/runtime.py` | Process/Sandbox composition privately mints the Current managed Worker launch capability with required containment | retain through rollback; Sandbox is the only non-Worker production importer of the Worker launch capability |
| `C5-CUR-WORKER-SESSION` | `src/loushang/harness/worker/session.py`, `src/loushang/harness/worker/protocol.py`, `src/loushang/harness/worker/supervisor.py`, and `src/loushang/harness/worker/journal.py` | atomic session abstraction, bounded protocol, health/fencing, and durable protocol-attempt phase evidence exist over injected launch/transport owners; the journal has no receipt, OS-tree owner, boot identity, or cleanup-settlement witness | retain as mechanism; a terminal protocol phase is not resource settlement and none may select Product policy or publish a domain generation |
| `C5-CUR-DOMAIN-CANARY` | `src/loushang/harness/worker/capability_query.py` | one read-only Capability adapter exists behind `enabled=False`, rechecks exact authority, and publishes nothing | retain as the only C5 canary domain; no other domain or effectful operation enters C5 |
| `C5-CUR-DOMAIN-GENERATION` | `src/loushang/harness/capabilities/component_host.py`, `src/loushang/harness/capabilities/owner_component_host.py`, and `src/loushang/harness/capabilities/component_runtime.py` | Capability hosts prepare exact bindings without publication; the owner component runtime/binder alone owns atomic generation publication and retirement | retain as the sole domain writer; C5.4 may delegate to it only after receipt, handshake, and domain admission all remain current |
| `C5-CUR-HOSTING-BRIDGE` | `src/loushang/harness/worker/hosting_adapter.py` and `src/loushang/harness/worker/owner_selection.py` | H6.4 preserves injected managed preparation; C5.2 admits the pathless native-profile port through the same adapter-owned private H6 seam; H5 selects Current by default and never falls back within an attempt | retain; `hosting_adapter.py` constructs no platform spec and the single private bridge owns Linux profile mapping |
| `C5-CUR-H6-CORE` | `src/loushang/hosting/_launch_preparation.py` and `src/loushang/hosting/_child_session_host.py` | H6 owns request-bound one-use opaque preparation and atomic process/endpoint lifetime | consume through the confined friend seam only; no Product vocabulary or raw material crosses the boundary |
| `C5-CUR-H6-LINUX` | `src/loushang/hosting/_posix_launch_preparation.py` and `src/loushang/hosting/_posix_process.py` | Linux x86_64 has private direct and contained static-ELF profiles with retained native evidence, but the selector currently accepts WSL when memfd/proc checks pass | C5.2 may use only the contained profile after Product closure admission and a separate non-WSL exact classifier succeeds |
| `C5-CUR-H6-WINDOWS` | `src/loushang/hosting/_windows_launch_preparation.py`, `src/loushang/hosting/_windows_process.py`, and `src/loushang/hosting/_win32_process.py` | Windows AMD64 has one private restricted-token/direct-import profile and Job/handle-list process mechanics; it is trusted-payload mechanics, not accepted Product required containment | C5.3 retains the oracle and proves Product rejection; it must not enable Windows Product activation |

The exact source set above is executable inventory. Proposed later C5 files are
not added until their owning guard transition lands.

## Current Composition And Absence Facts

- `SandboxExecutionRuntime` is the only non-Worker production source importing
  the existing Worker launch capability.
- No non-Worker production source names `HostingManagedWorkerSessionAdapter`,
  `WorkerHostingActivationV1`, `WorkerSessionOwnerRouter`, or
  `bind_capability_query_worker_adapter`.
- Coding source imports no Harness Worker or Hosting implementation.
- H6 private Windows profile specifications remain confined to Hosting. The
  single C5.2 bridge lazily imports only the accepted POSIX contained spec and
  capture backend; the only non-Hosting private H6 preparation import remains
  the reviewed H6.4 Worker adapter.
- `WorkerHostingActivationV1.owner` defaults to `"current"`; selection reads no
  environment and one attempt calls exactly one selected owner.
- Product Worker C5.1 contracts and the C5.2 Linux profile capability exist
  only inside Worker. The retained Linux native report is implemented, but no
  production allowlist/issuer/state store, Product consumer, or cross-entrypoint
  receipt report exists.
- `remote_service` remains absent from the declaration/runtime topology and the
  public author SDK has no Worker runtime owner.

## Current Shape Mismatches

| Boundary | Current producer | Current consumer | Current result |
| --- | --- | --- | --- |
| Product selection | Coding Product identity and inert Plugin selection | H5 accepts only a typed Current/Hosting owner input | no versioned Product decision joins the exact contribution to the owner selection |
| activation evidence | C5.1 defines strict pathless policy/receipt evidence; H5 selection and launch evidence remain separate mechanics | a future Product issuer and production composition | contract exists but no Product emits or consumes it |
| Linux contained profile | C5.2 rejoins the Worker payload digest, retained cwd identity, trusted launcher/profile digests, receipt catalog, and same-domain policy closure | H6.2 contained spec consumes the exact closed invocation after a non-WSL Linux x86_64 gate | implemented behind a single-use default-dark port; no Product composition exists |
| Windows identity | Worker runtime records executable digest and generic `st_dev/st_ino` fields | H6.3 requires locked volume/file identities for executable, cwd, and ancestors | no accepted identity adapter exists |
| Windows request | H6.4 Worker mapping uses an empty environment and piped stderr; the H6.3 native fixture reads ambient `os.environ["SystemRoot"]` | H6.3 requires one absolute `SystemRoot` environment entry and discarded stderr | the exact requests are incompatible; C5.3 needs a Hosting-private `GetWindowsDirectoryW` source that ignores ambient poisoning and rejects caller environment |
| Windows containment meaning | Product requires accepted required containment | H6.3 proves restricted-token/Job/direct-import mechanics, not AppContainer equivalence or full loader closure | current profile is explicitly rejected for Product required containment; Windows canary is deferred |
| restart settlement | C5.1 joins protocol terminal, exact domain retirement, durable complete-tree settlement/debt, host/boot identity, restart budget, and construction-pinned evidence identity; C5.2 retains Linux same-boot debt and changed-boot absence evidence | C5.3 platform settlement evidence and C5.4 Product recovery | Linux native evidence exists, but no production recovery route exists |
| kill-switch admission | C5.1 serializes receipt admission, first-effect registration, publication, latch generation, and the complete fake active registry; every gate first drains only shared authority-domain `release_due` debt and registers a non-drainable `reserved` exit before ambiguous entry | C5.4 Product/domain owners | deterministic contract covers live reserved/held races and release faults after CAS or before admission return; no production activation gate is composed |
| Session resume | discovery yields canonical/compatibility locator facts; Coding later validates its Product runtime snapshot | G7 needs Product identity and an opaque exact source/locator/revision fingerprint fixed before issuing a Worker receipt | no common operation currently binds selected locator revision to Worker activation |
| entrypoints | ordinary Coding Agent modes converge through shared construction, while early subcommands dispatch separately | G7 requires one receipt across every canary-capable Product entrypoint | no Worker receipt is passed anywhere; excluded early routes are not explicitly frozen yet |
| rollback | H5 retains future Current selection; C5.1 latch stales future Hosting admission and enumerates sticky attempts | C5.4 Product readiness plus native/domain termination owners | lifecycle aggregate exists; ordered production rollback remains absent |

## Current-To-Target Closure Ledger

| Gap | Target sole writer | First permitted slice | Completion evidence |
| --- | --- | --- | --- |
| explicit allowlist and required/optional decision | exact Product adapter | C5.1 | deterministic missing/wrong/disabled/stale policy tests |
| pathless activation receipt schema/freshness | Harness Worker contract, value issued by Product | C5.1 | canonical same-domain expected/realized policy closure plus separate full execution-closure evidence, strict version/field/fingerprint, and pre-acquire/pre-publication current-witness tests |
| serialized admission and active-attempt registry | Harness Worker coordinator over weak shared owner-domain capabilities | C5.1 | owner-snapshot/rollback race, durable restart-latch, `releasing` fail-fast plus later `release_due` fault takeover, all-domain callback fencing, and disjoint-owner parallel tests |
| durable cleanup settlement/debt | Harness Worker contract over injected owner evidence | C5.1 fake; C5.2/C5.3 platform evidence | protocol-terminal/domain-retired/tree-settled CAS, same-boot unknown debt, and changed-boot absence tests |
| Product readiness/rollback aggregate | exact Product/domain owner over injected Worker status | C5.1 fake, C5.4 production | atomic pre-publication witness+CAS under the admission gate, kill-switch-before-publish no-visibility race, exact-generation retirement CAS, required/optional, ordered kill-switch, and cleanup-debt tests |
| Linux contained native binding | the single private `_native_profile_bridge.py` plus Hosting | C5.2 | retained nonskipped Linux report with WSL/unknown rejection and execution-closure evidence |
| Windows restricted mechanics rejection | Hosting-private trusted-payload builder; the Harness bridge boundary remains closed to Windows private imports | C5.3 | `GetWindowsDirectoryW` trust, ambient poisoning/caller-environment rejection, discarded stderr, retained mechanics report, and Product required-containment rejection |
| Coding Product composition | Coding Product root | C5.4 only | exact allowlist route plus negative side-effect tests |
| Session/entrypoint convergence | Coding Product construction and Session identity owners | C5.4 | canonical/cwd/home, alias/conflict/tamper, and shared receipt report |
| recovery/rollback drill | Product/domain, Worker supervisor, Process/Hosting owners each settle their own state | C5.4 | latch-first, fence/revoke/drain, tree settlement/debt, readiness settlement, then new-Current receipt; prior-absent/reaped/uncertain/exhausted/host-restart evidence |

The first five rows have their C5.1 contract/fake evidence implemented by the
required `PLC9C5-C5.1-CONTRACT` report. That evidence does not close their later
native or production portions.

## Retained Deletion Fences

Until G9 separately accepts owner removal, C5 work must retain:

- the exact Current Worker `__all__` public surface, with only the explicitly
  named per-slice additions allowed;
- Current `ManagedWorkerLaunchPort` and its Process/Sandbox composition;
- `WorkerSessionOwnerRouter.rollback_to_current()` and direct no-fallback start;
- `WorkerSupervisor` protocol health, durable journal, fence, and ordered
  shutdown behavior;
- the C4 read-only Capability adapter and exact Capability generation owner;
- H6 Linux/Windows private profiles, process backends, Child Session owner, and
  retained native oracles;
- Session canonical/compatibility discovery and Coding Product-profile restore
  validation; and
- the H5/H6.4 default-dark tests and architecture import guards.

Deleting a source because a new path exists, changing a default, weakening a
native report to optional/skip, or removing a guard in an earlier slice is an
architecture failure. C5.4 success permits one explicit canary; it does not by
itself prove the Current owner unused.

## Inventory Exit Rule

Every later C5 slice must update this inventory in the same change as a source
or guard transition. The update names the exact added consumer/import, the
guard removed, its replacement runtime evidence, the retained rollback owner,
and any new platform exclusion. Uncertain or indirect evidence leaves the row
open.
