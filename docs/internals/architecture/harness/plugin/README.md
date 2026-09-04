# Loushang Plugin Architecture

## Status

- Authority: normative catalog for active Harness Plugin documents; it does
  not make a proposed child design accepted.
- Design status: mixed and explicitly labeled per document. Architecture V2 is
  independently reviewed and owner accepted under issue `#502`; incremental
  contracts record implemented slices; plans remain delivery records; baselines
  are implementation evidence.
- Implementation status: partial, summarized by `architecture.md` and tracked
  in the lifecycle plan.
- Owner: `loushang.harness` Plugin architecture scope; contribution runtime
  authority remains with each exact domain owner.

This directory is the single entrypoint for active Harness Plugin architecture,
delivery, frozen contracts, and baselines.

## Authority Order

When documents disagree, use this order:

1. current source and executable tests for implemented behavior;
2. accepted exact-owner runtime boundaries linked below;
3. [Plugin Architecture V2](architecture.md) for the canonical target and
   cross-document decisions;
4. frozen incremental contracts for their exact implemented slices;
5. the lifecycle plan for sequencing and delivery status;
6. baselines as implementation evidence, not current design authority; and
7. superseded ARDs only for design archaeology.

The architecture document answers what the Plugin system is and which owner
controls each state. The lifecycle plan answers when a target is delivered.
Neither may silently override a narrower implemented owner contract.

## Start Here

- [Plugin Architecture V2](architecture.md) is the only active Plugin
  architecture master document. It defines first principles, orthogonal
  artifact/identity/contribution/execution/trust/lifetime axes, exact ownership,
  Skill semantics, Worker and remote-service topology, security, and the public
  authoring ladder.
- [Plugin Lifecycle And Coding Pluginization Plan](plugin-lifecycle-coding-pluginization-plan.md)
  is the only coordinating PLC0-PLC9 delivery plan. Its status section tracks
  the current implementation, including the production `coding.lsp` route.
- [Plugin Authoring Primitives Delivery Plan](plugin-authoring-primitives-delivery-plan.md)
  refines Definition/Provider/Consumer, Component Host, declaration builder,
  admission, and future public SDK delivery.
- [Resource Catalog And Source Pluginization Plan](resource-catalog-pluginization-plan.md)
  owns the Resource/Skill catalog convergence and the rule that mechanisms may
  be Plugin components while individual Skills remain Resources.

## Frozen Contracts

- [PLC1B Declaration Foundation](plugin-declaration-foundation-plc1b-contract.md)
  freezes declaration sources, strict wire records, contribution kinds,
  fingerprints, aggregate claims, and version diagnostics.
- [PLC2 Lifecycle Contract](plugin-lifecycle-plc2-contract.md) freezes durable
  install/enable/disable/update, retirement handoff, Instance leases, cleanup,
  repair, and GC evidence.
- [PLC3 Execution Trust Contract](plugin-execution-trust-plc3-contract.md)
  freezes one-shot execution decisions, use consumption, verified Definition
  evaluation, and recovery.
- [PLC7 Second-Provider Contract](plugin-lifecycle-plc7-contract.md) freezes the
  `coding.arch.default` identities, typed facets, shared single-Graph Product
  composition, private indexed-state policy, direct-path deletion, and review
  gates.
- [PLC8 Public SDK And Managed Skill Action Contract](plugin-lifecycle-plc8-contract.md)
  freezes the public author namespace, engine negotiation, inert validation,
  single-Catalog action selection, and Approval/containment execution boundary.
- [PLC9A1 Management Application Contract](plugin-lifecycle-plc9a1-contract.md)
  freezes the internal transport-neutral command/query boundary, read-only
  owner-revisioned projection, one-way enablement migration, and Coding CLI
  adaptation without widening the public author SDK.
- [PLC9A2 Product Routing Contract](plugin-lifecycle-plc9a2-contract.md)
  freezes Product-owned recovery/epoch activation, one typed Package intent
  across operations/Session/CLI/RPC/startup, and explicit-non-Plugin-only
  fallback without granting transports Store or deletion authority.
