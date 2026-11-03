# ARD-007: Correlate Resume Effects In Their Original Journals

## Status

- ID: ARD-007
- Scope: Loushang
- Authority: normative — accepted cross-scope contract
- Design status: accepted
- Implementation status: partial
- Owner: Loushang architecture, Coding, Harness Approval and native Worker owners
- Tracking: [Issue #696](https://github.com/zhnt/loushang/issues/696)
- Source review: `e072a764`, 2026-10-12
- Accepted contract revision: `2026-10-12-r2`
- Acceptance review: `bf29c05d`, 2026-10-13
- Accepting role: Codex implementation agent, delegated Loushang common-parent responsibilities for Issue #696

This decision refines the external-effect prerequisite in
[ARD-005](../accepted/ARD-005-resume-continuation-commit.md). It does not replace
its accepted message commit or writer capability contract. Design acceptance
establishes the contract below; no implemented settlement protocol is claimed here.

## Question And Current Evidence

How does a resumed input find every original activation effect after a crash,
without treating a new candidate's successful activation as settlement of an
older attempt?

The [R2.1 plan](../../../plans/2026-10-12-resume-compatibility-and-activation-design.md)
requires crash recovery, one durable input and current admission. Current
source establishes these boundaries:

- Coding commits `coding.activation-attempt/v1` before preparing a Session.
  Its `effectClasses` are class names, not native operation identities.
- `harness/approval/plugin_execution.py` owns Definition execution decisions,
  consumed uses and transitions. A started use can become
  `FAILED_AFTER_START`; that state does not prove absence of external effects.
- `harness/approval/plugin_activation.py` owns component activation decisions
  and uses. A different host boot recovers started uses to `FAILED`, and
  unstarted uses to `CANCELLED_BEFORE_START`.
- `coding/_capability_plugin_composition.py` constructs those existing
  journals and original Hosts. Persistent approval state is selected through
  Product composition; ephemeral state is cleaned by its retained custodian.
- `harness/worker/product_activation.py` and the existing Product C5 state
  own Worker attempts and exact containment/cleanup settlement. Their native
  attempt identities cannot be replaced by a Transcript input identity.
- Coding's original Session checks live published components. That check
  does not correlate a prior Resume intent with native effects. The production
  coordinator still requires an externally supplied settlement callback.

Therefore current guards are necessary but insufficient for default Resume.
The missing association is a data contract between existing owners, rather
than permission to create another effect ledger.

## Options

| Option | Recovery properties | Cost and limitation |
| --- | --- | --- |
| Infer settlement from a new graph's receipt or COMMITTED state | Finds only the new live activation | Cannot resolve older started uses or arbitrary external effects; rejected. |
| Copy native states into a Coding Saga journal | Gives Coding a convenient index | Creates another effect authority and a cross-journal acknowledgement gap; rejected. |
| Attach bounded parent operation context to each original native use | Recovery reads original owner facts and preserves authority | Requires native journal version gates, complete effect enumeration and owner-specific reconciliation; recommended. |

A deterministic ID factory alone is insufficient: a sequence number does not
prove complete enumeration, and regenerating IDs after different preparation
orders cannot establish which effects started. IDs may aid lookup, but their
original owner must persist the exact causal association.

## Decision And Contract

### Parent context and native registration

Coding supplies inert parent context from the committed attempt: Product and
Session identity, `attemptId`, request identity and a digest of the exact
committed intent. Owners validate scope before accepting it. Context contains
no path, Credential, policy grant, permission confirmation or live object.
It is never a substitute for the native owner subject and admission.

The original Definition, component or Worker owner attaches that context to
its native use/attempt in the same durable owner transaction that consumes or
reserves the operation. Registration is acknowledged before import, evaluation,
process creation or other native start. Keep the native decision/use ID,
subject digest, instance revision and boot/domain identity. Repeated parent
context does not authorize a second use and does not deduplicate arbitrary
operations by itself.

Each owner must enumerate its registered operations completely for that parent,
including failed, cancelled and replaced candidates. The coordinator records
which original owners must participate before their effects can start; an
omitted owner, missing registration acknowledgement, incomplete scan, lost
journal or unsupported schema yields unknown. Absence in a partial view is
never verified not started. Registration failures preserve the Transcript
intent and native evidence for explicit reconciliation.

### Reconciliation and disposition

Original owners return outcomes for exact native operations, checked against
the parent context and their current authority:

| Outcome | Required original-owner evidence | Resume consequence |
| --- | --- | --- |
| Verified not started | The durable native state proves no start boundary was crossed, including native reservation/containment edges | The coordinator may request fresh admission; the observation itself grants no retry. |
| Completed | The domain owner proves completion of its declared effect contract | May satisfy that effect obligation, with current candidate and caller checks still required. |
| Disposed | The domain owner proves the exact cleanup/compensation or records an authorized explicit disposition | May satisfy only the obligations covered by that disposition. |
| Unknown | Started failure, missing or conflicting facts, unsupported version, incomplete cleanup or an unregistered effect | Keep input pending or enter recovery-required; no automatic re-execution. |

`EVALUATED` and `COMMITTED` establish their native execution/publication
boundaries. They do not settle unrelated filesystem, network, process or
publication effects produced by arbitrary Plugin code. A domain that can
produce such effects must declare its effect owner and provide original-owner
reconciliation. Unsupported domains remain unavailable for writable Resume
until that obligation is resolved. Human confirmation is current admission;
it does not retrospectively prove completion or absence.

An explicit disposition must identify the exact native operations, uncovered
obligations, current authorized actor and policy revision. Its original domain
owner persists it; Coding and UI cannot manufacture it from a checkbox or a
receipt. This decision does not introduce a generic force-retry flag.

### Coordination and lifetime

The existing Coding continuation coordinates the original owners after the
Transcript intent commit and before first-input commit. It validates current
admission before each owner operation and again after callbacks. It revalidates
current content, Product epoch and live component publication before input
commit, Runtime publication and model transport.

The original Session/graph still owns live components; the Product application
selection owns its epoch; the original Worker coordinator owns containment.
No second Root, live-session registry, authority issuer or cleanup owner is
introduced. Failed preparations retain their existing custodians until native
settlement succeeds. Durable effect evidence must outlive disposable import
or private-data state while reconciliation remains unresolved.

History and background planning never consume decisions, register native uses,
repair journals, settle effects or issue grants. They may show redacted
unavailability, but formal reconciliation belongs to admitted activation.
Embedded and Hosted use this same coordinator; Hosted additionally retains
its existing subject/controller generation and single Product binding.

## Accepted Wire And Owner Protocol

### Complete participation before evaluation

Use a new `coding.activation-attempt/v2` intent rather than silently extending
v1's exact fields. Retain the v1 identity, ancestry and payload-independent
intent fields. Add `effectOwners`: a sorted, unique list of at most eight
entries containing `ownerId`, `scopeDigest`, `contractDigest`, `phases` and
`effectClasses`. Enforce an 8 KiB total encoded intent budget and strict field,
identifier and digest validation. v1 remains historical input; it cannot prove
this v2 participation contract. The final message keeps the accepted single-record commit and RuntimeBinding
semantics. Its `coding.runtimeBindingV2` metadata carries the v1 fields
plus `intentDigest`, with `version: 2`; it has an 8 KiB encoded budget. v1 stays
readable. A decoder must not synthesize the new digest from a current graph or
accept a v1 Binding as proof of v2 participation. Unknown metadata stays inert
for display and unavailable for mutation. The original Transcript message owner
co-commits this Binding, ordinary resource evidence and the UserMessage as one
fixed-ID record; no additional preliminary Binding record is introduced.

The original Product selection computes participation from its verified,
inert package closure and its trusted host/domain configuration before any
Definition evaluation. The list includes Definition invocation, component
construction/import, Worker reservation/start and every declared external
startup domain. A manifest can request a domain but cannot register a trusted
reconciler, assert effect freedom or supply a contract digest as authority.
The selected original owner validates its own contract identity. Missing or
unsupported domains refuse activation before evaluation. If evaluation exposes
an additional domain, stop and preserve its already registered effects; do not
extend the frozen parent list or proceed to first-input commit.

Application-level Product preparation is a separate prerequisite: the original
Package Product owner must reconcile its existing cutover/management/bootstrap
operations under current admission before its selected epoch can be used as a
Resume dependency. An epoch fingerprint does not settle those operations. That
owner keeps its application operation identities and journals; this protocol
does not relabel an existing application operation as a Session native use or
permit it to be replayed using a new Resume ID. Unresolved application effects
block preparation before the first Resume Writer. The production bridge must
validate both that application prerequisite and this Session startup protocol.

Initial built-in support requires an audited, verified code closure and the
original owner contract for its actual startup effects. There is no blanket
assumption that all first-party, local or host-equivalent Python is effect-free.
Custom Plugin startup domains can participate through their trusted original
owners; unsupported domains remain readable and report writable unavailability.

### Original journal transactions and complete enumeration

Each participating owner persists the following in its existing journal/state
store, under its existing root, lock, revision CAS and current admission:

1. **Enroll** the parent context and this owner's exact obligation descriptor.
2. **Register** each native use together with its parent context atomically
   with native decision consumption or attempt reservation. Native start is
   forbidden until that registration has a known durable acknowledgement.
3. **Record outcomes** through existing native transitions and domain-owned
   completion, cleanup or disposition evidence. A parent context never changes
   the authorization needed for those transitions.
4. **Seal** this owner's operation enumeration, with its current revision and
   digest of sorted native operation identities. Sealing forbids additional
   startup registration for that parent. It grants no execution or retry.

A parent context has exact fields `contextVersion`, `productId`, `sessionId`,
`attemptId`, `requestId`, `intentDigest`, `ownerId`, `scopeDigest` and
`contractDigest`; its encoded budget is 2 KiB. Digests use domain-separated
canonical JSON. The context is lookup data. Native subjects retain their exact
instance/content, current authority, native use ID and host/domain identities.

Definition and component journals require versioned enrollment/seal events
and a parent context on the consumed-use event. Do not append an independent
link after consumption. Worker enrollment/registration/seal belongs in the
original C5 CAS state and its retained attempt projection, including checkpoint
and segmented-history replay. Its process attempt key remains the exact native
receipt/attempt/owner-generation tuple. Sealing a parent cannot authorize
skipping any native containment or cleanup edge.

Reconciliation requires a complete original-owner snapshot for the enrolled
scope, every registered native operation and its sealed membership digest.
Before sealing after a crash, the owner must fence outstanding original tasks
and possible native starters through its existing lifecycle/containment
mechanisms. A different random boot ID alone cannot prove that another process
or thread stopped. Starts and transitions recheck the parent's native fence;
sealing cannot race with an unchecked late start. Failure to establish that
fence remains unknown. A missing owner, journal, retained segment, enrollment,
seal or membership match is unknown. An empty sealed scope is evidence only
when the original owner proves this complete protocol, never from an empty
untrusted JSON list.

### Separate outcome obligations

| Original owner | Covered completion boundary | Failure/restart treatment |
| --- | --- | --- |
| Definition Host and its execution journal | The exact declared invocation returned and its domain obligations completed; `EVALUATED` alone covers only invocation return | Started failure stays unknown for external effects. Original import/cleanup and domain reconciliation must account for them. |
| Component Host and its activation journal | The exact factory completed, the original use published and its declared startup obligations completed | `FAILED` or disposal failure is not external settlement. A retired component cannot satisfy current live publication even after its prior effects settle. |
| Native Worker/C5 owner | The exact registered startup reaches admitted live readiness, or original no-start/cleanup proof establishes its applicable obligation | Live readiness is checked again through the original admitted facet; another boot needs original process/containment reconciliation. Historical cleanup must match exact native identities and the supported cleanup contract. |
| External domain owner | Its declared domain-specific completion or compensated/disposed outcome | Unknown filesystem/network/publication outcomes stay quarantined until that owner proves completion or records an authorized explicit disposition. |

The continuation validates the complete owner set, contexts, seals, native
identities and domain obligations before first-input commit. It separately
checks original live candidate publication and current caller/policy/content.
It repeats those current checks at publication and transport. A historical
settlement result cannot revive a retired component or start a model.

### Disposition authority and evidence retention

Native cleanup uses each domain's existing authority and lifecycle. An
administrative disposition is available only if that original domain has a
trusted issuer capable of authorizing that exact action under current policy.
Its evidence includes the parent digest, exact native operation identities,
covered obligations, actor/authorization identity, policy revision, revocation
epoch and disposition digest. The original owner revalidates authorization and
persists the result. An ordinary activation approval cannot silently become
administrative disposition authority. If no such issuer exists, return unknown;
this slice does not create one inside Coding, AppService or the UI.

Existing native completion and cleanup mechanisms are reused where their
contracts suffice. New trusted external reconcilers require their own reviewed
domain contracts. A callback that merely matches the current composition set
or returns None is not a production adapter. Original custodians retain the
native journals, required historical segments and evidence until every covered
operation is resolved; ephemeral data cannot erase unresolved durable evidence.
Session/graph, Product epoch and Worker owners retain their existing disposal
responsibilities. Post-publication Tool/model effects belong to their own Turn
identities and are not added retroactively to this sealed startup scope.

## Version And Release Boundary

Use versioned native owner events for the additional causal context and
settlement/disposition data. Keep legacy decoding explicit. A legacy use
without a complete parent association cannot supply verified absence or full
settlement for a Resume intent.

The required writer capabilities are `coding.resume-continuation/v2`,
`harness.plugin-execution.resume-context/v1`,
`harness.plugin-activation.resume-context/v1` and
`harness.worker-activation.resume-context/v1`. They identify protocol support,
not authorization. The original writer checks all required capabilities before
repair, enrollment or append. Native new readers decode v1 and v2 explicitly;
unknown future events refuse mutation. Store the required protocol boundary in
the original owner's version mechanism, not in a new Coding sidecar ledger.

Current old Approval journal implementations use partial-tail repair before
semantic replay. Therefore an arbitrary previously shipped binary cannot be
claimed to honor a new pre-repair fence. This is a concrete limitation, not a
property that a v2 event can retroactively add. Unfenced older writers are
unsupported for the upgraded owner state. Any supported downgrade operation
must use an original-owner, capability-aware entry and refuse before repair or
append; otherwise downgrade is read/export only. Installed-version tests must
exercise both complete and partial-tail journals and report the old binary's
actual behavior. No safe native writer rollback is promised by transcript
reader/export compatibility.

The first shipping build for each capability must be identified by released
artifact version and source revision after implementation. `0.1.0` alone does
not distinguish these builds. Release remains gated on installed N/N+1 history
reader/export, new writer, supported rollback refusal and explicit unsupported
old-writer evidence. Neither this decision nor a source checkout supplies those
release results.

## Review And Acceptance Gates

The implementation-session source review identified a specific unresolved
association between Transcript intent and original native operations. The original
proposal review was an author review; the acceptance record below identifies
the later delegated technical review. No independent reviewer is claimed. The
decision belongs to the common parent of Coding and Harness. The project governance profile
requires owner acceptance of this exact contract; it creates no blanket
customer-confirmation requirement.

The four initial design findings are addressed by the accepted contract above:

| Finding | Accepted design closure | Implementation/release evidence still required |
| --- | --- | --- |
| Complete owner enumeration before Definition evaluation | Frozen v2 owner obligations from verified inert Product closure; enrollment and sealed native membership | Unknown/omitted domain, late discovery and unsealed/partial enumeration fault tests |
| Atomic registration and native outcome meaning | Context co-committed with consume/reserve; separate Definition, component and Worker obligations | Actual native CAS/ack-loss, late-start fence and cross-boot containment tests |
| Original disposition authority | Existing domain issuer required; missing issuer remains unknown; no UI/Coding force retry | Authorization/revocation and incomplete compensation tests with original owners |
| Version, old writer and retention | Named capabilities; explicit v1/v2 decoding; unsupported unfenced old writers; original-owner retention | Installed artifact identities and complete/partial-tail downgrade behavior |

These mechanisms resolve the design findings for revision `2026-10-12-r2`.
Their implementation and release evidence remain outstanding. ARD-005 v1
paths remain effective until the accepted extension has implemented gates for
the affected clauses. No runtime activation is enabled by this review.

Required implementation evidence includes crash/ack loss at intent,
registration, start, completion, input commit and publication; recovery under
another boot; partial native journal tails; multiple native uses under one
attempt; changed caller/policy/content; journal loss; unknown external effects;
failed compensation; native Worker containment settlement; and old/new installed
reader and writer artifacts. Tests must use actual owner journals and retain
unknown results. A green callback fixture is not acceptance evidence.

The [accepted governance profile](../../governance-profile.md#target-acceptance-in-loushang)
and [decision catalog](../README.md) govern promotion. Until implementation and
release evidence, default writable Resume and the full Issue remain
incomplete. Independent quality gates and existing accepted work may continue.

## Acceptance Record

- Date: 2026-10-13.
- Reviewed revision: proposal `2026-10-12-r2` in task source `bf29c05d`.
- Reviewer and accepting role: Codex implementation agent acting under the
  already authorized Issue #696 task and the project's delegated Loushang
  common-parent responsibilities. This is an agent technical review and
  acceptance; it does not attribute approval to the user or a separate reviewer.
- Method consulted: local archmethod `master`,
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`.
- Accepted scope: parent context, frozen owner obligations, atomic native
  registration, fenced sealed enumeration, original-owner outcomes and
  disposition, retention, and the named intent/Binding/native writer versions
  defined above. ARD-005's v1 input commit remains effective; this decision
  accepts its explicit v2 extension without enabling a writable route.
- Rationale: exact causal association belongs with native consume/reserve and
  outcome authority. A new graph receipt cannot reconcile prior effects, and
  another Coding ledger would introduce a second effect authority. Frozen
  participation and fenced seals distinguish complete enumeration from a
  partial or empty observation.

The review checked the original Definition evaluator's consume/transition and
failed-start paths, the component Host's start/commit/failure transitions,
Approval journal replay and scope checks, Worker C5's native attempt keys,
CAS, effect-start and versioned cleanup validation, Product composition's
original journals/custodians, and the Coding continuation's committed-intent,
current-admission and settlement callback boundaries. The four design findings
above have explicit mechanisms; no unresolved design finding requires waiting
for a human approver. Implementations lacking those mechanisms still refuse
writable activation.

At acceptance, implementation findings were: native journals had no parent
enrollment or sealed membership; Worker attempts had no Resume context; the continuation
still takes an injected settlement callback; released artifact and old-writer
capability coverage are incomplete. The new pre-repair semantic-validation
regressions are useful journal evidence, not evidence for native v2 recovery.
All required fault tests and release gates above remain mandatory.

Reconsider this decision if an original owner cannot atomically register its
native use, cannot fence late starters and enumerate retained operations, or
cannot retain evidence across its custody lifetime. Changes to the accepted
scope or supported downgrade contract require a revised decision; they must
not be inferred from passing fixture callbacks or a new implementation version.


## Implementation Progress: Definition Journal

The original Definition Approval journal now stores explicit v2 enrollment and
seal events. Its v2 consumed-use event co-commits the exact parent context with
the native decision consumption and reservation. Existing v1 events and native
reservation/receipt identities remain explicit; v1 event payloads are unchanged.
The shared parent context is strict, immutable, 2 KiB bounded and contains only
the accepted lookup fields. Its digest is domain separated.

The journal validates its own scope and contract, rejects rebinding an existing
attempt to another intent, and exposes exact original native use membership.
Seal membership is sorted and digest checked. Original CAS serialization fences
registration versus seal; native STARTING transitions and replay reject a sealed
parent. An unresolved STARTING use prevents seal, including after a different
boot. Missing parent enrollment and unresolved starts refuse before partial-tail
repair. Native evaluated or failed facts do not settle external domain effects.

This is original-journal protocol infrastructure. The original Definition evaluator accepts an explicit typed parent context and
co-consumes it before import. The production Product selection has not yet
propagated that context from the committed v2 intent. Product owner
participation, retained custody and domain
reconciliation still require implementation and integration. The parent
snapshot is not proof of complete Product startup participation, current
admission or external settlement. Default writable Resume remains unavailable
until those remaining obligations and the release gates are satisfied.

## Implementation Progress: Component Journal

The original Activation Approval journal now persists explicit v2 parent
enrollment and sealed membership. Contextual native consumption records the
parent and the original decision/reservation in one event. Legacy v1 event
payloads and native use identities remain unchanged. Both in-process Component
Hosts accept the typed context through their shared native lifecycle; they
require original enrollment before consumption, recovery or import. Contextual
recovery only changes native uses registered under that exact parent.

Original CAS and replay fence further consumption and late STARTING after a
seal. Active STARTING or STARTED uses refuse sealing. Cross-boot recovery may
retain the original v1 FAILED state, but replay also retains the fact that the
factory was recovered without a stop fence. Those uses remain unresolved and
prevent sealing. A rejected seal or sealed late start preserves partial-tail
bytes. COMMITTED records graph publication; it does not prove completion of
external domain effects or custody retention.

These opt-in native protocols still need propagation from a committed Product
intent, complete trusted owner participation, Worker containment settlement,
custodian retention and domain reconciliation. They do not enable default
writable Resume. Focused tests exercise the actual Component factory, native
journal recovery and durable acknowledgement loss; release and full Product
integration evidence remain required.

## Implementation Progress: Worker C5 State

The original C5 CAS aggregate now supports an explicit Resume state version 3
and journal record version 2. Existing state version 2 and record version 1
remain on the ordinary path. Enrollment freezes the exact parent descriptor;
native admission co-commits its original receipt/attempt/owner-generation key
and parent association in one state revision. Contextual admission requires
cleanup contract v2, including native containment evidence.

Sealing enumerates sorted original keys and fences new registration and late
effect start. An effect-started or cleanup-unknown attempt prevents sealing;
published startup and original no-effect/cleanup settlement retain their native
meanings. Cross-process CAS and complete-history replay reject deletion or
rebinding of registration evidence, removal or reopening of seals, retroactive
registration and downgrade from Resume state. Linked settled attempts are
excluded from native compaction; exhausted capacity refuses new admission.

The coordinator and durable journal preserve original outcome authority.
Registration acknowledgement loss retains the original parent/key and does not
enter the effect body. A known durable no-effect settlement may then close that
attempt through the original owner. Publication and cleanup do not settle
arbitrary external domain effects. Current native facet admission remains
required after historical startup facts.

The restricted Coding continuation now propagates an exact selected Worker
plugin and its committed v2 parent into both POSIX and Windows C5 preparation.
C5 enrollment precedes payload materialization, native admission atomically
registers the attempt association before effect start, and graph publication
seals original membership. Retry reuses exact enrollment and recovers committed
enrollment or seal records after lost acknowledgements. Ordinary activation
continues through its context-free path.

This is restricted Product integration rather than default activation.
Segmented/checkpoint retention, custody retirement, installed writer capability
boundaries, domain reconciliation, Windows host-runtime evidence and
Embedded/Hosted integration remain required. The native protocol and this
propagation slice do not enable default writable Resume.
