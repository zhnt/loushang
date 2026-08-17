# Resource Provenance Migration Plan

## Goal

Move product-neutral source metadata and resource diagnostic records into
`loushang.harness.resources` without changing coding path representations,
public import paths, loader policy, or diagnostic behavior.

## Tasks

- [x] Add harness source-metadata behavior tests for string and `Path` values.
- [x] Add compatibility tests for coding source-info and extension imports.
- [x] Move `SourceInfo`, `SourceScope`, and `SourceOrigin` to harness resources.
- [x] Keep descriptor projection and executable identity in coding.
- [x] Add harness resource-diagnostic behavior tests.
- [x] Add compatibility tests for coding loader diagnostic imports.
- [x] Move resource diagnostics to Harness; this historical class was later
  replaced by the canonical `DiagnosticDraft` plus a resource factory.
- [x] Redirect coding internal consumers to the harness owners.
- [x] Add architecture ownership and documentation tests.
- [x] Update the harness architecture index and migration inventory.
- [x] Run focused resource, coding compatibility, and architecture tests.
- [x] Run Ruff, diff checks, and the full non-live test suite.

## Non-Goals

- Moving resource descriptors, source precedence, search roots, or merge policy.
- Moving executable installation or Git identity inspection.
- Moving coding diagnostics services, phases, queries, or UI behavior.
- Normalizing every source path to one representation.
- Adding resource symbols to top-level harness exports.
