# Plugin Lifecycle PLC9.0 Owner And Peer Inventory

## Status

- Source baseline: `1c104ce5`.
- Scope: source-backed starting inventory for PLC9.0.
- Effect: descriptive and test-frozen only; it grants no new runtime authority.
- Delivery boundary updated 2026-10-01: the Product owner ended pre-B
  workspace compatibility for the current Plugin architecture delivery. Rows
  below that describe migration `finalization`, old-release recovery, a
  downgrade window, or retention until PLC9E record the historical inventory;
  they are not current acceptance gates. Fresh and already-fenced B workspaces
  still require one Desired State writer. Unfenced pre-B inputs must refuse
  without persistent writes. See the accepted boundary in
  [Plugin Experience and PLC9 Closure Design](plugin-experience-and-plc9-closure-design.md).
- Companion decision:
  [Plugin Lifecycle PLC9.0 Baseline](plugin-lifecycle-plc9-baseline.md).
- PLC9B.0 refinement:
  [Safe Package Boundary Contract](plugin-lifecycle-plc9b-contract.md).
- PLC9D1 refinement:
  [Package GC Operator Projection Contract](plugin-lifecycle-plc9d1-contract.md)
  adds an internal all-revision read model over existing retention evidence.
  It grants no Store deletion or GC reservation authority.
- PLC9D2 refinement:
  [Dark Package GC Reservation Contract](plugin-lifecycle-plc9d2-contract.md)
  adds a durable, opt-in reference-writer fence. D3a composes its gate in
  Coding, but D2 itself grants no Store deletion authority.
- PLC9D3a refinement:
  [Writer Fence And Store Deletion Primitive](plugin-lifecycle-plc9d3a-contract.md)
  adds an explicit downgrade seal, irreversible reservation start, a durable
  handoff crosswalk, and dark Store-owned rooted deletion primitives. It does
  not add a Product GC route or a durable deletion result/debt receipt.
- PLC9D3b refinement:
  [Store GC Re-publication Fence](plugin-lifecycle-plc9d3b-contract.md)
  adds a Store-owned exact-ref tombstone before rooted deletion. Store replay
  excludes previous codecs and refuses re-staging, but no Product GC command
  or settled result/debt receipt exists.
- PLC9D3c refinement:
  [Exact Root GC Target Resolution](plugin-lifecycle-plc9d3c-contract.md)
  joins a durable precommit claim, confirmed Product handoff, committed set,
  and exact Store settlement only when identities and aliases are proven. It
  is a read-only checker, not an atomic capture or deletion authority. The
  internal claim audit distinguishes pending, failed, and missing-binding
  debt but has no release capability.
- PLC9D3d refinement:
  [Committed-Set Root Ref Fence](plugin-lifecycle-plc9d3d-contract.md)
  adds a Package-owner tombstone for one exact committed set/root ref and
  excludes previous codecs. The future executor must sequence it after a
  Product deletion start and before the Store tombstone.
- PLC9D3e refinement:
  [Durable GC Result And Retry Debt](plugin-lifecycle-plc9d3e-contract.md)
  adds a journal for exact-start Store results, retryable errors, and
  non-retryable Store collisions, with exact-settlement result matching; no
  coordinator was activated by this slice.
- PLC9D3f/D3g refinement:
  [Internal Root GC Execution](plugin-lifecycle-plc9d3f-contract.md) and
  [Explicit Product Root GC Command](plugin-lifecycle-plc9d3g-contract.md)
  join the exact candidate, reservation, root Store deletion, and durable
  result in a POSIX-tested Product owner graph. The command is explicitly
  composed; no default management or transport route selects it.
- PLC9D3h refinement:
  [Root GC Result Projection](plugin-lifecycle-plc9d3h-contract.md) joins
  active reservations, exact Store settlements, result attempts, and both
  root tombstones. It refuses to project success if their evidence diverges.
- PLC9D3i refinement:
  [Fenced Product Root GC Composition](plugin-lifecycle-plc9d3i-contract.md)
  binds the real B Product owners and exact POSIX Store behind an explicit
  offline, no-active-Session gate. No default transport route selects it.
- PLC9D3j refinement:
  [Offline Root GC Command](plugin-lifecycle-plc9d3j-contract.md) selects
  that owner through a declared POSIX operator CLI with separate prepare,
  candidate/status, exact delete, and durable-start retry actions.
  A local fenced Coding Product regression also installs and enables an
  external Skill v1, updates it to v2, deletes only the retained v1 root,
  and confirms a new Session can still select v2. This is root-version
  evidence, not shared-dependency GC or Windows Product evidence.
  The offline Product projection groups dependency refs across committed sets
  and treats a holder as released only after a verified root GC success. An
  orphan is joined to one exact dependency Store settlement and committed
  publisher. The POSIX Product owner now persists an exact dependency deletion
  start before the role-specific Store effect, records its result or failure disposition, and replays a started deletion
  after physical removal. Store collision or untrusted-root failure is terminal
  debt; ordinary retry returns the recorded attempt without another Store call. The operator
  CLI exposes exact dependency delete/retry and pathless status. A configured
  Linux local-Wheel Product regression proves the single-holder crash path and
  refuses a live holder, mismatched settlement, or active runtime. Its second
  dependency-bearing version is rejected by Product update admission even
  when both Wheels appear in policy. New POSIX dependency refs use a content
  revision; a separate configured Product regression installs two different
  Plugins over one physical dependency tree and proves GC waits for both root
  deletion results. Legacy operation-bound ref records remain readable.
  The Windows Store adapter now mirrors content refs, alias settlement,
  dependency deletion, a non-repairing read-only verified root-member owner,
  and exact-root adoption authorization. The Windows cutover owner has a
  source-free fenced reopen candidate that rechecks the selected native root.
  A narrow Product epoch owner now retains that fence and a native runtime
  lease registry, prepares pinned state/Source roots, and rejects a changed
  selected root or live local lease on close. Candidate native ACL admission
  now requires the control, state, and Source directories to have a protected
  DACL with exactly the current user and SYSTEM; directory creation supplies
  that descriptor explicitly and open/recheck requests `READ_CONTROL`. An
  explicit native control-root preparation function creates a missing root
  with this ACL or refuses an existing root with extra trustees; it never
  repairs an existing ACL silently. Native tests include an extra-trustee
  tamper case, but these tests have not run on Windows and the Coding Product
  route does not yet call this preparation function. Coding's Product state
  opener now accepts the fenced Windows owner and a native test uses the real
  Coding layout to open its GC, Desired State, management, Worker opt-in, and
  private-data confirmation journals. The Windows Product owner now issues an
  exact Session lease only after the runtime admission reader accepts the
  current fence and live native lease; a failed admission releases its handle.
  A Windows Product transaction guard now holds the registry's native
  coordination lock through admission and effects, reads a nested lease
  snapshot under that lock, and refuses nested mutation. Windows journal locks
  currently serialize these Product transactions; throughput and native
  behavior need acceptance evidence before default selection. A B-to-B cutover
  coordination adapter now supplies quiescence from the same lock and refuses
  an active Product lease; it deliberately requires an existing fence and does
  not claim first-B legacy registration authority. A separate Windows
  pre-fence owner now holds native per-startup liveness locks under that
  control directory and excludes new launches while first-B cutover reads the
  active set. Coding's legacy Session startup, management writer, and
  Continuity bootstrap now acquire the pre-fence registration before
  preparing lifecycle state; native tests cover the startup and management
  paths. The first-B
  coordinator refuses unexpected runtime lease history. These candidate
  paths have not run on Windows, and the Windows first-B Product command,
  Coding Session factory, and GC execution remain unbound.
  Store native sharing, tombstone,
  tamper, read, journal-corruption, root-replacement, file-swap, and adoption
  cases authored but no retained Windows
  execution for them. Ordinary Coding dependency-Wheel
  admission, Windows Product Session/GC composition, and broader dependency debt repair
  policy remain open.
  A separate Windows-native runtime lease registry candidate now uses a pinned
  control root, native liveness locks, and the existing lease record format.
  Its registration, release, quiescence, unfenced refusal, crash-orphan
  repair, and partial-journal refusal tests are selected by the mandatory
  Windows native workflow but skipped on Linux. It is not yet bound to the
  Windows Product runtime or accepted by a retained native Windows run.
- PLC9D3k refinement:
  [Private-Data Confirmation And Backup Projection Seams](plugin-lifecycle-plc9d3k-contract.md)
  adds separately authorized domain delegation and a conditional backup-owner
  read projection. Neither production data nor backup owner is bound.
- PLC9D3l refinement:
  [Durable Private-Data Confirmation Evidence](plugin-lifecycle-plc9d3l-contract.md)
  adds replayable exact-plan confirmation records for the D3k authority Port.
  The journal is fixed to the fenced Coding Product's private state root;
  no Product operator command or real data-domain owner is bound.
- PLC9D3m refinement:
  [Cutover Backup Status Projection](plugin-lifecycle-plc9d3m-contract.md)
  verifies a real pre-B workspace snapshot under the current Product fence.
  This workspace evidence cannot stand in for Plugin-level backup retention.
- PLC9B1 refinement: the dark internal Owner Kernel now supplies versioned
  inert records, classification, journal CAS, retry/cancel/status, and disabled
  refusal. It has no production composition or artifact capability; all
  acquisition/publication target rows below remain migration obligations.
