# Loushang Hosting Traceability

## Status

- Scope: `hosting`
- Parent: `loushang`
- Authority: normative — accepted design traceability
- Design status: accepted
- Implementation status: partial
- Owner: Loushang Hosting architecture

## Requirement Traceability

| Requirement | Primary design owner | Boundary/design evidence | Executable evidence / remaining gate |
| --- | --- | --- | --- |
| `HOST-FR-001` | `HOST-CMP-CONTRACT` | requirements; H0 Contract Model | H0 request validation and no-ambient-environment contract tests |
| `HOST-FR-002` | `HOST-CMP-PROCESS` | Process Lifetime Host; failure interaction | H1 fake lifecycle matrix and H2 real process-tree conformance |
| `HOST-FR-003` | `HOST-CMP-ENDPOINT` | Inherited Peer Endpoint Host; physical context | POSIX/Windows handle allowlist, peer closure, and leak tests |
| `HOST-FR-004` | `HOST-CMP-SESSION` | Child Session Host; H4 atomic transaction | H4 failure matrix at every acquisition/publication boundary |
| `HOST-FR-005` | `HOST-CMP-CONTRACT` | authority table; H0 observation boundary | H0 closed-schema, bounded-ID, and no-security-claim tests |
| `HOST-FR-006` | `HOST-CMP-PLATFORM` | explicit platform boundary | H2 exact backend selection, atomic ownership, and unsupported-platform tests |
| `HOST-QR-001` | Process, Endpoint, Session | lifecycle invariants | H1/H3 owner tests plus H4 joint close, cancellation, and cleanup-debt cases |
| `HOST-QR-002` | Process, Endpoint, Session | requirements and component interfaces | H1/H3 resource bounds plus H4 aggregate capacity and factory-bound validation |
| `HOST-QR-003` | Session, Platform Adapter | trust boundary | inherited-handle and effective-environment adversarial tests |
| `HOST-QR-004` | scope/composition root | [ARD-002: Hosting Top-Level Placement](../decisions/ARD-002-hosting-top-level-placement.md) and dependency view | H0 top-level standard-library-only and public-surface gates |
| `HOST-QR-005` | all components | discovery/refinement | H1 fake process/clock/failure seams; later real conformance remains |
| `HOST-QR-006` | `HOST-CMP-PLATFORM` | open validation questions | separate POSIX and Windows conformance manifests |

## H0 Evidence

The design baseline plus H0 executable evidence prove that:

- the accepted Hosting documents, ARD, and parent catalog entry exist;
- Current Harness source seams named by discovery still exist;
- the component set and forbidden dependency direction are explicit; and
- the H0 public modules contain only the Contract Model and stable failures;
- materialized requests reject shell, relative-path, ambient-environment, NUL,
  and ambiguous environment shapes;
- observations have a closed bounded schema without arbitrary payload; and
- Hosting has only standard-library dependencies and exposes no raw platform or
  caller-authority types.

H0 alone does not prove runtime behavior.

## H1 Evidence

H1 now proves the platform-neutral part of `HOST-CMP-PROCESS`:

- capacity is reserved before preparation and covers pending plus live owners;
- preparation verification is immediately before the private spawn seam and
  preparation cleanup remains in the same ownership transaction;
- natural exit, terminate, close, cancellation, early exit, and host fencing
  converge without publishing or retaining an unowned fake process;
- termination requests tree termination, waits through a fakeable bounded
  timeout, then kills and reaps before process-handle cleanup;
- concurrent close callers share one shielded owner operation;
- reads, writes, stderr tails, process capacity, termination grace, and stderr
  drain are fixed by immutable limits;
- cleanup faults are aggregated while later reachable operations continue; and
- observations remain bounded and cannot influence ownership.

H1 deliberately proves no OS process-tree behavior. That delta remains H2.

## Implementation Readiness Delta

| Gap | Classification | Closure condition |
| --- | --- | --- |
| top-level placement and dependency direction | `implemented` | ARD-002, parent architecture updates, and H0 import gate remain green |
| exact H0 public contract | `implemented` | versioned contract specification and behavior tests remain green |
| platform-neutral Process Lifetime Host | `implemented` | H1 fake lifecycle, cancellation, bound, fault, and architecture tests remain green |
| exact process-platform contract | `implemented` | H2a platform manifest and fail-closed architecture gate remain green |
| POSIX process-tree adapter | `implemented` | real group/session termination, kill, root/tree settlement, and descriptor-close conformance remain green |
| POSIX inherited endpoint | `implemented` | real socketpair/stdin-stdout round trip and host-descriptor leak evidence remain green |
| Windows inherited endpoint | `implemented` | fake lifecycle/allowlist tests and native Windows round trip remain green |
| Windows process spawn path | `implemented` | native Windows CI keeps atomic Job Object and strict handle-list evidence non-skipped |
| atomic Child Session Host | `implemented` | H4 transaction order, failure/cancellation matrix, joint lifetime, observation correlation, and native factory round trip remain green |
| Harness mechanics migration | `partial` | H2c dark adapter parity remains green; sealed-descriptor cases stay on Current owner until a later contract is accepted |
| default-dark Harness Worker adapter | `implemented` | H5 aggregate mapping, Supervisor session integration, selection, no-fallback, diagnostics, and rollback gates remain green |
| Hosting-consumable managed preparation | `partial` | H6.1 ownership and H6.2 private Linux x86_64 static-closure native evidence are implemented; H6.3 Windows evidence and H6.4 Harness parity remain |
| Product/native Worker path absent | `missing` | separate PLC9C5 activation review and gates |

The mechanism baseline is implemented through H4: contracts, process owner,
endpoint owner, exact platform sets, atomic child sessions, and the dark
Harness compatibility slice, and the H5 default-dark Worker aggregate adapter.
Overall migration remains partial because no production Worker owner has
switched to Hosting and the Current sealed-executable preparation cannot yet be
consumed by Hosting. The accepted, partially implemented
[H6 Managed Launch Preparation](managed-launch-preparation-h6.md), its
[H6.1 feasibility record](validation/managed-launch-preparation-h6-feasibility.md), and the
[source-backed Current inventory](validation/hosted-product-runtime-v1-inventory.md)
define the next closure gates without changing those Current facts.
