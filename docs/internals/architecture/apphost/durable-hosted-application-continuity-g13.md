# Durable Hosted Application Continuity G13

[Architecture](../README.md) · [AppHost](README.md) ·
[G12 Foreground Hosted Application](foreground-hosted-application-g12.md) ·
[AppService](../appservice/README.md) ·
[Inventory v6](durable-hosted-application-continuity-g13-entrypoint-inventory.json) ·
[Hosted Application Support Boundary](../hosting/key-designs/hosted-application-support-boundary.md)

## Status

- ID: `DURABLE-HOSTED-APPLICATION-CONTINUITY-G13`
- Kind: accepted delivery design
- Scope: AppService durable coordination / optional AppHost continuity edge /
  Product recovery integration
- Parent: Loushang application architecture
- Authority: normative accepted design
- Design status: accepted
- Implementation status: implemented — G13.0--G13.4 complete
- Activation status: explicit process-local recoverable library only
- Owner: Loushang AppService architecture with AppHost, Product, and storage
  boundary review

## Outcome And First-Principles Boundary

G13 makes the G12 application state reconstructible after its owning process is
gone. One explicitly selected application identity acquires an exclusive
continuity-store lease, persists the desired named-MuxSpace and hosted-Session
membership state, and can rebuild a fresh AppService by resuming every Session
through the current AppHost catalog and canonical Session identity owner.

```text
trusted composition root
  -> admitted continuity root + application identity + fresh owner epoch
  -> AppService continuity store
       -> exclusive application lease
       -> versioned desired coordination record
  -> current Product/AppHost generation
  -> recoverable G12 application
       -> restore hosted Sessions through canonical AppHost resume
       -> atomically publish MuxSpaces only after complete recovery
       -> accept normal in-process AppClient attachments
```

The durable record is desired application coordination, not a serialized live
runtime. It contains no Product generation pin, process identity, connection,
attachment, controller lease, delivery mailbox, event cursor, active Turn,
tool, Approval, transcript, prompt, model output, path, credential, or object
graph. Product/Harness persistence remains the recovery truth for each Session.

G13 is the continuity kernel required before a real background deployment can
be accepted. It proves zero-client retention and process reconstruction, but it
does not add an AppServer transport, listener, daemon launcher, service
controller, installed command, or default-owner change. A future external
connection and daemon profile may consume this exact library edge; it may not
move continuity authority into Hosting or AppServer.

## Current, Target, And Delta

| Plane | Statement |
| --- | --- |
| Facts | G11 owns process-local named mux/session semantics. G12 composes one explicit foreground AppService with AppHost canonical routing and an in-process client. G13 implements the strict record/store, commit-before-publish AppService mutation, all-or-nothing recovery, lease-last AppHost owner, Coding current-generation composition and fresh Harnesstui reattach canary. |
| Current | An explicitly constructed G13 application can retain named coordination through runtime/process-object loss and recover canonical cwd/user-home Sessions into a fresh current AppHost generation. The G12 constructor and every installed Current route remain unchanged and process-local/default-dark. |
| Target | One explicit G13 application key has a single fenced writer. Committed MuxSpace/session desired state survives process loss. A fresh G13 runtime acquires a new owner epoch, resumes canonical Sessions under the current admitted Product generation, publishes the complete recovered graph, and accepts a fresh attachment. |
| Delta | Add versioned coordination records, an exclusive store lease, commit-before-publication mutations, all-or-nothing recovery, Product integration and bounded evidence. External transport, process supervision and active-execution recovery remain future deltas. |

## Requirements

