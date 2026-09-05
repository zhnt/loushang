# Loushang Hosting H6 Managed Launch Preparation

## Status

- ID: `HOST-H6`
- Scope: `hosting`
- Parent: `loushang`
- Authority: normative accepted design
- Design status: accepted
- Implementation status: implemented — H6.1 through H6.4 remain default-dark
- Activation status: forbidden; H5 remains default-dark
- Owner: Loushang Hosting architecture

## Purpose

H6 closes the mechanical gap between the implemented Hosting child-session
owner and a caller that requires path-stable executable, cwd, inherited
resource, and containment launch mechanics. It does so without transferring
Policy, Approval, Authorization, Sandbox policy, Product activation, or Worker
meaning into Hosting.

This document fixes responsibility and proof obligations. It deliberately does
not reserve Python class names or claim that the current Linux-only Harness
sealed-descriptor implementation is a cross-platform contract.

## Current, Target, And Delta

### Current

- H1--H4 own process, endpoint, and atomic child-session mechanics.
- H5 supplies a default-dark Harness Worker adapter, and H6.4 preserves an
  injected private managed-preparation seam while adding only Worker semantic
  verification. No production composition supplies an eligible native Worker
  profile.
- Harness privately captures a Linux executable and cwd with retained file
  descriptors and passes them through a private Process Host request subtype.
- `hosting_compat` refuses that request because Hosting v1 has no safe way to
  consume the private descriptors.
- Windows Hosting proves Job Object process lifetime and strict endpoint-handle
  inheritance, but no equivalent immutable executable/cwd plus required
  containment preparation is accepted for the Worker route.

### Proposed target

A trusted consumer supplies an immutable, admitted preparation specification
and retains the meaning of every policy or containment requirement. Its
preparation adapter still materializes the exact containment wrapper/plan.
Through a narrow Hosting capture capability injected into that trusted
adapter, the selected Contract and Platform components acquire the native
executable/cwd/binding resources without exposing their values. The adapter
attaches each acquired resource to the receiving reservation before capture
returns, then returns the rewritten exact request plus an opaque one-use
preparation lease.
Process or Child Session Host performs final verification and atomically
consumes that lease at spawn.

### Explicit delta

The delta is a Hosting-consumable native preparation mechanism, not a Product
activation route. No Current owner changes, no public author SDK widens, and no
PLC9C5 absence guard is removed by H6 design or dark implementation alone.

## First-Principles Decisions

1. **Meaning stays with the caller; mechanism stays with Hosting.** The caller
   decides whether a launch is admitted and which constraints are mandatory.
   Hosting owns only the OS resources and operations needed to realize an exact
   admitted specification.
2. **An opaque lease crosses the ownership boundary.** Raw descriptors,
   handles, process objects, mutable paths, spawners, and backend instances are
   never public contract fields.
3. **Preparation is request-bound and one-use.** The lease is bound to the
   complete normalized launch request, preparation-specification fingerprint,
   selected backend identity, and one fresh attempt identity. It cannot be
   replayed, retargeted, copied to another host, or reused after any spawn
   attempt.
4. **Final verification is adjacent to the effect.** Identity and required
   native properties are rechecked after endpoint creation and immediately
   before the sole OS spawn operation. Failure closes every acquired resource
   before it is reported.
5. **Required means fail closed.** Unsupported capture, containment, handle
   transfer, or tree ownership never falls back to a mutable path, ambient
   inheritance, stdio rendezvous, TCP, or a weaker backend.
6. **Evidence does not acquire authority.** Hosting may report bounded facts
   such as material acquired, verified, consumed, or closed. Only the caller
   may interpret its own receipts as Approval, Authorization, Sandbox, Worker,
   or Product evidence.
7. **The five-component model remains stable until discovery disproves it.**
   Contract Model owns neutral shapes; Platform Adapter Set owns native
   acquisition/transfer; Process and Session owners consume the material.
   H6 does not create a generic Sandbox or sixth peer component by naming a new
   capability.