- PLC9B2a/B2b/B2c/B2d/B2e/B2f refinement: unbound Source
  Authority/bounded-sink/quarantine, safe wheel inspection, dark
  phase-CAS/evidence composition, and cleanup-domain tombstones exist inside
  the same Package owner boundary. Raw ZIP-layout, path/type/budget,
  WHEEL/METADATA/RECORD, and rooted
  POSIX extraction proofs now precede materialization. Adjacent operation
  phases, typed acquisition/wheel evidence, exact cleanup repair, and rooted
  acquired/verified crash adoption are append-once or exactly replayable.
  Recovery reconstructs process-local candidates from durable local evidence
  without Source reauthorization. A Package-local `NtCreateFile` rooted-handle
  backend and non-skippable native Windows fixture set were accepted by
  Windows Shell Compatibility run `33486925218` at head `fb263301`: five tests
  ran with zero skips, failures, or errors, and their XML was retained in
  artifact `windows-shell-pytest-reports` (ID `9792151355`).
  PLC9B2g implements six composed acquisition manifest fixtures, accepted by
  Linux Harness Quality run `33487861156`: its report executed 14 total nodes
  with zero skips, failures, or errors and was retained as artifact
  `plc9b-linux-native-pytest-report` (ID `9792500305`).
  PLC9B2h implements 24 composed archive/path/type/limit/wheel manifest rows,
  accepted by Linux Harness Quality run `33489524268`: 38 total nodes ran with
  zero skips, failures, or errors and artifact `9793161479` retained the XML.
  Wheel ZIP has no portable hardlink relation encoding; PLC9B2k therefore uses
  a real POSIX hardlinked source and proves the Wheel 1.x boundary normalizes it
  to independent regular archive and extracted entries rather than claiming a
  surrogate hardlink encoding. Linux Harness Quality run `33493714647`
  accepted that native row after all 52 manifest nodes passed without skips,
  failures, or errors; artifact `9794816942` retained the XML.
  PLC9B2i accepts seven exact Windows archive path/type fixtures after their
  dedicated non-skippable Windows 2022 report passed and its XML was retained;
  no simulated platform evidence promotes a native row.
  PLC9B2j accepts six exact Linux-native artifact-identity, early-crash, and
  cleanup-debt fixtures after the persisted non-skippable Linux report passed
  all 51 manifest nodes without skips, failures, or errors.
  PLC9B3a adds an accepted unbound pure closure-v2 verifier over typed Source,
  acquisition, and wheel evidence. It deterministically proves PEP 508 marker/
  specifier decisions, origin/digest binding, graph completeness, acyclicity,
  canonical identity, and composed budgets, but owns no I/O, pin, store,
  journal, publication, or transport capability. Its component fixtures do not
  promote global manifest rows. Harness Quality run `33497159996` accepted the
  component after Ruff and mypy passed and the full gate reported 3624 passed,
  20 skipped.
  PLC9B3b is an accepted dark slice that records attempt-scoped authenticated
  Source evidence before quarantine transfer, requires exact Source
  reauthorization when only that evidence survived, and reconstructs canonical raw
  `Requires-Dist` inputs by re-verifying the digest-bound Wheel `METADATA`.
  Accepted receipt and wheel-evidence v1 schemas remain unchanged; legacy
  receipt-first evidence can replay B2 behavior but is insufficient for
  closure-v2. Harness Quality run `33501681463` accepted the slice after all
  PR checks passed; its retained Linux manifest XML executed the same 52 tests
  with zero skips, failures, or errors. No global manifest row is promoted.
  PLC9B3c is an accepted dark recursive builder. Its resolver is selection-only;
  every selected node still traverses Source Authority, bounded acquisition,
  Wheel verification, and ordered artifact evidence before the accepted pure
  closure verifier decides the complete graph. It handles late extra expansion,
  digest-bound `Requires-Python`/`Provides-Extra`, and aggregate budgets, but
  has no phase/selection/plan journal, recovery, cleanup-debt integration,
  stable refs, pins, publication, desired-state mutation, or production route.
  Harness Quality run `33505702666` accepted the component after all PR checks
  passed; retained artifact `9799493328` executed the unchanged 52-row Linux
  manifest with zero skips, failures, or errors. Its component fixtures do not
  promote global manifest rows.
  PLC9B3d-1 accepted dark code binds a complete credential-free resolution basis
  before artifact I/O, journals every resolver selection before dependency
  Source access, journals the exact verified plan before the closure phase CAS,
  reopens durable dependency evidence without resolver or Source calls, and
  transfers dependency cleanup debt to the existing cleanup-domain owner. It
  remains dark. B3d-1 accepts the two resolving/closure crash rows after all PR
  checks passed and retained artifact `9802403797` executed exactly 54 native
  manifest nodes with zero skips, failures, or errors; the closure/limit rows
  were still planned at that acceptance point. B3d-2a accepts the three
  composed closure-limit rows with real root evidence and a dependency
  selection after all PR checks passed and retained artifact `9803312387`
  executed exactly 57 native manifest nodes with zero skips, failures, or
  errors. B3d-2b accepts all seven closure-integrity rows, including
  cleanup-debt custody for every rejected candidate, after all PR checks passed
  and retained artifact `9805712792` executed exactly 64 native manifest nodes
  with zero skips, failures, or errors.
  PLC9B3e-1 accepted code adds internal strict typed root/dependency refs, an
  immutable closure lock that reconstructs and revalidates the accepted v2
  plan, and one exact committed-set ref. It has no store or retention-ledger
  import, live pin, staging writer, atomic publication, admission, desired-state
  effect, or production route. No global adversarial row is promoted.
  All PR checks passed and retained artifact `9806065559` executed the
  unchanged 64 native manifest nodes without skips, failures, errors, or any
  `B-PUB-*` node.
  PLC9B3e-2a accepted code adds exact credential-free transaction-pin
  targets/requests/receipts, a narrow retention Port, and a durable owner-side
  evidence journal. It has no concrete retention-ledger import or runtime phase
  composition and promotes no manifest row. All PR checks passed and retained
  artifact `9807880155` executed the unchanged 64 native manifest nodes without
  skips, failures, errors, `B-CRASH-PINNED`, or any `B-PUB-*` node.
  PLC9B3e-2b accepted code composes the narrow retention Port with durable
  closure evidence and `closure_verified -> transaction_pinned` CAS. It adds
  candidate-free restart recovery and implements the composed
  `B-CRASH-PINNED` row. All PR checks passed and retained artifact `9810291887`
  executed exactly 65 native manifest nodes with zero skips, failures, or
  errors and no `B-PUB-*` node. Staging, publication, later transaction phases,
  and every production route remain migration obligations.
  PLC9B3e-3a accepted code now separates a neutral dependency staging Port
  from the designated Plugin-root staging Port, binds the latter to an
  authority-issued logical Product/scope/Installation/Plugin target, and
  journals exact typed staging receipts beside the Package transaction. A
  separate Package-owner journal atomically appends the complete immutable
  closure lock and its sole committed-set ref. These are dark contracts and
  local evidence only: no concrete store, phase runtime, admission, desired
  state, public facade, or production route imports them, and no global
  manifest row is promoted. All PR checks passed and retained artifact
  `9812156268` executed the unchanged 65 native manifest nodes without skips,
  failures, errors, `B-CRASH-STAGING`, `B-CRASH-SET`, or any `B-PUB-*` node.
  PLC9B3e-3b accepted code composes the accepted Ports and journals behind
  `transaction_pinned -> staging -> set_published` CAS. It validates every live
  candidate against the durable plan, stages dependencies before the Plugin
  root, adopts only exact prior-attempt receipts, rechecks classification before
  atomic set publication, and supports candidate-free resume/recovery. The
  composed `B-CRASH-STAGING` and `B-CRASH-SET` rows are executable; concrete
  store materialization, native publication-root defenses, admission, desired
  state, and production routing remain absent. All PR checks passed and
  retained artifact `9813586958` executed exactly 67 native manifest nodes
  without skips, failures, errors, or any `B-PUB-*` node.
  PLC9B3e-3c0 accepted code adds a strict files-only transfer manifest bound
  to exact Wheel evidence and separates quarantine-owned byte transfer from
  dependency-store and designated Plugin-root sink authorities. These are
  dark records and Protocols only: there is no transfer loop, concrete Store,
  native publication root, stable-ref issuance, admission, or production
  route. All 13 `B-PUB-*` rows remain planned; `B-PUB-UNCOMMITTED` stays with
  PLC9B4 commit admission rather than physical materialization. All PR checks
  passed and retained artifact `9815136763` executed the unchanged 67 native
  manifest nodes without skips, failures, errors, or any `B-PUB-*` node.
  PLC9B3e-3c1 accepted code implements the quarantine-owned identity-checked
  verified-file reader, bounded transfer owner, and separate POSIX-native
  dependency/Plugin-root Store adapters. Store operations pin and revalidate
  the complete visible ancestor chain, use descriptor-relative no-follow
  creates, sync and settle one immutable tree, fully hash exact reuse, and
  close every native handle on success or refusal. Five POSIX
  publication/root/handle rows are executable through the full dark lifecycle;
  Windows native publication, collision/reuse, commit admission, and production
  routes remain later gates. All PR checks passed and retained artifact
  `9817127845` executed exactly 72 manifest nodes with zero skips, failures, or
  errors and included exactly the five implemented POSIX publication rows.
  PLC9B3e-3c2 accepted code adds the two role-separated Windows-native Store
  adapters. They pin and revalidate the full visible ancestor chain, reject
  reparse/root/ancestor/staging ABA, flush each verified file, and settle by a
  non-replacing handle-relative rename before fully rehashing the final tree.
  The retained native artifact `9818964189` executed 15 component tests and 12
  manifest nodes with zero skips, failures, or errors, including all five
  Windows publication/ABA/handle rows. Collision/reuse, commit admission, and
  production routing remain later gates.
  PLC9B3e-3c3 accepted code adds Store-private durable settlement evidence to
  both native Store adapters. A pre-rename record binds the complete Store-root
  chain, final tree and member identities, exact manifest, and exact receipt;
  a cross-instance owner lock serializes namespace settlement. Restart can
  recover a renamed tree or validate an exact receipt without a live candidate
  and without another journal append, while same bytes under a different
  native identity fail as `package_publication_collision`. The accepted slice makes
  `B-PUB-COLLISION` and `B-PUB-REUSE` executable; only
  `B-PUB-UNCOMMITTED` remains planned among publication rows. It adds no public
  facade, commit-admission route, binding, desired-state mutation, or Product
  runtime composition. All 23 PR checks passed; retained Linux artifact
  `9821924161` executed 74 manifest nodes and retained Windows artifact
  `9821946893` executed 19 native component tests plus 12 manifest nodes, all
  with zero skips, failures, or errors.
  PLC9B4a accepted code closes the logical commit-admission boundary without
  opening a Product route. A sole commit owner validates the exact terminal
  set and live transaction pin before appending `committed`; its immutable
  receipt is deterministically recoverable from those durable journals. A
  separate read-only admission owner reprojects and compares operation/request,
  Product/scope, Installation/Plugin, designated root, set, closure, and pin
  evidence. It returns no path, runtime handle, store capability, binding, or
  desired-state authority. `B-PUB-UNCOMMITTED` and all seven `B-ADMISSION-*`
  threats are executable; B4b retention handoff and B4c epoch fencing remain
  later gates. All 23 candidate checks passed; retained Linux artifact
  `9823339334` executed exactly 82 manifest nodes with zero skips, failures, or
  errors and contained all eight B4a rows.
  PLC9B4b accepted code adds the dark retention-handoff record family,
  strict handoff CAS journal, and coordinator over read-only admission plus
  narrow Desired-CAS and Retention-settlement Ports. It proves dependency pins
  exist before Desired commit, preserves the transaction pin on rejection,
  and releases it only with a receipt that keeps the exact dependency set
  live. All six `B-HANDOFF-*` threats are executable, including settlement-to-
  projection crash recovery and concurrent replay. It imports no concrete
  management ledger, exports no public symbol, and leaves B4c epoch fencing,
  Product routing, and explicit legacy adapters as later gates. All 23 PR
  checks passed; retained Linux artifact `9825049355` executed exactly 88
  manifest nodes with zero skips, failures, or errors and contained all six
  B4b rows.
  Accepted PLC9B4c0 code adds an evidence-only adjacent epoch-fence journal,
  credential-free active-runtime lease snapshots, and read-only runtime
  admission. Exact fence/root/protocol mismatch is rejected before consulting
  leases; any active different-epoch/root lease rejects without mutation.
  `B-COMPAT-EPOCH` and `B-COMPAT-MIXED` are executable. The code owns no
  pathname or native switch capability and leaves POSIX/Windows cutover,
  offline restore, adoption, recovery convergence, and Product routing as
  later gates. Local `make check-harness` passed Ruff, mypy over 642 source
  files, and 3,824 tests with 23 expected skips. Candidate `18f0bab8` passed
  all 23 PR checks; retained Linux artifact `9826705491` executed exactly 90
  manifest nodes with zero skips, failures, or errors and contained both B4c0
  compatibility rows.
  PLC9B4c1 accepted code adds the dark POSIX-native offline cutover owner. An
  exclusive quiescence Port rejects live fence-aware or pre-fence writers
  before snapshot or path access. On success the owner pins the configured
  authority chain, creates and flushes a fresh identity-bound sibling epoch
  namespace, and uses the single adjacent epoch append as the only atomic root
  pointer. Precreated namespaces and authority swaps fail closed; exact replay
  performs no second snapshot or append. The two POSIX cutover rows are
  executable, so the Linux manifest now collects 92 nodes. Windows cutover,
  concrete backup/restore, recovery convergence, adoption, and every Product
  route remain closed. Local `make check-harness` passed Ruff, mypy over 643
  source files, and 3,837 tests with 23 expected skips; the focused component,
  manifest, and architecture regression passed all 142 tests. Candidate
  `e99945d2` passed all 23 PR checks; retained Linux artifact `9828433273`
  executed exactly 92 manifest nodes with zero skips, failures, or errors and
  contained both POSIX cutover rows.
  PLC9B4c2 accepted code adds the corresponding dark Windows-native cutover
  owner. It keeps one cross-platform pathless wire schema and one adjacent
  epoch pointer, but replaces every native path operation with rooted Windows
  directory handles, complete ancestor identity pins, direct-child creation,
  directory flushes, exact visible-child reopening, and identity-bound empty
  cleanup. `B-COMPAT-CUTOVER-WINDOWS` and
  `B-COMPAT-PREFENCE-LIVE-WINDOWS` now belong to the mandatory Windows native
  gate. Concrete backup/restore, recovery convergence, adoption, and every
  Product route remain closed. Local `make check-harness` passed Ruff, mypy
  over 644 source files, and 3,837 tests with 33 expected skips; the focused
  Linux regression passed 132 tests and collected the ten Windows-native
  component tests as explicit platform skips. Candidate `3d5d4394` passed all
  23 PR checks; retained Windows artifact `9829593062` executed exactly 29 PLC9B
  native-component tests and 14 manifest nodes, including both B4c2 rows, with
  zero skips, failures, or errors.
  PLC9B4c3a accepted code adds strict offline-restore request, complete
  snapshot-evidence, materialization, legacy-runtime activation, failure, and
  result records plus one dark coordinator. The snapshot evidence has a
  separate exact tree digest and closed complete-state coverage instead of
  treating the B4c1 opaque snapshot ID as content identity. The coordinator
  holds exclusive quiescence across evidence lookup, isolated restore, and
  exclusive old-runtime activation, rechecks the immutable epoch chain around
  both effects, and performs exact deactivation/discard on drift. It imports no
  native backend, process launcher, Product state owner, or public route;
  POSIX/Windows restore and all adoption manifest rows remain planned. Candidate
  `2fe7953a` passed all 23 PR checks; retained Linux artifact `9831701194`
  executed exactly 92 manifest nodes with zero skips, failures, or errors.
  PLC9B4c3b accepted code adds the dark POSIX-native snapshot-to-restore
  materializer behind the accepted pathless Port. It owns disjoint pinned
  snapshot, restore, and current-B authorities, binds the latter to the
  request's fenced-root identity, and validates one canonical complete-state
  manifest plus the exact payload tree, rejects links/special members, copies
  through rooted no-follow descriptors, and publishes one isolated namespace
  through a flushed atomic no-replace edge. A rooted cross-process lock and
  strict receipt marker make exact replay converge; identity-bound cleanup
  refuses foreign or changed trees. The composition fixture uses the accepted
  activation Port but does not launch an old process, so the complete POSIX
  offline-restore row remains planned and the Linux native gate remains at 92
  nodes. POSIX and Windows launchers, Windows restore, all adoption work,
  recovery composition, and Product routing remain closed.
  PLC9B4c3c accepted code adds the concrete Linux/Bubblewrap activation
  adapter under `loushang.harness.sandbox`, behind the accepted pathless Port;
  the resource kernel remains backend-free. A private cross-process lock admits
  one sandbox profile and one live old-runtime process, while readiness, procfs
  namespace/root identity checks, guardian lifetime, pidfd signalling, exact
  replay, and bounded deactivation make
  `B-COMPAT-OFFLINE-RESTORE-POSIX` executable in the mandatory Linux gate. The
  Linux manifest therefore advances from 92 to 93 nodes. The activation path
  remains dark; Windows restore, adoption, recovery convergence, and Product
  routing remain closed.
  PLC9B4c4a accepted code adds the dark, pathless legacy-adoption protocol to
  the resource-owner kernel. It binds an exact current fence and complete
  immutable legacy-state observation around one narrow, separately owned B
  transaction Port, accepts only the exact committed Plugin-bound publication,
  and preserves typed terminal failures. It exposes no locator, credential,
  path, native handle, Product state, or production capability. A concrete
  transaction adapter, all five adoption manifest rows, Windows restore,
  recovery convergence, and Product routing remain closed.
  PLC9B4c4b accepted code composes the existing closure, transaction-pin,
  staging/set, and commit owners behind the pathless adoption transaction Port.
  The adapter is a one-operation private capability: it may retain an opaque
  credential reference in its execution binding, but returns only the existing
  credential-free lifecycle/publication evidence. Exact journal confirmation
  follows every phase owner, and durable staging/commit phases resume without
  repeating prior effects. A bare transaction pin fails closed because it
  cannot reconstruct live verified candidates. Tests use real
  lifecycle/pin/set/commit evidence but deterministic closure and staging
  Ports, so all five adoption rows, native end-to-end acquisition, Windows
  restore, and Product routing remain closed.
  PLC9B4c4c accepted code adds explicit recovery-only `reacquire` seams to the
  artifact, recursive-closure, and closure-lifecycle owners. An active pinned
  attempt can now reconstruct live verified candidates from exact durable
  evidence without Source or resolver fallback, journal append, or lifecycle
  movement; the adoption adapter replays the same durable pin and continues the
  accepted staging/commit sequence. Missing or changed evidence fails closed.
  The seams remain dark, and native end-to-end adoption plus all five adoption
  manifest rows remain closed.
  PLC9B4c4d accepted evidence composes the positive legacy-adoption path from
  the production lifecycle, authenticated acquisition, quarantine, Wheel,
  closure, pin, POSIX-native Store, committed-set, commit, transaction, and
  adoption owners. Durable fence reads and filesystem-backed legacy-state
  recapture bracket both initial adoption and exact replay; the pin remains
  visible and all legacy/Product-domain bytes remain unchanged. Only
  `B-COMPAT-ADOPT` is promoted, increasing the Linux native manifest from 93
  to 94 nodes. The four adoption failure/crash rows, Windows restore, recovery
  convergence, and Product routing remain closed pending their own evidence.
  PLC9B4c4e accepted evidence executes authenticated Source refusal and
  bounded network unavailability through the same native adoption composition.
  Exact replay performs no extra network call, pin, staging, settlement, set,
  or publication effect, while legacy and four independently revisioned Product
  projections remain exact. The Linux native manifest therefore grows from 94
  to 96 nodes; the two crash rows remain closed.
  PLC9B4c4f accepted evidence adds the post-commit-CAS crash edge. Recovery
  and replay require the durable root target and native root identity, return
  one exact receipt, and do not repeat Source, pin, staging, settlement, or
  committed-set effects. This promotes Linux native node 97; only the
  every-precommit crash row remains closed.
  PLC9B4c4g accepted evidence exercises every durable pre-commit adoption
  phase by reconstructing the complete Package owner graph over durable
  evidence. Recovery resumes the same active attempt and converges on one exact
  receipt without repeated Source, pin, staging, settlement, or committed-set
  effects. It does not fabricate an interruption event for a dead process;
  explicit supervisor interruption and greater-epoch retry stay separate. This
  promotes Linux native node 98 and makes all five adoption rows executable and
  nonskippable in the retained Linux gate.
  Candidate head `d961e9d9` passed all 23 PR checks. Harness Quality run
  `33701887340`, Linux job `100482733307`, and retained artifact `9873812228`
  executed all 98 Linux manifest nodes plus three authority/recovery guard
  tests with zero skips, failures, or errors; artifact upload digest
  `1822656d9150bd1b2ff602906ae229922bcc04527bec6a6f41f3edfb34934d98`.
  PLC9B4c5 accepted code adds a dark Windows rooted-handle snapshot-to-restore
  adapter and a separately owned zero-capability AppContainer/Job activation
  adapter behind the accepted pathless Ports. It pins the snapshot, restore,
  and current-B ancestor chains, validates the complete canonical bundle,
  atomically publishes one isolated namespace, proves restored-root access and
  current-B denial with the process token, and reverses the exact process/ACL/
  profile authority. Five native component cases and the composed Windows
  offline-restore manifest row are mandatory and nonskippable. Recovery/state/
  no-execution and Product routing close in the adjacent B4d/B5 slices.
  PLC9B4d accepted code closes fourteen recovery, concurrency, cancellation,
  status, compatibility, no-execution, classification-drift, and secret-
  persistence rows. Exact committed replay is read-only, same-operation callers
  converge, stale attempts cannot alter the winner, and an interrupted pinned
  attempt rolls forward only under a greater fenced attempt epoch.
  PLC9B5 accepted code adds one capability-poor internal Product router for
  CLI, RPC, Session, startup, and operations provenance. All five Plugin-bound
  routes call only one injected transaction Port; direct materializer and
  publication attempts are durably refused without peer capability. Seven
  platform-neutral route rows make every PLC9B adversarial manifest row
  implemented while keeping the adapter out of the author SDK.
  Final candidate `fb0832d6` passed all 23 PR checks. Retained Linux run
  `33709473590`/artifact `9876413745` executed 119 manifest nodes plus three
  guards, while Windows run `33709473605`/artifact `9876434660` executed 34
  native component tests and all 15 Windows manifest nodes. Every retained
  PLC9B report recorded zero skips, failures, and errors.
- PLC9B Product transaction candidate:
  `resources/packages/product_transaction.py` composes the existing closure,
  transaction-pin, staging-set, commit, and Product handoff owners behind the
  B5 router. Local Linux-native tests send each of the five transport
  provenances through a real rooted Store, durable Package owner, and desired
  state ledger. A route-bound wheel execution factory derives operation,
  attempt, filename, and environment evidence for each request; unsupported
  non-wheel Sources receive a durable refusal before Source or Store access.
  Product issues the designated root target from exact classification and a
  stable Product/scope/Plugin Installation identity, then projects the
  installable revision from the exact
  committed-set root and refuses a handoff with a changed scope. The Product
  router requires a committed-handoff capability at
  composition, and committed replay completes a handoff interrupted before its
  first journal event. An admitted startup recovery can also scan durable
  committed requests and complete that pre-journal handoff under the shared
  epoch guard before activation. Ordinary startup recovery now also runs only
  after a preflight epoch admission and under that guard, with a second
  admission check before activation; its Product factory binding is still pending.
  A Linux rooted runtime-lease registry candidate now journals registration,
  release, and explicit orphan repair while holding per-lease OS liveness locks.
  Its complete active snapshot can feed the existing runtime-admission owner;
  the rooted Product guard shares its epoch coordination lock. An exclusive
  runtime-quiescence scope keeps the complete live set stable through a cutover
  attempt and refuses orphaned evidence, but does not claim pre-fence process
  quiescence. A POSIX cutover coordination candidate now combines that scope
  with a mandatory Product-owned pre-fence launch barrier; a native cutover
  refuses an active old-process registration before asking for a snapshot.
  The concrete pre-fence owner, real backup snapshot owner, Coding runtime
  registration, Product factory ownership of the admitted root/guard, and a
  Windows-native lease owner remain pending.
  A direct-materializer route and a changed execution
  identity reach neither Source nor Store. This is not a Coding production
  cutover: no Windows native transaction acceptance exists, and the legacy
  materializer callers listed below remain live.
- PLC9C1--PLC9C4 implementation candidate:
  [Local Worker Boundary](plugin-lifecycle-plc9c0-baseline.md) retains the
  accepted threat model and implements the additive declaration topology,
  owner-only launch capability, bounded protocol/supervisor, durable attempt
  journal, and one default-dark read-only Capability query adapter from base
  `90f6a9de`. It adds no Product activation/native IPC binding, author-SDK
  runtime owner, generation publication/retirement authority, PLC9D cleanup,
  PLC9E deletion, or remote-service topology.
- PLC9C third-party implementation candidate:
  [Third-Party Local Worker Admission](plugin-lifecycle-plc9c-third-party-admission.md)
  specifies the selected-Wheel, Product decision, native-containment, and
  recovery gates still needed beyond the exact C5.5c canaries. An inert file-set
  verifier rejoins exact Worker reservation, declaration, and executable bytes
  into pathless candidate facts. A read-only Product adapter can rejoin those
  facts to a previously selected manifest and check bounded ELF/PE header shape.
  An explicit Linux Product policy now admits one deterministic, internally
  authored native Worker Wheel through the real Package transaction and
  selected-root reader; the Product
  refuses disabled/stale selection and several changed Wheel shapes. An
  internal Coding policy derives a default-dark Worker decision from the
  selected revision. A Product-private, descriptor-rooted opt-in journal now
  records allow/revoke decisions under the shared GC gate with CAS, exact
  replay, and kill-switch generations. An internal Product receipt owner now
  persists and rechecks a receipt against that decision, the selected Wheel,
  Product-bound Session/runtime identities, and a gate-bound native closure
  read port; real Product evidence refuses forged, revoked, native-changed, and
  superseded receipts. The internal factory now derives the selected Transcript
  file, Session ID, and workspace from a persisted Coding Session owner; a
  Product regression refuses an unmaterialized Session or different file.
  A real Transcript Directory reader now rechecks one
  resumed Session on each witness and refuses missing, conflicting, incomplete,
  unreadable, or reconfigured discovery; a Product receipt regression
  invalidates the selected-route receipt after the transcript disappears.
  This reader is an
  internal adapter and is not yet composed into the default Session route.
  A v2 Product regression
  serializes a concurrent Desired
  State disable against receipt admission and refuses the receipt afterward.
  The real offline Product GC refuses deletion while a Worker Session is live;
  after its leases close it deletes only the retired v1 executable root, and a
  fresh Product Session can select preserved v2. A separate internal Coding
  Worker Source catalog pins a Linux candidate's bytes and exact admission
  identity, and only an explicitly opened Product owner imports that binding.
  An internal selected-Worker receipt factory captures the current Product
  manifest and checks the runtime's Desired State, crosswalk, and GC gate owner
  identities before binding the opt-in journal and required Transcript reader
  to the selected Session file. A real catalog Product regression rejects a
  foreign owner and a different Transcript file, issues a receipt
  only for a discovered Session after enable and opt-in, then invalidates it on
  disable. The factory does not issue a new-Session route without separate
  Transcript ownership proof.
  Ordinary Coding Sessions remain default-dark; the catalog refuses changed
  source decisions, altered controlled bytes, and a symlinked journal. A
  dependency-bearing v2 candidate with a configured dependency Wheel reaches
  Product candidate admission, is rejected, and leaves v1 selected. There
  is now an internal Linux Product one-shot installer for an approved native
  release Wheel under the fixed private state root. It retains the source Wheel
  and scoped receipt, rejects an unsettled staging directory, reopens exact
  installs, and invalidates a selected Worker receipt when installed launcher,
  source Wheel, or Product receipt bytes change. The reproducible
  platform-tagged Wheel has a native offline-install test and explicit Product
  variants in the Linux H6 CI gate. The Linux operator command now handles
  Product native release approval and selected candidate opt-in, while
  deployment actor policy and broader rollout remain open. Windows production
  closure, live third-party Session use, and default executable authority
  remain absent.

This inventory distinguishes accepted reusable owners, Product adapters,
parallel compatibility paths, and missing target boundaries. “Migrate” or
“delete” below is a delivery obligation, not a claim that the work is already
implemented.

## Durable Control And Lifecycle Owners

