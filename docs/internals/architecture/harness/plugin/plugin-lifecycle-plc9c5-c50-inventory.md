# PLC9C5 Current Product/Native Worker Inventory

## Status

- ID: `PLC9C5-C5.0-INVENTORY`
- Scope: `Product / Harness Worker / Hosting / Session`
- Parent: `PLC9C5-C5.0`
- Authority: descriptive — source-backed Current inventory
- Design status: not-applicable
- Implementation status: not-applicable
- Observation base: merged C5.5a design baseline `68151253`
- Effect: none; this inventory grants no runtime or activation authority
- Owner: Harness Worker architecture

## Reading Rule

This inventory records Current facts at the observation base and the exact
C5.1--C5.5c transitions. Source and
executable tests remain higher authority. A
source row records the narrow seam needed to reason about C5; it does not
transfer authority to Product or Plugin management.

## Exact Current Source Set

| ID | Exact source | Current fact | C5 disposition |
| --- | --- | --- | --- |
| `C5-CUR-DECL` | `src/loushang/harness/resources/plugins/declarations.py` and `src/loushang/harness/resources/plugins/selection.py` | versioned inert `local_worker` declaration/selection exists for `capability_provider`; declared required/optional and exact Worker configuration are data only | retain; Product must rejoin the exact selected reservation and immutable revision before a receipt and cannot downgrade declared requiredness |
| `C5-CUR-PRODUCT-CORE` | `src/loushang/harness/session/bootstrap_construction.py` and `src/loushang/harness/session/agent_product.py` | one Product-bound Agent Session construction path exists; it owns Product callbacks and final Session assembly but has no Worker activation input | reuse as the shared canary-capable construction boundary; do not put activation in presenters |
| `C5-CUR-CODING-PRODUCT` | `src/loushang/coding/bootstrap.py`, `src/loushang/coding/cli/__main__.py`, and `src/loushang/coding/_product_worker_canary.py` | Coding supplies an explicit `product_id`, converges ordinary Agent/TUI/RPC/channel/plain/workflow modes through one runtime builder, and owns the sole explicit Linux/Windows Worker canary composition; early-dispatch workspace/LSP/multiagent routes remain separate | implemented C5.4/C5.5c Product evidence; the one canary consumes the public Harness Worker facade plus the exact reviewed coordinator/friend seams and keeps every excluded route dark |
| `C5-CUR-PACKAGE-PRODUCT` | `src/loushang/harness/resources/packages/product_contract.py`, `src/loushang/harness/resources/packages/product_runtime.py`, `src/loushang/harness/resources/packages/product_activation.py`, and `src/loushang/harness/resources/packages/product_composition.py` | PLC9A2 owns Package lifecycle routing for CLI/RPC/Session/startup/operations; it is not a generic Product catalog and contains no Worker authority | retain as Product composition precedent; do not extend its Package-specific receipt into Worker activation |
| `C5-CUR-SESSION-PROFILE` | `src/loushang/harness/transcript/runtime_profile.py` and `src/loushang/coding/session_manager.py` | Coding persists a Product-bound runtime profile and refuses foreign Product profile snapshots on restore | reuse for the Coding-specific G7 resume row after locator selection; do not claim generic AppHost pre-routing identity |
| `C5-CUR-SESSION-DISCOVERY` | `src/loushang/harness/transcript/discovery.py`, `src/loushang/harness/transcript/directory.py`, `src/loushang/harness/transcript/session_catalog.py`, and `src/loushang/harness/machine_resources/control_plane.py` | canonical global plus cwd/home compatibility sources have stable source/locator, alias/conflict, and read-only projection semantics | retain; discovery selects a candidate and grants no Worker/Product authority |
| `C5-CUR-WORKER-PUBLIC` | `src/loushang/harness/worker/__init__.py` | public Worker contracts export launch/session/supervisor, owner selection, H6.4 adapter, C4 query-adapter mechanics, exactly three C5.1 policy/receipt/authority contracts, and the single C5.2 `ProductWorkerNativeProfilePort` | freeze the exact Current `__all__`; private coordinator/cleanup/status/bridge/platform types remain unexported |
| `C5-C51-RECEIPT-LIFECYCLE` | `src/loushang/harness/worker/product_activation.py` | strict pathless policy/receipt codec, statically bound synchronous Product-owned freshness gate, coordinator-wide callback reentry fence, deterministic CAS aggregate, closed monotonic attempt phases, sticky active registry, exact publication/retirement, durable restart policy plus pinned evidence-authority identity/fingerprint, two-phase retryable kill latch, retryable idempotent gate release, trusted cleanup settlement/debt, and exact registered-orphan no-effect recovery | retain as the Product-neutral internal C5.1 aggregate now consumed only by the exact C5.4 Coding root; evidence authority is construction-pinned and record APIs accept only opaque witnesses |
| `C5-C52-LINUX-NATIVE` | `src/loushang/harness/worker/_native_profile_bridge.py` | one request-bound, single-use, pathless Linux contained-profile capability rejoins the C5.1 receipt to the exact Worker request, binds the static launcher digest and containment-profile digest, rejects WSL/unknown/non-x86 before lazily loading the accepted private H6 POSIX symbols, and records policy/execution closure fingerprints | implemented and default-dark except for the sole explicit Coding Product root; Hosting retains all raw native material |
| `C5-C53-WINDOWS-MECHANICS` | `src/loushang/hosting/_windows_launch_preparation.py` and `src/loushang/hosting/_win32_process.py` | one Hosting-private builder rejects caller environment and non-discarded streams, obtains canonical `SystemRoot` from `GetWindowsDirectoryW`, snapshots locked executable/cwd identity, and emits the existing restricted-token/direct-import spec for capture-time reacquisition | implemented as retained mechanics only; no public export, Harness consumer, Windows Product activation, or required-containment claim |
| `C5-C54-LINUX-PRODUCT` | `src/loushang/coding/_product_worker_canary.py` | one explicit Product root joins Coding Product/Session evidence, the exact receipt/request/native closure, Worker supervisor health, read-only Capability admission, injected host/boot identity, readiness, recovery, and ordered rollback | implemented for the exact Linux contained profile; omission is Current, no same-attempt fallback exists, and all Windows/unlisted profiles remain closed |
| `C5-C55C-WINDOWS-PRODUCT` | `src/loushang/coding/_product_worker_canary.py`, `src/loushang/harness/worker/_native_profile_bridge.py`, and `src/loushang/harness/worker/product_activation.py` | the same Product root explicitly dispatches the accepted Windows LPAC profile through the sole friend bridge, persists a pathless attempt-scoped provisioning journal, and admits cleanup contract V2 | implemented only for exact Windows AMD64 policy/plan/request convergence; tree and native-containment witnesses are both required before settlement; Current remains default and no same-attempt fallback exists |
| `C5-CUR-WORKER-IDENTITY` | `src/loushang/harness/worker/contracts.py` | launch identity binds Plugin revision/contribution/Product/scope/generation/attempt; runtime binding captures executable digest and generic filesystem stat identity | retain; C5 receipt must bind this identity, while Windows native identity remains a separate gap |
| `C5-CUR-CURRENT-LAUNCH` | `src/loushang/harness/worker/launch.py` and `src/loushang/harness/sandbox/runtime.py` | Process/Sandbox composition privately mints the Current managed Worker launch capability with required containment | retain through rollback; Sandbox is the only non-Worker production importer of the Worker launch capability |
| `C5-CUR-WORKER-SESSION` | `src/loushang/harness/worker/session.py`, `src/loushang/harness/worker/protocol.py`, `src/loushang/harness/worker/supervisor.py`, and `src/loushang/harness/worker/journal.py` | atomic session abstraction, bounded protocol, health/fencing, and durable protocol-attempt phase evidence exist over injected launch/transport owners; the journal has no receipt, OS-tree owner, boot identity, or cleanup-settlement witness | retain as mechanism; a terminal protocol phase is not resource settlement and none may select Product policy or publish a domain generation |
| `C5-CUR-DOMAIN-CANARY` | `src/loushang/harness/worker/capability_query.py` | one read-only Capability adapter exists behind `enabled=False`, rechecks exact authority, and publishes nothing | retain as the only C5 canary domain; no other domain or effectful operation enters C5 |
| `C5-CUR-DOMAIN-GENERATION` | `src/loushang/harness/capabilities/component_host.py`, `src/loushang/harness/capabilities/owner_component_host.py`, and `src/loushang/harness/capabilities/component_runtime.py` | Capability hosts prepare exact bindings without publication; the owner component runtime/binder alone owns atomic generation publication and retirement | retain as the sole domain writer; C5.4 may delegate to it only after receipt, handshake, and domain admission all remain current |
| `C5-CUR-HOSTING-BRIDGE` | `src/loushang/harness/worker/hosting_adapter.py` and `src/loushang/harness/worker/owner_selection.py` | H6.4 preserves injected managed preparation; C5.2 admits the pathless native-profile port through the same adapter-owned private H6 seam; H5 selects Current by default and never falls back within an attempt | retain; `hosting_adapter.py` constructs no platform spec and the single private bridge owns Linux profile mapping |
| `C5-CUR-H6-CORE` | `src/loushang/hosting/_launch_preparation.py` and `src/loushang/hosting/_child_session_host.py` | H6 owns request-bound one-use opaque preparation and atomic process/endpoint lifetime | consume through the confined friend seam only; no Product vocabulary or raw material crosses the boundary |
| `C5-CUR-H6-LINUX` | `src/loushang/hosting/_posix_launch_preparation.py` and `src/loushang/hosting/_posix_process.py` | Linux x86_64 has private direct and contained static-ELF profiles with retained native evidence, but the selector currently accepts WSL when memfd/proc checks pass | C5.2 may use only the contained profile after Product closure admission and a separate non-WSL exact classifier succeeds |
| `C5-CUR-H6-WINDOWS` | `src/loushang/hosting/_windows_launch_preparation.py`, `src/loushang/hosting/_windows_process.py`, and `src/loushang/hosting/_win32_process.py` | Windows AMD64 retains the restricted-token/direct-import profile and the private per-attempt zero-capability LPAC provision/capture/process implementation, exact four-attribute launch, token-before-resume verification, and cleanup-only crash witness | C5.5b native evidence is mandatory; C5.5c consumes only the LPAC profile through the sole friend bridge, while the restricted-token profile remains Product-ineligible |