8. **One spawn has one inheritance manifest.** Endpoint resources and opaque
   preparation resources are combined inside Hosting into one private exact
   allowlist. Duplicate slots, descriptor/handle aliasing, stdio collision, an
   already-consumed resource, or any ambient extra fails before OS creation.
9. **Identity covers the execution closure.** Freezing only the final payload
   is insufficient when a containment launcher, script interpreter, runtime
   loader, or platform image dependency can be substituted. Every supported
   preparation profile names the exact execution-closure identities it proves;
   unknown or unproved chains fail closed.
10. **Capture is reservation-scoped and bounded.** The receiving Process/Child
    Session Host mints capture authority only for one already-reserved start
    transaction. The capability has the same backend identity and fixed
    resource limits, expires with that transaction, and cannot preallocate an
    unbounded pool beside host capacity.
11. **Acquisition attaches before cancellation can land.** A capture backend
    synchronously attaches every acquired native resource to the receiving
    reservation before its first post-acquisition cancellation point. The
    caller receives only an opaque binding token; it never temporarily owns the
    executable, cwd, token, profile, or inheritance material. If the caller
    raises or is cancelled after capture but before returning its preparation
    lease, the reservation already has everything required for rollback.

## Responsibility Boundary

| Concern | Primary owner | Collaborator | Explicit non-owner |
| --- | --- | --- | --- |
| Product/Plugin selection and rollout | Product/Harness composition | domain adapter | Hosting |
| Policy, Approval, and Authorization | Harness authority owners | Product policy | Hosting |
| required-containment selection and semantic evidence | Harness Sandbox owner | Product policy | Hosting |
| neutral preparation specification and lease vocabulary | `HOST-CMP-CONTRACT` | trusted consumer | Product catalog |
| native executable/cwd/resource acquisition and identity recheck | `HOST-CMP-PLATFORM` | Process Host | Harness Worker |
| exact spawn and process-tree ownership | `HOST-CMP-PROCESS` | Platform Adapter | Sandbox policy |
| preparation + endpoint + process transaction | `HOST-CMP-SESSION` | Process/Endpoint hosts | domain generation owner |
| Worker handshake, recovery, and restart | Harness Worker supervisor | Product/domain adapter | Hosting |
| Capability generation publication and retirement | exact Harness/domain owner | Worker adapter | Hosting |

The Sandbox owner may issue a signed or capability-bound requirement/receipt
to trusted composition, but Hosting neither verifies its business meaning nor
publishes it. Conversely, the Sandbox owner does not retain or transfer raw
native launch resources after Hosting accepts ownership.

## Two-Sided Preparation Boundary

The accepted H0--H5 `LaunchPreparationPort` remains caller-owned: it chooses
the exact wrapper/containment request, validates the caller's receipts, and
owns semantic cleanup. H6 adds only a complementary Hosting-owned one-shot
capture capability to trusted composition for the already-reserved start
transaction. The caller may request capture of admitted executable/cwd
identities and refer to those resources through typed opaque binding slots; it
cannot read their descriptor/handle values or hand them to a different
spawner.

The resulting preparation lease therefore joins two owners without blending
their meaning:

- the caller half owns the rewritten exact request, authority revalidation,
  containment-plan meaning, and caller cleanup; and
- the Hosting half owns native resource acquisition, private spawn binding,
  one-use consumption, and native cleanup.

Until `prepare_managed` returns a result, any caller semantic candidate remains
caller-owned. A managed preparation adapter that raises or is cancelled after
capture must close that candidate through its own cancellation-safe owner
operation; Hosting simultaneously rolls back every native material already
attached to the reservation. Once the result returns and its binding is
consumed, the joined preparation lease owns both cleanup paths.

