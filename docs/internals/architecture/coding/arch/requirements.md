# Coding Arch Requirements

[Coding Arch Architecture](README.md)

## Status

- Authority: normative — proposed requirements reconstructed from Product needs
  and implemented contracts
- Design status: proposed
- Implementation status: partial
- Owner: Coding Product

## Functional Requirements

### COD-ARCH-FR-001: Deterministic source discovery

Arch must deterministically discover supported language modules below an
admitted source root, honor explicit exclusions, and avoid following source
symlinks outside the intended traversal.

### COD-ARCH-FR-002: Language-neutral normalized facts

Each language provider must return versioned module, dependency, diagnostic and
source-evidence values that graph projection can consume without
language-specific branching.

### COD-ARCH-FR-003: Import classification

The Python provider must distinguish eager, typing-only, deferred and lazy
export dependencies, retain import kind and re-export information, and resolve
relative module imports consistently.

### COD-ARCH-FR-004: Stable graph projection

Arch must project normalized facts at module or subsystem granularity, remove
collapsed internal edges, preserve package-prefix semantics and identify
external dependencies separately.

### COD-ARCH-FR-005: Bounded query surface

Arch must provide bounded summary, cycle, edge, path, hotspot and boundary-rule
queries. Results must not require returning an unbounded complete graph to a
model or CLI consumer.

### COD-ARCH-FR-006: Verifiable boundary rules

Consumers must be able to declare explicit deny rules and receive deterministic
violations with source evidence. CLI callers may choose a failing exit status
when violations exist.

### COD-ARCH-FR-007: Rebuildable versioned cache

Per-file normalized facts may be cached in memory or persisted atomically. The
cache must be versioned, fingerprinted, invalidated for changed/deleted/renamed
files, and safely rebuilt after corruption or incompatibility.

### COD-ARCH-FR-008: Independent CLI

Coding must expose deterministic JSON queries without requiring an Agent turn.
Cache telemetry remains opt-in and must not change deterministic query meaning.

### COD-ARCH-FR-009: Policy-governed model tool

The model-facing tool must constrain roots to the current Coding workspace,
bound request sizes, use Harness authorization/tool hosting, and honor Session
tool policy.

### COD-ARCH-FR-010: Optional Product activation

Coding must control Arch through its standard `disabled | on_demand | always`
Capability mount policy. `always` must not bypass explicit tool allowlists, and
Arch must remain independently selectable from Coding's builtin tool pack.

### COD-ARCH-FR-011: Provider extensibility

Additional language providers may be added behind the provider port without
changing the graph/query model. Provider identities must be non-empty and
unique within one analyzer.

### COD-ARCH-FR-012: Optional semantic enrichment

If a future use case requires LSP semantic facts, Arch must own a narrow
optional consumer protocol. `coding.lsp` may implement an adapter, but Arch must
continue to operate without it and neither scope may import the other's
internals.

## Quality Requirements

- Results for the same source snapshot and options are ordered and
  deterministic.
- Deep graphs do not depend on Python recursion depth for cycle queries.
- Evidence and query responses are bounded by explicit caller limits.
- Syntax errors become diagnostics rather than aborting the entire scan.
- Cache failure never changes graph correctness.
- Source reads and model-facing roots remain within accepted workspace and
  policy boundaries.
- Public fact/query schemas have explicit versions when persisted or exposed as
  stable data.

## Non-Goals

This scope does not:

- replace compilers, linters, tests or LSP semantic analysis;
- create a universal code knowledge graph or Ontology store;
- mutate repository files;
- infer Product architecture policy from observed imports;
- make every language or build system a first-wave provider;
- own Loushang-wide AOD or architecture documentation governance.

## Acceptance

The current core has executable evidence for provider normalization,
projection/query behavior, cache correctness, CLI boundaries, tool
authorization and Product activation. Accepting this proposed requirements set
as Target architecture is a separate review decision. New Target requirements
remain partial until linked evidence is added to the traceability matrix.