| Current seam | Exact source owner or symbol | Current fact | PLC9 disposition and deletion gate |
| --- | --- | --- | --- |
| Old Desired-token migration readers | `src/loushang/coding/package_legacy_configured_source.py`, `src/loushang/coding/package_legacy_disabled_review.py`, `src/loushang/coding/package_legacy_local_adoption_read.py`, `src/loushang/coding/package_legacy_removed_adoption.py`, and `src/loushang/coding/package_legacy_removed_review.py` | These bounded migration owners interpret frozen `disabled_plugins` input or verify its accepted receipt; they do not write a peer Desired State ledger | Retain until supported old workspace shapes are receipted and sole Desired State selection is proven |
| Product Capability legacy-token reader | `src/loushang/coding/_product_capability_plugin_composition.py` | Rechecks the selected Product lineage against legacy `manifest.enabled` and `source.enabled` facts during compatibility composition | Retain behind Product selection; neither flag is a Desired State writer |
| Desired-state journal | `src/loushang/harness/plugin_management/ledger.py::PluginDesiredStateLedger` | Durable desired installation snapshots and transitions | Retain as state authority behind the management service; transports never import it to mutate state |
| Management command journal | `src/loushang/harness/plugin_management/service.py::PluginManagementService` | Sole PLC2-2/PLC2-3 command authority over inert desired state; handles install/enable/disable/remove and the v2 update command | Retain and compose behind one application boundary; revise only through an accepted command contract |
| Retirement intent | `src/loushang/harness/plugin_management/retirement.py::PluginRetirementIntentLedger` | Durable intent opened by lifecycle transitions | Retain; removal cannot bypass it when retirement is required |
| Retirement-set coordination | `src/loushang/harness/plugin_management/retirement_sets.py::PluginRetirementSetLedger` | Correlates exact covered Instance revisions and owner completion | Retain; completion must remain evidence-backed |
| Instance runtime | `src/loushang/harness/plugin_management/instance_runtime.py::PluginInstanceRuntimeLedger` | Durable Instance activation, lease-family, drain, revocation, and retirement state | Retain; do not replace with Worker/process state |
| Security retirement acceptance | `src/loushang/harness/plugin_management/security_acceptance.py::PluginInstanceSecurityRetirementJournal` | Durable acceptance evidence for security retirement | Retain; keep distinct from graceful retirement and generic management auth |
| Package retention and cleanup | `src/loushang/harness/plugin_management/package_lifecycle.py::PluginPackageLifecycleLedger` | Durable pins, cleanup leases/attempts/repair decisions, recovery barrier, retention snapshots, and GC candidates | Retain as lifecycle evidence; PLC9D must add deletion execution/result without weakening candidate recheck |
| Dark GC reservation and reference fence | `src/loushang/harness/plugin_management/package_gc_reservation.py::PluginPackageGcReservationJournal` and `src/loushang/harness/plugin_management/gc_fence.py::PluginPackageGcReferenceGatePort` | PLC9D2 journals exact reservation/cancellation, replays active fences, and guards opt-in desired/Instance/Package reference writers in one lock order | Retain dark; D3 needs Product-wide writer binding and downgrade exclusion before Store-owned rooted deletion; a reservation alone is not authorization |
| Coding Product composition | `src/loushang/coding/_plugin_lifecycle.py::CodingPluginLifecycle` | Product adapter composes the generic ledgers under one workspace identity and coordination lock | Retain as an outer Product adapter until common application ports replace Product-specific call sites; it must not become a second generic owner |
| Coding fresh B cutover and builtin bootstrap | `src/loushang/coding/package_pre_b_snapshot.py::cutover_and_bootstrap_coding_package_product`, `src/loushang/coding/package_product_runtime.py::bootstrap_coding_builtin_product_plugins`, `src/loushang/harness/package_product/product_local_wheel_runtime.py::PosixLocalWheelProductSessionOwner.settled_install_command_id`, and `src/loushang/coding/cli/package_cutover.py::main` | Declared offline `loushang-package-cutover` command prepares private roots, fences a fresh workspace, then installs and enables the three checked-in Plugins through the real Product transaction; retry reads the Product-owned settled handoff and resumes an interrupted enable only when its own install is still the latest desired transition. Ordinary Linux Session startup now runs the same fresh cutover after a no-write preflight; an interrupted bootstrap resumes only when its verified first-B snapshot is fresh. A fenced Session routes five Package actions through the Product from Session, CLI, and RPC; synchronous uninstall also cannot use the legacy fallback | Retain as a fresh-workspace POSIX slice only. Any unfenced pre-B Plugin member or legacy Plugin/Package setting refuses without writes; old-workspace compatibility is outside this delivery. Operator disable/remove is not overwritten. Windows ordinary first-B activation awaits native evidence |
| Coding cutover backup status | `src/loushang/coding/package_cutover_backup.py::inspect_coding_package_cutover_backup` | D3m reopens the exact Product fence and verifies its real pre-B workspace snapshot owner; pathless `--backup-status` reports retained or unknown with expiry unknown | Do not interpret this workspace snapshot as per-Installation Plugin backup retention or as permission to expire/delete it |
| Coding pre-B Source snapshot | `src/loushang/coding/package_source_snapshot.py` | Includes the legacy `disabled_plugins` settings field in an authenticated offline snapshot; it is evidence, not B Product selection | Retain as restore/adoption input; never infer a B desired Installation or enablement change from the snapshot alone |
| Coding legacy migration foundation | `src/loushang/coding/package_legacy_classification.py`, `src/loushang/coding/package_legacy_snapshot_member.py`, `src/loushang/coding/package_legacy_local_wheel.py`, `src/loushang/coding/package_legacy_binding_catalog.py`, `src/loushang/coding/package_legacy_review.py`, `src/loushang/coding/package_legacy_disabled_acceptance.py`, and `src/loushang/coding/cli/package_cutover.py` | Classifies scoped legacy `disabled_plugins` and Source settings, verifies first-B snapshot members and old desired state, reacquires exact local Source bytes, and prepares inert reviews. The disabled-only POSIX command commits a first-B fence, emits a stable review ID, explicitly accepts that ID in a durable Product receipt, then seeds the three builtins while preserving reviewed disables. Receipt replay reads through a pinned private directory and file descriptor with bounded bytes; first publication uses exclusive, descriptor-relative atomic write and refuses a replaced name. Read and publish replacement negatives pass. Default command restart replays an accepted receipt; real `coding-standard` and `coding-architecture` Sessions start with base disabled and selected Capabilities bound through Product. Independent external Skill/Prompt Product Resource composition works with base disabled, including persisted Prompt Model Input and duplicate-identity refusal. The fenced read-only Product preview follows the same base-disabled data route, including external conflict and native-only projections | Keep this as a narrow disabled-only migration path; configured Sources, old Plugin state, non-builtin disables, downgrade compatibility, full sole-writer selection, and Windows remain unproven. Fresh cutover still refuses implicit migration inputs |
| Coding builtin-only Desired migration | `src/loushang/coding/package_legacy_builtin_review.py`, `src/loushang/coding/package_legacy_builtin_acceptance.py`, `src/loushang/coding/package_legacy_builtin_adoption.py`, and `src/loushang/coding/cli/package_cutover.py` | A separate explicit Linux command rejects foreign removals before the first fence, then binds a frozen old Desired journal and scoped settings to a hash-bound review. Product accepts that review once before mutation, replays after acceptance or partial builtin commit, preserves old Base/LSP/Arch removed selections and Arch disabled/enabled intent, and keeps a later operator base disable. A fresh CLI process reopens the cutover; real Product-backed `coding-architecture` Sessions prove a removed Base stays absent while current Capability roots remain available, the disabled/removed Arch is absent, and the enabled Arch is mounted. A mixed old enabled intent plus scoped disable remains disabled after the live old setting is cleared, proving Product Desired selection for this shape; a replaced receipt symlink refuses reopen | This covers builtin-only old Desired history, not old executable or other Resource Installations. Mixed local Skill adoption now preserves a reviewed Base tombstone; an already removed local head plus Base tombstone has its own exact-history review. Windows has candidate frozen builtin-only read, one-shot Product acceptance with exact staged retry, and internal Product Desired adoption; native evidence and an operator migration command are pending. Broad old-workspace completion and sole Desired State rollout remain open |
| Coding installed-local migration review and acceptance | `src/loushang/coding/package_legacy_reacquisition.py`, `src/loushang/coding/package_legacy_review.py`, `src/loushang/coding/package_legacy_local_acceptance.py`, `src/loushang/coding/package_legacy_source_consumption.py`, `src/loushang/coding/package_legacy_local_adoption.py`, and `src/loushang/coding/cli/package_cutover.py::main` | The Skill prepare/adopt commands still support 1–16 local data Skills. Separate Prompt and Theme prepare/adopt commands accept their exact old local data Resources among at most 16 total data Plugins. Prompt v2 and Theme v3 acceptances and Source bindings carry their Resource kinds; Product precommit, selected Root, and Coding composition require the matching `resources.prompt` or `resources.theme` owner. A real CLI journey covers first-fence preparation, review, Product install and enablement after original Source deletion, ordinary cutover's read-only settled check, Session Prompt consumption into persisted Model Input, transcript reload, exact replay, operator disablement, and changed controlled Wheel refusal. Mixed Skill/Prompt journeys pass in either adoption order and expose both Resources in one Product Session. Wrong Skill/Prompt selection and duplicate Prompt names fail before the fence or acceptance; two distinct old Prompts pass separate adoptions and are consumed by one Product Session. An old Theme passes typed CLI adoption, original Source removal, Product Session selection, visible welcome-panel rendering, and later Product disable fallback. An old disabled Theme stays unselected after adoption; changed controlled Theme Wheel bytes refuse Product reopen. Invalid Theme JSON and duplicate Theme names refuse before the first fence; a mixed Skill/Theme set settles separately and shares one Product Session. Existing Skill crash, settings, multi-Source, and Session regressions remain covered | Public only for explicit offline Skill, Prompt, and Theme journeys within the bounded data set. Executables, Windows, broader old state, and automatic default adoption remain closed |
| Coding mixed old Skill and builtin disables | `src/loushang/coding/package_legacy_review.py`, `package_legacy_skill_cutover_admission.py`, `package_legacy_local_adoption.py`, `package_legacy_local_adoption_read.py`, and `bootstrap.py` | The one-Skill review now displays and binds frozen scoped `disabled_plugins` entries for the three checked-in builtins. Pre-fence admission rejects a foreign disable before publishing a fence. Explicit adoption installs the old Skill, carries its old Desired State, and leaves each reviewed builtin disabled. Default cutover reopens the mixed adoption through read-only Product evidence. Real CLI crash/replay journeys cover project-scoped LSP and global-scoped `coding.base` disables, Source removal, and actual Product-backed Session Skill loading. Product Session composition consults Desired State before capturing requested LSP/Arch roots and rechecks the observed selection at publication and refresh | One old Skill may carry a matching configured Source and builtin disables. Multiple old Skills have separate acceptance and whole-set settlement; same-scope lists and mixed configured/unconfigured Skills are supported. Mixed Skill/Prompt and Skill/Theme adoption have separate typed proof; unrelated configured Sources, Windows, and full sole-writer migration remain open |
| Coding multiple old local Skills | `src/loushang/coding/package_legacy_skill_cutover_admission.py`, `package_legacy_local_adoption.py`, `package_legacy_local_adoption_read.py`, `package_product_runtime.py`, and `cli/package_cutover.py` | First-B admission verifies every one of 1–16 old local Skill Sources and exact bounded Wheels before publishing a fence. Each Plugin has its own review and accepted Product installation; ordinary cutover reads all settled adoptions. A real two-Skill Product Session loads both after the first Source disappears. An operator LSP disable between adoptions remains the current Desired State; the second adoption does not bootstrap over it. Changed second Source, duplicate Skill names, and unrelated configured paths refuse before the fence. Two-Skill Product journeys cover separate scopes, two paths in one scope, and a configured/unconfigured mix. The same-scope path retains order, refuses manual clearing without a receipt or a damaged first receipt, and replays an interrupted second settlement; a separate three-Skill Product journey consumes one ordered list entry per acceptance, while real two-Skill Sessions load both after settlement | This multi-Skill journey covers local data Skills; the mixed journeys above also admit Prompt and Theme types. Unrelated configured Sources, executable Plugins, and broader old state remain closed |
| Pre-fence Product snapshot admission | `src/loushang/harness/resources/packages/plugin_lifecycle/posix_epoch_cutover.py`, `src/loushang/harness/resources/packages/product_pre_b_snapshot.py`, `src/loushang/coding/package_pre_b_snapshot.py`, and `src/loushang/coding/package_legacy_skill_cutover_admission.py` | Optional Product callback reads the verified immutable snapshot while native cutover still holds exclusive quiescence, before creating the B namespace or first fence. Coding's explicit offline 1–16-local-data-Plugin commands check old lock/desired/settings evidence, match any configured `plugin_sources` subset to the installed local data Plugins across global/project settings, and reacquire every exact bounded Source as a single typed data Wheel. Real Skill, Prompt, and Theme cutovers succeed through their explicit typed routes; wrong type, invalid Theme JSON, duplicate same-kind names, executable Source, additional/mismatched configured Source, and extra old-state negatives keep the old lock and desired bytes and publish no fence. Generic native refusal also permits retry without policy rejection | The default cutover does not select this callback. It does not authorize unrelated configured Sources, other Resource kinds, executable Plugins, or default routing |
| Coding accepted local Source binding and data Resource migration | `src/loushang/coding/package_legacy_local_binding_owner.py`, `src/loushang/coding/package_legacy_local_installation.py`, `src/loushang/coding/package_legacy_binding_catalog.py`, `src/loushang/coding/package_product_runtime.py`, and `src/loushang/coding/package_product_preview.py` | Internal Product owner reacquires the accepted original Source, matches its verified Wheel to the accepted review, publishes exact bytes, and appends a binding with the acceptance ID. Product policy reopen and read-only preview require the same frozen acceptance and Wheel evidence before adding the binding; an arbitrary `approval_id` fails closed. Cached Coding Product policy detects a newly bound legacy Source before serving a new Session. A deterministic internal owner routes an accepted typed data Wheel through the real Product Package transaction and verifies its settled `installed_disabled` handoff, including replay after original Source removal. A separate internal owner verifies the accepted old enabled state and settled B install transition, submits one B management enable, and refuses an intervening operator disable; an accepted old disabled Skill stays disabled. Real first-B Sessions load the selected Skill from Product Store with `coding.base` both disabled and enabled; a mixed Session selects it beside an ordinary data Skill, and disabling only the migrated Skill leaves the ordinary Skill in the next Session. Read-only Product preview follows its enablement. The Capability composition derives exact owner trust classes from selected candidates. The candidate gate checks the wrapped legacy distribution and admits only the exact accepted Skill, Prompt, or Theme owner; executable members still refuse | These Product owners now back explicit 1–16-local-data-Plugin CLI journeys. Other old Resource kinds, executable Plugins, full workspace adoption, default route promotion, and sole Desired State cutover remain open |
| Coding B Product revision selection | `src/loushang/coding/package_product_revisions.py` | Checks built-in Plugin `manifest.enabled` against the selected B Product revision and mount policy | Retain as a selected-revision check; a manifest flag alone cannot replace Product desired-state authority |
| Management application command adapter | `src/loushang/harness/plugin_management/application.py::PluginManagementCommandApplication` | A1-1 preserves correlation around the durable operation identity and delegates every mutation to `PluginManagementService` | Retain as the transport-neutral command boundary; transports cannot import the service or desired-state ledger directly |
| Management query projector | `src/loushang/harness/plugin_management/application.py::PluginManagementReadModelProjector` | A1-1 joins independently revisioned desired, operation, migration, Source, Instance, Package, and retirement snapshots without persisting another clock | Retain as the common read boundary; optional owners remain explicitly unsupported/unknown and forward/reverse skew remains observable |
| Source projection snapshot | `src/loushang/harness/plugin_management/application.py::PluginManagementSourceSnapshotV1` | A1-1 describes source identity, availability, version, and manifest install default as inert input facts | Retain behind a Product Source adapter; availability and install default never become live desired-selection writers |
| Enablement migration receipt | `src/loushang/harness/plugin_management/enablement_migration.py::PluginEnablementMigrationJournal` | A1-2 owns the durable migration receipt with strict append-only `accepted -> desired_committed -> compatibility_window -> finalized` evidence per Installation and rejects changed accepted input | Retain through the downgrade window; finalization evidence plus the minimum-version/downgrade gate is required before removing compatibility fields |
| Enablement migration coordinator | `src/loushang/harness/plugin_management/enablement_migration.py::PluginEnablementMigrationCoordinator` | A1-2 seeds only never-seen desired state through the common command port with deterministic retry identities; any desired history wins. Coding's migration and first-party default ingresses now require the exact workspace Installation scope, Product ID, and scope ID before Desired State writes; the default ingress also matches Package Revision to Plugin ID. Process and tenant keys with the same scope ID are refused | Retain until all legacy inputs are receipted; it cannot acquire Packages, infer Source availability as selection, or call a desired ledger commit |
| Legacy compatibility projection | `src/loushang/harness/plugin_management/enablement_migration.py::PluginEnablementCompatibilityProjector` | A1-2 derives legacy disabled ids from canonical desired snapshots plus migration receipts | Temporary retain; callers may consume it for downgrade compatibility but cannot mutate it as peer state |
| Coding compatibility writer | `src/loushang/coding/plugin_enablement_compatibility.py::CodingPluginEnablementCompatibilityWriter` | A1-3 pins the private root with a POSIX no-follow directory fd or a Windows identity-checked root descriptor; Windows opens every coordination/owner lock and journal relative to that descriptor through `NtCreateFile`, then both platforms acquire common coordination, migration transaction, desired journal, and migration journal locks in fixed order; it treats only newline-terminated records as committed before submitting a monotonic typed projection through the single Product registry authority, while an absent state root remains absent | Temporary Product-owned downgrade coordinator; rooted child I/O prevents root/ancestor namespace redirection, the registry aggregates workspace projections without holding its lock across config I/O, the settings owner atomically reloads/preserves/publishes/verifies, an incomplete crash tail remains for canonical owner repair, partial publication is repaired, and canonical desired state is never rolled back |
| Coding migration composition | `src/loushang/coding/_plugin_lifecycle.py::build_coding_plugin_lifecycle` | A1-2 binds the generic journal under the private workspace lifecycle root and checks the epoch fence before management recovery; A1-3 base, Capability, and Continuity paths import exact legacy inputs before mount | Retain as Product composition; `build_coding_plugin_management_application` and `project_coding_plugin_enablement_compatibility` keep durable owner construction out of transport adapters |
| Coding fresh B Product state | `src/loushang/coding/package_product_runtime.py::open_coding_package_product_state` | Opens a distinct desired-state ledger and management service only after the Store epoch is fenced | Retain as Product-owned B composition; command mutations still flow through the management service |
| Coding pre-B Source snapshot | `src/loushang/coding/package_source_snapshot.py` | Includes the legacy `disabled_plugins` settings field in an authenticated offline snapshot | Retain as restore/adoption input; never infer a B desired Installation or enablement change from the snapshot alone |
| Coding B Product revision selection | `src/loushang/coding/package_product_revisions.py` | Checks built-in `manifest.enabled` against the selected Product revision and mount policy | Retain as a selected-revision check; a manifest flag alone cannot replace Product desired-state authority |
| Configured Source projection | `src/loushang/harness/plugin_management/configured_sources.py::project_configured_plugin_sources` | A1-3 projects configured Source facts using Product identity, scope, root and Source strings supplied by a profile | Retain as an inert Harness query projector; it may inspect configured Sources but cannot construct or mutate a durable lifecycle ledger |
| Coding configured Source adapter | `src/loushang/coding/plugin_management_cli.py::CodingConfiguredPluginSourceProjection` | Reads Coding settings and supplies the current workspace-scoped Source profile to the common projector | Retain Product-owned settings validation and stable Coding error codes |
| Coding management CLI composition | `src/loushang/coding/plugin_management_cli.py::build_coding_plugin_management_cli_binding` and `src/loushang/harness/cli/plugin_management.py` | A1-3 composes common command/query ports and invokes the Product-owned compatibility reconciler before returning the transport binding. Harness now receives immutable Product identity facts separately from typed read/command owner strategies; Coding alone supplies settings, startup, and legacy compatibility behavior | Retain as Product composition; command admission requires a common projected migration receipt |
| Coding base migration caller | `src/loushang/coding/_base_plugin.py::prepare_managed_coding_base_plugin_assembly` | A1-3 imports the base manifest default and legacy disable input before mount; an existing desired history wins | Retain during migration; delete the legacy input only after PLC9E finalization evidence |
| Coding Capability migration caller | `src/loushang/coding/_capability_plugin_composition.py::_resolve_managed_capability_plugins` | A1-3 imports exact checked-in Capability revisions before mount and leaves legacy-disabled Installations unmounted | Retain during migration; canonical desired state is the only post-migration selection input |
| Coding standard startup compatibility caller | `src/loushang/coding/bootstrap.py::_create_agent_session` | Captures legacy input for base/Capability migration, then unconditionally resolves the durable workspace layout and binds/reconciles existing receipts even when no Plugin is selected; cleaned ephemeral roots are not reused | Temporary fence-aware startup caller; it cannot veto a receipted desired-state replay or recreate a cleaned one-shot root |

The `PluginManagementAction` v1 union in
`src/loushang/harness/plugin_management/operations.py` is exactly `install`,
`enable`, `disable`, and `remove`. Update is the separately versioned
`PluginManagementUpdateCommandV2` in
`src/loushang/harness/plugin_management/updates.py`. PLC9 must preserve replay
compatibility rather than silently widening the v1 wire union.

## Current Management And Enablement Peers

