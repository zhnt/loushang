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
| `HOST-FR-002` | `HOST-CMP-PROCESS` | Process Lifetime Host; failure interaction | H1 fake lifecycle matrix; H2 real process-tree conformance |
| `HOST-FR-003` | `HOST-CMP-ENDPOINT` | Inherited Peer Endpoint Host; physical context | POSIX/Windows handle allowlist, peer closure, and leak tests |
| `HOST-FR-004` | `HOST-CMP-SESSION` | Child Session Host; rollback interaction | fault injection at every acquisition/publication boundary |
| `HOST-FR-005` | `HOST-CMP-CONTRACT` | authority table; H0 observation boundary | H0 closed-schema, bounded-ID, and no-security-claim tests |
| `HOST-FR-006` | `HOST-CMP-PLATFORM` | explicit platform boundary | exact backend selection and unsupported-platform tests |
| `HOST-QR-001` | Process, Endpoint, Session | lifecycle invariants | H1 process close/cancellation tests; H3-H4 endpoint/session cases remain |
| `HOST-QR-002` | Process, Endpoint | requirements and component interfaces | H1 process capacity/write/tail/shutdown bounds; H3 endpoint buffers remain |
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
| POSIX process-tree adapter | `missing` | real group/session termination, kill, reap, and descriptor-close conformance |
| POSIX endpoint choice unproven | `missing` | narrow real-host validation with handle-leak evidence |
| Windows endpoint/spawn path unproven | `missing` | narrow Windows validation with strict handle-list evidence |
| Harness mechanics not migrated | `missing` | compatibility slices preserve current Process Host contracts |
| Product/native Worker path absent | `missing` | separate PLC9C5 activation review and gates |

The implementation is partial: H0 and the H1 platform-neutral process core are
complete; real platform adapters, Harness compatibility, endpoints, and atomic
child sessions remain explicit later delivery slices.