- [PLC9B Safe Package Boundary Contract](plugin-lifecycle-plc9b-contract.md)
  freezes the Package acquisition owner, exact entrypoint inventory, versioned
  wheel/closure/publication evidence, fail-closed recovery, and mandatory
  adversarial acceptance matrix. PLC9B1 implements the dark inert Owner Kernel;
  PLC9B2a adds an unbound bounded Source/quarantine component. Archive/wheel
  verification, phase integration, cleanup repair, and evidence-driven crash
  adoption are implemented by PLC9B2b/B2c/B2d/B2e. PLC9B2f supplies the
  accepted native Windows rooted-handle backend and its mandatory CI oracle.
  PLC9B2g is the accepted acquisition-level manifest slice; PLC9B2h is the
  accepted Linux archive/path/type/limit/wheel matrix; PLC9B2i is the accepted
  Windows archive path/type matrix. PLC9B2j is the accepted Linux-native slice
  for artifact identity, early crash, and cleanup-debt recovery. PLC9B2k is the
  accepted POSIX-native slice proving Wheel 1.x hardlinked sources are
  normalized to independent regular files. PLC9B3a is the accepted dark pure
  closure-v2 verifier with component-level adversarial fixtures. PLC9B3b is the
  accepted dark slice for durable authenticated-Source inputs and deterministic
  recovery of Wheel dependency headers. PLC9B3c is the accepted dark recursive
  builder that gives a selection-only resolver no acquisition authority and
  routes every dependency through accepted Source/acquisition/Wheel evidence
  before the pure closure proof. PLC9B3d-1 accepted dark code adds durable
  basis/selection/plan evidence, local dependency replay, cleanup-debt handoff,
  and dark closure phase-CAS. B3d-1 accepts its two crash rows after the retained
  54-row Linux-native report passed. B3d-2a accepts the three composed
  closure-limit rows after the retained 57-row Linux-native report passed;
  B3d-2b accepts all seven closure-integrity rows with bounded cleanup-debt
  custody after the retained 64-row Linux-native report passed. PLC9B3e-1
  accepted code adds dark credential-free typed stable refs, an immutable
  closure lock, and the exact committed-set record without pinning, staging,
  publishing, admission, or production binding; its retained native report
  remained exactly 64 rows and contained no `B-PUB-*` node. PLC9B3e-2a
  accepted code adds credential-free transaction-pin records, a narrow Port,
  and a durable adjacent-evidence journal without phase composition or a
  concrete retention-ledger import; its retained report remained exactly 64
  rows and contained neither `B-CRASH-PINNED` nor a `B-PUB-*` node.
  PLC9B3e-2b accepted code composes exact pin acquisition, durable receipt
  ordering, phase CAS, retry adoption, and candidate-free restart recovery. Its
  composed `B-CRASH-PINNED` row passed in the retained 65-row Linux-native
  report with zero skips, failures, or errors; publication and production
  routing remain unimplemented. PLC9B3e-3a accepted code adds dark,
  role-separated staging contracts with an authority-issued Plugin-root
  target, exact adjacent staging evidence, and a Package-owner atomic
  closure-lock/committed-set journal. It composes no store or lifecycle phase,
  keeps all publication/crash rows planned, and remains private to the Package
  owner boundary. Its retained 65-row Linux-native report passed with zero
  skips, failures, or errors and contained no staging/set crash or publication
  node. PLC9B3e-3b accepted code composes those dark contracts through
  deterministic dependency-first staging, classification recheck, atomic set
  evidence, and candidate-free recovery. It makes `B-CRASH-STAGING` and
  `B-CRASH-SET` executable without claiming a concrete store, native
  publication-root safety, admission, or production routing. Its retained
  67-row Linux-native report passed with zero skips, failures, or errors,
  included all three committed-phase crash rows, and contained no publication
  node. PLC9B3e-3c0 accepted contracts bind a files-only logical transfer
  manifest to exact Wheel evidence and separate quarantine transfer,
  dependency-root sinks, and designated Plugin-root sinks. They expose no
  physical path or handle, perform no Store effect, and keep every publication
  row planned pending native backends and later commit admission. Its retained
  67-row Linux-native report passed without skips, failures, errors, or a
  publication node.
  PLC9B3e-3c1 accepted code adds the first concrete POSIX-native consumers of
  those contracts: an identity-checked quarantine reader, bounded transfer
  owner, and role-separated immutable Store adapters. Five publication/root/
  handle manifest rows now traverse real acquisition-to-set composition;
  Windows native backends, collision/reuse, commit admission, and production
  routing remain closed. Its retained 72-row Linux-native report passed with
  zero skips, failures, or errors and included exactly those five publication
  nodes.
  PLC9B3e-3c2 accepted code adds corresponding role-separated Windows-native
  Store adapters using the accepted rooted-handle backend plus handle-relative
  atomic rename. Its retained native report passed 15 component tests and 12
  manifest nodes with zero skips, failures, or errors, including all five
  Windows publication/ABA/handle nodes. Collision/reuse, commit admission, and
  production routing remain closed.
  PLC9B3e-3c3 accepted code adds a durable Store-private settlement authority
  to both native adapters. It records the complete rooted physical identity,
  exact verified manifest, and receipt before rename, serializes Store
  instances with a durable owner lock, recovers the rename-to-receipt crash
  window, and distinguishes exact restart reuse from same-byte identity
  collision. Collision and reuse become executable without exposing a public
  route; `B-PUB-UNCOMMITTED` remains the PLC9B4 admission gate. All 23 PR
  checks passed; retained reports executed 74 Linux-native manifest nodes, 19
  Windows native-component tests, and 12 Windows manifest nodes without skips,
  failures, or errors.
  PLC9B4a accepted code adds the dark terminal commit owner, deterministic
  publication receipt, and candidate-free read-only admission owner. The
  admission boundary proves exact operation/request, Product/scope,
  Installation/Plugin, root/set/closure, and live transaction-pin evidence but
  cannot reopen a revision or mutate binding/desired state. The missing-receipt
  publication row and seven cross-context admission rows are executable; the
  later retention-handoff, epoch, and Product-routing gates remain closed. All
  23 candidate checks passed, and retained Linux artifact `9823339334`
  executed exactly 82 manifest nodes with no skips, failures, or errors.
  PLC9B4b accepted code adds strict Desired-CAS, dependency-pin, handoff, and
  settlement receipts plus a durable handoff CAS coordinator. Dependency pins
  precede Desired commit; rejection preserves the transaction pin; successful
  settlement proves exact dependency retention before transaction-pin release.
  All six handoff rows are executable, including post-settlement recovery and
  concurrent replay. The code remains dark and independent of concrete
  `plugin_management` ledgers; B4c epoch fencing and Product adapters remain
  closed. All 23 PR checks passed, and retained Linux artifact `9825049355`
  executed exactly 88 manifest nodes with no skips, failures, or errors.
  Accepted PLC9B4c0 code adds the dark adjacent epoch-fence journal and a
  read-only runtime admission owner over exact fence/root/protocol and complete
  active-lease evidence. Newer/older runtime epochs and mixed active epochs
  fail closed without journal or Product mutation, making `B-COMPAT-EPOCH` and
  `B-COMPAT-MIXED` executable. Native root cutover, offline restore, adoption,
  recovery convergence, and every Product route remain closed. Local
  `make check-harness` passed Ruff, mypy over 642 source files, and 3,824 tests
  with 23 expected skips. Candidate `18f0bab8` passed all 23 PR checks, and
  retained Linux artifact `9826705491` executed exactly 90 manifest nodes with
  no skips, failures, or errors.
  PLC9B4c1 accepted code adds a dark POSIX-native offline cutover owner over
  exclusive quiescence and snapshot Ports. It creates a fresh identity-pinned
  sibling namespace and treats the adjacent epoch-journal append as the sole
  atomic Product-root pointer; live pre-fence writers reject before native
  mutation. The two POSIX compatibility rows are executable, raising the
  Linux manifest to 92 nodes. Windows cutover, concrete restore/recovery,
  adoption, and all Product routes remain closed. Local `make check-harness`
  passed Ruff, mypy over 643 source files, and 3,837 tests with 23 expected
  skips; the focused regression passed all 142 tests. Candidate `e99945d2`
  passed all 23 PR checks, and retained Linux artifact `9828433273` executed
  exactly 92 manifest nodes with no skips, failures, or errors.
  PLC9B4c2 accepted code adds the symmetric dark Windows-native cutover owner.
  It reuses the exact B4c1 pathless schema and epoch visibility edge while
  preparing, identity-pinning, flushing, reopening, and cleaning the sibling
  namespace through rooted Windows handles. The two Windows compatibility
  rows are executable only in the mandatory Windows XML gate. Concrete
  restore/recovery, adoption, and all Product routes remain closed. Local
  `make check-harness` passed Ruff, mypy over 644 source files, and 3,837 tests
  with 33 expected skips; the focused regression passed 132 tests with the ten
  Windows-native component tests collected but skipped on Linux. Windows Shell
  Compatibility run `33584494760`, native job `100105659525`, and retained
  artifact `9829593062` then executed all 29 PLC9B native-component tests and
  all 14 Windows manifest nodes with zero skips, failures, or errors; all 23
  candidate PR checks passed.
  PLC9B4c3a accepted code adds the dark, pathless offline-restore protocol.
  It binds the exact current and genesis fences to complete pre-B snapshot
  evidence covering store bytes plus Source, lock/binding, Desired, Instance,
  enablement, root-pointer, and fence state. Exclusive quiescence encloses
  evidence lookup, isolated materialization, and old-runtime activation; fence
  drift deactivates and discards exact residue. Native restore and adoption
  remain unimplemented, so all seven remaining compatibility rows stay planned.
  Candidate `2fe7953a` passed all 23 PR checks; retained Linux artifact
  `9831701194` executed the unchanged 92 manifest nodes with zero skips,
  failures, or errors.
  PLC9B4c3b accepted code adds rooted POSIX snapshot verification, a
  request-bound current-B identity check, exact no-follow copying, durable
  same-request replay, atomic isolated namespace publication, and
  identity-bound discard behind the accepted offline-restore Port. The request
  and receipt remain pathless and no Product journal or public route is added.
  Its in-memory activation-Port composition is not a
  native process-start proof, so `B-COMPAT-OFFLINE-RESTORE-POSIX` remains
  planned and the Linux manifest remains at 92 nodes; Windows restore, concrete
  legacy process launchers, adoption, and Product binding remain closed.
  PLC9B4c3c accepted code adds one dark Linux/Bubblewrap activation adapter
  owned by `loushang.harness.sandbox`; the resource kernel remains backend-free.
  It verifies the durable restored tree and current-B identity, requires an
  application readiness handshake, proves the real sandbox child's namespaces
  and view of the restored/B roots through procfs, persists a private
  identity-bound process marker, and uses a guardian plus pidfds for exact
  replay/deactivation without worker-thread or PID-reuse races. The
  complete POSIX offline-restore row now executes as node 93 in the named Linux
  native gate; Windows restore, adoption, and Product routing remain closed.
  PLC9B4c4a accepted code freezes a dark, pathless legacy-adoption coordinator
  in the Package resource-owner kernel. Its versioned evidence binds an exact
  current fence and complete immutable legacy state around a separately owned
  B transaction, and it accepts only an exact committed Plugin-bound receipt
  while the fence and legacy state remain unchanged. It owns no source,
  filesystem, process, publication, Product-state, or public-route capability;
  the concrete adapter and all five adoption manifest rows remain closed.
  PLC9B4c4b accepted code adds a one-operation adoption transaction adapter
  that sequences the existing closure, pin, staging/set, and commit owners. Its
  private execution binding may retain an opaque credential reference, while
  adoption requests/results stay pathless and credential-free. Shared-journal
  confirmation rejects invented phase results, and durable staging/commit
  replay skips prior effects. A bare transaction pin cannot reconstruct live
  verified candidates and therefore fails closed until a reacquisition seam is
  supplied. The adapter remains dark; native end-to-end acquisition and all
  five adoption manifest rows remain closed.
  PLC9B4c4c accepted code supplies that seam without adding ambient
  authority. The artifact and closure owners reopen and reverify the exact
  pinned attempt solely from durable authenticated-source, acquisition, Wheel,
  selection, and closure-plan evidence. Recovery never falls back to Source or
  resolver calls, does not append evidence or move lifecycle phase, and the
  adoption adapter replays the existing pin before ordinary staging/commit.
  Native end-to-end adoption and all five adoption manifest rows remain closed.
  PLC9B4c4d accepted evidence composes the positive adoption path through the
  production authenticated-acquisition, verification, closure, pin,
  POSIX-native Store, committed-set, commit, transaction, and adoption owners.
  It proves exact receipt replay, one physical Source request/pin/publication,
  a still-visible acquired pin, filesystem-recaptured legacy snapshot equality,
  unchanged Product-domain bytes, and no credential persistence. The positive
  `B-COMPAT-ADOPT` row now executes as Linux native node 94; the four
  failure/crash adoption rows, Windows restore, and Product routing remain
  closed pending their own retained evidence.
  PLC9B4c4e accepted evidence promotes the unauthorized and temporarily
  unavailable adoption Source paths as Linux native nodes 95 and 96. Both
  fail or retry at `acquiring`, replay without extra network work, leave no
  publication or bounded residue, and preserve independent revisioned Product
  projections plus the complete legacy snapshot. The two crash rows remain
  closed.
  PLC9B4c4f accepted evidence promotes crash-after-committed as Linux native
  node 97. A one-shot post-CAS crash yields no first receipt; restart and replay
  reauthorize the durable root and reconstruct the same receipt without
  repeating Source, pin, staging, settlement, or committed-set effects. The
  every-precommit crash row remains closed.
  PLC9B4c4g accepted evidence injects a one-shot crash after each of the nine
  durable pre-commit phases. A completely rebuilt Package owner graph resumes
  the same active attempt to one exact receipt without repeating Source, pin,
  staging, settlement, or committed-set effects. No interruption event is
  fabricated for a process that could not write one; explicit supervisor
  interruption and greater-epoch retry remain a separate lifecycle action.
  This promotes `B-COMPAT-ADOPT-CRASH` as Linux native node 98, so all five
  adoption rows are executable and nonskippable in the retained Linux gate.
  Candidate head `d961e9d9` passed all 23 PR checks. Harness Quality run
  `33701887340`, Linux job `100482733307`, and retained artifact `9873812228`
  executed all 98 Linux manifest nodes plus three authority/recovery guard
  tests with zero skips, failures, or errors; artifact upload digest
  `1822656d9150bd1b2ff602906ae229922bcc04527bec6a6f41f3edfb34934d98`.
  PLC9B4c5 accepted code adds the dark Windows rooted-handle peer of the
  accepted POSIX offline-restore materializer plus a separately owned
  zero-capability AppContainer/Job old-runtime activation adapter. It publishes
  one exact isolated namespace, proves restored-root reachability and current-B
  denial with the real process token, binds replay to native process identity,
  and reverses the process tree and granted authority. Five component cases and
  `B-COMPAT-OFFLINE-RESTORE-WINDOWS` run without skips in the mandatory Windows
  native XML gates.
  PLC9B4d accepted code closes fourteen remaining recovery, concurrency,
  cancellation, status, compatibility, no-execution, drift, and secret-
  persistence rows. Exact terminal replay stays read-only and fenced retry is
  the only roll-forward route for an interrupted pinned attempt.
  PLC9B5 accepted code adds one internal, capability-poor Product router for
  CLI, RPC, Session, startup, and operations provenance. Plugin-bound routes
  share one transaction Port; direct materialization and publication bypasses
  are durably refused. Its seven cross-platform nodes complete the 127-row
  PLC9B adversarial manifest without adding an author-SDK surface.
  Final candidate `fb0832d6` passed all 23 PR checks. Retained Linux run
  `33709473590`/artifact `9876413745` executed 119 manifest nodes plus three
  guards; Windows run `33709473605`/artifact `9876434660` executed 34 native
  component tests and all 15 Windows manifest nodes. All retained PLC9B XML
  reports recorded zero skips, failures, and errors.