H6.1 must select and prove one common composition protocol. Candidate shapes
include typed opaque binding slots or private double-dispatch into the selected
backend. String placeholder substitution, duck-typed raw-handle carriers, and
backend option dictionaries are forbidden. H6.1 begins with non-committing
POSIX and Windows feasibility probes. Those probes validate that one private
core can represent attachment, verification, claim, transfer, and close on both
platform families; they are inputs to, not implementations of, H6.2 or H6.3.
Only after both probes succeed does the fake-backed H6.1 freeze the common core.
H6.2 and H6.3 may add reviewed platform-private profile data without changing
that ownership state machine or public H0--H5 contracts. H6.0 reserves no
public fields or symbols.

The capture capability is a leaf resource operation. It must not reserve
Process/Child Session capacity, call either host recursively, select a backend
independently from the receiving host, or publish a lease. This prevents the
caller-owned preparation callback from re-entering the transaction owner and
creating a lock, capacity, or backend-identity cycle.

Opaque here is an API and ownership property, not a hostile same-process Python
security boundary. Only trusted composition and its preparation adapter receive
the object; an untrusted Plugin or Worker process never does. Sandbox/process
isolation remains the security boundary for untrusted code.

## Opaque Capture State And Resource Transfer

Each capture authority and captured material has one serialized owner
operation. The normative state machine is:

```text
MINTED -> CAPTURING -> CAPTURED -> VERIFYING -> VERIFIED
                                            -> CLAIMED -> ATTACHED -> CLOSED
any pre-ATTACHED failure -------------------------------> CLOSED
ambiguous spawn/transfer -------------------------------> FENCED
```

- `MINTED` is bound to one reservation, attempt, and backend. Capture is legal
  once; a second or concurrent call fails before acquisition.
- The backend invokes the reservation attachment callback synchronously while
  `CAPTURING`, before returning material or reaching a cancellation point.
- Verification and claim are one-use operations bound to the complete prepared
  request. Concurrent verify, claim, replay, retarget, or close joins or loses
  against the single owner operation; it never performs a second native action.
- `CLAIMED` through process attachment is an uninterruptible backend critical
  section containing the unique inheritance-manifest claim, sole OS process
  creation effect, and synchronous process attachment callback. Caller
  cancellation is observed only after its outcome is known and cleanup is
  owned. The attempt mints the only valid pre-effect `not-created` receipt; the
  matched backend crosses its effect gate immediately before OS creation. A
  trusted native backend may then mint a distinct settled-without-process
  receipt only when the operating-system attempt conclusively returned with no
  owned process. Neither receipt is valid after an attachment witness. An
  unreceipted or unknowable post-effect outcome becomes `FENCED`, never a retry
  authority.
- A close racing with capture/verify/claim waits for that owner operation. It
  must not close a descriptor or handle whose transfer outcome is unresolved.
  Repeated close joins one idempotent cleanup operation.

Resource classes have explicit successful release points:

| Resource class | Parent-side owner before spawn | Successful handoff/release |
| --- | --- | --- |
| executable, cwd, launcher/interpreter and loader identity references | reservation-scoped captured material | close parent copies only after the backend confirms the OS consumed or duplicated the exact reference |
| child-inherited descriptors/handles | one combined inheritance manifest | transfer only the exact allowlist; close parent child-side copies immediately after confirmed attachment |
| token, AppContainer/profile, namespace, Job, or equivalent process-lifetime containment resource | captured material, then attached Process Lease | retain until the complete process tree exits and platform cleanup settles |
| caller semantic preparation lease | caller preparation owner, then Process Lease | close after attached process finalization; close during rollback if publication never occurs |
| opaque binding token | caller-visible but non-owning | expires when the reservation leaves `CAPTURED` or the transaction closes |