| Peer seam | Exact source site | Current fact | PLC9 migration/deletion gate |
| --- | --- | --- | --- |
| Shared CLI mutation | `src/loushang/harness/cli/resource_toggles.py::apply_resource_toggles` | A1-3 routes Plugin enable/disable through `PluginManagementCliBinding`; Skill and source configuration retain their settings owner and compatibility aliases retain source meaning | Retain the transport-only split; Plugin commands cannot call settings enable/disable mutators or materialize an unmigrated Installation |
| Shared CLI listing | `src/loushang/harness/cli/plugin_listing.py::list_plugin_records` | A1-3 maps the correlated common management projection into legacy TSV/JSON fields without inspecting Sources or constructing an authority | Retain as pure formatting/projection adaptation; Product Source inspection stays behind the injected query owner |
| Partial operation explanation query | `src/loushang/harness/plugin_management/operation_explanation.py::project_plugin_operation_explanation`, `src/loushang/coding/plugin_management_explanation.py::CodingPluginOperationExplanationQuery` | Reads A2 Package, the settled Product handoff, and A1 Management through strict read-only owner ports; exact request, scope, command, Package revision, and owner revisions bound the partial result. Coding CLI and optional Session RPC now call this typed projection instead of opening an owner in either transport | Retain a partial-evidence query, with Product selection, Session capture, and atomic-snapshot gaps visible. Real install/update/rejected/forged-command regressions and absent/corrupt owner reads cover its positive and negative paths; it has no command or repair authority |
| Local management read SDK and TUI views | `src/loushang/coding/plugin_management_read_sdk.py::CodingPluginManagementReadClientV1`, `src/loushang/coding/ui/product_binding.py` | Derives Coding Product/scope from the local workspace and exposes typed current preview, management Installation snapshot, and A2 operation explanation. Screen/plain TUI `/plugins`, `/plugins list`, and `/plugins explain ID` render pathless partial composition, Desired State, and cross-owner Package/Management/handoff evidence through those read ports; the public `loushang.plugin` author namespace does not import them | Retain as read-only Product adapters. Real fenced Product and absent-workspace no-write regressions apply; TUI command, Package, and repair authorities remain separate |
| Local management Desired State command SDK | `src/loushang/harness/plugin_management/desired_command.py` and `src/loushang/coding/plugin_management_command_sdk.py::CodingPluginManagementCommandClientV1` | A Product-scoped command profile binds exact workspace, actor and policy to enable/disable/remove; caller supplies Desired inventory CAS and replayable operation ID. The SDK and TUI factories select distinct fixed actor/policy profiles. Real fenced Product regressions cover commands, replay, stale refusal, unfenced no-write refusal, workspace replacement, and own pending-command recovery after a commit-before-terminal crash | Retain separate from the public author SDK and Package install/update. Each profile repairs only its own pending A1 commands; A2 lifecycle repair and wider authorization review remain open |
| Coding local management TUI actions | `src/loushang/coding/plugin_management_ui.py::execute_coding_plugin_management_ui_command`, `src/loushang/coding/ui/product_binding.py` | Screen and plain TUI route explicit `/plugins enable|disable|remove` through the fenced Product Desired State owner with one CAS revision, deterministic operation ID, separate `coding:tui` actor, and no model prompt. `/plugins repair` accepts only the TUI actor's pending A1 operation. Real Product tests cover Desired State transitions, new-Session selection, foreign actor refusal, and terminal/unknown repair without writes | Retain as Coding local UI; Package install/update, A2 repair, Hosted Mux management, and default route promotion remain independent gates |
| Optional management Desired State RPC | `src/loushang/harness/host/rpc/commands/plugin_desired.py` and `src/loushang/coding/plugin_management_command_rpc.py` | Generic RPC binds no write route by default. Coding injects a fenced Product command client; submit, operation lookup, and own pending-command repair validate Product/scope and typed operation identity, redact exceptions, and preserve CAS/replay evidence. Real Product Session/RPC regression reaches the Desired State owner and recovers a commit-before-terminal crash | Retain as the v1 enable/disable/remove transport; install/update, A2 repair, UI, active-Session selection impact, and broader authorization review remain separate gates |
| Guarded management Desired State CLI repair | `src/loushang/coding/cli/application.py::_run_coding_plugin_desired_repair_cli`, `src/loushang/coding/package_product_management_cli.py::repair_coding_fenced_cli_desired_operation` | A fenced Product early route accepts only an exact CLI-owned pending A1 operation ID; unknown and terminal observations are inert. Real crash recovery and foreign-actor refusal regressions check its result and no-write paths | Retain as narrow explicit repair, with A2 repair, UI, and default route promotion separately gated |
| Narrow POSIX A2 staged repair CLI | `src/loushang/coding/cli/package_repair.py` | `inspect-staging` activates a fenced Product runtime and checks the exact staged checkpoint and Source/lease preflight without selecting that operation; it is not a strict read-only query because activation may recover Product state. `repair-staging` prepares and executes under one live admission, returns nonzero unless the Product commits, and exposes only a pathless result. A real Coding Product test covers staged-root crash, changed Source refusal, crash after CLI selection, next-runtime supersession, and commit. A separate Linux Product factory regression recovers a partial two-node checkpoint through two real Agent Sessions and epoch guards, refusing a live old lease, tampered dependency Store bytes, and dependency Source drift before committing only the missing root | This route handles only a `transaction_pinned` staged prefix on POSIX. The dependency Product is a configured Harness fixture; Coding's external-data policy still rejects dependencies. General A2 repair policy, other phases, and Windows Product evidence remain open |
| Narrow POSIX A2 pinned repair CLI | `src/loushang/coding/cli/package_repair.py::main` | `repair-pinned` prepares and executes Product pinned adoption for an exact `transaction_pinned` operation with no staged Store effect. A real Coding Product CLI regression refuses the wrong action and Source drift without lifecycle mutation, then commits the Wheel and leaves it disabled. Real Session RPC/UI regressions also refuse the wrong action before committing | Staged prefixes use `repair-staging`; later publication/handoff states, general A2 policy, broader SDK policy, and Windows Product evidence remain open |
| Narrow POSIX A2 failed-attempt repair CLI | `src/loushang/coding/cli/package_repair.py::main` | `repair-retryable` opens the fenced Coding Product, prepares an exact cross-runtime rebind decision, and executes it under the same live admission. A real Coding Product regression changes the pinned Source after Product open and observes `package_source_digest_mismatch` with no proposal or lifecycle write, then crashes after selection and commits the data Wheel under a later CLI runtime; the CLI returns nonzero unless committed | Only `retryable_failure` attempts admitted by the existing Source, cleanup, and lease owners are eligible. Abandoned active claims use the separate actions below; real Session RPC/UI coverage now includes retryable repair. Later phases, general A2 repair policy, broader SDK policy, and Windows Product evidence remain separate gates |
| Narrow POSIX A2 abandoned-claim repair CLI | `src/loushang/coding/cli/package_repair.py::main`, `src/loushang/harness/package_product/product_rebind_decision.py::PackageProductRebindDecisionOwner.recover_unstarted_claim` | `repair-unstarted`, `repair-acquired`, `repair-resolving`, and `repair-verified` each call the matching Product recovery owner, then select and execute an exact cross-runtime retry under the same new lease. The unstarted owner now checks selected Source bytes before interrupting an effect-free claim. Four real Coding Product CLI regressions refuse a wrong phase and post-open Source drift without a lifecycle write, then commit through the Product; eight more real Session RPC/UI regressions refuse a wrong phase without a lifecycle write before committing those four claims through the same SDK. The local Wheel remains disabled | Only selected `classified`/`acquiring`, `acquired`/`inspecting`/`extracted`, `resolving_closure`, and root-only `closure_verified` claims are admitted. A crash after recovery may leave `retryable_failure`, which uses `repair-retryable`; pinned/staged states use the separate actions above. Later phases, general A2 policy, broader SDK policy, and Windows evidence remain open |
| Local Coding A2 repair SDK | `src/loushang/coding/package_product_repair.py::CodingPackageRepairClientV1` | The local management client binds the exact workspace identity and runs ten explicit inspection/repair actions through one Product owner and runtime lease per call; structured pathless results keep inspection distinct from committed disposition. Its async entry can be awaited by an RPC host without a nested event loop. A real Product SDK regression refuses a mismatched action without lifecycle writes, then commits an exact retryable Wheel. Separate regressions reject a replaced workspace and invalid operation ID before Product open; the CLI now also exercises a published-set crash, inspection, wrong-action refusal, and committed recovery through this shared service | This is a Coding management SDK, never the public author SDK. General repair policy, later transaction phases, Windows Product evidence, and non-POSIX clients remain open |
| Optional Coding A2 repair RPC | `src/loushang/harness/host/rpc/commands/package_repair.py`, `src/loushang/coding/package_product_repair_rpc.py`, and `src/loushang/coding/cli/application.py` | Generic RPC hosts omit this command unless a Product binds a client. Coding binds the same exact workspace repair SDK; the async command validates Product/scope, action, operation identity, and pathless result fields and redacts exceptions. Real POSIX Coding Session RPC regressions refuse a wrong scope or phase without lifecycle writes, then commit through a separate fenced Product runtime while the Session is active. Unit regressions reject invalid actions and spoofed results | This is a narrow optional A2 transport, not general Package management. Real Session RPC coverage now includes all ten explicit actions: the four early abandoned-claim actions, retryable and pinned repair, published-set inspection and repair, and staging inspection and repair. Broader authorization policy and Windows Product evidence remain open |
| Local Coding A2 repair TUI | `src/loushang/coding/package_product_repair_ui.py` and `src/loushang/coding/ui/product_binding.py` | Explicit `/plugins repair-package ACTION OPERATION_ID` runs through the same POSIX Product repair SDK in a UI worker thread; `inspect-staging` reports counts, committed repairs request a new Session, and exceptions are redacted. Real Coding Session TUI regressions refuse wrong repair actions without lifecycle writes, then commit through another Product runtime. No model prompt is submitted | This is a narrow local operator route. Real Session TUI coverage now includes all ten explicit actions: the four early abandoned-claim actions, retryable and pinned repair, published-set inspection and repair, and staging inspection and repair. Broader authorization policy, hosted UI management, and Windows Product evidence remain open |
| Same-epoch A2 retry mechanism candidate | `src/loushang/harness/resources/packages/product_lifecycle.py::PackageProductLifecycleRouter.retry`, `src/loushang/harness/resources/packages/product_activation.py::PackageProductLifecycleActivation.retry`, and `src/loushang/harness/resources/packages/product_local_wheel_policy.py::PackageProductLocalWheelPolicy.prove_rebind_root_source` | An exact retryable Package owner attempt resumes under the admitted Product epoch and runs the transaction through the same router. Stale attempt, changed Source, new runtime admission, direct materializer, and terminal operation paths refuse before owner mutation. A separate read-only preflight rechecks the old Product classification and pinned root Wheel bytes without writing the Package journal | Cross-runtime execution now has a separate guarded route. Keep operator A2 repair closed until later-phase recovery and Product command policy are proven |
| A2 rebind-decision journal primitive | `src/loushang/harness/resources/packages/plugin_lifecycle/records.py::PackageLifecycleRebindRecordV1`, `src/loushang/harness/resources/packages/plugin_lifecycle/journal.py::PackageLifecycleJournal.record_rebind`, `supersede_rebind`, and `resume_rebind` | Records an exact failed-attempt CAS and new admission ID with Source/cleanup/lease evidence references without rewriting the original v2 request. An exact decision and record CAS can claim the next attempt once; a separate supersession record links one pending decision to a replacement admission and invalidates the old decision. Reopen/replay do not append, while an ordinary second pending decision or old retry path is refused | Product now verifies referenced evidence and proposed admissions under an epoch guard before internal execution. Journal lineage alone grants no authority; later-phase transaction recovery and broader operator transport remain open; narrow POSIX Coding CLI actions use the guarded Product owner |
| A2 cleanup-bound restart journal primitive | `src/loushang/harness/resources/packages/plugin_lifecycle/records.py::PackageLifecycleRestartRecordV1` and `src/loushang/harness/resources/packages/plugin_lifecycle/journal.py::PackageLifecycleJournal.restart_after_cleanup` | Records an exact failed-attempt phase and dual-CAS reset from `acquiring` through `closure_verified` to `classified`, with Source, cleanup, and lease proof references. The original v2 request and old history remain intact. Exact replay does not append; stale CAS, changed references, a pending rebind, and tampered records refuse. A rebind decision or supersession must keep the restart Source and cleanup refs before claiming a fresh classified attempt | Journal grants no authority. An internal Product owner now verifies and invokes it for selected `acquired`, `inspecting`, and `extracted` root claims, selected `resolving_closure` node sets, and root-only `closure_verified` plans, including real Coding Product routes; pin/publication settlement, later phases, and broader operator transport remain open; narrow POSIX Coding CLI actions now invoke Product restart |
| A2 cleanup-domain read fact | `src/loushang/harness/resources/packages/plugin_lifecycle/cleanup.py::PackageQuarantineCleanupOwner.read_operation_tombstones` | Strictly reads all tombstones for one A2 operation without creating locks, repairing a partial journal tail, or mutating cleanup state | Used by current Product rebind preflight and replay; absence of a tombstone does not prove physical quarantine cleanup, and general Product A2 repair remains open; narrow POSIX Coding CLI actions are separately gated |
| A2 resolution-attempt read fact | `src/loushang/harness/resources/packages/plugin_lifecycle/closure_journal.py::PackageClosureResolutionJournal.read_attempt_evidence` and `read_plan` | Reads one exact attempt's basis, selections, and verified dependency plan without creating or repairing the resolution journal; strict replay rejects corrupt tails | A plan can be absent before closure verification, while selections may already exist; recovery must validate that selection evidence and recheck pinned bytes before accepting a Source proof |
| A2 selected-Source byte check | `src/loushang/harness/resources/packages/product_local_wheel_policy.py::PackageProductLocalWheelPolicy.prove_rebind_selected_sources` | Checks the original failed Plugin-bound request, current policy authority, each selected dependency version/digest, and bounded root plus dependency bytes | The policy method does not read the resolution journal itself or authorize retry; Product composition must bind strict owner evidence and the new admission before recording a rebind decision |
| A2 Product Source observation | `src/loushang/harness/package_product/product_rebind_source.py::PackageProductRebindSourceReader`, `src/loushang/harness/package_product/product_runtime.py::PackageProductRuntimeBindingV1.inspect_rebind_source`, and POSIX local-Wheel Product composition | Strictly reads the original failed lifecycle request and complete attempt-resolution evidence, checks phase-required basis/plan, and binds pinned root/dependency bytes plus owner evidence references into a deterministic observation digest. The POSIX Product binding injects the reader and invokes it only through the existing epoch-guarded admission query; inactive or generic bindings refuse | The read grants no execution authority alone. Product rechecks it while preparing and executing a selected decision; later-phase recovery remains open |
| A2 original-admission lease binding | `src/loushang/harness/resources/packages/product_admission_binding.py::PackageProductAdmissionBindingJournal`, `src/loushang/harness/resources/packages/product_lifecycle.py::PackageProductLifecycleRouter._bind_original_admission`, and POSIX Product composition | After lifecycle acceptance and before transaction effects, Product durably binds the original request fingerprint to the full admission receipt and lease ID. Exact replay is idempotent; changed admission and corrupt owner history refuse before transaction effects. Real POSIX CLI and startup composition checks read the binding | Cross-epoch repair refuses preexisting v2 attempts without this binding. Internal executable rebind, unstarted/root-claim recovery, selected `resolving_closure` recovery, and root-only `closure_verified` recovery have distinct routes; later phases remain missing |
| A2 Product proposed-admission binding and lease observation | `src/loushang/harness/resources/packages/product_rebind_admission_binding.py`, `src/loushang/harness/package_product/product_rebind_lease.py::PackageProductRebindLeaseReader`, `src/loushang/harness/package_product/product_runtime.py::PackageProductRuntimeBindingV1.inspect_rebind_lease`, and POSIX Product composition | A separate append-once Product journal binds each proposed decision to its full admission and lease; an orphan proposal alone is inert. Under the admitted epoch query, the lease reader joins the original request/binding, strict Package decision history, matching proposals and complete live-lease snapshot. It refuses any live original or previously selected proposed lease, missing current lease/binding, or changed Store fence/root | Product writes proposals before decisions and rechecks owner evidence under mutation guards. Effect-free, selected `acquired`/`inspecting`/`extracted` root claims, selected `resolving_closure` node sets, and root-only `closure_verified` plans have separate internal recovery paths; later phases remain open |
| A2 Product cleanup and joined preflight | `src/loushang/harness/package_product/product_rebind_cleanup.py`, `src/loushang/harness/package_product/product_rebind_preflight.py`, and `src/loushang/harness/package_product/product_runtime.py::PackageProductRuntimeBindingV1.inspect_rebind_preflight` | The POSIX Product reads strict artifact/selection/cleanup, transaction-pin, staging, committed-set, and handoff evidence plus exact quarantine slots under the admitted epoch guard; committed operations' retained roots are allowed only when each physical directory matches a committed Package status and its bounded-acquisition sink identity. A pin record for the current attempt or later operation fact refuses cleanup even if quarantine is empty. Unknown entries, pending debt, or moved completed attempts refuse. A real Coding Product test proves same-name directory replacement refusal before proposal write | Product rechecks the momentary read before execution. Recovery of a classified or acquiring claim requires empty attempt evidence and a complete Store scan; pinned, published, and later-phase effects still require their own owner settlement |
| A2 selected root-claim read | `src/loushang/harness/package_product/product_rebind_source.py::PackageProductRebindSourceReader.observe_acquired_claim`, `product_rebind_lease.py::PackageProductRebindLeaseReader.observe_acquired_claim`, `product_rebind_cleanup.py::PackageProductRebindCleanupReader.observe_acquired_claim`, and `product_runtime.py::PackageProductRuntimeBindingV1.inspect_acquired_rebind_claim` | Read-only Product observers require a selected active `acquired`, `inspecting`, or `extracted` attempt, current pinned Source bytes, a later live admission with all selected leases exited, exact root Source/acquisition evidence and the optional `inspecting` or required `extracted` verification record, no current-attempt pin or cleanup history, and a physical sink matching its acquisition receipt. The cleanup reader accounts for the entire Store, including unrelated committed roots, and refuses unattributed entries. The Product binding joins their exact attempt and resolution identities under one admitted epoch query | These are momentary observations. The internal root-restart Product owner rechecks them under a mutation guard; the narrow POSIX Coding CLI action is now available, while general A2 policy remains open |
| A2 resolving-closure node account and guarded preflight | `src/loushang/harness/package_product/product_rebind_cleanup.py::PackageProductRebindCleanupReader.observe_resolving_claim`, `src/loushang/harness/package_product/product_rebind_preflight.py::PackageProductResolvingRebindPreflightV1`, `src/loushang/harness/package_product/product_rebind_decision.py::PackageProductRebindDecisionOwner.recover_resolving_claim`, and `src/loushang/harness/package_product/product_runtime.py::PackageProductRuntimeBindingV1.inspect_resolving_rebind_claim`/`recover_resolving_rebind` | Read-only Product cleanup observation joins the selected dependency set to strict root and dependency artifact prefixes, proves each acquired physical sink, rejects unselected evidence or unattributed physical slots, and accounts for the entire quarantine Store. A verified plan requires all selected nodes to be acquired and verified. Owner regressions cover root-only, selection-only, Source-only, acquired and verified dependency prefixes plus unattributed and mismatched Source refusal | Evidence only. The interrupted read reconstructs per-node tombstone targets, rejects foreign or moved targets, and handles physical removal before completion or one completed node beside a live node. The admitted Product query joins Source, lease, and node facts. The mutation owner now rechecks them, records per-node tombstones before deletion, settles the whole Store, and appends a cleanup-bound restart; owner regressions cover partial multi-node cleanup and replaced or foreign targets. A real Coding Product root-only resolving claim recovers and commits a fresh Wheel. A real Product dependency claim also recovers after Source-drift refusal; its re-execution reaches `closure_verified` and rejects the Wheel under Coding's existing `local-data-only` no-dependency policy. Trusted dependency Product execution, later phases, and broader operator transport remain open; the root-only POSIX Coding CLI action is available |
| A2 verified-closure restart | `src/loushang/harness/package_product/product_rebind_cleanup.py::PackageProductRebindCleanupReader.observe_verified_claim`, `product_rebind_source.py::PackageProductRebindSourceReader.observe_verified_claim`, `product_rebind_decision.py::PackageProductRebindDecisionOwner.recover_verified_claim`, and `product_runtime.py::PackageProductRuntimeBindingV1.inspect_verified_rebind_claim`/`recover_verified_rebind` | A selected active `closure_verified` attempt requires one plan whose complete node set and Source, acquisition, Wheel, digest, size, and extraction evidence match the strict owner journals. The admitted Product query joins pinned bytes, exited leases, and the whole quarantine Store; the guarded mutation uses inode-bound per-node tombstones and a cleanup-bound restart at `classified` | Owner regressions prove root and dependency plan recovery, root-plan replay, absent-plan refusal, mismatched-plan refusal, and Source drift without mutation. A real Coding Product regression recovers a root-only verified plan and commits a fresh Wheel. A trusted dependency Product path, pin settlement, later phases, and broader A2 transport remain open; the root-only POSIX Coding CLI action is available |
| A2 pinned-claim read and inert adoption CAS | `src/loushang/harness/package_product/product_rebind_cleanup.py::PackageProductRebindCleanupReader.observe_pinned_claim`, `product_rebind_source.py::PackageProductRebindSourceReader.observe_pinned_claim`, `product_rebind_lease.py::PackageProductRebindLeaseReader.observe_pinned_claim`, `product_runtime.py::PackageProductRuntimeBindingV1.prepare_pinned_adoption`, `product_pinned_adoption.py::PackageProductPinnedAdoptionOwner.prepare`, and `plugin_lifecycle/journal.py::PackageLifecycleJournal.record_pinned_adoption` | The admitted Product query requires a selected active `transaction_pinned` claim, complete verified node evidence, an exact current/original plan, one still-acquired retention pin bound to configured recovery identity and graph targets, exited leases, current Source bytes, a complete Store scan, and no staging/publication/handoff facts. The Product records the full proposed admission before the Package CAS, then rechecks the plan, pin, Source and lease under mutation guard. The owner CAS preserves the attempt epoch, verified phase, and original request while selecting one new proposal | Owner regressions cover acquired, released, and missing pins, exact adoption replay, stale CAS refusal, missing Product proposal, prior live lease, and supersession tamper. A real Coding Product regression refuses changed Source, selects and replays the pinned proposal, and refuses a released pin. Existing Product routes refuse the old admission after selection, including after reopen. The adoption record grants no pin-release, cleanup, restart, or execution authority. Exact target fingerprints prevent a fresh-acquisition restart from reusing this pin. The guarded pinned route now commits a real Coding data Wheel using the unchanged verified attempt and one-use Product permit; Product tests cover selected-proposal supersession after runtime exit and recovery of a post-commit, pre-handoff crash. An operator repair command and later-phase recovery remain separate gates |
| A2 internal root cleanup and restart | `src/loushang/harness/package_product/product_rebind_decision.py::PackageProductRebindDecisionOwner.recover_acquired_claim`, `product_rebind_cleanup.py::PackageProductRebindCleanupReader.observe_interrupted_acquired_attempt`, and `product_runtime.py::PackageProductRuntimeBindingV1.recover_acquired_rebind` | A selected `acquired`, `inspecting`, or `extracted` root claim with no pin or later effects is interrupted under exact dual CAS only after Source, lease, Store, and receipt preflight. The Product then records an inode-bound cleanup tombstone, repairs only that target, verifies the whole Store and settled cleanup, and appends a Source/cleanup/lease-bound restart at `classified`. Owner regressions cover prior-live lease, Source drift, crashes before tombstone/repair/restart and after physical removal, exact replay, and a fresh rebind. A real Coding Product regression reopens a third runtime, refuses root Source drift without owner writes, runs the guarded restart, and commits a fresh Wheel | The narrow POSIX Coding CLI now invokes this Product owner. Selected `resolving_closure` node sets use a separate action; later phases, pin/retention settlement, and broader A2 transport remain separate gates |
| A2 Product guarded decision and execution owner | `src/loushang/harness/package_product/product_rebind_decision.py::PackageProductRebindDecisionOwner`, `src/loushang/harness/package_product/product_runtime.py::PackageProductRuntimeBindingV1`, and POSIX Product composition | Joins current Source, lease, and cleanup facts, binds the proposed admission before an exact Package decision CAS, supports replay and supersession, then rechecks and resumes under a fresh guard. A one-use process-local permit allows only the selected transaction and is revoked on guard exit. Real Coding Product tests commit a valid external data Wheel across two runtimes and recover an effect-free claimed attempt under a third runtime before a fresh decision and commitment | Narrow POSIX Coding CLI actions use this owner; general A2 policy, later phases, and broader transport remain open |
| A2 rebound execution and committed-handoff seam | `src/loushang/harness/resources/packages/product_lifecycle.py::PackageProductReboundRouteRequestV1`, `product_transaction.py`, `product_handoff.py`, and `product_composition.py::PackageCommittedProductHandoffRecovery` | The route keeps original ingress and new admission distinct; transaction and finalizer require the exact selected/resumed Package decision. Transaction execution refuses by default without a Product supplied authority; the local Wheel Product injects its guarded one-use authority. Finalizer checks the proposed-admission journal. Admitted startup recovery can reconstruct a committed rebound route under a third admission in the same Store epoch | A native Store regression proves missing-proposal refusal and settled handoff recovery. The internal `acquired`/`inspecting`/`extracted` restart avoids inheriting the old phase; selected `resolving_closure` and root-only `closure_verified` recovery use separate routes. The transaction can resume `set_published` under its existing admission. A strict Package checkpoint and guarded Coding Product query rejoin the published set, acquired pin, settled Store, current Source, and exited prior lease; a real Product crash and reopen regression refuses Source drift without lifecycle mutation. An exact published checkpoint now has a guarded replacement-admission selection and one-use commit permit; a second reopen supersedes a pending selection and refuses the old pinned route. Real POSIX Coding CLI, Session RPC, and Session TUI crash/reopen cases inspect, refuse `repair-staging` without lifecycle mutation, and commit through `repair-published`. Committed handoff recovery does not grant this authority. Broader A2 policy and later phases remain open |
| Candidate external Coding Screen Theme | `src/loushang/harness/resources/theme_document.py`, `src/loushang/harness/resources/_resource_item_projection.py`, `src/loushang/coding/ui/plugin_theme.py`, and `src/loushang/plugin/_coding_data_skill_wheel.py` | A style-only JSON document is validated at author and Product wheel boundaries, admitted by `resources.theme`, projected from the selected Product Store into the Session Catalog, and consumed only by an explicitly selected Coding Screen. Real Product regressions cover visible style, malformed refusal, duplicate identity, and new-Session disable fallback. The read-only Product preview reports selected Theme Catalog descriptors, duplicate-identity Product conflict, and disable removal without claiming visual consumption | Keep candidate until separate Product owner rollout decision, Hosted Mux/refresh policy, and broader platform evidence; Theme has no model-input semantics |
| Mutable helper manager | `src/loushang/harness/resources/plugins/manager.py::PluginManager` | Owns a registry and `_disabled_plugins`; exposes add/remove/enable/disable helpers | No new production construction; delete or reduce to inert compatibility/tests after all callers use management ports |
| Config persistence and fence | `src/loushang/harness/config/engine.py::LayeredConfig.transaction`, `src/loushang/harness/config/runtime.py::ScopedConfigRuntime.transaction`, `src/loushang/harness/config/_file_transaction.py`, `src/loushang/harness/config/agent/types.py`, `src/loushang/harness/config/agent/_settings_patch.py`, `src/loushang/harness/config/agent/_settings_codec.py`, and `src/loushang/harness/config/agent/manager.py::SettingsManager.bind_plugin_enablement_legacy_mutation_guard` | `LayeredConfig` locks all path-backed reads/writes in normalized order, rechecks exact runtime authority in the final engine-locked critical section, fences direct publication, queues captured commit snapshots before unlock, and does not decrement an active outer transaction when a nested authority check rejects entry; a bound `ScopedConfigRuntime` is the exclusive mutation/projection owner, follows `path -> engine -> runtime`, and exposes only the final transaction change. The settings schema defines/decodes the legacy `disabled_plugins` field, accepts one Coding registry authority, atomically publishes its conservative workspace aggregate, and rejects fenced peer writes after any receipt | Retain the generic config transaction and exclusive runtime binding; retain the legacy field/fence only through the minimum-version downgrade gate, then PLC9E deletes the field and mutators after evidence |
| Session activation dependency | `src/loushang/harness/session/bootstrap_activation.py::standard_agent_session_activation_plan` | Treats `disabled_plugins` as a Resource-root and Extension activation input | Delete this dependency after those consumers read the desired-state projection |
| Package/Resource projection chain | `src/loushang/harness/resources/packages/roots.py`, `src/loushang/harness/resources/packages/catalog.py`, `src/loushang/harness/resources/packages/projection.py`, and `src/loushang/harness/resources/packages/session.py` | Threads `disabled_plugins` through package catalog/root resolution and derives enabled mounts/entries | PLC9A migrates selection to exact desired revisions; retain Package/Resource projection while deleting the legacy veto input |
| Coding Continuity compatibility caller | `src/loushang/coding/continuity_bootstrap.py::bind_coding_configured_continuity` | A1-3 reads legacy `disabled_plugins` only as one-time migration input, resolves tombstones by canonical Source identity even without a live binding, reconciles before fingerprint/empty-source/idempotent returns, maps early compatibility failures into the stable bootstrap error/status contract, restores the last ready status when a same-fingerprint retry reuses a healthy composition, and reconciles again after new migration or desired-state changes | Retain the migration input through the compatibility window; never reinspect an absent tombstone and delete the field only at PLC9E after finalization evidence |
| Coding package-list fallback | `src/loushang/coding/cli/application.py::_run_list_packages` | Passes settings `disabled_plugins` into legacy catalog projection when the session query is unavailable | Delete the fallback after the common query port is mandatory and covered by startup diagnostics |
| Settings disable list | `src/loushang/harness/resources/plugins/authority.py::PluginResolutionAuthority.project_package` | Combines `source.enabled` with settings `disabled_plugins` | One-time migration to desired state; delete as runtime-selection input only after replay-safe migration proves explicit disabled/removed state is preserved |
| Resolver projection veto | `src/loushang/harness/resources/plugins/resolver.py::PluginResolver.project_package` | Computes effective enabled from source and manifest flags | Retain inert descriptor projection only after it stops deciding runtime selection |
| Preflight selection authority | `src/loushang/harness/resources/plugins/selection.py::PluginSelectionResolver.preflight` | An exact Product selection of a published revision is no longer vetoed by its `source.enabled` availability or `manifest.enabled` author default; package, binding, trust, and Approval checks remain | Preserve the absence of peer enablement vetoes; Source availability governs acquisition/update, and Product Desired State governs runtime selection |
| Manifest author default | `src/loushang/harness/resources/plugins/manifest.py::PluginManifestParser` | Legacy manifest parsing can carry `enabled`; the new v1 data-Wheel author manifest has exact fields and Product candidate admission rejects an `enabled` field, including `false`, before installation | Legacy `manifest.enabled` may seed install Desired State once after migration; it cannot remain a live veto. Keep the new author schema free of a second enablement writer |