The exact source set above is executable inventory. Proposed later C5 files are
not added until their owning guard transition lands.

## Current Composition And Absence Facts

- `SandboxExecutionRuntime` is the only non-Worker production source importing
  the existing Worker launch capability.
- Only `src/loushang/coding/_product_worker_canary.py` outside Worker names
  `HostingManagedWorkerSessionAdapter`, `WorkerHostingActivationV1`,
  `WorkerSessionOwnerRouter`, or `bind_capability_query_worker_adapter`.
- Coding's exact canary root imports the public Harness Worker facade, the C5.1
  coordinator, and the C5.2 friend binder, but no Hosting module; every other
  Coding source remains free of Worker/Hosting composition imports.
- H6 private Windows profile specifications remain confined to Hosting. The
  single bridge lazily imports the exact accepted POSIX or LPAC symbols after
  platform/profile validation; no second friend or raw Win32 import exists.
- `WorkerHostingActivationV1.owner` defaults to `"current"`; selection reads no
  environment and one attempt calls exactly one selected owner.
- Product Worker lifecycle contracts and the cross-platform profile capability remain
  owned inside Worker. C5.4/C5.5c add one Coding consumer over injected Product,
  native, machine-identity, durable-state, Capability, and cleanup owners; its
  retained cross-entrypoint report is implemented.
