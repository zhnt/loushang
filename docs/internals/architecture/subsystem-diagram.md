# Loushang Architecture Scope Diagrams

## Status

- Authority: descriptive — Current semantic scope and dependency-policy projections
- Design status: accepted
- Implementation status: partial
- Owner: Loushang architecture

## Reading Rule

This document shows ownership and major semantic relationships. It does not
duplicate the exact physical Python import graph. For observed imports, use the
generated
[Current Package Dependencies](generated/current-package-dependencies.md).

Every diagram states its view and state. `A --> B` has only the meaning written
on that edge; composition, runtime interaction and import dependency are not
interchangeable.

## Current Semantic Runtime And Composition View

```mermaid
flowchart TD
    CODING["loushang.coding\nProduct composition"]
    HARNESS["loushang.harness\nexecution governance"]
    AGENT["loushang.agent\nmodel-tool loop"]
    AI["loushang.ai\nproviders and streaming"]
    HTUI["loushang.harnesstui\nconversation UI composition"]
    TUI["loushang.tui\nterminal substrate"]
    HWORK["loushang.harnesswork\ndurable Work facts"]
    WORK["loushang.work\ncompatibility/integration"]
    METHOD["loushang.method\nwork contract and plans"]
    CHANNEL["loushang.channel\nboundary values and delivery"]
    ONTOLOGY["loushang.ontology\nsemantic facts and projections"]
    FOUNDATION["loushang.foundation\nstrict values and observability"]
    HOSTING["loushang.hosting\ndefault-dark local child mechanism"]
    APPHOST["loushang.apphost\nA0.1 contracts only"]

    CODING -->|composes| HARNESS
    HARNESS -->|executes one prepared run through| AGENT
    AGENT -->|streams through| AI

    CODING -->|binds conversation UI| HTUI
    HTUI -->|uses terminal primitives| TUI

    CODING -->|optionally binds durable work| HWORK
    WORK -->|forwards compatibility surface to| HWORK
    CODING -->|optionally consumes plans from| METHOD
    CODING -->|selects boundary adapters from| CHANNEL
    CHANNEL -->|carries accepted Work/runtime views from| HWORK

    ONTOLOGY -->|uses strict values from| FOUNDATION
    HARNESS -->|explicit default-dark Worker adapter| HOSTING
```

The diagram intentionally omits many direct physical imports and Foundation
edges. It describes the primary semantic path and owner relationships.

## Current Architecture Scope Tree

```mermaid
flowchart TD
    LOUSHANG["Loushang"]
    CODING["Coding"]
    HARNESS["Harness"]
    AI["AI"]
    AGENT["Agent"]
    TUI["TUI"]
    HOSTING["Hosting"]
    APPHOST["AppHost"]
    OTHER["Channel / Method / HarnessWork / Ontology / ..."]

    LSP["coding.lsp"]
    ARCH["coding.arch"]
    MULTI["harness.multiagent"]

    LOUSHANG --> CODING
    LOUSHANG --> HARNESS
    LOUSHANG --> AI
    LOUSHANG --> AGENT
    LOUSHANG --> TUI
    LOUSHANG --> HOSTING
    LOUSHANG --> APPHOST
    LOUSHANG --> OTHER

    CODING --> LSP
    CODING --> ARCH
    HARNESS --> MULTI
```

Nested scopes own internal architecture but inherit placement and cross-sibling
dependency governance from their parent.

## Dependency Policy Summary

```text
Product composition -> Harness -> Agent -> AI -> Foundation

HarnessTUI -> Harness + TUI
HarnessWork -> Harness
Work compatibility -> HarnessWork
Ontology -> Foundation
Harness -> Hosting
AppHost A0.1 -> Python standard library only
```

This is a descriptive projection of policy, not its normative source or an
exhaustive allowlist. Exact forbidden and exception edges are executable under
`tests/architecture/` and explained by canonical scope boundaries.

Future Product scopes such as Design, Research, PPT, or Cowork remain peers of
Coding when accepted and implemented. They are not children of Agent, Work, or
Method merely because they consume those capabilities.

The accepted Target allows future AppHost runtime/profile components to depend
on AppHost contracts and injected Product ports. Optional hosted and launcher
adapters may depend on AppServer and Hosting respectively; those optional
edges are not AppHost core dependencies and are not implemented by A0.1.