The settings manager and Product configuration remain valid owners of settings
that are not Plugin lifecycle facts. PLC9A changes only Plugin lifecycle routes;
it must not absorb Skill, theme, model, or unrelated Product settings.

## Existing Command And Adapter Surfaces

| Surface | Exact source site | Current semantics and risk | PLC9 disposition and gate |
| --- | --- | --- | --- |
| Standard CLI grammar | `src/loushang/harness/cli/profile.py` and `src/loushang/harness/cli/parser.py::build_parser` | Exposes Package materialize/install/update/remove/uninstall and Plugin source/list/enable/disable flags; `--add-plugin`/`--remove-plugin` are compatibility aliases for source mutation | Preserve alias meaning, deprecate rather than reinterpret, and add distinct desired-state commands through a versioned CLI contract |
| CLI Package startup arguments | `src/loushang/harness/cli/agent_args.py::agent_cli_argument_values` | Projects startup `update_packages` and `check_package_updates` flags into normalized launch values | Retain as inert argument projection; execution remains behind the same PLC9B Package route/refusal gate |
| CLI Package dispatcher | `src/loushang/harness/cli/package_lifecycle.py::run_package_lifecycle` | A2 prefers `execute_package_lifecycle` with explicit `cli` provenance and one operation id per source; the compatibility method path remains only for Products without the typed seam | Retain the generic compatibility path; an activated Product Session always exposes the typed seam, so Plugin-bound input cannot bypass classification |
| Shared CLI composition | `src/loushang/harness/cli/host_operations.py::run_standard_cli_operations` | Composes Plugin listing/toggles and Package lifecycle operations as separate early operations | PLC9A1 migrates list/enable/disable; PLC9B migrates artifact operations; retain unrelated Skill/Package behavior |
| RPC Package commands | `src/loushang/harness/host/rpc/commands/packages.py::RpcPackageCommands` | A2 resolves the typed executor across runtime/Session before compatibility methods, preserves `rpc` provenance, and derives a stable operation id from the RPC command id | Retain as the existing Package RPC projection; it is not a second Plugin-management protocol and holds no owner/store/materializer authority |
| Session lifecycle facade | `src/loushang/harness/session/lifecycle_adapter.py::SessionLifecycleOperationAdapter` | Passes Package lifecycle calls to the current Session by dynamic method lookup | Replace Plugin-bound fallback with typed application ports; no concrete ledger/store mutation in the adapter |
| Public Session optional forwarding | `src/loushang/harness/session/facade_optional.py::SessionPackagePort` and `src/loushang/harness/session/facade_optional.py::SessionFacadeOptionalOperations` | A2 adds a typed, correlated lifecycle forwarder and retains legacy optional methods for compatibility | Keep forwarding-only; it imports records/provenance types but no concrete lifecycle owner |
| Session Package controller | `src/loushang/harness/resources/packages/session.py::SessionPackageController` | A2 owns one `execute_package_lifecycle` dispatcher and serializes either legacy records or pathless Product records | Retain for non-Plugin Packages; Product-bound operations preserve caller provenance and route once through `PackageOperationsRuntime` |
| Package operation coordinator | `src/loushang/harness/resources/packages/operations.py::PackageOperationsRuntime` | A2 classifies every single-source operation before materializer, settings, remove, or forget; active bulk update routes each installed record separately | Retain as the choke point; only explicit `non_plugin` may enter legacy behavior, while PLC9E later removes the sync compatibility path |
| Product application contract | `src/loushang/harness/resources/packages/product_contract.py` | A2 owns the versioned intent/outcome/pathless record, action/provenance types, and capability-poor operation Port separately from concrete activation | Transports and Product Session composition depend only on this contract; it imports no materializer, settings, Store, CLI/RPC, process, or filesystem owner |
| Product execution binding | `src/loushang/harness/resources/packages/product_lifecycle.py::PackageProductLifecycleExecutionBinding` | Indivisibly binds one lifecycle journal owner to one transaction port and rechecks the transaction's opaque owner binding immediately before every effect | Retain as the only Product-to-transaction binding; no transport or inventory may synthesize the owner identity |
| Product epoch transaction/query guard | `src/loushang/harness/resources/packages/product_activation.py::PackageProductEpochTransactionGuardPort`, `PackageProductLifecycleActivation.route`, and `PackageProductLifecycleActivation.execute_guarded_query` | Holds the cutover-paired shared runtime guard across fresh admission plus the complete transaction or inventory query; failure deactivates the binding | A2.3 must compose the guard from the same coordination identity as offline cutover; transports receive no lock/path capability |
| Product file epoch guard | `src/loushang/harness/resources/packages/product_epoch_guard.py::PackageProductFileEpochTransactionGuard` | Provides a concrete shared file-lock scope across admission and effects; an exclusive lock at that exact path cannot enter until the Product scope exits | Coding composition must bind it to the same coordination file as offline cutover and provide a real complete runtime-lease snapshot; this guard alone does not issue a lease or cut over a legacy root |
| Product lifecycle inventory and rollout mode | `src/loushang/harness/resources/packages/product_contract.py::PackageProductLifecycleInventoryPort`, `PackageProductLifecycleMode`, `PackageProductUpdateTargetV1`, `PackageProductUpdateCheckRequestV1`, and `PackageProductUpdateCheckV1` | Inventory targets bind opaque refs to exact Source identity; the typed check request carries operation id, entrypoint, and canonical scope; check output derives an opaque name and generic failure code; `legacy`, `dark`, and `enforced` are validated at the operation owner | Product inventory must carry the lifecycle `binding_id`, which is rechecked around every inventory access; legacy settings translate canonical `user` back to compatibility `global` without scope fallback |
| Product update batch manifest | `src/loushang/harness/resources/packages/product_inventory.py::PackageProductUpdateManifestJournal` and `src/loushang/harness/resources/packages/product_contract.py::PackageProductUpdateManifestReceiptV1` | Sole durable writer for credential-free `owner binding + batch operation id + canonical scope + ordered target refs`; it returns an exact pathless receipt, rejects unsafe existing storage, and makes owner/target drift fail closed | Retain separate from the lifecycle journal because it owns collection membership, not child effects; use the shared durable JSONL contract in a private directory with regular-file/no-link/owner/mode checks, directory fsync, lock, and partial-tail repair |
| Product activation/composition | `src/loushang/harness/resources/packages/product_activation.py::PackageProductLifecycleActivation`, `src/loushang/harness/resources/packages/product_composition.py::compose_package_product_lifecycle`, `src/loushang/harness/package_product/product_runtime.py::PackageProductRuntimeBindingV1`, and `src/loushang/harness/resources/packages/plugin_lifecycle/records.py::PackageLifecycleIngressRequestV2`/`PackageLifecycleRequestV2` | A2 recovers durable handoffs, admits/rechecks the exact epoch, writes the stable admission-request identity into an independent V2 lifecycle request field covered by the atomic accept/request fingerprint, preserves the V1 schema/fingerprint and real resolution-environment fingerprint, and requires the Product route DTO to match ingress with its admission receipt. A2.3 validates and activates one Product-owned aggregate before standard Session bootstrap and delivers the same lifecycle/inventory/mode to the Session | Product injects one factory at the canonical bootstrap boundary; omission remains legacy rollback. No default singleton, ambient Store, path, materializer, or deletion authority |
| Desired-state handoff adapter | `src/loushang/harness/plugin_management/package_product.py::PluginManagementPackageDesiredStateAdapter` | Maps the accepted post-publication install handoff to the sole management command owner with exact Package revision and inventory CAS evidence | Keep capability-poor and install-only in v1; remove/GC requires its separately accepted lifecycle contract |
| Product retention settlement | `src/loushang/harness/resources/packages/plugin_lifecycle/product_retention.py::PackageProductRetentionSettlementOwner` | Durably owns dependency pin evidence and replay-safe exact transaction-pin release after desired commit | Retain as the narrow handoff port implementation; it has no Store deletion, acquisition, selection, or transport authority |
| Startup source resolver | `src/loushang/harness/resources/packages/source_resolver.py::PackageSourceResolver.resolve_configured_sources_sync` | A2 routes a missing source with `startup` provenance before any synchronous legacy materialization | Only explicit `non_plugin` may fall back; Product-bound refusal is returned as a handled pathless record |

Source operations and desired operations are never synonyms:

| Command family | Sole meaning |
| --- | --- |
| source add/remove | change Source Authority configuration/availability only; never install, enable, retire, or delete a published revision |
| Package materialize/remove/uninstall | manage acquisition cache/source registration; a Plugin-bound target must route to canonical lifecycle or fail without mutation |
| Plugin install/enable/disable/update/remove | consume an exact verified revision where required and mutate desired state only through `PluginManagementService`; removal opens retirement but does not delete data/artifacts |

Every CLI alias, RPC binding, Session method, and future UI/SDK operation is
included in the common conformance matrix. Dynamic runtime/Session fallback is
not an authority boundary.

## Package Acquisition And Publication Seams