| ID | Requirement |
| --- | --- |
| `G13-R1-EXPLICIT-CONTINUITY` | Continuity requires an exact typed activation, a validated application identity, an injected admitted storage root/store, and a fresh opaque owner epoch. Import, omission, environment, current directory, home discovery, persisted records, AppClient creation and profile discovery cannot activate it. |
| `G13-R2-ONE-WRITER-LEASE` | Exactly one live store lease may mutate one application record. The store holds an OS-released exclusive lock for the runtime lifetime and fences every load/commit by application identity and owner epoch. A record or PID is never proof of a live owner. |
| `G13-R3-DURABLE-SEMANTIC-STATE` | The record contains only application identity, Product identity, record revision, MuxSpace identities/names/revisions/order and normalized hosted Session identity/title/scope facts. Attachments, cursors, controller generations, transient errors and runtime objects are excluded. |
| `G13-R4-COMMIT-BEFORE-PUBLISH` | Create/close MuxSpace and open/close member stage one complete next record and commit it by expected revision before publishing the corresponding live mutation or success. Conflict or storage failure changes no visible live state; an adopted Product Session is compensated. |
| `G13-R5-CANONICAL-RECOVERY` | Recovery uses `SessionOpenSpecV1` with the committed Session identity and calls the injected Product resolver, which reaches AppHost canonical resume. It never derives a path, opens a locator directly, reuses a persisted Product generation, or creates a replacement Session when resume is unavailable. |
| `G13-R6-ATOMIC-REHYDRATION` | A recovered AppService remains unpublished until all record structure is validated, every Session owner is adopted and identity-checked, and the complete MuxSpace graph is assembled. The caller owns a published recovery-attempt owner before the first effect; any failure retains the durable record and exact bounded retryable cleanup debt on that owner. |
| `G13-R7-FRESH-LIVE-EPOCH` | Attachments, controller generations, mailboxes, subscriptions, delivery cursors, interactions and in-flight operations are always fresh after recovery. Stale pre-restart attachment authority cannot mutate the new runtime. |
| `G13-R8-SESSION-TRUTH` | G13 claims recovery only for coordination metadata and canonical Session reopening. Product/Harness stores decide transcript and Session recovery. Active Turns, tools, queued input and Approval outcomes are not claimed to survive a crash. |
| `G13-R9-MULTI-RECORD-ISOLATION` | One store root may contain several independently keyed application records, but each runtime opens exactly one key and admits exactly one Product ID. No global live application manager, cross-Product MuxSpace or default Product fallback is introduced. |
| `G13-R10-ORDERED-SETTLEMENT` | Shutdown fences application/AppService admission, closes live Service → AppHost → Product owners using G12 order, then releases the continuity lease while retaining the record for restart. Explicit retirement is a separate operation that settles live owners, compare-and-swap deletes the record, then releases the lease. A failed prerequisite retains exact debt; a second application instance cannot acquire the key early. |
| `G13-R11-BOUNDED-PRIVATE-STORAGE` | The concrete JSON store receives one exact root, creates private state artifacts, uses bounded strict decoding and atomic replace, fsyncs committed content, exposes safe error codes only, and never resolves cwd, home or environment itself. Corrupt or incompatible records fail closed and are not overwritten implicitly. |
| `G13-R12-NO-AUTHORITY-EXPANSION` | Passing G13 grants no AppServer connection/listener/IPC, network authentication, Hosting process/service control, detached OS process, installed hosted route, default profile/owner change, Current deletion, multi-client takeover, live-Turn crash recovery, or machine-reboot availability claim. |

## System And Component Boundary

| Component | Owns | Must not own |
| --- | --- | --- |
| `loushang.appservice.continuity` | immutable desired-state values, strict codec, store/lease ports, exact-root JSON adapter and record listing | Product generation, Session storage, AppHost routing, process/service records, attachments or UI |
| `loushang.appservice.runtime` | optional commit-before-publish coordination, all-or-nothing restore, process-local live MuxSpace/Session owners | path discovery, file-lock mechanics, Product lookup, process continuity or transport |
| `loushang.apphost.continuity` optional G13 edge | continuity activation, published recovery-attempt owner, lease lifetime, recoverable AppService construction and settlement after G12 owners | record schema, Product recovery policy, Hosting, listener or presentation |
| Product integration edge | current Product generation admission plus canonical resume implementation | generic continuity schema, mux policy, store path resolution or daemon control |
| Product/Harness Session owner | transcript, Blob, Session and execution recovery truth | MuxSpace/application registry or store lease |
| AppServer | future connection/listener owner | continuity store, recovery orchestration or process lifetime |
| Hosting | future process/service mechanism | application record, AppService recovery or Session truth |

The persistent directory is a catalog of desired records, not a service
locator or a live application registry. “Several applications” means several
isolated durable keys under one admitted root. It does not mean one AppService
coordinates multiple Products or one process-global manager owns every live
application.