- [PLC9C Local Worker Boundary](plugin-lifecycle-plc9c0-baseline.md) freezes the
  threat model and implements C1--C4's additive `local_worker` declaration,
  owner-only Process/Sandbox launch capability, bounded protocol/supervisor,
  durable attempt journal, and default-dark read-only Capability adapter. C5
  Product/native activation, author-SDK runtime owners, generation publication,
  and `remote_service` remain absent.
- [Plugin Authoring Guide](plugin-authoring-guide.md) documents the minimum
  stable Provider, Skill package, validation, and developer-conformance flows.
- [PAP4 Capability Admission Contract](plugin-capability-admission-pap4-contract.md)
  freezes exact Capability-owner admission and Product Provider selection.
- [Phase 5B Continuity Provider Foundation](continuity-provider-phase5b-contract.md)
  freezes portable read-only Provider contracts, Product lifecycle bridging,
  and the handoff requirements for later Plugin admission.
- [Phase 5C Continuity Provider Plugin Lifecycle](continuity-provider-phase5c-contract.md)
  implements the installed-Plugin declaration, exact owner-component
  lifecycle, sealed process composition, revocation linearization, durable
  recovery barrier, and Package cleanup handoff.
- [Phase 5D Continuity Mutation Foundation](continuity-mutation-phase5d-contract.md)
  implements exact deletion proposals, opaque Product authorization evidence,
  cancellation-safe settlement, and the lifecycle handoff required before an
  installed Plugin may expose mutation.