No successful path leaves native material owned only by a callback-local
variable. A capture acquisition failure that cannot close all attached
material faults and retains the reservation as cleanup debt. A joined native
plus caller preparation is likewise attached to the Child Session reservation
before endpoint acquisition and remains there until Process Host accepts it.
Lower Process/Endpoint cleanup debt is retained by exact session and source;
an unrelated `CLEANUP_FAILED` exception is never treated as proof that a lower
owner still holds resources.

## Accepted Contract Properties

The private H6.1 schema expresses only the minimum neutral constraints that
Hosting can enforce mechanically:

- normalized expected launch-request fingerprint;
- executable content and file identity expectations, without a caller-visible
  native descriptor/handle;
- cwd directory identity and access intent, without granting a writable cwd by
  implication;
- a closed execution-closure profile covering the containment launcher,
  payload, and any interpreter/loader identities required by that profile;
- a closed loader/search policy covering environment keys, search roots, and
  dependency content identities that can affect executed code;
- an exact required native preparation profile selected by trusted
  composition, not by environment fallback;
- the finite inherited-resource intent already admitted by the endpoint and
  stream contract;
- bounded attempt/correlation identities suitable for observations; and
- an idempotent close path for every resource acquired before spawn.

Every profile must either bind each dynamic dependency to a content identity or
bind it to an immutable, explicitly admitted platform-image trust root. It
normalizes or rejects loader-affecting environment such as `LD_*`, `DYLD_*`,
DLL search controls, `PATH`, `PYTHONPATH`, and language/runtime preload paths.
Scripts or dynamically linked programs whose effective closure cannot be
proved fail closed rather than silently reducing "execution closure" to the
top-level executable.

The contract must not carry Product IDs, Plugin declarations, Approval records,
credentials, arbitrary environment discovery, raw containment commands, raw
platform handles, or an extensible dictionary of backend options. A
platform-specific private representation may be richer, but remains behind the
selected Hosting backend.

The existing caller-provided `LaunchPreparationPort` remains the semantic
fence. H6.1 adds a separate private managed-preparation port and reservation
capture capability while preserving H0--H5 compatibility. Native H6.2/H6.3
profile data remains private behind matched backend double-dispatch; promotion
of any author-facing field is a separate versioned contract decision.

## Successful Interaction

```text
Product/Harness composition
  -> select exact Product/contribution and obtain authority receipts
  -> Sandbox owner: build the admitted exact containment plan
  -> Child Session Host: start(exact request, preparation port)
  -> preparation port: validate caller meaning and invoke Hosting capture port
  -> Hosting Platform Adapter: acquire opaque executable/cwd/binding material
  -> preparation port: return exact rewritten request + joined opaque lease
  -> Inherited Endpoint Host: acquire the one child endpoint
  -> preparation lease: final request, identity, and native-property verification
  -> Hosting backend: build one collision-free endpoint + preparation allowlist
  -> Process Host: atomically consume preparation + endpoint inheritance at spawn
  -> Child Session Host: publish process lease + host endpoint
  -> Harness Worker supervisor: handshake and domain admission
  -> Product/domain owner: publish an accepted generation
```

The first publication is a Hosting resource publication. The final publication
is a domain decision and is outside Hosting.

## Failure, Cancellation, And Cleanup

One owner transaction covers every pending resource. On rejection, failure, or
cancellation it attempts all reachable cleanup in this order unless a native
backend proves a stricter order is required:

1. prevent Child Session publication and mark the opaque preparation consumed;
2. terminate, kill, and reap an attached process tree if spawn crossed the OS
   creation boundary;
3. close the unused child endpoint and host endpoint;
4. close native executable, cwd, token/profile, and containment resources;
5. close the caller preparation lease and release capacity; and
6. propagate the primary typed failure with bounded cleanup context.

Caller cancellation is re-raised only after owned cleanup settles. An uncertain
spawn or cleanup result fences the host/attempt; it never authorizes a retry on
the Current owner within the same attempt.

## Native Proof Obligations

### POSIX/Linux

