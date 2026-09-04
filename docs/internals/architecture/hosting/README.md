# Loushang Hosting Architecture

## Status

- Scope: `hosting`
- Parent: `loushang`
- Authority: normative — accepted top-level Architecture Scope
- Design status: accepted
- Implementation status: partial
- Owner: Loushang Hosting architecture

## Scope

Hosting is the Product-neutral substrate for owning bounded local
child execution. It creates and owns local processes, inherited peer byte
endpoints,
and the atomic lifetime that joins them into one child session.

Hosting is a scope rather than a synonym for a package directory because it
owns OS-facing lifecycle, identity, resource, portability, cancellation, and
failure semantics. Its placement is accepted by
[ARD-002: Hosting Top-Level Placement](../decisions/ARD-002-hosting-top-level-placement.md).

## Current

H0 implements the standard-library-only `loushang.hosting` Contract Model:
immutable launch/session requests, raw results, stable mechanism failures,
bounded observations, and required/provided port protocols. It performs no OS
operations and has no current consumer.

Current process mechanics remain implemented inside Harness, principally by:

- `src/loushang/harness/workspace/process/`;
- `src/loushang/harness/tools/process_hosting.py`;
- `src/loushang/harness/sandbox/process.py`;
- `src/loushang/harness/worker/`.

Those paths remain authoritative Current facts. The existing
[Harness Process Hosting Boundary](../harness/process-hosting-boundary.md) and
[PLC9C Local Worker Boundary](../harness/plugin/plugin-lifecycle-plc9c0-baseline.md)
remain authoritative for the implemented Harness behavior.

## Target

The accepted Target implements `loushang.hosting` inside the existing
`loushang` distribution. H0 establishes the contract package; later slices let
Harness consume Hosting through narrow owner adapters. Hosting does not import
Harness and does not acquire Harness authority merely because it performs the
final OS operation.

Target dependency direction:

```text
Product composition
  -> Harness policy / approval / authorization / sandbox / Worker semantics
       -> loushang.hosting process and child-session ports
            -> local operating system

loushang.harness -> loushang.hosting     # accepted Target; not yet Current
loushang.hosting -> loushang.harness     # forbidden
```

Moving the code, publishing a separate distribution, and activating a native
Worker route are distinct decisions. This proposal makes none of them Current.

## Owns

- shell-free local process creation and one-owner process lifetime;
- bounded process capacity, stdio mechanics, exit settlement, termination,
  kill fallback, and process-tree reclamation;
- inherited native peer-endpoint creation and exact parent/child handle
  ownership;
- atomic process-plus-endpoint child-session creation and rollback;
- platform-backend selection and explicit unsupported-platform failure;
- neutral observations about resources Hosting actually created and closed.

## Does Not Own

- Product or Plugin selection, trust, admission, installation, or activation;
- Policy, Approval, Authorization, credentials, Sandbox policy, or claims that
  a launch is safe;
- Worker framing, handshake, heartbeat, request correlation, restart, durable
  attempt journals, or domain generation publication;
- tool semantics, LSP semantics, Capability graphs, registries, or management
  read models;
- remote execution, scheduling, daemon discovery, live process adoption, or
  surviving-process reattachment;
- AppServer listener selection, accept loops, transport authentication,
  connection routing, or slow-client policy;
- durable Session state, log retention, trace storage, clipboard, images, or
  Product artifact meaning.

## Direct Actors And Neighboring Scopes

| Actor or scope | Relationship to Hosting |
| --- | --- |
| Harness composition root | initial trusted consumer; supplies admitted requests and owns the security/domain interpretation |
| Harness Sandbox adapter | implements the required preparation/cleanup port; Hosting treats it as mechanism, not proof of safety |
| Harness Worker supervisor | receives a child-session lease and byte transport; retains protocol and restart ownership |
| Cross-Product AppHost | its controller-side launcher may request exact hosting of the complete foreground AppHost executable; target-process composition and application meaning remain outside Hosting |
| Local operating system | creates processes, descriptors/handles, endpoint pairs, exit status, and termination effects |
| Future trusted host scopes | may consume the same ports only after a real use case and parent-level dependency review |
| Plugin author SDK / Worker child | never receives a Hosting owner, raw process host, or endpoint factory |

## Direct Child Components

| ID | Component | Owns |
| --- | --- | --- |
| `HOST-CMP-CONTRACT` | Hosting Contract Model | immutable requests, leases, observations, stable failure categories, and required-port shapes |
| `HOST-CMP-PROCESS` | Process Lifetime Host | process capacity, spawn attachment, stdio, exit convergence, termination, and reclamation |
| `HOST-CMP-ENDPOINT` | Inherited Peer Endpoint Host | parent/child endpoint pairs, handle allowlisting/transfer, byte transport, and endpoint cleanup |
| `HOST-CMP-SESSION` | Child Session Host | the atomic process-plus-endpoint transaction and joint lifetime |
| `HOST-CMP-PLATFORM` | Platform Adapter Set | exact POSIX and Windows mechanics and fail-closed platform selection |