- `remote_service` remains absent from the declaration/runtime topology and the
  public author SDK has no Worker runtime owner.

## Current Shape Mismatches

| Boundary | Current producer | Current consumer | Current result |
| --- | --- | --- | --- |
| Product selection | Coding Product identity and exact policy/receipt input | H5 typed Current/Hosting owner selection | exact Linux or Windows LPAC canary joins the decision; every omitted, disabled, foreign, or unlisted route remains Current/closed |
| activation evidence | strict pathless policy/receipt evidence | Coding Product composition | the exact receipt/request/Session/native/Capability identities are joined before effect; no generic AppHost issuer exists |
| Linux contained profile | C5.2 rejoins the Worker payload digest, retained cwd identity, trusted launcher/profile digests, receipt catalog, and same-domain policy closure | C5.4 invokes the exact friend binder and receives only its opaque port; H6.2 owns capture | implemented behind an explicit Linux-only Product canary; no platform material or native authority crosses into Coding |
| Windows identity | the LPAC provisioner snapshots exact runtime/grant/profile identities and the bridge binds their pathless plan to the receipt/request | Product required-containment profile admission | implemented for the fresh per-attempt LPAC profile; stale or foreign provisioning fails closed |
| Windows request | the LPAC builder accepts only an empty caller environment, obtains canonical bootstrap values through OS APIs, and emits the exact closed allowlist | H6.4 Worker mapping plus friend-owned prepared-request handoff | ambient poisoning remains closed and the semantic lease verifies the Hosting-built request before effect |
| Windows containment meaning | Product requires accepted required containment | C5.5b proves LPAC/zero-capability/opt-out/grant/Job mechanics and C5.5c binds them to Product lifecycle | exact Windows AMD64 canary accepted; H6.3 restricted-token profile remains rejected |
| restart settlement | C5.1 joins protocol terminal, exact domain retirement, durable complete-tree settlement/debt, host/boot identity, restart budget, and construction-pinned evidence identity; C5.2/C5.3 retain Linux/Windows mechanics evidence | C5.4 ordered recovery port | the Product requires the full V1--V6 vector and rejects incomplete/reordered recovery; owner-specific durable proof remains injected |
| kill-switch admission | C5.1 serializes receipt admission, first-effect registration, publication, latch generation, and the complete active registry | C5.4 Product/domain owners | production canary latches first and conservatively treats an ambiguous publication call as possibly effectful |
| Session resume | discovery yields canonical/compatibility locator facts and Coding validates its Product runtime snapshot | C5.4 exact Product root | selected locator provenance is hashed into the receipt and canonical/cwd/home/alias routes pass only when unambiguous and unchanged |
| entrypoints | ordinary Coding Agent modes converge through shared construction, while early subcommands dispatch separately | C5.4 receipt projection | CLI/TUI/Product paths receive the identical receipt object; excluded early routes reject activation |
| rollback | H5 retains future Current selection; C5.1 latch stales future Hosting admission and enumerates sticky attempts | C5.4 Product/domain/native owners | R1--R7 is executable: latch, fence, revoke/drain, terminate, settle/debt, readiness, then new Current |

