# Harness Resource Frontmatter Boundary

## Status

Status: accepted for `lane/harness`.

This document defines `loushang.harness.resources.frontmatter` as the owner of
product-neutral frontmatter parsing. Coding, method, and the legacy top-level
resource package consume that owner without duplicating parser behavior.

## Decision

Harness owns:

- `ParsedFrontmatter`
- `FrontmatterParseError`
- `parse_frontmatter`
- `strip_frontmatter`
- newline normalization, delimiter extraction, the supported YAML subset,
  scalar/list/map parsing, block scalar handling, and parse locations

The parser remains intentionally bounded. This migration preserves the current
YAML subset and error messages; it does not add a general YAML dependency or
expand accepted syntax.

## Canonical Imports

The Harness owner is the only Coding import path:

```python
from loushang.harness.resources.frontmatter import parse_frontmatter
from loushang.resource.frontmatter import parse_frontmatter
```

`loushang.resource.frontmatter` remains a legacy top-level resource path.
Coding does not provide a frontmatter import facade. Harness-owned classes
retain their harness `__module__`; the focused resources symbols are not added
to top-level `loushang.harness.__all__`.

## Internal Consumers

In-repository consumers import the owner directly:

```text
loushang.coding.resource_runtime -> loushang.harness.resources.loader -> loushang.harness.resources.frontmatter
loushang.method        -> loushang.harness.resources.frontmatter
```

`loushang.resource` remains only as an accepted compatibility package. New
shared resource behavior must not be added there.

## Non-Goals

This focused parser migration does not move or redesign:

- coding `SourceInfo` or extension source records
- resource diagnostics or diagnostics services
- prompt, skill, extension, or theme descriptors
- resource search roots, precedence, merge policy, or enablement in this change
- method resource semantics
- `AGENTS.md` discovery or prompt assembly behavior in this change

The later
[Platform Resource Layout Boundary](platform-resource-layout-boundary.md)
assigns platform roots, standard conventions, discovery, and precedence/merge
mechanisms to Harness while keeping activation and prompt projection in Product.

## Dependency Rules

`loushang.harness.resources.frontmatter` is self-contained and must not import
coding, method, work, TUI, AI, or provider packages. Coding and method may depend
on the harness owner; harness must not depend on either consumer.

## Validation

The migration must prove:

- existing parsing, newline, block scalar, collection, and error behavior is
  unchanged under the harness path;
- the legacy top-level resource path preserves object identity;
- Coding does not expose a frontmatter facade;
- coding and method internal imports use the harness owner;
- architecture import boundaries and top-level export discipline pass;
- coding loader and method resource suites remain green.
