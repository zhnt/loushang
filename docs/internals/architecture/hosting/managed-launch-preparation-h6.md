# Loushang Hosting H6 Managed Launch Preparation

## Status

- ID: `HOST-H6`
- Scope: `hosting`
- Parent: `loushang`
- Authority: normative proposed design
- Design status: proposed
- Implementation status: not-started
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
- H5 supplies a default-dark Harness Worker adapter over the public
  `LaunchPreparationPort`, but its mapped request contains only strings.
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
returns the rewritten exact request plus an opaque one-use preparation lease.
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

H6.1 must select and prove one common composition protocol. Candidate shapes
include typed opaque binding slots or private double-dispatch into the selected
backend. String placeholder substitution, duck-typed raw-handle carriers, and
backend option dictionaries are forbidden. Until that protocol is accepted,
H6.0 reserves no public fields or symbols.

The capture capability is a leaf resource operation. It must not reserve
Process/Child Session capacity, call either host recursively, select a backend
independently from the receiving host, or publish a lease. This prevents the
caller-owned preparation callback from re-entering the transaction owner and
creating a lock, capacity, or backend-identity cycle.

Opaque here is an API and ownership property, not a hostile same-process Python
security boundary. Only trusted composition and its preparation adapter receive
the object; an untrusted Plugin or Worker process never does. Sandbox/process
isolation remains the security boundary for untrusted code.

## Proposed Contract Properties

The future exact schema must express only the minimum neutral constraints that
Hosting can enforce mechanically:

- normalized expected launch-request fingerprint;
- executable content and file identity expectations, without a caller-visible
  native descriptor/handle;
- cwd directory identity and access intent, without granting a writable cwd by
  implication;
- a closed execution-closure profile covering the containment launcher,
  payload, and any interpreter/loader identities required by that profile;
- an exact required native preparation profile selected by trusted
  composition, not by environment fallback;
- the finite inherited-resource intent already admitted by the endpoint and
  stream contract;
- bounded attempt/correlation identities suitable for observations; and
- an idempotent close path for every resource acquired before spawn.

The contract must not carry Product IDs, Plugin declarations, Approval records,
credentials, arbitrary environment discovery, raw containment commands, raw
platform handles, or an extensible dictionary of backend options. A
platform-specific private representation may be richer, but remains behind the
selected Hosting backend.

The existing caller-provided `LaunchPreparationPort` remains the semantic
fence. H6 may extend its result through a new versioned opaque capability or a
separate required port, but must preserve H0--H5 compatibility. Field-level API
selection is deferred until the POSIX and Windows feasibility spikes prove one
common ownership protocol.

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

### Windows

Native evidence must prove immutable executable/cwd identity or document an
equally strong accepted mechanism, strict `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`
inheritance, required AppContainer/restricted-token properties where selected,
atomic Job Object ownership, executable image/interpreter and DLL-search
assumptions for the selected profile, and deterministic handle cleanup. Handle
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
| H6.1 | private fake-backed two-sided opaque preparation transaction | caller/Hosting ownership, replay/retarget/cancellation/fault matrix passes; no public activation |
| H6.2 | Linux native preparation backend | required-containment and executable/cwd/descriptor adversarial oracle passes |
| H6.3 | Windows native preparation backend | AppContainer/token, handle-list, Job, identity, and cleanup oracle passes |
| H6.4 | dark Harness preparation adapter and H5 parity matrix | Current and Hosting owners are independently conformant; default remains Current |

H6.2, H6.3, and the fake-backed part of H6.4 may be developed in parallel after
H6.1 freezes the common ownership protocol. Each native parity claim still
depends on its matching H6.2/H6.3 evidence. H6.4 may not erase the Current
implementation or enable a Product route.

## Conformance Inventory

| ID | Planned evidence |
| --- | --- |
| `H6-BOUND` | preparation is bound to one complete request, specification, backend, and attempt |
| `H6-OPAQUE` | public surfaces expose no raw descriptor, handle, spawner, process, or mutable-path escape |
| `H6-ONE-SHOT` | success, failure, cancellation, replay, and cross-host transfer consume or close exactly once |
| `H6-CAPACITY` | capture authority exists only inside one reserved transaction and obeys fixed resource limits |
| `H6-FINAL-FENCE` | final identity/native-property verification is adjacent to the only spawn effect |
| `H6-INHERITANCE` | endpoint and preparation resources form one exact collision-free allowlist |
| `H6-EXEC-CLOSURE` | the selected profile proves its launcher, payload, interpreter/loader execution chain |
| `H6-CLEANUP` | every acquisition and publication fault settles all reachable owners |
| `H6-POSIX-NATIVE` | retained Linux adversarial preparation/containment report passes without fallback |
| `H6-WINDOWS-NATIVE` | retained Windows adversarial preparation/containment report passes without fallback |
| `H6-NO-AUTHORITY` | imports, vocabulary, and observations contain no Harness/Product security meaning |
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
