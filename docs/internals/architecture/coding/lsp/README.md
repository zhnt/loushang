# Coding LSP Architecture

[Coding Architecture](../README.md)

## Status

- Scope: `coding.lsp`
- Parent: `coding`
- Authority: normative — proposed architecture with evidence-linked Current summary
- Design status: proposed
- Implementation status: partial
- Owner: Coding Product

This package defines the target `coding.lsp` Product capability. Individual
delivery slices may exist before the complete target is accepted. Current code
and executable tests remain authoritative for implemented behavior. Coding owns
placement, activation and sibling dependencies; this scope owns the LSP
black-box contract and internal component model.

## Architecture Method

The design follows the repository's
[Architecture Design And Governance Method](../../../architecture-method/README.md)
in this order:

```text
Requirements
  -> Placement and boundary
  -> System context
  -> Specification
  -> Candidate components
  -> Final component boundaries
  -> Traceability
```

Read the documents in that order:

1. [Requirements](requirements.md)
2. [Subsystem Placement And Boundary](subsystem.md)
3. [System Context](system-context.md)
4. [Specification](specification.md)
5. [Candidate Components](candidate-components.md)
6. [Final Component Boundaries](component-boundaries.md)
7. [Traceability](traceability.md)

`candidate-components.md` is design-working material. Once this scope is
accepted, `component-boundaries.md` is the canonical final component model and
the candidate inventory becomes historical rationale.

The adjacent [Harness Foundation](harness-foundation.md) design records the
rationale for the Product-neutral Process Hosting, authorization/sandbox-
lifetime, and session cleanup used by active LSP. The canonical accepted
Harness boundary is [Process Hosting](../../harness/process-hosting-boundary.md).
Its separate committed
workspace-mutation contract supports the later passive diagnostic loop; it is
not a prerequisite for active semantic queries. The design does not move LSP
protocol semantics into Harness.

## Decision Summary

The canonical Product capability id is `coding.lsp`, not `code.lsp`, because
the owning Product package is `loushang.coding` and the established sibling id
is `coding.arch`.

`coding.lsp` is a mountable Capability ID, not a live Mount instance. A
target P0 binding creates a Session-scoped Mounted Capability such as
`coding.lsp@session:<session-id>` according to Coding's
`disabled | on_demand | always` Mount Policy. Workspace identity remains an
explicit binding input and signature component; P0 does not pool a live LSP
runtime across Sessions. Its supervisor, clients, documents, diagnostics,
queries, and Tool family remain internal Capability Bundle facets rather than
top-level Capability nodes. The canonical terminology and graph rules are
defined by
[Capability Dependency And Mount Lifecycle](../../harness/capability-dependency-and-mount-lifecycle.md).

`coding.lsp` is:

- a `coding.lsp` Capability Bundle owned by the Coding Product;
- language-extensible through declarative Server definitions;
- independent of VS Code, Cursor, or another editor;
- backed by separately installed language-server executables;
- model-facing through bounded, structured code-intelligence tools;
- Session-scoped at first, with workspace identity in its binding inputs and
  language-server processes started lazily and retained until crash, explicit
  stop, or Session close in P0;
- capable of both active semantic queries and passive diagnostic feedback;
- optional and governed by the existing `disabled | on_demand | always`
  Product capability mount policy.

It is not:

- a new top-level Loushang subsystem;
- part of `loushang.agent` or `loushang.ai`;
- a Method or Work runtime;
- a replacement for `coding.arch`, compilers, linters, or tests;
- permission to download or execute an arbitrary language server.

## Reference Synthesis

The target combines two reference lessons:

```text
CC lesson
  Product-native feedback loop:
  semantic query -> edit sync -> diagnostics -> next-turn repair

Codex lesson
  Optional capability packaging:
  core remains small; specialized capability is discovered and activated
  only when relevant, and a warm helper process can be reused.
```

Loushang adds its own boundary model:

```text
Coding Product
  owns capability identity, defaults, server admission, tools, diagnostics,
  prompt guidance, configuration, and presentation

Harness
  owns product-neutral tool composition, policy/approval enforcement,
  workspace mutation mechanics, lifecycle/disposal, and context budgets

Extension or package
  may contribute declarations, but cannot grant itself execution authority
```

At the accepted target top-level Capability-plan granularity, the required
dependency is:

```text
coding.lsp -> harness.workspace
```

The dependency requests only admitted workspace read and authorized
process-launch facets. It does not expose Harness authorization, Sandbox,
process Host, or cleanup internals and does not turn those facets into more DAG
nodes.

The references are used deliberately, not copied wholesale:

| Concern | CC reference | Codex reference | Loushang decision |
| --- | --- | --- | --- |
| Product loop | Native semantic tools plus edit-to-diagnostic feedback | Mainline has no equivalent Product LSP loop | Adopt the complete loop as a Coding capability |
| Packaging | Product-integrated runtime and plugin Server declarations | Experimental Skill/daemon demonstrates optional, warm capability packaging | Use `coding.lsp` plus a separate `coding.lsp.tools` family |
| Lifecycle | Lazy external Server processes | A task-specific warm helper can survive repeated calls | Keep processes warm only inside a session/workspace owner |
| Safety | Trust and file filtering around Server use | Narrow task surface | Product admission precedes launch; no implicit installation |
| Extensibility | Language definitions supplied by plugins | Skill-specific adapter | Normalize declarative definitions through Coding, not Harness |

CC is the behavioral feedback-loop reference. The observed Codex LSP work is
experimental capability packaging rather than an accepted generic Codex LSP
subsystem, so this design does not attribute Product runtime guarantees to it.

## Target Shape

```text
Coding config / CLI / package / extension
                |
                v
      coding.lsp Mounted Capability
        catalog + admission + selector
                |
                v
      workspace-scoped LSP runtime
       supervisor + client + documents
          |                    |
          v                    v
 active semantic tools    diagnostic inbox
          |                    |
          +--------+-----------+
                   v
             Agent context
```

Tool activation and process startup are deliberately separate:

- `on_demand` or `always` controls whether tool definitions are available or
  active in the Coding session;
- the selected language-server process still starts only on first relevant
  use; workspace warm-up is a deferred Product policy.

## Relationship To `coding.arch`

`coding.arch` owns deterministic project-structure facts such as import graphs,
cycles, hotspots, and architecture boundaries. `coding.lsp` owns online
language-semantic facts such as definitions, references, types, implementations,
call hierarchy, and diagnostics.

Future integration may let `coding.arch` consume an optional semantic-fact
facet. If accepted, the Product plan may declare
`coding.arch -> coding.lsp` as an optional dependency, but the initial accepted
target graph has no such edge. The deterministic analyzer and CI gates must
continue to work without an LSP Server.

## Implementation Status Rule

Implementation progress belongs in a dated plan or issue, not in these live
architecture documents. When implementation changes an accepted boundary,
update this package and the affected canonical Coding/Harness architecture note
in the same integration change.