- [Phase 5E Installed Continuity Mutation Lifecycle](continuity-mutation-phase5e-contract.md)
  implements the durable Product deletion journal, generation-gated installed
  Provider adapter, startup recovery barrier, and explicit Coding binding.
- [Phase 5F Continuity Production Composition and Operations](continuity-production-phase5f-contract.md)
  binds that lifecycle to real Coding configuration, `--resume`, TUI stable
  references, canonical machine state, recovery diagnostics, retry, and
  process-owned shutdown.
- [RCP5 Resource Catalog Skill Convergence](resource-catalog-rcp5-contract.md)
  freezes the conservative, exact-generation typed Skill Consumer and the
  ordered deletion of legacy Skill/Resource peer authority. Its first slice is
  internal and does not authorize Product cutover.

These contracts refine the architecture only inside their stated versions and
implemented slices. An unimplemented Worker, Skill-action, remote-service, or
public SDK shape cannot be inferred from them.

## Baselines

- [PLC0 Baseline](plugin-lifecycle-plc0-baseline.md)
- [PLC1A Baseline](plugin-lifecycle-plc1a-baseline.md)
- [PLC9.0 Baseline](plugin-lifecycle-plc9-baseline.md)
- [PLC9.0 Owner And Peer Inventory](plugin-lifecycle-plc9-inventory.md)
- [Resource Catalog RCP0 Baseline](resource-catalog-rcp0-baseline.md)