## Dependency Direction

```text
appservice.continuity -> appserver.protocol + standard library
appservice.runtime -> appservice.continuity + appserver.protocol
apphost.application -> apphost core + appservice + appserver.client
apphost.continuity -> apphost.application + appservice + appserver.client
Product recovery edge -> apphost.continuity + appservice.continuity + Product public ports

appservice.continuity -/-> AppHost / Hosting / Product / Harness / Harnesstui / TUI
appservice.runtime -/-> AppHost / Hosting / Product / Harness / Harnesstui / TUI
apphost.application -/-> Hosting / Product / Harness / Harnesstui / TUI
apphost.continuity -/-> Hosting / Product / Harness / Harnesstui / TUI
Hosting -/-> appservice / appserver / apphost / Product / UI
AppServer -/-> appservice.continuity / AppHost / Hosting / Product / UI
```

The concrete JSON adapter belongs beside the semantic record because it is the
only component that understands that schema. It receives an admitted exact
root from the outer composition; it does not import PlatformPaths or invent a
new global state policy. It uses the standard-library JSON decoder with an
exact duplicate-key hook, so G13 does not create a new AppService-to-Foundation
dependency merely for encoding convenience.

## Identity And Durable Record

The identity domains remain distinct:

| Identity | Lifetime and authority |
| --- | --- |
| `application_id` | stable durable record key chosen by trusted composition; safe selector, never a path |
| `owner_epoch` | fresh opaque writer-fencing identity for one acquired runtime lifetime; not persisted as Product state |
| `record_revision` | monotonically increasing compare-and-swap revision for desired coordination state |
| `generation_id` | current AppHost catalog admission only; never persisted or recovered |
| `mux_space_id` / `member_id` | stable desired coordination identities persisted in the application record |
| `session_id` / `continuity_id` | canonical Product Session identity persisted only as client-safe values |
| `attachment_id` / controller generation | fresh process-local authority; never persisted |

Conceptual bounded record:

```text
ApplicationContinuityRecordV1
  application_id
  product_id
  record_revision
  mux_spaces[]
    mux_space_id, name, revision
    members[]
      member_id, title, position
      SessionIdentityV1
```

There is no separate durable Session table in G13 because every supported live
hosted Session belongs to exactly one MuxSpace. The existing G11
`close_member(close_session=False)` behavior remains valid only for the
process-local profile. A continuity-enabled service rejects that non-durable
orphaning operation with a stable unsupported-operation error; callers either
retain membership or close the Session. This prevents a durable record from
silently losing an owned Session.

## Store And Writer-Fencing Contract

The store opens one `ApplicationContinuityLeaseV1` by exact application ID and
fresh owner epoch. The concrete file adapter:

1. creates the already-admitted root with private directory permissions when
   absent;
2. opens a deterministic lock artifact without following a symlink;
3. acquires a non-blocking OS advisory lock held by the lease until close;
4. loads at most one bounded strict record and validates its application key;
5. commits only when `expected_revision` matches the current record;
6. writes a same-directory private temporary, flushes and fsyncs it, atomically
   replaces the record, then fsyncs the directory where supported; and
7. retains an incompatible or corrupt record unchanged.

The OS lock, not lock-file contents, represents live exclusion and is released
by process death. The lock artifact may remain. Symlinked roots, records, locks
and temporary targets fail closed. The adapter never prints the root or nested
exception text through public errors.

One root can list a bounded set of valid application summaries for future
control-plane presentation. Listing creates no lease, activation, readiness or
process claim. A corrupt entry makes that exact key unavailable and cannot
silently hide or rewrite another key.

Deleting a record is available only through the exact acquired lease and an
expected revision. Ordinary shutdown never deletes it. Explicit retirement
first settles all live application owners, then deletes the matching record,
then releases the lease. A failed delete retains the lease and retry debt; a
crash before deletion conservatively leaves the record recoverable.

## Mutation Transaction

For a continuity-enabled mutation:

```text
validate request and current live revision
  -> acquire/adopt any new Product Session owner
  -> stage complete next immutable coordination record
  -> lease.commit(expected_revision, next_record)
  -> publish live dictionaries/member order/revision
  -> settle invalidated attachments
  -> return success
```