Native evidence must prove executable identity is not substituted between
admission and exec, cwd identity remains bound, only the intended descriptors
are inherited, the required containment wrapper/profile is the one executed,
and the complete process tree is reclaimed. `/proc/self/fd`, `fexecve`, memfd,
bubblewrap, and descriptor-relative cwd are implementation candidates, not
accepted contract promises. Tests must include rename/replace, symlink, fd
reuse, endpoint/preparation descriptor collision, cancellation, exec failure,
early exit, and cleanup-fault cases. If the payload is a script or dynamically
loaded program, the accepted profile must additionally bind or explicitly
admit its interpreter/loader chain; sealing payload bytes alone is not enough.
Loader-affecting environment, dependency search roots, and admitted dynamic
dependency or platform-image identities are part of the adversarial oracle;
library replacement and search-order substitution must fail closed.
Absence of startup `PT_INTERP`/`PT_DYNAMIC` closes only the kernel startup
loader chain; runtime executable mapping, `dlopen`, subsequent exec, and
process-group escape remain part of caller-owned profile evidence bound to the
exact captured launcher/payload identities.

### Windows

Native evidence must prove immutable executable/cwd identity or document an
equally strong accepted mechanism, strict `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`
inheritance, required AppContainer/restricted-token properties where selected,
atomic Job Object ownership, executable image/interpreter and DLL-search
policy plus dependency/platform-image identities for the selected profile, and
deterministic handle cleanup. Handle
alias/collision and AppContainer-token creation must be exercised with the
same endpoint-plus-preparation spawn. A POSIX test, fake Win32 adapter, or Job
Object result alone cannot promote this gate.

### Other environments

macOS, WSL, containers, and every unlisted host/backend pair remain separate
profiles. They fail closed until their exact preparation, containment, handle,
and tree-lifetime properties have native evidence.

## Delivery Slices

| Slice | Delivery | Exit gate |
| --- | --- | --- |
| H6.0 | this responsibility/contract baseline, Current inventory, and absence guards | architecture review accepts ownership; no runtime activation |
| H6.1 | non-committing POSIX/Windows feasibility probes followed by a private fake-backed two-sided opaque preparation transaction | both probes support one core state machine; caller/Hosting ownership and the complete concurrency/fault matrix pass; no public activation |
| H6.2 | implemented private Linux static-closure preparation profiles | required-containment and executable/cwd/descriptor adversarial oracle passes |
| H6.3 | implemented private Windows AMD64 restricted-token PE preparation | restricted token, handle-list, Job, identity, and cleanup oracle passes |
| H6.4 | implemented dark Harness managed-preparation bridge and H5 semantic parity matrix | public and managed preparation paths retain the same Worker fences; default remains Current and native Worker compatibility is not claimed |

H6.1 is implemented as a private, default-dark core. Its non-committing POSIX
and Windows mapping probes and fake-backed lifecycle evidence are retained in
[H6.1 Managed Launch Preparation Feasibility Record](validation/managed-launch-preparation-h6-feasibility.md).
No H6.2/H6.3 native adapter or H6.4 Harness adapter was implied by that result.

H6.2 is implemented for two exact Linux x86_64 profiles. The release profile pins a
caller-admitted static containment launcher and static payload, rejects every
dynamic loader/interpreter chain, binds an empty loader environment and exact
profile digest, and retains a non-skippable Ubuntu adversarial oracle. See the
[H6.2 POSIX native record](validation/managed-launch-preparation-h6-posix-native.md).
This evidence does not make dynamic bubblewrap or an arbitrary Worker
entrypoint conformant, and it adds no public composition route.

H6.3 is implemented for one exact Windows AMD64 profile. It locks the admitted
PE and cwd identities, creates the fixed restricted-token recipe and
kill-on-close Job, retains the complete resolved local ancestor chain,
restricts PE direct-import names to a fixed platform-name set, and retains a
non-skippable Windows adversarial oracle. This direct-import mechanics profile
does not claim a complete Windows loader closure. See the
[H6.3 Windows native record](validation/managed-launch-preparation-h6-windows-native.md).
This profile is deliberately narrower than Python or the Current Worker and
adds no public composition route.

