# Plugin Lifecycle PLC9.0 Baseline

## Status And Authority

- Slice: PLC9.0 management, isolation, package-lifecycle, and cleanup design
  baseline.
- Source baseline: `1c104ce5` on `lane/harness`.
- Delivery branch: `harness/plugin-plc9-baseline`.
- Status: accepted on 2026-08-31 after architecture, correctness/security, and
  Product/test review of this document, the source-backed inventory, and the
  executable architecture guards. No P0/P1 remained after correction and
  re-review.
- Runtime effect: none. PLC9.0 changes documentation and architecture tests
  only. It does not add a management endpoint, migrate enablement, materialize
  a package, start a Worker, delete data, or authorize a remote service.

This baseline refines the PLC9 delivery scope in the
[Unified Plugin Lifecycle And Coding Pluginization Delivery Plan](plugin-lifecycle-coding-pluginization-plan.md)
under the accepted
[Plugin Architecture V2](architecture.md). Current source and executable tests
remain authoritative for implemented behavior. The accompanying
[PLC9.0 Owner And Peer Inventory](plugin-lifecycle-plc9-inventory.md) freezes
the exact starting seams that later slices must migrate or retain.

## First-Principles Decisions

PLC9 closes lifecycle gaps by following six rules:

1. **One fact, one authority.** Desired selection, source availability,
   immutable package identity, Instance state, process state, containment,
   domain publication, private data, and backup retention remain separate
   facts owned by the subsystem that enforces each invariant.
2. **One management application boundary, many transports.** CLI, RPC, UI, and
   management SDK are adapters over the same command and query contracts. They
   do not write settings, ledgers, package pointers, or owner state directly.
3. **A projection is a join, not a new clock.** Management reads correlate
   owner snapshots using explicit revisions and report skew. They never cache
   a second effective Plugin state.
4. **Safety precedes reachability.** An executable topology is not admitted
   until artifact verification, exact authorization, containment, Process Host
   ownership, and domain protocol ownership are all proven. A same-user child
   process is not containment.
5. **Removal is not deletion.** Desired-state removal, Instance retirement,
   process termination, owner cleanup, artifact GC, private-data deletion, and
   backup expiry are distinct operations with distinct evidence.
6. **Compatibility only points inward.** A temporary adapter may translate an
   old input into the canonical boundary. It may not own a parallel mutation,
   parsing, selection, publication, or cleanup path, and it must have a named
   deletion gate.

The public `loushang.plugin` package remains the authoring SDK. A future
management client surface is a control-plane projection and must not leak
management ledgers, Process Host, Sandbox, Approval, registries, or Product
owner objects into that authoring namespace.

## Target Ownership Model

| Fact or transition | Sole target authority | Projection or consumer |
| --- | --- | --- |
| Source identity, authentication, availability, fetched provenance and bounded bytes | Source Authority | Package lifecycle sink |
| Quarantine, safe extraction, dependency closure, immutable revision publication and artifact GC | Package lifecycle/store owner | management projection and exact revision consumers |
| Install, enable, disable, update, and remove desired state | `PluginManagementService` command boundary | CLI/RPC/UI/management SDK |
| Correlated lifecycle inventory | one read-only management query boundary over owner snapshots | CLI/RPC/UI/management SDK |
| Instance activation, drain, revocation, retirement, and family leases | `PluginInstanceRuntimeLedger` plus exact lifecycle coordinator | management projection and domain hosts |
| Capability, Resource, Tool, Command, Skill, and continuity publication | exact domain Component Host/owner | Product Consumers and diagnostics |
| Worker spawn, bounded I/O, termination, and child cleanup | authorized `ProcessHost` binding | exact domain Worker host |
| Enforced process containment and degradation/failure evidence | Sandbox runtime | Process Host binding and diagnostics |
| Plugin-private mutable data and its deletion | exact data-domain owner under a separately confirmed deletion command | management projection |
| Backup retention and expiry | backup/retention owner, not Plugin desired state | management projection |

`PluginManagementService` is already the durable command authority over Plugin
desired state. PLC9 may extend the application boundary around it, but must not
turn it into the Package store, Process Host, Sandbox, domain publication host,
or private-data owner. The read side may correlate these owners; it cannot
write on their behalf.

## State And Operation Separation

There is deliberately no universal `PluginState` enum. The management view
must expose at least these independent dimensions:

```text
source availability
package acquisition / verification / retention
desired installation and selected revision
Instance activation / drain / revocation / retirement
owner-generation publication and retirement
Worker process / protocol / containment status
cleanup debt and repair decisions
private-data deletion status
backup-retention status
```

The target meanings of **desired-state command commit** are:

| Desired-state command | Terminal success means | It never implies |
| --- | --- | --- |
| install | a verified immutable revision is durably identified and desired installation is committed through the management boundary | enabled, activated, imported, or owner-published |
| enable | desired selection is committed | an already-running Session changed revision or activation succeeded |
| disable | desired selection is disabled and required retirement intent is durably opened | Instances drained, Workers terminated, or bytes deleted |
| update | the replacement revision is verified/staged and the desired pointer transition is committed with restart policy | pinned old Sessions were mutated in place |
| remove | desired installation is absent and required retirement coordination is durable | retirement, GC, private-data deletion, or backup expiry completed |

Separate lifecycle operations have their own terminal success:

| Lifecycle operation | Terminal success means | It never implies |
| --- | --- | --- |
| retire | all covered Instances are `RETIRED` and all exact owner/process cleanup sets have successful evidence | a terminal failure is success, or package bytes/private data were deleted |
| GC | an exact revision candidate is rechecked, its exact revision is deleted, and a durable deletion receipt is committed | private data or backups were deleted |
| delete private data | a separately confirmed, domain-owned deletion command completed with a receipt | desired-state removal, artifact GC, or backup expiry |
| repair | an operator decision advances or safely abandons one identified failed cleanup attempt | missing evidence may be invented or a false terminal state reported |

Command and convergence results are two different contracts:

- command status preserves the durable `accepted` -> `running` -> `terminal`
  operation journal and reports `desired_state_committed` or a stable failure;
- convergence reports facts such as `retirement_pending`, `draining`,
  `revoking`, `cleanup_debt`, `inactive`, `stale`, `unknown`, and
  `unsupported`, each with the relevant owner revision; and
- no surface emits an unqualified `disabled`, `removed`, or `completed` while
  an old Instance, Worker, owner generation, cleanup lease, or failed cleanup
  remains. Terminal cleanup failure is debt, never successful retirement.

Every command needs stable operation, idempotency, and correlation identity. A
transport may retry or reconnect, but cannot reinterpret an accepted command.
Every surface must support operation query/resume; a bounded wait presentation
may poll that same query port, but timeout returns the last qualified
convergence state rather than inventing completion. Query results carry the
owner revisions needed to distinguish convergence from skew.

The lifecycle behavior matrix is:

| Action | New Session / cold start | Already pinned Session | Replay and GC |
| --- | --- | --- | --- |
| source add | source becomes available for inspection/acquisition; nothing is installed or enabled | unchanged | creates no desired state or GC eligibility |
| source remove | source is unavailable for new acquisition | an already published, pinned immutable revision remains replayable | cannot erase binding history or published bytes; not desired remove or GC |
| disable | new selection excludes the installation after desired commit | keeps its exact revision until drain/revocation policy retires it | restart reads disabled desired state; GC waits for all pins/Instances/cleanup |
| update | new Sessions select the committed replacement subject to restart policy | keeps the old exact revision | both revisions remain replayable until retention evidence permits old-revision GC |
| desired remove | new selection treats the installation as absent | keeps its exact revision until required retirement succeeds | tombstone/history prevents reseeding; GC and private-data deletion remain separate |

Generic Package `materialize`, `remove`, and `uninstall` are acquisition/cache
operations, not aliases for Plugin install/remove. If a Package operation
targets a Plugin-bound revision, it must route through the canonical Plugin
lifecycle or refuse without mutation. It may not directly destroy a replayable
binding or revision.

## Management Projection Boundary

PLC9A introduces the common control-plane seam before adding transports:

- command adapters construct typed management commands and submit them to the
  one application service;
- query adapters request a correlated snapshot from one read-only projector;
- streaming progress, if added, is a projection of durable operation events,
  not an in-memory transport-owned state machine;
- transport authentication, authorization, tenancy, and presentation remain
  outside the domain command records; and
- the versioned JSON result vocabulary includes operation, idempotency and
  correlation IDs; owner revisions; stable error codes; `stale`, `skew`,
  `unknown`, and `unsupported`; and partial progress plus cleanup debt.