Store I/O and live publication run inside one service coordination boundary,
but no Product callback runs while that boundary is held. A cancellation after
commit joins the owned commit and completes the matching live publication
before propagation. A failure before commit leaves live state unchanged. A
failure after a newly opened Session was adopted closes that Session before
return; incomplete cleanup is retained as existing AppService cleanup debt.

Close mutations commit the record that removes routing authority before
releasing Product Session owners. If owner cleanup then fails, the record still
correctly says the Session is no longer recoverable through AppService, while
the same live runtime retains cleanup debt. Restart does not resurrect an
explicitly closed Session.

## Recovery And Publication

1. Publish one caller-owned recovery-attempt owner before the first effect.
2. Acquire the exact application lease before creating AppService and adopt it
   into that attempt.
3. Strictly load and validate the record, Product ID and all cardinalities.
4. Admit the current Product/AppHost generation; the record supplies no
   generation identity.
5. Resume each member Session through the injected resolver using all committed
   identity/scope facts and `session_id`.
6. Adopt and identity-check every returned Session before inspecting the next
   publication boundary.
7. Assemble private MuxSpace/member/session owners with the committed stable
   IDs and revisions.
8. Publish one accepting AppService only after the complete graph exists.
9. A client performs a fresh normal attach and receives new attachment and
   controller authority plus current snapshots.

If any record or Session is unavailable, the whole application recovery fails
closed. Every adopted owner is closed in reverse acquisition order under a
finite budget. Unresolved debt remains on the already-published attempt and its
lease stays held; after cleanup completes, the lease is released and the
unchanged record is available for a later clean retry. G13 does not partially
omit a failed member or mint a replacement Session.

## Lifecycle And Failure Semantics

```text
construct/recover
  acquire continuity lease
  -> build current Product/AppHost graph
  -> load and rehydrate AppService
  -> publish recoverable application

normal zero-client period
  detach attachment only
  -> MuxSpaces and Sessions remain live
  -> committed desired record remains unchanged

shutdown/restart
  fence application admission
  -> AppService close (record retained)
  -> AppHost shutdown
  -> Product factory cleanup
  -> continuity lease close

explicit desired-state deletion
  mux/member close commits removal
  -> live owner cleanup

explicit application retirement
  settle Service -> AppHost -> Product
  -> compare-and-swap delete the application record
  -> continuity lease close
```

The wrapper retains a single retryable shutdown task and owner-specific phase
debt. Cancellation joins every adopted cleanup. The lease is never released
while Service, AppHost or Product cleanup is unresolved, preventing a new
process from recovering state while an old owner may still affect it.

## Threat Model

| Threat | Control |
| --- | --- |
| persisted record activates hosted mode | exact G13 activation and caller-supplied application key/store; records are inert facts |
| two processes mutate one application | lifetime OS lock plus application/epoch/revision fencing |
| stale Product generation is resurrected | generation excluded from record; current AppHost admission and canonical resume rerun |
| partial recovery publishes a truncated mux | all-or-nothing private rehydration and reverse cleanup |
| store failure diverges live and durable state | expected-revision commit before visible publication |
| crash recovery invents active execution | explicit exclusion of Turn/tool/Approval/mailbox state; Product Session is sole recovery truth |
| durable record becomes a path/service locator | safe application selector; exact root injected; no endpoint or path in record |
| detached client accidentally closes work | detach remains attachment-only and produces no durable mutation |
| old attachment controls recovered runtime | attachments and generations are never persisted and fresh attach is mandatory |
| “multi-application registry” becomes a global service locator | isolated records only; one key/Product per runtime; no live manager or fallback |
| file corruption is overwritten | strict bounded decode, stable failure and unchanged corrupt artifact |
| continuity pulls in daemon authority | import/entrypoint guards prohibit AppServer transport, Hosting and installed routes |

## Delivery Slices

