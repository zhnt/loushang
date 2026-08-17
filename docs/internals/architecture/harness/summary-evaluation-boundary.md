# Summary Evaluation Boundary

## Status

Implemented in the `harness/summary-evaluation-core` migration wave.

## Purpose

`loushang.harness.context` provides a profile-driven evaluator for structured
summaries. It validates a summary's declared structure and captures resource
evidence without assuming that the summary belongs to Coding, Research, PPT,
Design, or any other Product.

## Harness Ownership

Harness owns:

- `SummaryResourceOperationTag`, which maps a Product-selected XML-style block
  tag to a neutral operation name;
- the standard `read-files -> read` and `modified-files -> modified` mappings;
- `SummaryResourceOperation` and `SummaryResourceOperations` evidence values;
- extraction, required-phrase checks, structural validation, suite aggregation,
  and JSON fixture loading;
- per-case profile resolution for a fixture.

The standard mappings are defaults, not Coding fields. A Product may select
none of them or declare its own operations such as `cited`, `created`, or
`reviewed` with its own tags.

`SummaryProfile.resource_operation_tags` is the composition point. Its tags
are also ignored while checking Markdown section structure, so resource lists
cannot accidentally become summary headings.

## Product Ownership

Products retain:

- prompt text, summary modes, required sections, placeholder policy, and
  selected `SummaryProfile` values;
- production summary serialization and any artifact `details` schema;
- product fixtures and a narrow convenience entrypoint that binds its profile
  registry;
- product-specific semantic checks not expressible as generic resource
  operations.

For example, Coding binds its compaction and branch profiles in
`coding.compaction.evaluation`; it does not own the evaluator or special
`expected_read_files` / `expected_modified_files` fields.

## Contracts And Failure Semantics

- A fixture case supplies a `profile_id`, either on the case or as the fixture
  default. The evaluator resolves every case independently.
- An unknown or absent profile is a clear `ValueError`; no case silently falls
  back to a Product default.
- Unknown resource operation names are valid data. Extraction is driven only by
  the selected profile's declared tags.
- Evaluation is observational. It does not modify summaries, transcripts,
  Product stores, or runtime state.

Harness context remains Product-neutral and does not import Coding or another
Product to evaluate a summary.
