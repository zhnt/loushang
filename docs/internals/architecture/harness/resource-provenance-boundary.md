# Harness Resource Provenance Boundary

## Status

Status: accepted for `lane/harness`.

This document defines product-neutral resource source metadata and resource
diagnostic records as `loushang.harness.resources` responsibilities. Coding
keeps resource discovery policy, executable installation diagnostics, and
product-facing diagnostic behavior.

## Decision

Harness owns one focused provenance record and one resource diagnostic factory:

- `loushang.harness.resources.source` owns `SourceInfo`, `SourceScope`, and
  `SourceOrigin`.
- `loushang.harness.resources.diagnostics` owns `resource_diagnostic`.

`SourceInfo` is generic over its path representation. Harness preserves the
path and base-directory values supplied by an adapter rather than choosing a
filesystem or serialization representation. Coding command surfaces may use
`SourceInfo[str]`, while extension runtime surfaces may use
`SourceInfo[pathlib.Path]`. These are the same harness-owned classes regardless
of the product-facing path representation.

`resource_diagnostic` maps a code, message, optional source path, resource
identity, opaque source-kind string, and neutral metadata into the `details`
of a `loushang.harness.diagnostics.types.DiagnosticDraft`. Harness does not
define coding resource kinds, resource-check phase/source assignment,
remediation text, or display policy.

## Compatibility

The factory and source records are imported from their focused Harness owners:

```python
from loushang.harness.resources.source import SourceInfo
from loushang.harness.resources.diagnostics import resource_diagnostic
```

`resource_diagnostic(...)` returns the canonical `DiagnosticDraft`; resources
does not define or re-export a second diagnostic class. Deleted Coding resource
facades do not preserve an alternate import path.

The former `loushang.coding.source_info` adapter is removed. Descriptor
projection remains in `harness.resources.source`; executable, package,
environment, and Git identity live in
`loushang.foundation.observability.identity`.
Coding supplies only package/module aliases and a display title through
`coding.diagnostics.profile`.

## Outside This Focused Migration

This provenance migration does not move or redesign:

- `ResourceSourceKind` or `ResourceSourceScope`;
- prompt, skill, theme, or extension descriptors;
- search roots, source precedence, merge decisions, or conflict policy in this
  change;
- product-specific runtime-identity labels;
- resource check selection, phase/source assignment, or emission timing;
- product remediation messages, UI projection, or session recording policy.

The later
[Platform Resource Layout Boundary](platform-resource-layout-boundary.md)
assigns platform roots, standard scopes/precedence, descriptors, discovery,
merging, and package mechanisms to Harness. Product-specific content,
activation, trust, projection, and remediation remain outside Harness.

General diagnostic vocabulary, records, queries, aggregation, and fingerprints
are owned by `loushang.harness.diagnostics`. Resource-specific check selection
and emission policy remain in Coding.

## Dependency Direction

The target direction is:

```text
coding loaders / extensions / commands / sessions
  -> loushang.harness.resources.source
coding loaders / extensions / commands / sessions
  -> loushang.harness.diagnostics.types
loushang.harness.resources.diagnostics
  -> loushang.harness.diagnostics.types
```

The resource modules must not import coding, method, work, TUI, AI, provider,
or product packages. The diagnostics core must not import resources. No
provenance or diagnostic symbols are added to top-level
`loushang.harness.__all__`.

## Validation

The migration must prove:

- string and `Path` source representations are preserved without coercion;
- coding source-info and extension paths share the harness class identity;
- resource diagnostic factories return the canonical `DiagnosticDraft`;
- resource identity, source kind, metadata, and normalization precedence are
  preserved inside draft details;
- diagnostics core modules do not import resources;
- existing descriptor projection and executable identity behavior is unchanged;
- coding internal consumers import the focused harness owners;
- harness import boundaries and top-level export discipline still pass.