The detailed responsibilities and allowed edges are in
[Component Model](component-model.md). Candidate discovery and refinement are
retained separately as validation evidence rather than treated as the final
model.

## Core Invariants

1. A process, PID, descriptor, address, handshake, or log line never becomes
   Policy, Approval, Sandbox, Plugin, or domain authority.
2. Each OS resource has exactly one live owner and one idempotent close path.
3. Child-session publication is atomic: the caller receives both a running
   process lease and the host endpoint, or receives neither.
4. Only the child endpoint is inheritable, only for the intended spawn; the
   parent endpoint and ambient handles are not inherited.
5. Cancellation never abandons an in-flight spawn, endpoint, process tree, or
   external preparation cleanup.
6. PID alone is never durable identity; v1 does not reattach to a surviving
   process.
7. Native byte transport carries bytes only. Framing and domain meaning remain
   above Hosting.
8. Unsupported or unproven platform behavior fails closed; there is no silent
   TCP, stdio, filesystem-rendezvous, or uncontained fallback.
9. Hosting chooses no user-home, workspace, log, or durable-state root. Any
   unavoidable temporary artifact is caller-rooted, owner-private,
   lease-bound, and removed during cleanup.
10. Hosting observations report only Hosting facts and never synthesize
    security or business evidence owned by a caller.

## Vocabulary And Inherited Principles

- Inherits the [Loushang Architecture Principles](../loushang-architecture-principles.md),
  especially stable substrate, structural security, explicit authority, and
  verification/traceability.
- **Process lease**: the exclusive lifetime capability for one Hosting-owned
  child process; it is not a durable identity or authority grant.
- **Inherited peer endpoint**: a host/child local byte channel transferred only
  to the intended child without service discovery or stdout address
  negotiation. It is not an AppServer listener.
- **Child session**: the atomic Hosting-owned aggregate of one process lease
  and one inherited host peer endpoint. It is not a Harness Session or Worker protocol
  session.
- **Preparation lease**: caller-supplied exact spawn material, final validation,
  and cleanup. Hosting does not reinterpret it as authorization or containment
  proof.

## Composition, Interaction And Dependency

- [System Context](system-context.md) defines logical and physical boundaries,
  trust flows, provided ports, and required ports.
- [Component Discovery](validation/component-discovery.md) records candidate
  functions, reference inputs, function mapping, and `split / merge / keep`.
- [Component Model](component-model.md) defines final components, composition,
  main interactions, and intended/forbidden dependencies.
- [Hosted Application Support Boundary](key-designs/hosted-application-support-boundary.md)
  defines how embedded, foreground, sidecar, and daemon profiles relate to
  Hosting without moving AppService into this scope.
- [Traceability](traceability.md) maps requirements to design and future gates.

## Architecture Reading Order

1. this scope overview;
2. [Requirements](requirements.md);
3. [System Context](system-context.md);
4. [Component Discovery](validation/component-discovery.md);
5. [Component Model](component-model.md);
6. [H0 Contract Model](contract-model-h0.md);
7. [Hosted Application Support Boundary](key-designs/hosted-application-support-boundary.md);
8. [ARD-002: Hosting Top-Level Placement](../decisions/ARD-002-hosting-top-level-placement.md);
9. [Traceability](traceability.md);
10. current source, tests, and generated package facts.

## Current-To-Target Gaps

- `partial`: `loushang.hosting` and `HOST-CMP-CONTRACT` are implemented by H0;
  the four resource/platform components remain missing.
- `deviated`: reusable process mechanics currently reside under Harness rather
  than the accepted neutral owner; their Current
  Harness contracts remain valid until migration.
- `missing`: POSIX and Windows inherited peer-endpoint feasibility evidence.
- `missing`: compatibility facades and a behavior-preserving migration plan.
- `implemented`: H0 standard-library-only and no-authority public-surface gates.
- `missing`: a reviewed Product/native Worker activation route; PLC9C5 remains
  separate from Hosting extraction.
- `missing`: daemon/service-instance lifecycle remains a trigger-gated future
  candidate and is not part of the five-component v1 baseline.

## Change Triggers And Evidence

- H0 intentionally replaces the implementation-absence guard with contract and
  dependency gates in `tests/architecture/test_hosting_h0_contract.py` and
  `tests/architecture/test_hosting_architecture_baseline.py`.
- Top-level placement acceptance is recorded by ARD-002 and reflected in the
  AOD, subsystem map, governance profile, generated facts, and cross-scope
  decision catalog.
- Any public contract requires specification and contract tests before it is
  called stable.
- Source migration must retain the Harness behavior and default-dark Worker
  gates until a separately reviewed activation slice changes them.