## Current-To-Target Closure Ledger

| Gap | Target sole writer | First permitted slice | Completion evidence |
| --- | --- | --- | --- |
| explicit allowlist and required/optional decision | exact Product adapter | C5.1 | deterministic missing/wrong/disabled/stale policy tests |
| pathless activation receipt schema/freshness | Harness Worker contract, value issued by Product | C5.1 | canonical same-domain expected/realized policy closure plus separate full execution-closure evidence, strict version/field/fingerprint, and pre-acquire/pre-publication current-witness tests |
| serialized admission and active-attempt registry | Harness Worker coordinator over weak shared owner-domain capabilities | C5.1 | owner-snapshot/rollback race, durable restart-latch, `releasing` fail-fast plus later `release_due` fault takeover, all-domain callback fencing, and disjoint-owner parallel tests |
| durable cleanup settlement/debt | Harness Worker contract over injected owner evidence | C5.1 fake; C5.2/C5.3 platform evidence | protocol-terminal/domain-retired/tree-settled CAS, same-boot unknown debt, and changed-boot absence tests |
| Product readiness/rollback aggregate | exact Product/domain owner over injected Worker status | C5.1 fake, C5.4 production | atomic pre-publication witness+CAS under the admission gate, kill-switch-before-publish no-visibility race, exact-generation retirement CAS, required/optional, ordered kill-switch, and cleanup-debt tests |
| Linux contained native binding | the single private `_native_profile_bridge.py` plus Hosting | C5.2 | retained nonskipped Linux report with WSL/unknown rejection and execution-closure evidence |
| Windows restricted mechanics rejection | Hosting-private trusted-payload builder; Product selection excludes the profile | C5.3 | implemented `GetWindowsDirectoryW` trust, ambient poisoning/caller-environment rejection, discarded stderr, retained mechanics report, and Product required-containment rejection |
| Coding Product composition | Coding Product root | C5.4 only | implemented exact allowlist route plus negative no-side-effect tests |
| Session/entrypoint convergence | Coding Product construction and Session identity owners | C5.4 | implemented canonical/cwd/home, alias/conflict/tamper, and shared receipt report |
| recovery/rollback drill | Product/domain, Worker supervisor, Process/Hosting owners each settle their own state | C5.4 | implemented latch-first R1--R7 and complete V1--V6 evidence validation |
| Windows required containment | Product/Package/Sandbox durable coordinator, sole Harness friend bridge, and Hosting native owners at their respective boundaries | C5.5a design; C5.5b native; C5.5c Product | accepted design for a zero-capability per-attempt LPAC, dedicated immutable runtime closure, cleanup V2, exact native/Product reports, and retained no-fallback/default-Current fences |

The C5.1 contract/fake, C5.2 Linux native, C5.3 Windows mechanics/rejection,
C5.4 Linux Product, C5.5b Windows LPAC native, and C5.5c Windows Product reports
are all retained. G7 is closed by their combined evidence; neither the native
report nor the Product report grants authority alone.

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