| Slice | Deliverable | Exit evidence |
| --- | --- | --- |
| G13.0 | accepted boundary, record/lease model, transaction, recovery, threat model and architecture guards | three-view design review has no unresolved high/medium finding; no production source change |
| G13.1 | immutable continuity values/codec/ports and exact-root private JSON store | strict bounds/round trips, lock exclusion, CAS conflict, crash-release, atomic durability, corrupt/symlink and multi-record isolation tests |
| G13.2 | optional AppService commit-before-publish mutations and all-or-nothing restore | every mux/member mutation, cancellation point, conflict, orphan rejection, identity mismatch and cleanup-debt path is deterministic |
| G13.3 | optional AppHost continuity lease owner and Coding recovery composition | current generation admission, canonical cwd/user-home resume, zero-client retention, shutdown order and restart canary |
| G13.4 | fresh Harnesstui reattach canary, inventory v6, affected gates, architecture reconciliation and implementation review | detach → shutdown/process-object loss → reconstruct → attach by name preserves exact mux/session identity without stale authority |

## Evidence Contract

| ID | Proof |
| --- | --- |
| `G13-EXPLICIT-CONTINUITY` | exact activation/application/store inputs and unchanged installed omission routes |
| `G13-LEASE-FENCE` | concurrent acquisition fails, process/lease close permits a new epoch, and revision conflict changes nothing |
| `G13-STRICT-RECORD` | closed immutable codec rejects unknown, duplicate, oversized, corrupt, path-like and incompatible values |
| `G13-ATOMIC-MUTATION` | each durable mutation commits before live publication; failure/cancellation converges without split state |
| `G13-CANONICAL-RECOVERY` | restore calls exact AppHost-backed resume with committed cwd/user-home identity and current catalog generation |
| `G13-ALL-OR-NOTHING` | one failed/mismatched member publishes none and closes every adopted Session owner |
| `G13-FRESH-AUTHORITY` | recovered runtime rejects stale attachments and issues fresh attachment/controller identities |
| `G13-DETACH-RETENTION` | zero attachments neither closes Sessions nor changes the committed record |
| `G13-MULTI-RECORD` | two application keys remain isolated without a live global manager or cross-Product mux |
| `G13-SHUTDOWN-LEASE-ORDER` | lease releases only after Service, AppHost and Product settle; retry retains it |
| `G13-RESTART-CANARY` | real AppHost/Coding/AppService/Harnesstui path restores names, order and canonical Session identities from a fresh runtime graph |
| `G13-INVENTORY-V6` | every continuity/store/composition surface has a source-backed disposition and no listener/daemon/installed activation |

## Three-View Review Contract

G13.0 design and G13.4 implementation are reviewed independently through:

1. **Architecture and authority:** semantic persistence ownership, Product and
   Session truth, one-Product endpoint, multi-record isolation, dependency
   direction, explicit activation and unchanged Current/Hosting/AppServer
   authority.
2. **Lifecycle, concurrency and safety:** writer fencing, commit/publication
   order, cancellation, compensation, all-or-nothing recovery, fresh live
   authority, cleanup debt and lease-last shutdown.
3. **Contract, compatibility and evidence:** strict bounded record/codec,
   existing G11/G12 source compatibility, cwd/user-home identity, private
   storage, error redaction, restart behavior, inventories and affected gates.

High or medium findings block implementation or completion. Fixes are rerun
through the same view and recorded here.

## G13.0 Design Review

The first three-view review found five medium risks and revised the design:

- **Architecture and authority:** an initial generic “multi-application live
  registry” would have competed with AppHost and violated the one-Product
  endpoint. G13 now provides isolated durable application keys only; each live
  runtime opens one key and one Product, with no process-global manager,
  fallback or service-locator authority.
- **Architecture and authority:** using Foundation's JSON helper would have
  introduced a sibling dependency solely for encoding convenience. The
  continuity component instead owns its strict standard-library codec and
  duplicate-key rejection beside its schema.
- **Lifecycle, concurrency and safety:** a factory that raised after adopting
  Sessions could hide unresolved cleanup and the store lease. Construction now
  publishes a caller-owned recovery-attempt owner before the first effect;
  failure debt and the exclusive lease remain reachable and retryable.
- **Lifecycle, concurrency and safety:** treating application close as record
  deletion would make an ordinary restart destroy its own recovery source.
  Shutdown now retains the record and releases the lease last; explicit
  retirement settles live owners, CAS-deletes the record and only then releases
  the lease.
- **Contract, compatibility and evidence:** G11 permits
  `close_member(close_session=False)`, but the proposed record had no durable
  orphan-Session domain. Continuity mode now rejects that option explicitly
  instead of silently losing an owned Session; the process-local G11 behavior
  remains source and behavior compatible.