CLI is the first migration proof. RPC, UI, and management SDK may follow only
after the same conformance fixture proves that none can bypass the common
ports. PLC9A must not expose remote or Python-package installation more broadly
while the PLC9B safe-materialization gate is open.

Cross-owner management is a journaled orchestration, not a distributed
transaction. Install/update first consume a Package-owner-verified immutable
revision reference, then submit the desired-state command. Recovery resumes the
recorded phase or exposes debt; it never compensates by deleting a revision
that another installation or Session may have pinned. Source/Package install is
not absorbed into `PluginManagementService`.

The enablement migration is one-way and has its own durable, versioned journal
per Product scope and installation:

```text
accepted -> desired_committed -> compatibility_window -> finalized
```

Each receipt binds the migration schema/epoch, Product/scope/installation key,
legacy input fingerprint, prior desired-history revision, committed desired
transition revision or `already_authoritative` disposition, and journal
revision. The rules are:

1. any desired history, including an `absent` tombstone, wins forever and is
   recorded as `already_authoritative`; legacy input cannot reseed it;
2. only a never-seen installation may seed once; explicit legacy disable wins
   over `manifest.enabled`, which is only the final install-time default;
3. `source.enabled` remains Source Authority availability and is never mapped
   into desired selection;
4. a crash before `desired_committed` replays the same idempotent command; a
   crash afterward observes the exact transition revision and advances the
   receipt without a second mutation;
5. while supported older binaries exist, legacy fields remain a derived
   compatibility projection and current writers reject peer mutation. Once a
   receipt exists, an old runtime that cannot honor its epoch is refused by a
   runtime/version compatibility gate rather than allowed to mutate state;
6. finalization and field deletion require a declared minimum-version window,
   backup/restore evidence, and a tested roll-forward procedure. Downgrade
   after finalization is unsupported unless that binary reads the migration
   receipt and treats desired state as authoritative; and
7. after finalization, remove `manifest.enabled`, `source.enabled`, settings
   `disabled_plugins`, and `PluginManager` as runtime-selection writers, and
   fail architecture tests if a new peer writer or veto appears.

Migration tests cover never-seen enabled/disabled defaults, existing enabled,
disabled and absent/tombstoned desired history, conflicting legacy values,
crash at every journal edge, repeated execution, and upgrade -> downgrade ->
upgrade behavior. No partial migration deletes a legacy veto.

The compatibility aliases `--add-plugin` and `--remove-plugin` keep their
existing Source add/remove meaning during a deprecation window. They are never
silently reinterpreted as desired install/remove. New desired-state commands
use distinct names and typed identities.

## Safe Package Lifecycle Boundary

PLC9B makes one Package lifecycle/store owner responsible for the complete
materialization transaction:

```text
authenticated source + provenance + bounded bytes
  -> owner-created bounded quarantine
  -> safe regular-file/directory-only extraction
  -> digest-locked recursive dependency closure
  -> canonical tree and release verification
  -> atomic immutable publication
```

The boundary rejects absolute paths, traversal, symlinks, hard links, device
nodes, sockets, FIFOs, unstable file identities, duplicate/colliding paths,
size/count/depth overflow, and writes outside owner-created quarantine. It
executes no import, setup script, package-manager lifecycle hook, source build,
or adjacent executable during acquire, inspect, validate, or publish.

Python input is verified wheel-only. An sdist is rejected unless a separately
designed contained build service returns a digest-addressed verified artifact
to the same Package lifecycle sink; that build service is not authorized by
PLC9.0. The current `PythonPackageInstallerBackend` invocation of `uv`/`pip`
does not satisfy this target and remains an explicit migration item.

The same gate covers every current entrypoint: CLI Package lifecycle commands,
RPC Package commands, Session Package adapters/controllers, startup
`PackageSourceResolver` auto-materialization, and direct materializer calls.
PLC9B is not complete while any of those paths can publish a Plugin-bound
Package outside the canonical sink. The current `PackageSourcePolicy` is a
policy port, not a complete Source Authority; the Git backend shells out to
fetch/checkout; and `PluginDependencyClosureLock` v1 binds the final package
tree plus installed `name==version` facts, not a recursive digest graph of
verified wheel artifacts. PLC9B introduces versioned closure evidence rather
than reinterpreting v1 records.

