# Harness Refactoring Principles

## Purpose

This document defines the rules for moving shared behavior into
`loushang.harness`.

The goal is to make future products small by providing a batteries-included,
cross-product runtime kernel without making harness a second agent loop or a
home for product semantics.

## Core Rule

Harness owns reusable mechanisms, cross-product conventions, and reusable
concrete defaults. Products own only behavior that is irreducibly exclusive to
their product identity or domain.

The default destination is Harness. Code remains in a product only when the
product boundary is explicit and testable. The fact that code currently has
one Product consumer, contains user-facing wording, or chooses a default is not
enough to keep it in that Product. A Product exception must show at least one
of these properties:

- it defines product-exclusive goals, domain language, completion criteria,
  prompts, skills, or artifact semantics that are not useful as a standard
  Harness convention;
- it chooses product-exclusive defaults, tool-pack activation, context salience,
  risk/approval behavior, permissions, storage, commands, or presentation;
- it integrates product UI, product-exclusive compatibility/resource formats,
  or a domain-specific external system;
- moving it would require Harness to import or understand product state.

Put code in Harness when all of these are true:

- it is demonstrably product-neutral and useful to planned product lines; a
  second production consumer is evidence, not a prerequisite;
- it does not depend on coding, design, research, ppt, cowork, TUI, method,
  work, or AI provider semantics;
- it describes a contract, helper engine, registry, resolver, lifecycle shape,
  neutral record, or reusable concrete capability;
- products can override the standard defaults and inject product-exclusive
  policy, activation, storage, and UI behavior outside Harness.

Keep code out of Harness only when it decides what one specific Product should
do in terms that cannot be generalized without importing or encoding that
Product. A useful overridable default, standard resource convention, or
resource-aware prompt workflow belongs in Harness even though it necessarily
makes choices. Product adapters replace or extend those choices where their
domain genuinely differs.

## Neutrality Evidence Gate

A Harness extraction does not require a second production consumer. It may
proceed before another product ships only when all of the following evidence
is present:

- a boundary decision names the product-neutral mechanism, the product policy
  left behind, and explicit non-goals;
- the Harness API uses product-neutral vocabulary and carries no Product
  imports, Product-exclusive defaults, or product-specific storage and UI
  semantics;
- the existing product adapter proves compatibility with current behavior;
- an independent contract probe exercises the proposed API without Coding
  runtime objects or Coding vocabulary;
- focused tests enforce behavioral invariants, dependency direction, and any
  accepted compatibility identities;
- the API stays in a focused module and avoids premature top-level exports.

The independent contract probe may be a minimal reference adapter, a planned
product spike, or a product-neutral test fixture. A renamed Coding fixture is
not sufficient: the probe must construct and exercise the contract from the
neutral boundary. When that probe exposes a required product-shaped field or
policy decision, split the contract again or keep it product-owned.

A later production consumer should validate and refine the contract, but its
absence is not a migration blocker when this evidence gate is satisfied.

## Dependency-First Migration Order

Migration order follows reusable dependency direction across the whole product,
not the historical order of feature slices. If `A` imports `B`, `A` is the
dependent consumer and `B` is the depended-on foundation. Move `B` before `A`
when `B` belongs in Harness.

Apply that rule with these constraints:

- decide ownership before considering topology; a highly referenced
  product-specific module does not move merely because it has high fan-in;
- start with the lowest product-neutral dependency closure that unlocks one or
  more upper layers;
- when modules form a strongly connected component, first extract the neutral
  records, protocols, and pure mechanisms that break the cycle;
- move the resulting contracts and concrete engines together as one capability
  batch, then redirect product consumers through compatibility adapters;
- migrate upper orchestration only after its reusable dependencies have stable
  Harness owners.

Dependency count is evidence about leverage, not evidence about ownership. For
example, a domain-specific transcript payload can remain product-owned even
when many Product modules import it, while a common Agent transcript profile
belongs in Harness despite initially having one Product adapter. Conversely, a
small package-source identity module should move early when it is a neutral
foundation for discovery, materialization, and extension loading.

The preferred dependency flow is:

```text
neutral records and policy protocols
  -> reusable leaf utilities and persistence primitives
  -> registries, resolvers, materializers, and catalogs
  -> resource, extension, context, and workflow engines
  -> host/session orchestration
  -> product bootstrap, commands, channels, and UI
```

## Mechanism Versus Policy

Use this split when judging a candidate:

