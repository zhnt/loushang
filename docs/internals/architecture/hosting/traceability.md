# Loushang Hosting Traceability

## Status

- Scope: `hosting`
- Parent: `loushang`
- Authority: normative — proposed design traceability
- Design status: proposed
- Implementation status: not-started
- Owner: Loushang Hosting architecture

## Requirement Traceability

| Requirement | Primary design owner | Boundary/design evidence | Planned executable evidence |
| --- | --- | --- | --- |
| `HOST-FR-001` | `HOST-CMP-CONTRACT` | requirements; Contract Model interface | request validation and no-ambient-environment contract tests |
| `HOST-FR-002` | `HOST-CMP-PROCESS` | Process Lifetime Host; failure interaction | fake spawn lifecycle matrix and real process-tree conformance |
| `HOST-FR-003` | `HOST-CMP-ENDPOINT` | Inherited Peer Endpoint Host; physical context | POSIX/Windows handle allowlist, peer closure, and leak tests |
| `HOST-FR-004` | `HOST-CMP-SESSION` | Child Session Host; rollback interaction | fault injection at every acquisition/publication boundary |
| `HOST-FR-005` | `HOST-CMP-CONTRACT` | authority table; observation boundary | redaction and no-security-claim schema tests |
| `HOST-FR-006` | `HOST-CMP-PLATFORM` | explicit platform boundary | exact backend selection and unsupported-platform tests |
| `HOST-QR-001` | Process, Endpoint, Session | lifecycle invariants | repeated/concurrent close and cancellation tests |
| `HOST-QR-002` | Process, Endpoint | requirements and component interfaces | capacity/write/tail/buffer/shutdown bound tests |
| `HOST-QR-003` | Session, Platform Adapter | trust boundary | inherited-handle and effective-environment adversarial tests |
| `HOST-QR-004` | scope/composition root | [Hosting Top-Level Placement](../drafts/hosting-top-level-placement.md) and dependency view | top-level and internal import architecture gates |
| `HOST-QR-005` | all components | discovery/refinement | fake-backed component contracts plus real conformance markers |
| `HOST-QR-006` | `HOST-CMP-PLATFORM` | open validation questions | separate POSIX and Windows conformance manifests |

## Baseline Evidence

At design baseline, the only executable evidence is
`tests/architecture/test_hosting_architecture_baseline.py`. It proves that:

- the proposed documents and parent catalog entry exist;
- Current Harness source seams named by discovery still exist;
- the component set and forbidden dependency direction are explicit; and
- no `src/loushang/hosting` implementation appears before the baseline guard is
  deliberately revised.

It does not prove runtime behavior. Each implementation slice must replace the
relevant `missing` row with contract and platform evidence.

## Implementation Readiness Delta

| Gap | Classification | Closure condition |
| --- | --- | --- |
| top-level placement not accepted | `missing` | three-view review and accepted ARD/AOD updates |
| exact public types unspecified | `missing` | versioned contract specification before public export |
| POSIX endpoint choice unproven | `missing` | narrow real-host validation with handle-leak evidence |
| Windows endpoint/spawn path unproven | `missing` | narrow Windows validation with strict handle-list evidence |
| Harness mechanics not migrated | `missing` | compatibility slices preserve current Process Host contracts |
| Product/native Worker path absent | `missing` | separate PLC9C5 activation review and gates |

The design remains not-started until these gaps enter explicit delivery slices.