| Current seam | Exact source owner or symbol | Current fact | PLC9 disposition and gate |
| --- | --- | --- | --- |
| General package materializer | `src/loushang/harness/resources/packages/materializer.py::PackageMaterializer` | Owns install roots, lockfile mutation, source materialization, Plugin revision publication, and bindings | Split/compose behind one Package lifecycle transaction without duplicating lock or publication authority |
| Existing source policy port | `src/loushang/harness/resources/packages/materializer.py::PackageSourcePolicy` | Allows/denies a source string before materialization | Retain as one policy input only; it is not authenticated provenance, a bounded sink, or the complete Source Authority |
| Pinned POSIX local Wheel Source | `src/loushang/harness/resources/packages/plugin_lifecycle/local_source.py::PackagePinnedLocalWheelSourceAuthority` | Accepts only Product-listed canonical paths and policy revision with pinned SHA-256; opens each path component without following links and streams bytes through the bounded Package sink | Bind behind the Product runtime factory; Windows and network Sources need their own reviewed adapters, and this component alone does not activate a production route |
| Python installer backend | `src/loushang/harness/resources/packages/materializer.py::PythonPackageInstallerBackend` | Calls `uv pip install` and falls back to `python -m pip install` into a temporary target; the command does not enforce verified wheel-only input | Must not publish untrusted Plugin packages after PLC9B; replace with verified wheel acquisition/extraction or a separately accepted contained build service |
| Git materializer backend | `src/loushang/harness/resources/packages/materializer.py::GitPackageMaterializerBackend` | Shells out to fetch/clone/checkout Git sources as a source adapter/backend | Limit to authenticated fetch plus provenance/bytes; it must not choose final quarantine, publication, binding, or runtime authority |
| Startup auto-materializer | `src/loushang/harness/resources/packages/source_resolver.py::PackageSourceResolver.resolve_configured_sources_sync` | A2 routes each missing source through the Product lifecycle before the synchronous legacy materializer | Retain explicit-non-Plugin fallback only; startup remains neither a classifier nor a safe-publication owner |
| Package operation runtime | `src/loushang/harness/resources/packages/operations.py::PackageOperationsRuntime` | A2 is the one pre-effect classification choke point for materialize/install/update/remove/uninstall and per-record bulk update | Retain non-Plugin behavior; handled Plugin input cannot reach settings, materializer, mutable removal, or forget peers |
| Direct mutable removal | `src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.remove_remote_source` | Directly `shutil.rmtree()`s the mutable materialized target and updates the lockfile without Package lifecycle GC evidence | Never use as immutable Plugin revision GC; route/refuse Plugin-bound targets and narrow/delete at PLC9E after replay/pin/rollback proof |
| Binding/history forgetting | `src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.forget_remote_source` and `src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.forget_plugin_binding` | Removes current source records/bindings and can remove replay binding history | Preserve history required by desired revisions and pinned Sessions; mutation needs canonical lifecycle evidence or must refuse |
| Verified revision store | `src/loushang/harness/resources/plugins/revisions.py::PluginRevisionStore` | Copies a resolved local tree into owner-created quarantine, rejects unsafe filesystem entries, computes content identity, freezes, and atomically renames an immutable revision | Retain as a safe publication primitive; integrate only after bounded archive/wheel extraction and dependency closure verification |
| Verified revision handle | `src/loushang/harness/resources/plugins/revisions.py::VerifiedRevisionHandle` | Provides no-follow/stability-checked access to a published revision | Retain; consumers use exact handles rather than mutable source paths |
| Dependency lock v1 | `src/loushang/harness/resources/plugins/dependencies.py::PluginDependencyClosureLock` | Binds the final package content digest plus canonical installed `name==version` facts | Retain for replay compatibility; PLC9B adds a new version for recursive verified-artifact digests and never reinterprets v1 |
| Package lifecycle evidence | `src/loushang/harness/plugin_management/package_lifecycle.py::PluginPackageLifecycleLedger` | Determines conservative retention and recheckable GC candidates from desired/Instance/family/pin/cleanup evidence | Retain; it does not yet perform complete safe acquisition or artifact deletion |

No current single symbol owns the complete PLC9 target transaction from bounded
source bytes through safe extraction and dependency verification to immutable
publication. PLC9B must create that composition without claiming that
`PluginRevisionStore` validates archives or that `PluginPackageLifecycleLedger`
materializes packages.

## PLC9B.0 Exact Entrypoint And Owner Inventory

PLC9B.0 began with the pre-runtime-migration snapshot at parent `4bd71d63`; A2
revises the same two independently checked source-wide inventories to 110
ingress/declaration rows with 163 occurrences and 143 effect/capability rows
with 159 occurrences. The executable
guard parses Python syntax across `src/loushang`, including module/class/function
scope, imports/renamed imports, names, attributes, and exact dynamic strings.
Any count or qualified-site change must update this canonical inventory and
receive the same security-boundary review.

| Entrypoint/owner group | Current exact owner | PLC9B target authority and gate |
| --- | --- | --- |
| Coding Package query | `src/loushang/coding/cli/application.py::_run_list_packages` | Read-only query may remain; a future Plugin-bound artifact action must use the common application gate and cannot construct a materializer |
| CLI launch flags | `src/loushang/harness/cli/agent_args.py::agent_cli_argument_values` | Inert projection only; startup execution classifies before any side effect |
| Shared CLI Package dispatch | `src/loushang/harness/cli/package_lifecycle.py::run_package_lifecycle` and `_invoke_source_operation` | Transport adapter calls the one PLC9B application port or returns stable refusal |
| RPC Package transport | `src/loushang/harness/host/rpc/commands/packages.py::_PackageCapabilities`, `_DynamicPackageCapabilities`, and `RpcPackageCommands` | Transport capability cannot use dynamic fallback as authority; classify and route/refuse before Session/materializer mutation |
| Public Session forwarding | `src/loushang/harness/session/facade_optional.py::SessionPackagePort` and `SessionFacadeOptionalOperations` | Typed forwarding only; no concrete Package owner import or unsafe fallback |
| Session lifecycle compatibility | `src/loushang/harness/session/lifecycle_adapter.py::SessionLifecycleOperationAdapter` | Temporary adapter routes/refuses Plugin-bound input; dynamic method lookup grants no authority |
| Product Package composition | `src/loushang/harness/resources/packages/session.py::SessionPackageController` and `operations.py::PackageOperationsRuntime` | Retain non-Plugin behavior; Plugin-bound transaction enters the single Package lifecycle owner |
| Startup source materialization | `src/loushang/harness/resources/packages/source_resolver.py::PackageSourceResolver.resolve_configured_sources_sync` | Missing/ambiguous Plugin-bound Sources fail closed; startup is never a publication owner |
| Current general materializer | `src/loushang/harness/resources/packages/materializer.py::PackageMaterializer` | Narrow to source/cache compatibility or compose behind the PLC9B owner; direct sync/check, remove, and forget routes cannot publish/delete Plugin revisions |
| Future ingress/classifier | one Package lifecycle ingress composition in `loushang.harness.resources.packages` (absent in PLC9B.0) | Sole three-way classification authority; transports submit unclassified requests and cannot choose non-Plugin fallback |
| Future complete transaction | one Package lifecycle composition in `loushang.harness.resources.packages` (absent in PLC9B.0) | Sole owner of quarantine, limits, inert extraction, wheel/closure verification, retention-pin coordination, staged committed-set publication, durable phases, and final receipt |
| Source adapter | future typed Source Authority byte/provenance port over current policy/Git/Python inputs (absent in PLC9B.0) | Authenticated provenance and bounded streaming only; never receives an owner path or publication/binding authority |
| Neutral artifact publication primitive | future inert artifact-store evolution in `loushang.harness.resources.packages` (absent in PLC9B.0) | Sole physical owner of dependency trees and their `VerifiedArtifactRefV1` values; it never stores/designates a Plugin root or commits/admits a graph |
| Plugin-root publication primitive | `src/loushang/harness/resources/plugins/revisions.py::PluginRevisionStore` | Sole physical owner of the root tree and its only stable `PluginRevisionRefV1`, bound to Installation/Plugin identity; it never owns dependencies or logical set commit |
| Committed-set owner | future PLC9B Package lifecycle owner (absent in PLC9B.0) | Sole writer of `CommittedPackageSetRefV1`, binding one designated Plugin root plus exact dependency refs to request/operation, Product/scope, identities, closure/set digest, and commit revision |
| Commit admission | future read-only Package commit-admission port (absent in PLC9B.0) | Proves that the requested `PluginRevisionRefV1` is the designated root of the exact committed set for the request/operation, Product/scope, Installation/Plugin, and closure digest; dependency-as-root and cross-set/scope/Plugin refs fail without reopening |
| Recursive closure evidence | future closure v2 owned by the PLC9B Package lifecycle owner (absent in PLC9B.0) | Freezes a prepublication verified plan first, then constructs immutable nodes/lock once from exact typed stable refs; digested evidence is never patched and `PluginDependencyClosureLock` v1 remains replay-only |
| Retention evidence | future narrow retention port over `src/loushang/harness/plugin_management/package_lifecycle.py::PluginPackageLifecycleLedger` | Transaction pins cover the complete graph before staging and transfer only after desired evidence; Package owner does not import the ledger, which never acquires, extracts, publishes, selects, or deletes by itself |

The first machine-checked block freezes lifecycle ingress declarations,
forwarding calls, module-level transport specifications, and dynamic strings.

<!-- plc9b-entrypoint-inventory:start -->
```text
src/loushang/coding/cli/application.py::_run_coding_pre_runtime_operation::update_packages = 2
src/loushang/coding/cli/application.py::_run_list_packages::get_packages = 5
src/loushang/coding/cli/application.py::run_cli::update_packages = 1
src/loushang/coding/package_product_cli.py::uninstall_coding_fenced_data_wheels::uninstall_package = 1
src/loushang/harness/cli/agent_args.py::AgentCliArgs::check_package_updates = 1
src/loushang/harness/cli/agent_args.py::AgentCliArgs::update_packages = 1
src/loushang/harness/cli/agent_args.py::agent_cli_argument_values::check_package_updates = 2
src/loushang/harness/cli/agent_args.py::agent_cli_argument_values::install_package = 1
src/loushang/harness/cli/agent_args.py::agent_cli_argument_values::materialize_package = 1
src/loushang/harness/cli/agent_args.py::agent_cli_argument_values::remove_package = 1
src/loushang/harness/cli/agent_args.py::agent_cli_argument_values::uninstall_package = 1
src/loushang/harness/cli/agent_args.py::agent_cli_argument_values::update_package = 1
src/loushang/harness/cli/agent_args.py::agent_cli_argument_values::update_packages = 2
src/loushang/harness/cli/host_operations.py::agent_standard_cli_operation_request::check_package_updates = 1
src/loushang/harness/cli/host_operations.py::agent_standard_cli_operation_request::update_packages = 1
src/loushang/harness/cli/launch.py::agent_cli_launch_plan::check_package_updates = 2
src/loushang/harness/cli/launch.py::agent_cli_launch_plan::update_packages = 2
src/loushang/harness/cli/package_lifecycle.py::_invoke_source_operation::execute_package_lifecycle = 1
src/loushang/harness/cli/package_lifecycle.py::_invoke_source_operation::install_package = 1
src/loushang/harness/cli/package_lifecycle.py::_invoke_source_operation::uninstall_package = 3
src/loushang/harness/cli/package_lifecycle.py::_invoke_source_operation::uninstall_package_async = 1
src/loushang/harness/cli/package_lifecycle.py::_lifecycle_action::install_package = 1
src/loushang/harness/cli/package_lifecycle.py::_lifecycle_action::materialize_package = 1
src/loushang/harness/cli/package_lifecycle.py::_lifecycle_action::remove_package = 1
src/loushang/harness/cli/package_lifecycle.py::_lifecycle_action::uninstall_package = 1
src/loushang/harness/cli/package_lifecycle.py::_lifecycle_action::update_package = 1
src/loushang/harness/cli/package_lifecycle.py::run_package_lifecycle::check_package_updates = 3
src/loushang/harness/cli/package_lifecycle.py::run_package_lifecycle::install_package = 2
src/loushang/harness/cli/package_lifecycle.py::run_package_lifecycle::materialize_package = 1
src/loushang/harness/cli/package_lifecycle.py::run_package_lifecycle::remove_package = 1
src/loushang/harness/cli/package_lifecycle.py::run_package_lifecycle::uninstall_package = 1
src/loushang/harness/cli/package_lifecycle.py::run_package_lifecycle::update_package = 1
src/loushang/harness/cli/package_lifecycle.py::run_package_lifecycle::update_packages = 4
src/loushang/harness/cli/package_lifecycle.py::_invoke_operation::check_package_updates = 1
src/loushang/harness/cli/package_lifecycle.py::_invoke_operation::update_packages = 2
src/loushang/harness/cli/profile.py::<module>::check_package_updates = 1
src/loushang/harness/cli/profile.py::<module>::install_package = 1
src/loushang/harness/cli/profile.py::<module>::materialize_package = 1
src/loushang/harness/cli/profile.py::<module>::remove_package = 1
src/loushang/harness/cli/profile.py::<module>::uninstall_package = 1
src/loushang/harness/cli/profile.py::<module>::update_package = 1
src/loushang/harness/cli/profile.py::<module>::update_packages = 1
src/loushang/harness/host/rpc/commands/packages.py::<module>::check_package_updates = 2
src/loushang/harness/host/rpc/commands/packages.py::<module>::install_package = 2
src/loushang/harness/host/rpc/commands/packages.py::<module>::materialize_package = 2
src/loushang/harness/host/rpc/commands/packages.py::<module>::remove_package = 2
src/loushang/harness/host/rpc/commands/packages.py::<module>::uninstall_package = 2
src/loushang/harness/host/rpc/commands/packages.py::<module>::update_package = 2
src/loushang/harness/host/rpc/commands/packages.py::<module>::update_packages = 2
src/loushang/harness/host/rpc/commands/packages.py::RpcPackageCommands.bindings::get_packages = 2
src/loushang/harness/host/rpc/commands/packages.py::RpcPackageCommands.get_packages::get_packages = 6
src/loushang/harness/host/rpc/commands/packages.py::_DynamicPackageCapabilities.check_package_updates::check_package_updates = 1
src/loushang/harness/host/rpc/commands/packages.py::_DynamicPackageCapabilities.get_packages::get_packages = 2
src/loushang/harness/host/rpc/commands/packages.py::_DynamicPackageCapabilities.install_package::install_package = 1
src/loushang/harness/host/rpc/commands/packages.py::_DynamicPackageCapabilities.materialize_package::materialize_package = 1
src/loushang/harness/host/rpc/commands/packages.py::_DynamicPackageCapabilities.remove_package::remove_package = 1
src/loushang/harness/host/rpc/commands/packages.py::_DynamicPackageCapabilities.uninstall_package::uninstall_package = 1
src/loushang/harness/host/rpc/commands/packages.py::_DynamicPackageCapabilities.update_package::update_package = 1
src/loushang/harness/host/rpc/commands/packages.py::_DynamicPackageCapabilities.update_packages::update_packages = 1
src/loushang/harness/host/rpc/commands/packages.py::_DynamicPackageCapabilities._invoke_collection::check_package_updates = 1
src/loushang/harness/host/rpc/commands/packages.py::_DynamicPackageCapabilities._invoke_collection::update_packages = 1
src/loushang/harness/host/rpc/commands/packages.py::_DynamicPackageCapabilities._invoke_lifecycle::execute_package_lifecycle = 3
src/loushang/harness/host/rpc/commands/packages.py::_DynamicPackageCapabilities._invoke_lifecycle::install_package = 1
src/loushang/harness/host/rpc/commands/packages.py::_DynamicPackageCapabilities._invoke_lifecycle::materialize_package = 1
src/loushang/harness/host/rpc/commands/packages.py::_DynamicPackageCapabilities._invoke_lifecycle::remove_package = 1
src/loushang/harness/host/rpc/commands/packages.py::_DynamicPackageCapabilities._invoke_lifecycle::uninstall_package = 1
src/loushang/harness/host/rpc/commands/packages.py::_DynamicPackageCapabilities._invoke_lifecycle::uninstall_package_async = 1
src/loushang/harness/host/rpc/commands/packages.py::_DynamicPackageCapabilities._invoke_lifecycle::update_package = 1
src/loushang/harness/host/rpc/commands/packages.py::_PackageCapabilities.check_package_updates::check_package_updates = 1
src/loushang/harness/host/rpc/commands/packages.py::_PackageCapabilities.get_packages::get_packages = 1
src/loushang/harness/host/rpc/commands/packages.py::_PackageCapabilities.install_package::install_package = 1
src/loushang/harness/host/rpc/commands/packages.py::_PackageCapabilities.materialize_package::materialize_package = 1
src/loushang/harness/host/rpc/commands/packages.py::_PackageCapabilities.remove_package::remove_package = 1
src/loushang/harness/host/rpc/commands/packages.py::_PackageCapabilities.uninstall_package::uninstall_package = 1
src/loushang/harness/host/rpc/commands/packages.py::_PackageCapabilities.update_package::update_package = 1
src/loushang/harness/host/rpc/commands/packages.py::_PackageCapabilities.update_packages::update_packages = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.check_package_updates::check_package_updates = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.materialize_remote_source_sync::materialize_remote_source_sync = 1
src/loushang/harness/resources/packages/session.py::SessionPackageController.check_package_updates::check_package_updates = 2
src/loushang/harness/resources/packages/session.py::SessionPackageController.execute_package_lifecycle::execute_package_lifecycle = 1
src/loushang/harness/resources/packages/session.py::SessionPackageController.execute_package_lifecycle_collection::check_package_updates = 1
src/loushang/harness/resources/packages/session.py::SessionPackageController.get_packages::get_packages = 1
src/loushang/harness/resources/packages/session.py::SessionPackageController.install_package::install_package = 1
src/loushang/harness/resources/packages/session.py::SessionPackageController.materialize_package::materialize_package = 1
src/loushang/harness/resources/packages/session.py::SessionPackageController.remove_package::remove_package = 1
src/loushang/harness/resources/packages/session.py::SessionPackageController.uninstall_package::uninstall_package = 1
src/loushang/harness/resources/packages/session.py::SessionPackageController.uninstall_package_async::uninstall_package_async = 1
src/loushang/harness/resources/packages/session.py::SessionPackageController.update_package::update_package = 1
src/loushang/harness/resources/packages/session.py::SessionPackageController.update_packages::update_packages = 1
src/loushang/harness/resources/packages/source_resolver.py::PackageSourceResolver._materialize_startup_source::materialize_remote_source_sync = 2
src/loushang/harness/session/facade_optional.py::SessionFacadeOptionalOperations.check_package_updates::check_package_updates = 2
src/loushang/harness/session/facade_optional.py::SessionFacadeOptionalOperations.execute_package_lifecycle::execute_package_lifecycle = 2
src/loushang/harness/session/facade_optional.py::SessionFacadeOptionalOperations.get_packages::get_packages = 2
src/loushang/harness/session/facade_optional.py::SessionFacadeOptionalOperations.install_package::install_package = 2
src/loushang/harness/session/facade_optional.py::SessionFacadeOptionalOperations.materialize_package::materialize_package = 2
src/loushang/harness/session/facade_optional.py::SessionFacadeOptionalOperations.remove_package::remove_package = 2
src/loushang/harness/session/facade_optional.py::SessionFacadeOptionalOperations.uninstall_package::uninstall_package = 2
src/loushang/harness/session/facade_optional.py::SessionFacadeOptionalOperations.uninstall_package_async::uninstall_package_async = 2
src/loushang/harness/session/facade_optional.py::SessionFacadeOptionalOperations.update_package::update_package = 2
src/loushang/harness/session/facade_optional.py::SessionFacadeOptionalOperations.update_packages::update_packages = 2
src/loushang/harness/session/facade_optional.py::SessionPackagePort.check_package_updates::check_package_updates = 1
src/loushang/harness/session/facade_optional.py::SessionPackagePort.execute_package_lifecycle::execute_package_lifecycle = 1
src/loushang/harness/session/facade_optional.py::SessionPackagePort.get_packages::get_packages = 1
src/loushang/harness/session/facade_optional.py::SessionPackagePort.install_package::install_package = 1
src/loushang/harness/session/facade_optional.py::SessionPackagePort.materialize_package::materialize_package = 1
src/loushang/harness/session/facade_optional.py::SessionPackagePort.remove_package::remove_package = 1
src/loushang/harness/session/facade_optional.py::SessionPackagePort.uninstall_package::uninstall_package = 1
src/loushang/harness/session/facade_optional.py::SessionPackagePort.uninstall_package_async::uninstall_package_async = 1
src/loushang/harness/session/facade_optional.py::SessionPackagePort.update_package::update_package = 1
src/loushang/harness/session/facade_optional.py::SessionPackagePort.update_packages::update_packages = 1
src/loushang/harness/session/lifecycle_adapter.py::SessionLifecycleOperationAdapter.check_package_updates::check_package_updates = 2
src/loushang/harness/session/lifecycle_adapter.py::SessionLifecycleOperationAdapter.get_packages::get_packages = 2
src/loushang/harness/session/lifecycle_adapter.py::SessionLifecycleOperationAdapter.install_package::install_package = 2
src/loushang/harness/session/lifecycle_adapter.py::SessionLifecycleOperationAdapter.materialize_package::materialize_package = 2
src/loushang/harness/session/lifecycle_adapter.py::SessionLifecycleOperationAdapter.remove_package::remove_package = 2
src/loushang/harness/session/lifecycle_adapter.py::SessionLifecycleOperationAdapter.uninstall_package::uninstall_package = 2
src/loushang/harness/session/lifecycle_adapter.py::SessionLifecycleOperationAdapter.uninstall_package::uninstall_package_async = 2
src/loushang/harness/session/lifecycle_adapter.py::SessionLifecycleOperationAdapter.update_package::update_package = 2
src/loushang/harness/session/lifecycle_adapter.py::SessionLifecycleOperationAdapter.update_packages::update_packages = 2
```
<!-- plc9b-entrypoint-inventory:end -->

The second machine-checked block freezes capability construction/reference and
effect seams across Product composition, operations, source resolution,
materialization, mutable remove/forget, Plugin publish/bind/reopen, and revision
store access. It counts renamed imports as their original sensitive symbol.