| Concern | Harness may own | Product adapter owns |
| --- | --- | --- |
| Tools | registry/schema/contribution mechanics, execution wrappers, and reusable concrete tool packs such as workspace read/search/edit/exec | default tool-pack activation, domain-specific tools, destructive-tool policy, and product-tuned names/descriptions |
| Approval | approval request/decision value types, resolver protocol, headless deny/allow defaults | interactive approval UI, product-specific rules, persisted allowlists |
| Policy | neutral allow/deny/ask decision records and evaluator protocols | risk classification, trust rules, allowlists, and product defaults |
| Presentation | neutral content blocks, renderer protocol, renderer registry | terminal/web widgets, product-specific transcript layout |
| Resources | platform roots/layout, standard conventions, descriptors, discovery/package engines, precedence presets, merge/diagnostic mechanisms | domain content, convention activation, additional/override roots, trust and runtime projection |
| Workspace | file/process protocols and backends, neutral exec shapes, path/mutation mechanics, reusable workspace tools | allowed roots, activation, risk/approval classification, user explanations, workspace defaults |
| Context | context item refs, budget accounting, packing contracts, turn-aware cut planning, and checkpoint replay mechanics | what content is important, token/message projection, summarization prompts, and product-specific memory policy |
| Session | conversation repository/catalog/branch/fork/replay mechanics, host/turn/retry lifecycle, resource and extension refresh coordination, session operation/navigation transactions, idle/abort/dispose/queue snapshots | transcript schema/codecs, storage roots and retention, controller policy/adapters, commands, Product messages, and Product execution policy |
| Diagnostics | diagnostic records, severity/source vocabulary, query interface | product health checks, user-facing grouping, remediation text |