The existing `PluginRevisionStore` safe-copy/immutable-revision boundary and
`PluginPackageLifecycleLedger` retention evidence are reusable substrates.
Neither alone constitutes the complete acquisition/materialization owner.

## Local Worker Boundary

PLC9C1 adds `local_worker` only as a new version of the contribution
execution-topology IR with its wire codec, compatibility fixture, security
classification, and negative tests. It is not a new
`PluginDeclarationSourceKind`: a document may declare a Worker topology, while
declaration acquisition and contribution execution remain independent axes.
The declaration expresses intent and protocol identity; it does not grant
process, filesystem, network, credential, publication, or Sandbox authority.

The exact domain Component Host owns semantic IPC and any contribution it
publishes. PLC9C2 provides a narrow, owner-only `ManagedWorkerLaunchPort`
minted by the Process/Sandbox composition root after required-containment
availability is established. That port is not the current generic
`AuthorizedProcessLauncher` returned by
`SandboxExecutionRuntime.bind_process_launcher`: its public `start()` also
supports non-managed best-effort execution and is therefore explicitly
forbidden for Worker admission. The managed port implementation privately
builds `_managed_process_launch_request` evidence and invokes
`ScopeBoundProcessLauncher._start_managed`, whose authority check requires a
Process-owner-minted launcher, mandatory Approval, `required` containment, and
a Sandbox-owner-bound plan before the final Process Host call. A Worker host
cannot construct a raw `ProcessHost`, Sandbox service/planner, managed request,
or copy Policy/Approval/Authorization logic. The Worker receives a narrow
protocol, not owner registrars or ambient Host authority.
Every effectful request is reconstructed as a Host-side exact action and passes
current Policy, Approval when required, Authorization, Sandbox, and audit.

Bare `ProcessHost.start()` and `LocalSandboxService` existence are not Worker
admission. Required-containment failure is terminal before spawn/admission. Crash,
protocol mismatch, heartbeat loss, output/queue limit, cancellation, shutdown,
and restart budget exhaustion remain independently diagnosable. A Worker
cannot publish a generation before handshake and exact owner admission, and
its process exit cannot by itself claim owner retirement.

`remote_service` is not a second arm hidden inside `local_worker`. It is
deferred to a separate topology contract and threat model covering service
identity, authentication, authorization, egress, tenant isolation, revocation,
protocol versioning, secret placement, audit, data residency, and remote
failure semantics. PLC9.0 authorizes no remote-service declaration or client.

## Cleanup, GC, Data Deletion, And Repair

PLC9D builds execution on the existing conservative retention evidence:

- cleanup attempts remain journaled, retryable, and lease-protected;
- a terminal failure retains its lease until an explicit `retry` or
  `safe_abandon` repair decision;
- GC enumerates candidates, rechecks their exact snapshot/recovery evidence at
  deletion time, deletes only the exact immutable artifact revision, and
  journals a durable success/failure receipt;
- desired absence never directly deletes a revision;
- generic Plugin-private data deletion is separately confirmed and delegated
  to the exact data-domain owner; and
- backup retention/expiry is reported separately and is never inferred from
  local deletion.

The existing continuity-provider deletion path is a domain-specific precedent,
not a generic Plugin data-deletion authority. `PluginContinuityDeletionAuthority`
owns durable Product authorization, serialization, and receipt settlement; the
source-owned `PreparedContinuityDeletion.commit(plan)` performs the destructive
domain mutation before settlement. PLC9 must preserve that order and must not
move destructive execution into `plugin_management`, widen it by type checks,
or replace it with ambient filesystem deletion.

Current Package `remove_remote_source`, `forget_remote_source`, and
`forget_plugin_binding` are mutable acquisition-cache/source-binding cleanup
paths. They are not immutable revision GC and cannot be used for a Plugin-bound
Package after the PLC9D cutover. PLC9E deletes or narrows them only after replay,
pin, retirement, rollback, and non-Plugin Package behavior are proven.

Repair is an operation over durable evidence. It may resume an idempotent
attempt, authorize a narrowly justified safe abandonment, or report a manual
action. It cannot erase a journal gap, release a live lease, treat process loss
as domain cleanup, or synthesize successful retirement.

## Delivery Slices And Gates