<!-- plc9b-effect-inventory:start -->
```text
src/loushang/coding/_base_plugin.py::<module>::CodingPackageMaterializer = 1
src/loushang/coding/_base_plugin.py::prepare_coding_base_plugin_assembly::CodingPackageMaterializer = 2
src/loushang/coding/_base_plugin.py::prepare_managed_coding_base_plugin_assembly::CodingPackageMaterializer = 2
src/loushang/coding/_base_plugin.py::prepare_managed_coding_base_plugin_assembly::reopen_plugin_package = 1
src/loushang/coding/_capability_plugin_composition.py::<module>::CodingPackageMaterializer = 1
src/loushang/coding/_capability_plugin_composition.py::_resolve_managed_capability_plugins::CodingPackageMaterializer = 1
src/loushang/coding/_capability_plugin_composition.py::_resolve_managed_capability_plugins::reopen_plugin_package = 1
src/loushang/coding/_capability_plugin_composition.py::_validate_preparation_inputs::CodingPackageMaterializer = 2
src/loushang/coding/_capability_plugin_composition.py::prepare_coding_capability_plugin_composition::CodingPackageMaterializer = 1
src/loushang/coding/bootstrap.py::<module>::CodingPackageMaterializer = 1
src/loushang/coding/bootstrap.py::<module>::GitPackageMaterializerBackend = 1
src/loushang/coding/bootstrap.py::_create_agent_session::CodingPackageMaterializer = 4
src/loushang/coding/bootstrap.py::_create_agent_session::GitPackageMaterializerBackend = 1
src/loushang/coding/bootstrap.py::_default_package_materializer::CodingPackageMaterializer = 2
src/loushang/coding/bootstrap.py::_default_package_materializer::GitPackageMaterializerBackend = 1
src/loushang/coding/bootstrap.py::create_agent_session::CodingPackageMaterializer = 1
src/loushang/coding/bootstrap.py::create_agent_session_from_services::CodingPackageMaterializer = 1
src/loushang/coding/bootstrap.py::create_agent_session_result::CodingPackageMaterializer = 1
src/loushang/coding/continuity_bootstrap.py::<module>::CodingPackageMaterializer = 1
src/loushang/coding/continuity_bootstrap.py::<module>::GitPackageMaterializerBackend = 1
src/loushang/coding/continuity_bootstrap.py::<module>::PackageMaterializer = 1
src/loushang/coding/continuity_bootstrap.py::_coding_continuity_materializer::CodingPackageMaterializer = 2
src/loushang/coding/continuity_bootstrap.py::_coding_continuity_materializer::GitPackageMaterializerBackend = 1
src/loushang/coding/continuity_bootstrap.py::_continuity_runtime_inputs::PackageMaterializer = 1
src/loushang/coding/continuity_bootstrap.py::_continuity_runtime_inputs::reopen_plugin_package = 1
src/loushang/coding/continuity_bootstrap.py::_inspect_continuity_source::PackageMaterializer = 1
src/loushang/coding/continuity_bootstrap.py::_publish_continuity_runtime::PackageMaterializer = 1
src/loushang/coding/continuity_bootstrap.py::bind_coding_configured_continuity::PackageMaterializer = 1
src/loushang/coding/lsp/_plugin_opt_in.py::<module>::CodingPackageMaterializer = 1
src/loushang/coding/lsp/_plugin_opt_in.py::assemble_coding_lsp_plugin_opt_in::CodingPackageMaterializer = 1
src/loushang/coding/lsp/_plugin_opt_in.py::prepare_coding_lsp_plugin_opt_in::CodingPackageMaterializer = 1
src/loushang/coding/package_legacy_local_wheel.py::<module>::PluginRevisionStore = 1
src/loushang/coding/package_legacy_local_wheel.py::reacquire_coding_legacy_local_plugin_wheel::PluginRevisionStore = 1
src/loushang/coding/resource_runtime.py::<module>::CodingPackageMaterializer = 1
src/loushang/coding/resource_runtime.py::<module>::PackageMaterializer = 1
src/loushang/coding/resource_runtime.py::CodingPackageMaterializer::CodingPackageMaterializer = 1
src/loushang/coding/resource_runtime.py::CodingPackageMaterializer::PackageMaterializer = 1
src/loushang/coding/session/agent_session.py::<module>::CodingPackageMaterializer = 1
src/loushang/coding/session/agent_session.py::AgentSession.__init__::CodingPackageMaterializer = 1
src/loushang/harness/resources/packages/__init__.py::<module>::GitPackageMaterializerBackend = 2
src/loushang/harness/resources/packages/__init__.py::<module>::PackageMaterializer = 2
src/loushang/harness/resources/packages/__init__.py::<module>::PackageOperationsRuntime = 2
src/loushang/harness/resources/packages/__init__.py::<module>::PackageSourceResolver = 2
src/loushang/harness/resources/packages/__init__.py::<module>::PythonPackageInstallerBackend = 2
src/loushang/harness/resources/packages/catalog.py::<module>::PackageMaterializer = 1
src/loushang/harness/resources/packages/catalog.py::PackageCatalogBuilder._local_plugin_entry::PackageMaterializer = 1
src/loushang/harness/resources/packages/catalog.py::PackageCatalogBuilder.collect::PackageMaterializer = 1
src/loushang/harness/resources/packages/catalog.py::PackageCatalogBuilder.remote_package_entry::PackageMaterializer = 1
src/loushang/harness/resources/packages/catalog.py::collect_package_catalog::PackageMaterializer = 1
src/loushang/harness/resources/packages/materializer.py::<module>::PluginRevisionStore = 1
src/loushang/harness/resources/packages/materializer.py::GitPackageMaterializerBackend::GitPackageMaterializerBackend = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer::PackageMaterializer = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.__init__::PluginRevisionStore = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.__init__::PythonPackageInstallerBackend = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.__init__::_plugin_revision_store = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer._bind_plugin_packages::_bind_plugin_packages = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer._run_backend_for_record::_run_backend_for_record = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer._run_backend_for_record_sync::_run_backend_for_record_sync = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.bind_plugin_packages::_bind_plugin_packages = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.bind_plugin_packages::bind_plugin_packages = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.forget_plugin_binding::forget_plugin_binding = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.forget_remote_source::forget_remote_source = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.materialize_remote_source::_run_backend_for_record = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.materialize_remote_source::materialize_remote_source = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.materialize_remote_source::prepare_remote_source = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.materialize_remote_source_sync::_run_backend_for_record_sync = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.materialize_remote_source_sync::materialize_remote_source_sync = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.materialize_remote_source_sync::prepare_remote_source = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.materialize_temporary_remote_source::_run_backend_for_record = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.materialize_temporary_remote_source::materialize_temporary_remote_source = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.materialize_temporary_remote_source_sync::_run_backend_for_record_sync = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.materialize_temporary_remote_source_sync::materialize_temporary_remote_source_sync = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.prepare_remote_source::prepare_remote_source = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.publish_plugin_packages::PluginRevisionStore.publish_all = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.publish_plugin_packages::_plugin_revision_store = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.publish_plugin_packages::publish_all = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.publish_plugin_packages::publish_plugin_packages = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.rebind_plugin_packages::_bind_plugin_packages = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.rebind_plugin_packages::rebind_plugin_packages = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.remove_remote_source::remove_remote_source = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.reopen_plugin_package::PluginRevisionStore.reopen = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.reopen_plugin_package::_plugin_revision_store = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.reopen_plugin_package::reopen_plugin_package = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.update_all_remote_sources::update_all_remote_sources = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.update_all_remote_sources::update_remote_source = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.update_remote_source::_run_backend_for_record = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.update_remote_source::prepare_remote_source = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.update_remote_source::update_remote_source = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.update_remote_source_sync::_run_backend_for_record_sync = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.update_remote_source_sync::prepare_remote_source = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.update_remote_source_sync::update_remote_source_sync = 1
src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.uses_storage_authority::_plugin_revision_store = 1
src/loushang/harness/resources/packages/materializer.py::PythonPackageInstallerBackend::PythonPackageInstallerBackend = 1
src/loushang/harness/resources/packages/materializer.py::_record_with_local_git_state::GitPackageMaterializerBackend = 1
src/loushang/harness/resources/packages/operations.py::<module>::PackageOperationsRuntime = 1
src/loushang/harness/resources/packages/operations.py::PackageMaterializerPort.forget_remote_source::forget_remote_source = 1
src/loushang/harness/resources/packages/operations.py::PackageMaterializerPort.materialize_remote_source::materialize_remote_source = 1
src/loushang/harness/resources/packages/operations.py::PackageMaterializerPort.remove_remote_source::remove_remote_source = 1
src/loushang/harness/resources/packages/operations.py::PackageMaterializerPort.update_all_remote_sources::update_all_remote_sources = 1
src/loushang/harness/resources/packages/operations.py::PackageMaterializerPort.update_remote_source::update_remote_source = 1
src/loushang/harness/resources/packages/operations.py::PackageOperationsRuntime::PackageOperationsRuntime = 1
src/loushang/harness/resources/packages/operations.py::PackageOperationsRuntime._forget_remote_source::forget_remote_source = 1
src/loushang/harness/resources/packages/operations.py::PackageOperationsRuntime._materialize_legacy::materialize_remote_source = 1
src/loushang/harness/resources/packages/operations.py::PackageOperationsRuntime._remove_legacy::remove_remote_source = 1
src/loushang/harness/resources/packages/operations.py::PackageOperationsRuntime.update::update_remote_source = 1
src/loushang/harness/resources/packages/operations.py::PackageOperationsRuntime.update_all::update_all_remote_sources = 1
src/loushang/harness/resources/packages/projection.py::<module>::PackageMaterializer = 1
src/loushang/harness/resources/packages/projection.py::collect_projected_package_entries::PackageMaterializer = 1
src/loushang/harness/resources/packages/roots.py::<module>::PackageMaterializer = 1
src/loushang/harness/resources/packages/roots.py::configure_resource_loader_roots::PackageMaterializer = 1
src/loushang/harness/resources/packages/roots.py::resolve_package_resource_roots::PackageMaterializer = 1
src/loushang/harness/resources/packages/session.py::<module>::PackageMaterializer = 2
src/loushang/harness/resources/packages/session.py::<module>::PackageOperationsRuntime = 1
src/loushang/harness/resources/packages/session.py::<module>::PackageSourceResolver = 1
src/loushang/harness/resources/packages/session.py::SessionPackageController::PackageOperationsRuntime = 1
src/loushang/harness/resources/packages/session.py::SessionPackageController.__post_init__::PackageOperationsRuntime = 1
src/loushang/harness/resources/packages/session.py::SessionPackageController.prepare_configured_remote_package_records::PackageSourceResolver = 1
src/loushang/harness/resources/packages/source_resolver.py::<module>::PackageMaterializer = 1
src/loushang/harness/resources/packages/source_resolver.py::PackageSourceResolver::PackageMaterializer = 1
src/loushang/harness/resources/packages/source_resolver.py::PackageSourceResolver::PackageSourceResolver = 1
src/loushang/harness/resources/packages/source_resolver.py::PackageSourceResolver.prepare_configured_remote_records::prepare_remote_source = 1
src/loushang/harness/resources/packages/source_resolver.py::PackageSourceResolver._materialize_startup_source::materialize_remote_source_sync = 2
src/loushang/harness/resources/plugins/__init__.py::<module>::PluginRevisionStore = 2
src/loushang/harness/resources/plugins/authority.py::PluginBindingStore.bind_plugin_packages::bind_plugin_packages = 1
src/loushang/harness/resources/plugins/authority.py::PluginBindingStore.publish_plugin_packages::publish_plugin_packages = 1
src/loushang/harness/resources/plugins/authority.py::PluginResolutionAuthority.publish_runtime::bind_plugin_packages = 1
src/loushang/harness/resources/plugins/authority.py::PluginResolutionAuthority.publish_runtime::publish_plugin_packages = 1
src/loushang/harness/resources/plugins/revisions.py::<module>::PluginRevisionStore = 1
src/loushang/harness/resources/plugins/revisions.py::PluginRevisionStore::PluginRevisionStore = 1
src/loushang/harness/resources/plugins/revisions.py::PluginRevisionStore.publish::PluginRevisionStore.publish = 1
src/loushang/harness/resources/plugins/revisions.py::PluginRevisionStore.publish_all::PluginRevisionStore.publish = 1
src/loushang/harness/resources/plugins/revisions.py::PluginRevisionStore.publish_all::publish_all = 1
src/loushang/harness/resources/plugins/revisions.py::PluginRevisionStore.reopen::PluginRevisionStore.reopen = 1
src/loushang/harness/session/agent_adapter.py::<module>::PackageMaterializer = 1
src/loushang/harness/session/agent_adapter.py::AgentSessionAdapterMixin::PackageMaterializer = 1
src/loushang/harness/session/agent_product.py::<module>::PackageMaterializer = 1
src/loushang/harness/session/agent_product.py::AgentProductSession.__init__::PackageMaterializer = 1
src/loushang/harness/session/bootstrap_configuration.py::<module>::PackageMaterializer = 1
src/loushang/harness/session/bootstrap_configuration.py::<module>::PackageSourceResolver = 1
src/loushang/harness/session/bootstrap_configuration.py::StandardAgentSessionConfigurationRequest::PackageMaterializer = 1
src/loushang/harness/session/bootstrap_configuration.py::StandardAgentSessionConfigurationRuntime._package_sources::PackageSourceResolver = 1
src/loushang/harness/session/bootstrap_construction.py::<module>::PackageMaterializer = 1
src/loushang/harness/session/bootstrap_construction.py::AgentProductConstructionBinding.construct::PackageMaterializer = 1
```
<!-- plc9b-effect-inventory:end -->

Static syntax cannot prove a complete Python call graph. Computed reflection,
string-built sensitive names, and callable laundering are forbidden, and later
runtime route-conformance must prove one owner plus negative side effects. The
effect inventory ensures that acquiring or referencing a known sensitive
capability in a new scope cannot pass silently.

## Execution And Containment Seams

| Current seam | Exact source owner or symbol | Current fact | PLC9 disposition and gate |
| --- | --- | --- | --- |
| Declaration source union | `src/loushang/harness/resources/plugins/declarations.py::PluginDeclarationSourceKind` | Exactly `document` or `in_process`; this describes how the inert declaration is acquired | Retain as an independent axis; a document may declare Worker execution, so PLC9 does not invent a Worker source kind |
| Contribution execution model | `src/loushang/harness/resources/plugins/contribution_types.py::PluginContributionExecutionModel`; `src/loushang/harness/resources/plugins/declarations.py::PluginLocalWorkerConfiguration`, `PluginContributionIndex`, and `PluginDeclarationDocument`; `src/loushang/harness/resources/plugins/selection.py::PluginSelectionResolver._finalize` | Exactly `data_only`, `in_process`, or `local_worker`; legacy index v2/IR v2/document v1 retain exact meaning, while v3/v3/v2 carry an explicit versioned Worker configuration and reject downgrade/partial records; final selection rejoins the IR version/topology/configuration to its indexed reservation | Retain as the inert execution-topology axis; `remote_service` remains separately deferred and decoding/selection mint no runtime authority |
| Author SDK | `src/loushang/plugin/__init__.py` | Exposes declarative authoring/validation and the narrow Provider runtime ABI; no management, Worker, Process Host, or Sandbox owner objects | Preserve the authority firewall; any future Worker authoring surface is data-only and versioned |
| Raw process owner | `src/loushang/harness/workspace/process/host.py::ProcessHost` | Owns bounded child count, I/O limits, process lifetime, termination, and an optional containment-planner hook | Reuse only behind the authorized launcher; raw construction/start is not Worker admission |
| Generic authorized process launcher | `src/loushang/harness/tools/process_hosting.py::ScopeBoundProcessLauncher.start` | Runs Policy/Approval/Authorization and permits the configured best-effort or required containment mode; it rejects private managed requests | Retain for general process Tools, but explicitly forbid this generic public method for managed Worker admission |
| Private managed-process substrate | `src/loushang/harness/tools/process_hosting.py::_managed_process_launch_request`, `src/loushang/harness/tools/process_hosting.py::ScopeBoundProcessLauncher._start_managed`, and `src/loushang/harness/tools/process_hosting.py::ScopeBoundProcessLauncher._verify_managed_start_authority` | Existing private mechanics require an owner-minted request/launcher, mandatory Approval, required containment, and verification of a Sandbox-owner-bound plan | Reuse behind a new owner-only `ManagedWorkerLaunchPort`; neither the private symbols nor the generic launcher become a Worker-facing API |
| Existing managed caller precedent | `src/loushang/harness/tools/skill_actions.py::execute_managed_skill_action` | Managed Skill actions privately construct the sealed request and call the managed start path after verifying authority | Retain as proof of the current owner-only chain, not as a Worker port or declaration contract |
| Long-lived containment planner | `src/loushang/harness/sandbox/process.py::HostedProcessContainmentPlanner` | Plans/tracks hosted-process containment; required mode fails closed and verifies Sandbox-owned managed plans | Retain as the Worker containment owner; degraded/best-effort plans never satisfy managed Worker admission |
| Process/Sandbox composition root | `src/loushang/harness/sandbox/runtime.py::SandboxExecutionRuntime.bind_process_launcher` and `bind_managed_worker_launch_port` | Mints distinct generic and Worker-only capabilities over its owned Process Host and containment planner; the Worker path privately binds managed-owner authority and mandatory required containment | Retain as the only Worker launch-capability minting root; Worker hosts do not construct Process Host/Sandbox directly |
| Exec-scope Sandbox service | `src/loushang/harness/sandbox/service.py::LocalSandboxService` | Owns selected backend Exec scopes and fail-closed behavior when containment is required | Retain for Exec; do not misidentify it as the complete hosted-Worker chain |
| Capability binding preparation hosts | `src/loushang/harness/capabilities/component_host.py::CapabilityComponentHost` and `src/loushang/harness/capabilities/owner_component_host.py::CapabilityOwnerComponentHost` | Prepare exact Capability and owner-component bindings; neither host publishes an owner generation | Retain as exact domain admission/preparation seams; a Worker adapter may delegate here but cannot treat preparation as publication |
| Capability generation owner | `src/loushang/harness/capabilities/component_runtime.py::CapabilityOwnerComponentRuntime` and `src/loushang/harness/capabilities/component_runtime.py::CapabilityOwnerComponentBinder` | Own current/retired owner-component generations and the atomic publication window after all selected bindings construct | Retain as the Capability publication/retirement owner; neither a Worker transport nor Plugin management may replace it |
| Resource owner generation | `src/loushang/harness/resource_catalog/generation.py::PreparedResourceOwnerGeneration` | Owns prepared Resource/Skill Catalog generation publication/rollback/retirement | Retain; Worker-derived Resource facts still publish through this owner path |
| Continuity domain host | `src/loushang/harness/continuity/plugin_provider.py::PluginContinuityProvider` | Owns Continuity provider generation calls, mutation preparation, and domain deletion candidates | Retain; a Worker transport cannot become the Continuity owner |
| Worker runtime identity and launch port | `src/loushang/harness/worker/contracts.py::{WorkerRuntimeBindingV1,WorkerLaunchIdentityV1,ManagedWorkerLaunchRequestV1,WorkerLaunchEvidenceV1}` and `src/loushang/harness/worker/launch.py::ManagedWorkerLaunchPort` | Captures contained regular executable/cwd identity and content digests, revalidates before spawn, exposes no arbitrary command/environment, and returns pathless launch evidence over the existing private managed Process substrate | Retain behind the Process/Sandbox composition root; native IPC/platform activation remains PLC9C5 |
| Hosting Worker seam | `src/loushang/harness/worker/session.py`, `src/loushang/harness/worker/hosting_adapter.py`, `src/loushang/harness/worker/owner_selection.py`, and `src/loushang/harness/worker/supervisor.py::WorkerSupervisor.start_session` | HOST-H5 added an atomic process-plus-transport session shape, exact Worker-to-Hosting mapping, explicit Current/Hosting selection, pathless diagnostics, no-fallback routing, and future-attempt rollback; PLC9C5 C5.4/C5.5c now compose it from the sole explicit Coding Product canary | Retain as the Worker mechanism for the accepted Linux/Windows AMD64 canaries; only their receipt-bound H6 friend profiles make native preparation available, while Current remains the default and unlisted Product routes stay closed |
| Product-neutral Worker protocol and supervisor | `src/loushang/harness/worker/protocol.py`, `src/loushang/harness/worker/supervisor.py`, and `src/loushang/harness/worker/journal.py` | Exact bounded canonical-JSON frames over an injected byte transport; owns handshake, direction/state validation, correlation/tombstones, heartbeat, shutdown, process-exit fencing, and durable contiguous attempt epoch/restart budget | Retain as mechanism only; it owns no semantic action, contribution publication, rollback, or retirement |
| Exact read-only Capability Worker adapter | `src/loushang/harness/worker/capability_query.py::{CapabilityQueryWorkerAdapter,bind_capability_query_worker_adapter}` | Binds one Plugin/contribution/Product/scope/owner generation to a sorted Capability allowlist, rechecks authority around every response, returns typed descriptors, and fences invalid/stale output; construction is disabled by policy unless explicitly enabled | Retain as the C4 low-authority canary; it has no publish, retire, mutation, credential, or arbitrary execution capability |
| Product/native Worker activation | explicit canaries implemented through PLC9C5 C5.5c | C5.1 owns receipt/lifecycle and durable cleanup evidence; C5.2/C5.4 bind the exact Linux native profile and Coding Product route; C5.3 retains rejected Windows mechanics; C5.5b/c add accepted Windows LPAC containment and the exact Windows AMD64 Coding route | Retain default-Current, explicit-policy, no-same-attempt-fallback behavior; general third-party authoring, other Products/domains/platforms, and `remote_service` remain closed; see the [C5.0 baseline](plugin-lifecycle-plc9c5-c50-baseline.md), [C5.5 contract](plugin-lifecycle-plc9c5-c55-windows-containment.md), [current inventory](plugin-lifecycle-plc9c5-c50-inventory.md), and [third-party candidate](plugin-lifecycle-plc9c-third-party-admission.md) |
| Remote-service topology | absent through PLC9C5 C5.5c | No service identity, authentication, egress, tenant, residency, or remote revocation contract exists | Defer to a separate threat model; never add it as a `local_worker` compatibility arm |