The same three views were rerun after these changes. Product generations,
attachments and active execution remain deliberately absent from the record;
canonical resume, strict storage, exact retry debt and affected gates are
explicit. No unresolved high or medium finding remains, so implementation may
proceed inside the requirements and non-goals above.

## G13.4 Implementation Review

The independent architecture/authority, lifecycle/concurrency, and
contract/evidence views found eight medium risks across the implementation
pass and retained platform gate. All were fixed before closure:

- **Architecture and authority:** the first Coding composition admitted its
  AppHost catalog before acquiring the application lease. Coding now acquires
  the exact lease as its first effect and transfers that capability into the
  Product-neutral AppHost continuity attempt; Session recovery and every
  mutation therefore occur only behind the one-writer fence.
- **Architecture and authority:** the continuity runtime constructor could be
  invoked without passing the explicit activation-bearing attempt. Runtime
  construction is now token-guarded, while AppHost's core facade, Hosting,
  AppServer and all installed routes remain unaware of the optional edge.
- **Lifecycle, concurrency and safety:** a close racing the nested
  AppHost-to-Coding attempt handoff could leave a successfully recovered
  runtime between owners. Each layer now records the received owner before
  returning it and closes that exact owner when publication loses the race.
- **Lifecycle, concurrency and safety:** a deterministic ID factory could
  replay an attachment ID and controller generation after restart. Every new
  continuity-mode live ID is now namespaced by a one-way digest of the fresh
  lease owner epoch; persisted mux/member IDs remain stable, while stale
  pre-restart attachment authority deterministically fails.
- **Lifecycle, concurrency and safety:** recovery originally risked losing a
  raw Session port when adaptation failed and could return a closed service in
  an open/close race. The published recovery attempt now retains ordered,
  retryable raw-port debt and makes close win before publication.
- **Lifecycle, concurrency and safety:** the first Windows lease locked byte
  zero, where mandatory range locking could block a second contender before
  its non-blocking lock attempt. The lock now uses a fixed offset outside file
  content, preserving exact one-writer fencing and crash release without
  making the lock file itself inaccessible.
- **Contract, compatibility and evidence:** two evidence paths were not bounded
  by their semantic inputs. The process-death proof waited without a deadline
  for child stdout, and the oversized-record case exposed its 1 MiB payload as
  a pytest node identifier. The proof now retains the lease explicitly,
  publishes readiness through a private marker, and converts child exit or a
  bounded readiness deadline into a diagnostic failure. Its post-crash probe
  also allows a bounded Windows kernel-release interval without weakening the
  immediate live-owner exclusion check. Hostile record samples use short
  semantic IDs, keeping Windows collection, logs and reports bounded.
- **Contract, compatibility and evidence:** unexpected store exceptions,
  monolithic line budgets and pre-G13 exact package inventories obscured the
  new boundary. Errors are redacted to stable codes; core and continuity
  budgets are independent; inventory v6 is source-backed/default-dark; and
  Linux, macOS and Windows gates cover the affected portable surfaces.

The same three views were rerun over the corrected source, tests, inventory and
parent status. G12 construction remains source/behavior compatible, canonical
cwd and user-home recovery always uses the current generation, lease release is
last, and no transport/process/default authority was added. No unresolved high
or medium finding remains.

## Exit Gate

G13 is complete only when G13.0--G13.4 and all twelve evidence cases are
implemented; inventory v6 matches exact source and installed surfaces; both
three-view reviews have no unresolved high/medium finding; and the same
immutable head passes:

- focused G13 AppService/AppHost/Coding/Harnesstui tests;
- `make check-appservice`;
- `make check-apphost`;
- `make check-hosting` for non-interference and exact package inventory;
- `make check-harnesstui`;
- `make check-harness`;
- `make check-architecture-docs`; and
- affected Linux/macOS/Windows-safe CI gates.

Passing G13 proves durable coordination reconstruction through explicit
library composition. It does not authorize AppServer transport, a local
listener, Hosting service control, an OS-detached process, an installed daemon
or attach command, default-path migration, active-execution crash continuation,
multi-client takeover, or Current deletion.