| Slice | Scope | Entry/exit gate |
| --- | --- | --- |
| PLC9.0 | this design baseline, source inventory, and architecture guards | three-view design review passes after corrections; no runtime behavior changes |
| PLC9A1 | common command/query ports, correlated read model, CLI list/enable/disable migration, and durable enablement migration | CLI uses common ports; migration crash/downgrade matrix passes; no artifact operation is broadened |
| PLC9B | bounded acquisition, safe extraction, versioned wheel-only dependency closure, immutable publication ownership, and migration of every CLI/RPC/Session/startup materialization entry | malicious archives and sdists cannot escape or execute; no current installer route can publish a Plugin-bound revision outside the Package owner |
| PLC9A2 | project existing RPC and later UI/management SDK surfaces one at a time over the common ports; activate artifact commands only after PLC9B | each transport passes the same versioned command/query conformance fixture and has no fallback/bypass |
| PLC9C | versioned `local_worker`, required containment, supervised protocol/Process Host/domain-host composition | no spawn on failed containment; lifecycle, protocol, authority, and publication tests pass independently |
| PLC9D | executable cleanup/GC, generic private-data confirmation contract, backup-retention projection, operator repair | remove/retire/GC/data deletion/backup expiry stay distinct; failures never report false completion |
| PLC9E | delete superseded peer writers, vetoes, adapters, and temporary bridges; terminal conformance | architecture inventory contains only accepted owners and all management transports pass one conformance suite |

The dependency order is `PLC9.0 -> PLC9A1`; PLC9B then gates every artifact
command in PLC9A2 and is also required before PLC9C. PLC9D requires A1, B, and
the relevant C lifecycle evidence. PLC9E runs only after all replacement paths
and rollback gates pass. A non-artifact A2 projection may land after A1, but it
cannot expose install/update/materialize/remove/uninstall until B passes.

Each slice requires targeted tests before broader Harness validation, an
explicit rollback/roll-forward gate, and review proportional to the authority
it changes. PLC9B and PLC9C are security boundaries and require adversarial
tests, not only happy-path unit tests.

## Frozen Forbidden Routes

Until an accepted slice intentionally revises the inventory, architecture
tests reject:

- a new source-visible desired-ledger construction or mutation site outside the
  inventoried composition root and `PluginManagementService` methods;
- a new source-visible use of `manifest.enabled`, `source.enabled`, settings
  `disabled_plugins`, or `PluginManager` outside the frozen qualified-site and
  occurrence inventory;
- a new function-scoped named CLI/RPC/Session/startup Package lifecycle method
  or call outside the frozen qualified-site and occurrence inventory;
- reinterpretation of `--add-plugin` or `--remove-plugin` from source mutation
  into desired-state or destructive semantics;
- a management transport that imports a concrete ledger/store to mutate it;
- a management read model persisted as another effective-state authority;
- an authoring SDK export of management, Process Host, Sandbox, Approval,
  registry, or owner-authority objects;
- `local_worker` appearing outside its accepted additive index-v3/IR-v3/
  document-v2 contract, or `remote_service` appearing in any declaration codec;
- direct `uv`/`pip install` being described as the safe Plugin package owner;
- a Source adapter selecting quarantine/publication paths or binding a runtime;
- a Worker spawn that can proceed after required containment is unavailable or
  degraded;
- a Worker host that constructs raw Process Host/Sandbox owners or uses generic
  `AuthorizedProcessLauncher.start()` instead of consuming the owner-only
  managed Worker launch port;
- destructive data-domain commit inside `plugin_management` rather than the
  source/domain-owned candidate;
- artifact GC derived only from desired absence, or reuse of mutable Package
  `remove`/`forget` as immutable revision GC; or
- any operation that collapses remove, retirement, GC, private-data deletion,
  or backup expiry into one terminal flag.

## PLC9.0 Exit Gate

PLC9.0 is complete only when:

- the inventory names every current management, enablement, package,
  Instance, Process Host, Sandbox, compatibility, GC, and data-deletion seam
  relevant to PLC9;
- architecture tests prove the documents are indexed and freeze the material
  current-source facts without pretending target code exists;
- architecture, correctness, and Product/test reviewers independently accept
  the corrected design; and
- the working tree contains no PLC9 runtime implementation.

Passing PLC9.0 permits a separately scoped PLC9A1 implementation. It does not
pre-approve the APIs, wire formats, filesystem deletion mechanics, Worker
protocol, remote-service topology, or compatibility deletion of later slices.