H6.4 is implemented as a private friend adapter in the Harness Worker scope.
It preserves an injected nominal managed-preparation port, delegates the
reservation capture without interpreting its opaque binding, and decorates
only the caller semantic lease with the existing Worker final fence. Ordinary
public preparation remains on the H5 path. Its fake-backed parity matrix,
ownership proof, and explicit native-compatibility limits are retained in the
[H6.4 Harness parity record](validation/managed-launch-preparation-h6-harness-parity.md).
It adds no native profile supplier, Product composition, owner fallback, or
activation route.

The H6.1 probes perform no production spawn and reserve no public API. H6.2,
H6.3, and the fake-backed part of H6.4 may be developed in parallel only after
H6.1 freezes the common ownership protocol. Each native parity claim still
depends on its matching H6.2/H6.3 evidence. H6.4 may not erase the Current
implementation or enable a Product route.

The H6.1 matrix includes concurrent double-capture/double-consume,
verify-versus-close, claim-versus-close, capture followed by callback failure or
cancellation, endpoint/preparation slot collision, retarget/cross-host replay,
quota exhaustion, forbidden recursive capacity acquisition, final-fence
cancellation, ambiguous spawn, cleanup failure, and host-close races. Exact
state, attachment count, native close count, retained cleanup debt, and absence
of publication are asserted for every case.

## Conformance Inventory

| ID | Planned evidence |
| --- | --- |
| `H6-BOUND` | preparation is bound to one complete request, specification, backend, and attempt |
| `H6-OPAQUE` | public surfaces expose no raw descriptor, handle, spawner, process, or mutable-path escape |
| `H6-ONE-SHOT` | success, failure, cancellation, replay, and cross-host transfer consume or close exactly once |
| `H6-STATE` | capture, verify, claim, attach, close, and host-close races linearize through one owner operation |
| `H6-CAPACITY` | capture authority exists only inside one reserved transaction and obeys fixed resource limits |
| `H6-ATTACH` | each acquired resource attaches to the reservation before post-acquisition cancellation can land |
| `H6-FINAL-FENCE` | final identity/native-property verification is adjacent to the only spawn effect |
| `H6-INHERITANCE` | endpoint and preparation resources form one exact collision-free allowlist |
| `H6-EXEC-CLOSURE` | the selected profile proves its launcher, payload, interpreter/loader execution chain |
| `H6-LOAD-CLOSURE` | loader environment, search policy, and dependency content/platform-image identity cannot be substituted |
| `H6-CLEANUP` | every acquisition and publication fault settles all reachable owners |
| `H6-POSIX-NATIVE` | retained Linux adversarial preparation/containment report passes without fallback |
| `H6-WINDOWS-NATIVE` | retained Windows adversarial preparation/containment report passes without fallback |
| `H6-HARNESS-PARITY` | the private bridge preserves managed capture and the existing Worker semantic fence without claiming native Worker compatibility |
| `H6-NO-AUTHORITY` | Hosting imports, vocabulary, and observations contain no Harness/Product security meaning |
| `H6-DARK` | non-Worker production modules do not compose the path and owner default remains Current |

## Activation Fence

H6 is necessary but not sufficient for PLC9C5. Product/native Worker activation
requires a separate Product-owned change that consumes H6 evidence, binds an
exact domain adapter and generation owner, supplies recovery and rollback
receipts, and passes native cross-entrypoint conformance. Until that review:

- `WorkerHostingActivationV1.owner` remains `"current"` by default;
- a selected Hosting failure never falls back within the same attempt;
- no environment variable, auto-detection, or missing configuration enables
  the Hosting Worker owner; and
- the PLC9C5 Product-activation/platform absence guard remains intact.
