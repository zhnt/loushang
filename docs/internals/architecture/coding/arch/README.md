# Coding Arch Architecture

[Coding Architecture](../README.md)

## Status

- Scope: `coding.arch`
- Parent: `coding`
- Authority: normative — proposed boundary with evidence-linked Current summary
- Design status: proposed
- Implementation status: partial
- Owner: Coding Product

## Scope

`coding.arch` is Coding's deterministic repository architecture-analysis
Product Capability. It discovers language source modules, normalizes import
facts with evidence, projects bounded graphs, evaluates architecture queries
and boundary rules, and exposes those operations through a CLI and an optional
model-facing tool pack.

It is a nested Architecture Scope because it has a stable Capability identity,
its own language-provider boundary, rebuildable cache, query contract,
activation/security rules, component model, CLI/tool surfaces, and independent
tests. It is not a top-level Loushang subsystem.

## Current

The implemented core includes:

- immutable language-neutral fact, graph, diagnostic and rule values;
- a replaceable `ImportGraphProvider` port and Python provider;
- deterministic module/subsystem projection and bounded queries;
- a versioned rebuildable per-file fact cache with optional atomic persistence;
- JSON CLI queries and boundary-gate exit behavior;
- a workspace-contained, policy-governed `inspect_import_graph` tool;
- independent `disabled | on_demand | always` Product Capability activation.

Current implementation evidence is under `tests/coding/arch/`.

## Target

The proposed direction is a Coding-owned, language-extensible architecture fact
and query capability. New language providers normalize facts into the stable
Arch model rather than teaching graph queries each language.

Future semantic enrichment from `coding.lsp` is optional. Arch remains usable
without a language server and owns the narrow consumer protocol if that
dependency is accepted. Arch does not take ownership of language-server
processes or LSP wire semantics.

## Scope Boundary

Arch owns:

- deterministic repository architecture facts and graph projections;
- provider normalization contracts;
- import classification and source evidence;
- bounded queries and boundary-rule evaluation;
- rebuildable cache schema and invalidation semantics;
- Coding-specific CLI, tool and Capability pack surfaces.

Arch does not own:

- compiler, linter or test-runner results;
- language-server lifecycle or LSP protocol;
- arbitrary code execution or workspace mutation;
- Harness policy, authorization or tool-hosting mechanics;
- system-wide architecture governance truth;
- Ontology or Work authority.

## Core Invariants

1. Query results are deterministic for the same source snapshot and options.
2. Every internal dependency fact retains bounded source evidence.
3. Cache data is versioned and rebuildable; corruption degrades to rescan rather
   than becoming architecture authority.
4. Model-facing roots remain inside the admitted Coding workspace.
5. Capability activation cannot bypass the Session tool allowlist or policy.
6. Provider replacement does not change the language-neutral graph/query
   contract.
7. LSP enrichment remains optional and cannot make Arch unavailable without an
   active language server.

## Architecture Documents

Read in this order:

1. this scope overview and boundary;
2. [Requirements](requirements.md);
3. [System Context](system-context.md);
4. [Component Model](component-model.md);
5. [Traceability](traceability.md);
6. source and `tests/coding/arch/` for executable Current behavior.

## Current-To-Target Gaps

- this architecture package is newly formalized from an already implemented
  slice and remains proposed until reviewed as the canonical Target;
- non-Python provider demand has not yet demonstrated another concrete
  provider;
- the optional `coding.arch -> coding.lsp` semantic-fact port is not part of the
  initial Current graph;
- architectural fact persistence remains a rebuildable cache, not a durable
  cross-run knowledge or Ontology store.
