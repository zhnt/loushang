# Loushang Hosting Traceability

## Status

- Scope: `hosting`
- Parent: `loushang`
- Authority: normative — accepted design traceability
- Design status: accepted
- Implementation status: partial
- Owner: Loushang Hosting architecture

## Requirement Traceability

| Requirement | Primary design owner | Boundary/design evidence | Planned executable evidence |
| --- | --- | --- | --- |
| `HOST-FR-001` | `HOST-CMP-CONTRACT` | requirements; H0 Contract Model | H0 request validation and no-ambient-environment contract tests |
| `HOST-FR-002` | `HOST-CMP-PROCESS` | Process Lifetime Host; failure interaction | fake spawn lifecycle matrix and real process-tree conformance |
| `HOST-FR-003` | `HOST-CMP-ENDPOINT` | Inherited Peer Endpoint Host; physical context | POSIX/Windows handle allowlist, peer closure, and leak tests |
| `HOST-FR-004` | `HOST-CMP-SESSION` | Child Session Host; rollback interaction | fault injection at every acquisition/publication boundary |
| `HOST-FR-005` | `HOST-CMP-CONTRACT` | authority table; H0 observation boundary | H0 closed-schema, bounded-ID, and no-security-claim tests |
| `HOST-FR-006` | `HOST-CMP-PLATFORM` | explicit platform boundary | exact backend selection and unsupported-platform tests |
| `HOST-QR-001` | Process, Endpoint, Session | lifecycle invariants | repeated/concurrent close and cancellation tests |
| `HOST-QR-002` | Process, Endpoint | requirements and component interfaces | capacity/write/tail/buffer/shutdown bound tests |
| `HOST-QR-003` | Session, Platform Adapter | trust boundary | inherited-handle and effective-environment adversarial tests |
| `HOST-QR-004` | scope/composition root | [ARD-002: Hosting Top-Level Placement](../decisions/ARD-002-hosting-top-level-placement.md) and dependency view | H0 top-level standard-library-only and public-surface gates |
| `HOST-QR-005` | all components | discovery/refinement | fake-backed component contracts plus real conformance markers |
| `HOST-QR-006` | `HOST-CMP-PLATFORM` | open validation questions | separate POSIX and Windows conformance manifests |

## H0 Evidence

The design baseline plus H0 executable evidence prove that:

- the accepted Hosting documents, ARD, and parent catalog entry exist;
- Current Harness source seams named by discovery still exist;
- the component set and forbidden dependency direction are explicit; and
- `src/loushang/hosting` contains only the Contract Model and stable failures;
- materialized requests reject shell, relative-path, ambient-environment, NUL,
  and ambiguous environment shapes;
- observations have a closed bounded schema without arbitrary payload; and
- Hosting has only standard-library dependencies and exposes no raw platform or
  caller-authority types.

H0 does not prove runtime behavior. Each later implementation slice must
replace the relevant `missing` row with lifecycle and platform evidence.

## Implementation Readiness Delta

| Gap | Classification | Closure condition |
| --- | --- | --- |
| top-level placement and dependency direction | `implemented` | ARD-002, parent architecture updates, and H0 import gate remain green |
| exact H0 public contract | `implemented` | versioned contract specification and behavior tests remain green |
| POSIX endpoint choice unproven | `missing` | narrow real-host validation with handle-leak evidence |
| Windows endpoint/spawn path unproven | `missing` | narrow Windows validation with strict handle-list evidence |
| Harness mechanics not migrated | `missing` | compatibility slices preserve current Process Host contracts |
| Product/native Worker path absent | `missing` | separate PLC9C5 activation review and gates |

The implementation is partial: H0 is complete while every runtime gap remains
an explicit later delivery slice.