The product adapter can call harness engines. The product adapter chooses how
those engines are configured and exposed. The irreducible policy and semantic
surface that remains in each product is recorded under
[Product Kernel Ownership](shared-capability-boundaries.md#product-kernel-ownership).

## Top-Level Package Discipline

Do not create new top-level packages merely because a concept is shared.

Preferred destinations for shared substrate:

- `loushang.harness.workspace`
- `loushang.harness.resources`
- `loushang.harness.context`
- `loushang.harness.approval`
- `loushang.harness.policy`
- `loushang.harness.presentation`
- `loushang.harness.tools`
- `loushang.harness.diagnostics`

Avoid new top-level packages such as:

- `loushang.runtime`
- `loushang.product`
- `loushang.workspace`
- `loushang.context`
- `loushang.memory`
- `loushang.session`

`loushang.work`, `loushang.method`, `loushang.agent`, `loushang.ai`, and
`loushang.tui` are separate subsystem packages with their own boundaries. They
should not be absorbed into harness.

`loushang.resource` currently exists as a small shared frontmatter location. If
resource substrate becomes harness-owned, prefer a planned migration into
`loushang.harness.resources.frontmatter` instead of expanding the top-level
`loushang.resource` package.

## Import Rules

Neutral Harness core packages may remain independent of Agent and AI. Declared
Agent integration packages may import stable public `loushang.agent` and
`loushang.ai` capabilities when their contract requires it. Such modules do
not own provider registration, credential resolution, or Product model policy;
Agent and AI packages must not reverse-depend on Harness.

Harness must not import:

- product packages;
- `loushang.method`;
- `loushang.work`;
- `loushang.tui`;
- channel implementations.

If a contract needs to reference work, method, channel, UI, or product facts, it
should use opaque strings, dataclasses with neutral fields, or protocols defined
inside harness. The consumer outside harness performs the interpretation.

## Public API Rules

Keep `loushang.harness.__init__` small.

Do not add every harness type to top-level `__all__`. Prefer direct imports
from focused modules, such as:

```python
from loushang.harness.commands import CommandDef
```

Top-level exports are reserved for stable, intentional entry points. This
prevents early internal contracts from becoming public API accidentally.

## Migration Batch Size

Use capability-sized migration batches rather than file-sized or temporary
feature slices. A batch should normally include the complete reusable dependency
closure for one capability:

- neutral records and protocols;
- reusable concrete implementations;
- product policy injection points;
- compatibility adapters for accepted imports;
- internal consumer rewrites;
- focused behavior and import-boundary tests;
- ownership and migration-inventory updates.

Large ownership moves are expected during consolidation. Split a batch only at
a real ownership boundary, a forbidden subsystem dependency, an independently
reversible capability boundary, or a change that cannot be validated with the
same test matrix. Do not create a separate branch or named slice for every leaf
type, helper, or compatibility shim. Within one semantic task branch, use
ordered commits for foundations, engines, adapters, and closure so review and
rollback remain practical.

Batch size never relaxes neutrality, dependency direction, compatibility, or
test requirements. It reduces coordination overhead by completing a coherent
ownership transfer in one pass.

## Migration Batch Checklist

Each migration batch should be reviewable as one capability cluster. During
runtime consolidation, prefer an ownership lift-and-shift with compatibility
shims over a simultaneous API redesign.

Before moving code:

- identify the harness mechanism and the product policy being left behind;
- inspect the product-wide dependency graph and any strongly connected
  component containing the candidate;
- identify the lowest reusable dependency closure and the consumers it
  unlocks;
- choose the target harness module;
- check that no forbidden imports are introduced;
- decide whether old imports are removed or temporarily shimmed;
- define focused tests proving product behavior is unchanged.

During the move:

- move a coherent reusable implementation, not only its protocols and types;
- keep a capability's foundations, engines, adapters, consumer rewrites, and
  tests in the same migration batch;
- preserve accepted product import paths with thin compatibility adapters;
- defer renaming, public API cleanup, and shim removal until ownership has
  moved and behavior is green;
- keep command handlers, prompt policy, UI controllers, Product controller
  policy/adapters, and Product transcript stores in product packages;
- update internal imports to the new harness path;
- run architecture import-boundary tests.

After the move:

- keep or add docs that explain the new owner;
- remove transitional shims unless an accepted compatibility decision says
  otherwise;
- do not expand harness top-level exports unless the contract is intentionally
  public.

## Upgrade Compatibility Contracts

Harness upgrades must remain compatible with existing OEM overrides and
product adapters. Four contracts define this boundary:

| Contract | Harness guarantees | Consumer guarantees |
| --- | --- | --- |
| **Protocol contract** | Public protocols (`PolicyEvaluator`, `ApprovalResolver`, `ExtensionPolicyResolver`, tool-definition protocols, etc.) follow additive evolution: new methods receive default implementations; existing signatures are preserved; deprecation uses warnings, not removal | Implement protocols with explicit parameter names; avoid `*args` / `**kwargs` that silently absorb new required parameters |
| **Data contract** | Frozen dataclasses gain new fields only with default values; existing field semantics, order, and identity remain stable | Do not depend on field ordering, `__repr__` output, or pickled representation; read fields by name only |
| **Resource contract** | Resource layout conventions (`skills/*/SKILL.md`, `methods/*/METHOD.md`, `themes/*.json`, `prompts/*.md`) and the loader merge algorithm are stable; discovery mechanics may improve (faster scan, richer diagnostics) but do not change precedence or key identity | Place OEM resources in dedicated directories; do not modify built-in or product-shipped resource files; use the loader API rather than filesystem hacks |
| **Channel contract** | `WorkOperation`, `WorkEvent`, and the separate `RuntimeEventView` family follow additive evolution; unknown `kind` values or new payload fields must not break existing consumers; `delivery_hint` semantics are preserved | Ignore unknown fields rather than rejecting them; treat unknown `kind` values as opaque pass-through |

### OEM Contract Tests

Harness CI should include a focused OEM contract-test suite that runs against
main-harness changes. Each test validates one compatibility guarantee:

- An OEM `PolicyEvaluator` implementation still satisfies the protocol and
  returns valid `PolicyDecision` values.
- An OEM model registered via `models.json` overlay is still resolvable
  through `ModelRegistry` after the overlay is merged.
- An OEM resource root placed under `oem/` still contributes skills, methods,
  and prompts after a loader engine upgrade.
- An OEM extension declaring `tool` and `hook` surfaces still loads, registers,
  and dispatches without importing product packages.

These tests are not a replacement for product-specific integration tests.
They assert the Harness-compatibility boundary, not product correctness.

## Parallel Lane Safety

Harness refactoring is safe to run in parallel with `tui`, `agent`, and `ai`
lanes if it follows these constraints:

- it does not change the agent loop contract without coordination with the
  agent lane;
- it does not change provider/model/auth behavior without coordination with the
  AI lane;
- it does not change terminal primitives or render-loop behavior without
  coordination with the TUI lane;
- it keeps shared contracts product-neutral and leaves product-specific wiring
  in product packages.

The harness lane should coordinate with the code lane whenever a slice changes
`loushang.coding` behavior, tests, or imports.