Baselines freeze source and authority facts required by later contracts. Review
discussion and acceptance evidence belong to issue `#502`, its delivery PR,
and Git history; they are not maintained as parallel architecture documents.

## Runtime Boundaries That Remain Outside This Directory

Plugin contributions must integrate with these existing authorities rather
than reimplement them:

- [Capability Dependency And Mount Lifecycle](../capability-dependency-and-mount-lifecycle.md)
- [Product Capability Composition Core](../product-capability-composition-core.md)
- [Capability Variation And Replacement](../capability-variation-and-replacement-boundary.md)
- [Extension And Resource Generation Lifecycle](../extension-generation-lifecycle-boundary.md)
- [Extension Runtime Core](../extension-runtime-core-boundary.md)
- [Contribution Inventory](../contribution-inventory-boundary.md)
- [Effective Runtime Diagnostics](../effective-runtime-diagnostics-boundary.md)
- [Runtime Provenance](../runtime-provenance-boundary.md)
- [Capability Catalog](../capability-catalog.md)
- [Current Owner Map](../current-owner-map.md)
- [OEM Extension Architecture](../oem-extension-architecture.md)
- [Process Hosting Boundary](../process-hosting-boundary.md)
- [Sandbox Runtime Boundary](../sandbox-runtime-boundary.md)

They remain outside `plugin/` because their primary reason to change is their
own runtime domain. Moving them here would make Plugin appear to own the Graph,
Resource generations, process mechanics, or containment.

## Superseded Decisions

Superseded ARDs may remain in their owning domain as explicitly historical
decision records. Retired drafts, dated replacement designs, and review
transcripts are recovered from Git/issue history rather than kept as searchable
competitors. New Plugin work starts here and follows the exact owner documents
above.

## Placement Rule

Place a document in this directory when its primary subject is Plugin identity,
manifest/declaration, desired state, Plugin execution trust, authoring, Plugin
Instance lifecycle, or Plugin-to-owner admission. Keep a document with its
domain owner when Plugin is only one consumer of that boundary.

New documents must declare:

- whether they are architecture, an incremental contract, a delivery plan, or
  a baseline;
- current versus target implementation status;
- the sole writer for every new state;
- the architecture or owner boundary they refine; and
- which earlier document, if any, they supersede.