The internal Plugin `local_worker` declaration and supervised mechanism exist,
and PLC9C5 adds only the two explicit Linux/Windows AMD64 Coding canary routes.
There is still no general third-party Product/native activation path or accepted
`remote_service` declaration/client topology. Process Host and Sandbox
substrate existence alone proves neither Worker admission nor domain
publication outside those exact canaries.

## Cleanup, Data, And Compatibility Seams

| Current seam | Exact source owner or symbol | Current fact | PLC9 disposition and gate |
| --- | --- | --- | --- |
| Cleanup attempts and repair | `src/loushang/harness/plugin_management/package_lifecycle.py::PluginPackageLifecycleLedger` | Derives `pending`, `retryable_failure`, `terminal_failure`, `retry_permitted`, `succeeded`, and `safe_abandoned` from durable attempts/decisions | Retain; PLC9D1 projects this evidence, while later deletion execution must not release debt implicitly |
| Package GC operator projection | `src/loushang/harness/plugin_management/package_gc.py::PluginPackageGcReadModel`, `src/loushang/harness/package_product/product_gc_executor.py::PackageProductRootGcReadModel`, and `src/loushang/coding/cli/package_gc.py::main` | D1 projects every known revision and cleanup blocker; D3h projects active root-GC reservations and durable result/debt, verifying both root fences before success; D3i composes real POSIX Product owners while excluding active Session leases; D3j exposes explicit offline CLI preparation, status, deletion, started-deletion retry, exact terminal dependency debt review/repair, and separate repair status under the Product GC fence. An installed `loushang-package-gc` entry point now passes the real Coding Product root-deletion and replay journey after offline `uv sync --locked`; the installed entry point now also repairs genuine terminal dependency debt from an explicitly flagged Linux Worker candidate Product, with fresh-process review, repair, replay, and status evidence | Retain pathless operator evidence; explicit Windows candidate cutover and GC CLI now have strict native Product proof, while ordinary/default management and RPC selection plus broader terminal repair acceptance remain separate gates |
| Terminal dependency GC repair lineage | `src/loushang/harness/plugin_management/package_gc_dependency_review.py::PackageDependencyGcRepairReviewJournal`, `package_gc_dependency_repair.py::PackageDependencyGcRepairJournal`, and `src/loushang/harness/package_product/product_root_gc_runtime.py::PosixLocalWheelProductRootGcOwner` | Binds one exact terminal start/attempt and actor/policy review, then records a separate repair start before Store effects and an exact result afterward. A failed repair can be superseded only by a new review naming its exact terminal result; the prior result remains immutable. The Product requires an injected repair authority and rechecks current holders, target, and Store proof. Configured Product regressions recover a post-deletion crash in a fresh subprocess through the CLI command handler, retry after persistent collision with a new review, reject a policy refusal, and keep ordinary retry on the original debt | Narrow POSIX offline candidate only; the explicit Linux Worker candidate Product now has positive deployed Coding CLI entry-point evidence; Windows Product execution and broader repair policy remain gates |
| GC candidate | `src/loushang/harness/plugin_management/package_lifecycle.py::PluginPackageGcCandidateV1` | Binds desired, Instance, package-journal, and recovery-barrier revisions | Retain; later executable GC must reserve against new references and recheck under the owner fence before exact revision deletion; desired absence alone is insufficient |
| Coding private roots | `src/loushang/coding/_plugin_lifecycle.py::CodingPluginLifecycleStateLayout` | Separates private lifecycle state and package data bases and prepares private directory permissions | Retain path containment; path ownership is not deletion authorization |
| Continuity deletion authorization | `src/loushang/harness/plugin_management/continuity_mutation.py::PluginContinuityDeletionAuthority` | Serializes one exact deletion, durably authorizes it, and settles terminal receipt/cancel evidence; it does not perform the source mutation | Retain as Product authorization/settlement precedent; never elevate it into a generic destructive executor |
| Continuity destructive commit | `src/loushang/harness/continuity/mutation.py::AuthorizedContinuityDeletionLease._commit_complete_and_release` over the source-owned `PreparedContinuityDeletion.commit` port, prepared by `src/loushang/harness/continuity/plugin_provider.py::PluginContinuityProvider._prepare_delete` | Calls the source/data-domain candidate commit first, validates its receipt, then asks the Product authority to settle | Retain the plan -> authorization -> source commit -> receipt settlement order for any future domain deletion contract |
| Continuity lifecycle adapter | `src/loushang/harness/plugin_management/continuity_adapter.py::PluginInstanceLedgerContinuityFamilyAuthority` | Adapts Continuity provider family lifetime to generic Instance/package ledgers | Retain until the same exact domain contract has another accepted composition; never delete merely because its filename says adapter |
| Generic private-data deletion and backup | `src/loushang/harness/plugin_management/private_data_deletion.py::PluginPrivateDataDeletionCoordinator`, `private_data_confirmation.py::PluginPrivateDataConfirmationJournal`, and `src/loushang/coding/package_installation_private_data.py`, `package_private_data_deletion_preview.py`, `package_private_data_deletion_journal.py`, `package_private_data_deletion_owner.py`, `package_private_data_backup.py`, `package_private_data_restore.py`, `package_private_data_restore_journal.py`, `cli/plugin_private_data.py` | D3k checks an exact plan and domain-owned receipt. Coding Product binds confirmation and start/rename/completion journals to private state. Persistent Product Arch writes use an exact Installation subtree; the POSIX data owner holds runtime quiescence, requires separate confirmation and Desired State absence, rechecks a bounded file snapshot, moves the exact tree to an inode-bound tombstone, and durably issues a deletion receipt. The Linux local-operator CLI has separate preview/confirm/delete plus backup/status/exact-ID verification commands; real Product tests cover independent invocations, restart, post-deletion backup verification, tamper refusal, and interrupted deletion. A separate Arch backup owner requires exact Product Installation history, verifies private archive files and directory permissions, and projects `retained`/`unknown` through Product management; retained status survives source deletion and tampering downgrades it. The POSIX restore owner requires the latest matching deletion receipt, verifies the archive, and records start/completion around no-replace publication; cross-process tests cover both interruption windows. The Linux CLI exposes exact restore preview and fingerprint acceptance. A separate durable restore confirmation and independently confirmed, receipt-backed backup expiry now exist for this Arch Installation on POSIX; RPC/UI mutation routes, other private-data types, and Windows remain closed | Retain the separate restore confirmation and backup-expiry journals. Existing Session roots remain outside this deletion target; remove/GC cannot invoke the data owner or infer backup expiry |
| Backup retention/expiry | `src/loushang/harness/plugin_management/application.py::PluginManagementReadModelProjector` | D3k conditionally projects a backup-owner snapshot and receipt-backed expiry; Coding now binds a POSIX per-Installation Arch backup owner for `retained`/`unknown`, plus separate confirmed expiry execution and a terminal receipt. D3m separately verifies the real workspace cutover snapshot | Retain the narrow authenticated Arch owner; other data types and Windows remain unsupported/unknown, and expiry execution remains restricted to the separate POSIX receipt-backed owner. Never infer expiry from local deletion or workspace-level backup availability |

The Windows Arch backup candidate in
`src/loushang/coding/package_private_data_windows_backup.py` copies only the
current Product-observed cache shape, uses the shared backup receipt, resumes
an exact-prefix partial file or intact unpublished archive, and supplies a
verified `retained` or
conservative `unknown` read source to the generic management projector in an
explicit Product test. The separate
`package_private_data_windows_backup_client.py` candidate reopens that Product
for retain, verify, status, deletion preview/confirmation/recovery, restore
preview/write/confirmation, and backup expiry with a workspace identity check.
Those writes remain candidate-only pending native Windows evidence; the client
exposes no ordinary management route. A
Windows-specific confirmation candidate now
recaptures the exact Product target and writes an immutable, ACL-verified
acceptance under the pinned Product state root. Native cases cover a present
and an absent target, staged publication recovery, and ACL, named-stream, and
attribute tamper refusal. Those native cases have not run on Windows. The
shared native private-receipt reader now checks bounded file and directory
attributes, streams, and visible identity. The existing generic deletion and
confirmation journals do not validate Windows Product-state ACLs, so they
cannot be reused as Windows deletion authority. The separate Windows
confirmation candidate also grants no deletion authority by itself. A separate
Windows deletion-event candidate now writes immutable native start, rename,
and completion records under one cross-process offline Product transaction;
its start requires a separate verified confirmation and removed Product
Installation. Its reader checks contiguous sequence, phase lineage, and
unpublished-stage debt. The authored native case rejects an unissued
confirmation and an active Installation, retries an interrupted start, and
reopens the unfinished event from a new Product owner. It has no retained
Windows result. The absent-target candidate now recaptures the missing root
before start and before its `already_absent` completion, binds a deterministic
receipt ID, and completes the Product event after reopening. The present-target
rename and completion journal methods check the original root receipt and
exact tombstone state. The later physical-deletion candidate consumes those
methods; its native recovery case is authored but unrun.
The native rooted-I/O layer now offers a deletion handle that excludes writers
and other rename/delete opens, checks the expected entry identity on that same
handle before disposition, and renames a verified directory on that same
handle. Its native file/directory regressions are authored but have not run on
Windows.
The Arch root binding now projects completed, present-target deletion receipts
into consecutive immutable root generations. A successor intent names the
prior deletion receipt; a successor root receipt binds the new directory
identity. Read-only inspection treats a fully retired root as absent and
refuses unfinished deletion, incomplete generation publication, mismatched
predecessors, and changed root identities. Portable regressions cover two
deletion receipts, a successor bind, future-generation refusal, and a replaced
successor root. A separate Product-bound physical-deletion candidate now
consumes the confirmation and deletion events under one offline transaction,
renames the root, rechecks each remaining member through native handles,
deletes only matching content, and publishes completion. Its authored native
case interrupts after rename, reopens Product, and resumes to a receipt. This
case has not run on Windows. Native execution and production binding remain
open.
The restore plan/result records are now platform-neutral. A separate Windows
read-only restore preview verifies the retained archive against the latest
matching completed deletion, removed Product Desired State, and absent root;
it refuses unfinished deletion or archive stages. An authored native case
retains before deletion and checks this preview after restart and completed
deletion. No Windows restore write or completion receipt is admitted yet.
An internal Windows restore-stage candidate now records immutable native
`started` and `completed` events with contiguous revision and unpublished-stage
checks under Product quiescence. It rechecks the removed Desired revision,
latest matching deletion, exact archive bytes, and a bound restored root with
matching logical members before completion. A separate immutable publication
record binds the exact restore plan and staged directory identity before a
no-replace rename, so restart can reject an unrelated root. A candidate
physical restore owner copies verified archive files into that stage, verifies
its logical members, publishes the root through a native same-handle rename,
binds the successor root generation, and completes the restore journal. The
explicit candidate client requires the exact preview plan. Portable phase and
publication tests pass; an authored native case interrupts both before and
after the rename, reopens Product after each interruption, and resumes to a
completed restore. A separate explicit candidate confirmation now reopens the
completed restore, verifies the exact retained archive, restored root binding,
and current bytes, and publishes an immutable native confirmation receipt.
Portable confirmation replay, malformed-record, and stale-ID checks pass; the
authored native case verifies the receipt after reopening and rejects changed
restored bytes. The backup-expiry plan, operator confirmation, and terminal
receipt records are now platform-neutral; the POSIX event journal retains its
own archive snapshot type. A Windows
read-only expiry candidate now requires that independent confirmation and
rechecks the removed Desired revision, completed deletion/restore, exact
archive manifest and files, and the bound restored root. Its archive snapshot
keeps a nested, bounded `files/` snapshot plus the `manifest.json` identity
and content digest, preserving the full 4096-member source limit;
its expiry event uses an explicit 16 MiB native receipt bound because an
admitted full snapshot with long file names and full-width identities can
exceed the shared 4 MiB receipt default;
the authored native case previews the exact plan and rejects changed restored
bytes. A separate candidate expiry journal records operator confirmation and
an exact archive snapshot before any effect, with strict native receipt ordering
and replay checks. A candidate owner now renames the verified archive through
its native handle, deletes only snapshot-bound members, and records a terminal
expiry receipt. After the rename it checks Desired State, deletion and restore
history, publication binding, and current restored bytes without needing the
original archive path. Portable recovery and manifest-byte/inode replacement
refusals pass; an authored native case
interrupts before rename, during member deletion, and after physical deletion
before the terminal receipt. The explicit candidate status projection now reads
the same native journal and reports `expiry_pending` or receipt-backed `expired`
only when the archive shape agrees with that history. Native execution remains
pending, so the Windows restore and expiry writes are not admitted as
production. The Windows root owner also has an internal restore-only
successor-generation intent and receipt path: it requires the exact predecessor deletion receipt,
an absent root before intent, and a matching new root identity before receipt.
Portable lineage tests cover wrong predecessor, absent-root preflight,
identity mismatch, and exact receipt replay.
Ordinary
Windows management routing, unsafe-stage cleanup, restore, deletion, expiry,
and production backup admission remain open; the table's Windows gate is not
lifted by the candidate.

## Compatibility Candidate Ledger

PLC9.0 classifies current candidates now; PLC9E may update this ledger but may
not discover an unnamed deletion target in the deletion change itself.

| Candidate | Current caller/authority risk | Disposition | Named deletion or retention gate |
| --- | --- | --- | --- |
| `src/loushang/harness/resources/packages/operations.py::PackageOperationsRuntime.uninstall_sync` | `SessionPackageController.uninstall_package` preserves a synchronous fallback that can reach mutable Package deletion | migrate/delete | async Session/RPC/CLI conformance passes, no production sync caller remains, and rollback does not need the sync mutation |
| `src/loushang/harness/resources/plugins/manager.py::PluginManager` | owns peer registry and enable/disable/source mutation | delete | production and supported test/client callers use management/query/Source ports; architecture guard forbids reconstruction |
| `src/loushang/harness/resources/plugins/resolver.py::PluginResolver.resolve_resources` | deny-only compatibility entrypoint; direct callers could mistake it for runtime Resource authority | delete | all supported callers use `PluginResolutionAuthority.resolve_resources`; route-exclusivity tests move to the canonical port |
| `src/loushang/harness/resources/plugins/safe_files.py` compatibility import | Plugin manifest and public validation currently import the Plugin-local alias of the neutral safe-file capture | migrate/delete shim | a supported neutral import surface exists for both internal parser and public SDK validation; callers migrate in one compatibility-reviewed change |
| `src/loushang/harness/resources/plugins/import_realm.py::PluginImportRealm` | named “compatibility” but is the active fail-closed gate for verified in-process imports | retain | retain until in-process topology is removed by a separate architecture decision; never delete or bypass based on naming alone |
| `src/loushang/harness/extensions/loader.py::_adapt_legacy_extension_object` | synthesizes legacy Extension handlers/Tools during load | decision-required, then migrate/delete | exact Product caller inventory, parity through canonical Extension declarations/owners, and rollback fixture are accepted |
| `src/loushang/coding/_plugin_lifecycle.py::CodingPluginLifecycle.publish_session_owner_generations` | preserves direct publish for legacy/public callers and synthesizes prepare evidence | migrate/delete compatibility branch | every publisher calls prepare before publication, historical journal replay passes, and the direct method has no caller |
| `src/loushang/harness/plugin_management/continuity_adapter.py::PluginInstanceLedgerContinuityFamilyAuthority` | Product/domain adapter binds Continuity family lifetime to generic Instance/Package ledgers without peer state | retain | retain while Continuity uses this exact contract; replacement requires equivalent domain conformance and recovery evidence |
| `src/loushang/harness/resources/packages/materializer.py::PackageMaterializer.remove_remote_source`, `forget_remote_source`, and `forget_plugin_binding` | mutable cache/source-binding compatibility deletion can bypass Plugin retirement/GC/replay evidence | narrow for non-Plugin; route/refuse Plugin-bound targets | exact Plugin-bound caller inventory is empty, replay/pin/rollback tests pass, and architecture guard rejects future bypass |

Each candidate records whether it is retained, migrated, deleted, narrowed, or
requires a decision. A filename or “legacy” comment is never deletion evidence.

## Missing Target Boundaries

These remain deliberately absent and therefore cannot be imported or exercised
by PLC9A1 tests. The former missing common management query snapshot/projector
and transport-neutral query port is now implemented by
`src/loushang/harness/plugin_management/application.py` and frozen by the
PLC9A1 contract:

- wider UI management conformance; Coding Screen and plain TUI now expose
  `/plugins` composition preview, `/plugins list` management projection, and
  fenced enable/disable/remove with own A1 repair. Local management SDK,
  optional RPC, and guarded CLI also cover their own A1 Desired State repair.
  Package install/update and A2 repair remain separate;
- complete bounded byte/archive/wheel materialization transaction;
- Product/native Worker activation, IPC handle binding, platform conformance,
  domain generation publication, and recovery/rollback composition; C5.0
  documents and guards these absences but implements none of them;
- `remote_service` topology contract and client;
- default management/RPC selection beyond the declared D3j offline GC CLI,
  terminal GC debt repair, and Windows native Product execution evidence;
- a production private-data owner, authenticated confirmation issuer, and bound
  deletion command beyond the D3k/D3l contracts; and
- production backup-owner binding beyond the D3k conditional projection.

Later slices must first add a focused contract and negative tests for the
relevant boundary, then revise this inventory in the same change. Absence is a
guardrail, not an invitation to infer an API shape.

## Dependency Direction

The accepted direction is:

```text
CLI / RPC / UI / management SDK
  -> management application command/query ports
     -> durable desired/operation owner
     -> read-only joins over Package, Instance, domain-owner, Process Host,
        Sandbox, cleanup, private-data, and backup snapshots

Source Authority -> bounded Package lifecycle sink -> immutable revision
exact domain Worker host -> authorized Process Host + Sandbox
exact domain Worker host -> exact domain publication owner
```

Forbidden reverse edges include management ledgers importing CLI/UI/RPC,
Process Host importing Plugin declarations, Sandbox importing management,
Package materialization importing Product UI, and the author SDK importing any
concrete owner implementation.

## Inventory Change Protocol

Any PLC9 change that adds, migrates, or deletes a row must include:

1. the exact qualified source site and authority classification;
2. the old and new caller inventory;
3. positive behavioral evidence at the canonical port;
4. a negative architecture guard against restoring the peer path;
5. recovery, replay, idempotency, and partial-failure evidence when durable
   state changes; and
6. an explicit deletion gate for every compatibility bridge.

Directory-wide exemptions and prose-only claims are not acceptable inventory
updates.
