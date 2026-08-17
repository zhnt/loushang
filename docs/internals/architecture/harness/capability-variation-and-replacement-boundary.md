# Harness Capability Variation And Replacement Boundary

## Status

Accepted architecture decision. Implementation remains boundary-specific: this
decision does not make every described provider, backend, or lifecycle seam a
public API.

Canonical terms are defined in the
[Product And OEM Glossary](../../glossary/loushang-product.md). This document
defines when those variation semantics apply and how they preserve dependency,
authority, and lifecycle boundaries.
Top-level Capability IDs, dependency direction, Mounted Capability identity,
graph lifecycle, and graph diagnostics are defined by
[Capability Dependency And Mount Lifecycle](capability-dependency-and-mount-lifecycle.md).

## Decision

Loushang separates runtime-profile binding shape from behavioral variation
semantics. They are orthogonal contracts and must not be collapsed into one
enum or resolution rule.

Every `RuntimeCapabilitySlot` declares one binding shape, allowed contribution
sources, lifecycle scope, refresh boundary, and selection-conflict behavior:

| Binding shape | Selection rule |
| --- | --- |
| `single` | retain at most one final admitted selection; refresh follows the slot's declared boundary |
| `exclusive` | retain at most one final admitted selection and require a sealed refresh boundary |
| `ordered` | retain distinct implementation/version identities in deterministic order, replacing an earlier selection of the same identity |
| `append_only` | retain every admitted selection, including repeated identities, in deterministic order |

An executable variation surface separately declares how its resolved values
interact. A Product-only sealed slot need not expose an external variation
surface. `Override` is only an umbrella term; it is never a sufficient
resolution rule.

The three executable composition semantics are:

| Semantic | Cardinality | Resolution rule | Typical use |
| --- | --- | --- | --- |
| Aggregate Contribution | zero or more | admit every compatible entry and combine deterministically | tools, commands, server definitions, independent hooks |
| Ordered Interception | zero or more around one operation or provider | build an explicit ordered chain with a declared error policy | policy interceptors, tracing, metrics, caching |
| Exclusive Replacement | zero or one active provider per slot | apply the owning surface's explicit deterministic selection rule; reject only unresolved ambiguity | approval resolver, model provider, storage or channel adapter |

Decoration is the restricted case of Ordered Interception that wraps an
already resolved capability without acquiring its selection, authority, or
lifecycle ownership. Resource Overlay is a separate data-merge semantic: it
may shadow a same-identity resource according to a documented precedence
order, but it is not executable provider replacement.

There is no one-to-one mapping between the two axes. An `ordered` slot may bind
an Aggregate Contribution composer or an Ordered Interception pipeline. A
`single` or `exclusive` slot may bind one provider, but admission and the
surface contract decide whether Product, OEM, Extension, or session sources
may replace it. An Extension may be carried by a Plugin, but Plugin identity is
not a runtime-profile source. `append_only` is a selection-retention rule, not
permission to execute every retained contribution.

There is also no one-to-one mapping between a Runtime Capability Slot and a
top-level Capability ID. A slot may be an owner-private Binding Facet within a
coarser Capability Bundle. Variation semantics still govern that facet, while
the top-level Capability dependency graph records only the stable owner-level
Capability ID and its aggregate Mounted Capability state.

## Contract Ownership And Dependency Direction

The layer that can state a contract without importing upstream domain
vocabulary owns that contract:

- Product-semantic ports remain Product-owned. For example, Coding owns a
  future `LanguageServiceProvider` because language-server behavior, document
  synchronization, and semantic operations are Coding concerns.
- Product-neutral mechanism ports remain Harness-owned. For example,
  `AuthorizedProcessLauncher` is a Harness capability that a Product may
  consume.
- The outer Product or Platform composition root selects concrete providers
  and injects the narrow capabilities required to bind them.

The resulting source dependency remains one-way:

```text
Product provider -> Product port and Harness public capabilities
Harness          -X-> Product package or Product vocabulary
```

Harness may invoke an injected object at runtime without creating a reverse
source dependency. It must not discover a Product implementation by deriving
an import path, inspect Product-only types, branch on Product identity, or
require a Product registry to interpret the injected contract.

## Composition Lifecycle

Replaceable capabilities follow a staged lifecycle:

```text
discover -> admit -> resolve -> bind -> dispose
```

- **Discover** reads descriptors and compatibility metadata without creating
  live services or acquiring execution authority.
- **Admit** applies Product, OEM, trust, version, and execution policy.
- **Resolve** produces one deterministic and explainable selection or ordered
  composition. Continuity-critical choices belong in the Resolved Runtime
  Profile or its durable snapshot.
- **Bind** constructs scoped live objects from a narrow immutable context. It
  must not hand a Plugin the complete runtime as a service locator.
- **Dispose** releases providers in the reverse of successful binding order.
  Process-, Product-, Session-, workspace-, and document-scoped ownership must
  be explicit.

Discovery order is not selection policy. Priority may order admitted aggregate
or interceptor entries where a boundary defines that behavior, but priority
must not silently choose between ambiguous exclusive providers.

## Safe Replacement Sandwich

Product variation and Plugin-carried contributions are composed outside
non-bypassable Harness invariants:

```text
Product-selected provider
  -> Harness public capability
     -> authorization / approval / sandbox / limit / cleanup enforcement
        -> private mechanism
```

An allowed replacement may change Product behavior or policy within the
declared execution-profile ceiling. It may add stricter checks. It cannot
remove authorization, bypass approval coordination, disable required
containment, enlarge Host-owned limits, or take cleanup ownership away from
the Harness lifecycle.

An approval resolver can therefore be an admitted Exclusive Replacement while
the authorization gateway, immutable execution scope, revalidation, and
cleanup invariants remain non-replaceable. Similarly, a trusted Platform may
substitute a backend only where the owning boundary explicitly exposes that
trusted seam. Backend substitution is not an ordinary Plugin right.

## Registration And Conflict Rules

Every replaceable or composable surface declares:

- a stable capability or slot identifier;
- its Runtime Capability Shape when it is profile-bound;
- its behavioral composition semantic when variation is exposed;
- compatible contract version;
- allowed Product, OEM, Platform, Extension, or session sources and any
  required Plugin provenance;
- lifecycle scope and refresh boundary;
- deterministic ordering where ordering is meaningful;
- duplicate, ambiguity, failure, and fallback behavior.

Registries must reject duplicate identities that the owning semantic cannot
combine. Exclusive replacements require an explicit Product, OEM, or Platform
selection rule. A runtime-profile `single` slot may use its declared
source/layer/selection precedence; another surface may require a named provider
or reject competing candidates. These policies do not use incidental import or
discovery order. Fallback providers are selected by the slot owner and are
visible in the resolved profile and diagnostics.

## Top-Level Capabilities And Internal Facets

The accepted target top-level Harness Capability IDs are `harness.workspace`,
`harness.resources`, and `harness.session`. The accepted target Coding-specific
mountable Capability IDs are `coding.lsp` and `coding.arch`; matching Coding
constants already exist. The generic Planner, Binder, live Mount Runtime, and
Projector are implemented, while the generated
[Harness Capability Catalog](capability-catalog.md) records which target Bundles
currently have complete source-backed Definition / Provider / Consumer seams.

The accepted target Capability dependency graph intentionally stays coarser
than the current Runtime Profile inventory:

| Top-level Capability | Representative internal Runtime Profile facets |
| --- | --- |
| `harness.resources` | `resource.runtime`, `prompt.sections`, `skill.activation`, `tool.packs`, `command.packs` |
| `harness.session` | `conversation.store`, `agent.transcript_profile`, `context.compaction`, `interaction.side_question`, `continuity.provider_packs` |
| `harness.workspace` | workspace access and authorized-execution facets; non-bypassable authorization, Sandbox, audit, limits, and cleanup remain internal invariants |
| `coding.lsp` | Product-owned LSP catalog, selection, supervisor, document, diagnostic, query, and tool facets |
| `coding.arch` | Product-owned analyzer, import-graph, diagnostic, query, and tool facets |

An Extension may contribute to a declared facet such as an LSP Server
definition, architecture analyzer, Tool pack, or side-question provider. The
Extension and contribution are not graph nodes. A full Bundle replacement is a
separate, higher-authority surface and must be explicitly admitted by the
Capability owner.

Coarse Capability identity does not widen authority. A dependency such as
`coding.lsp -> harness.workspace` may request only a narrow read/process-launch
facet view; the requested facets remain admission and typed-injection metadata,
not additional nodes.

## Standard Runtime Capability Semantic Inventory

This internal-facet inventory applies the canonical glossary terms to the
standard Harness runtime slots. It is not the top-level Capability dependency
graph and not a second glossary: term definitions remain in the
[Product And OEM Glossary](../../glossary/loushang-product.md), while
`src/loushang/harness/runtime/_profile_standard.py` remains the code authority
for current slot keys, shapes, scopes, refresh boundaries, and source ceilings.

The **slot semantic** describes how alternative bound implementations interact.
The **nested semantic** describes values subsequently consumed by the selected
implementation. Keeping these columns separate prevents an ordered collection
of prompt sections or capability packs from being mistaken for permission to
bind multiple composer implementations.

| Standard slot | Owner boundary | Current profile contract | Slot semantic | Nested semantic | Alignment status |
| --- | --- | --- | --- | --- | --- |
| `conversation.store` | Harness Conversation and transcript runtime | `single`; Session; sealed; Product/OEM | Exclusive Replacement | None | Executable: profile precedence selects one store implementation. |
| `agent.transcript_profile` | Harness transcript runtime | `single`; Session; sealed; Product/OEM | Exclusive Replacement | None | Executable: profile precedence selects one transcript profile. |
| `context.compaction` | Harness Context and transcript runtime | `single`; Session; turn; Product/OEM/Extension/session | Exclusive Replacement | None | Executable: profile precedence selects one turn-refreshable implementation. |
| `resource.runtime` | Harness Resources | `single`; workspace; sealed; Product/OEM | Exclusive Replacement of the activation runtime | Resource Overlay inside the admitted `ResourceBundle` | Executable; the provider and data-overlay axes remain separate. |
| `prompt.sections` | Product prompt policy with Harness composition mechanics | `single`; Session; turn; Product/OEM/Extension/session | Exclusive Replacement of the composer | Aggregate Contribution of admitted `PromptSection` values | Aligned: exactly one composer binds, while its input sections remain an ordered aggregate. |
| `skill.activation` | Product activation policy with Harness resource mechanics | `single`; Session; turn; Product/OEM/Extension/session | Exclusive Replacement | One selected policy transforms the admitted resource bundle | Executable: exactly one activation runtime binds. |
| `tool.packs` | Product tool policy with Harness pack composition | `single`; Session; turn; Product/OEM/Extension | Exclusive Replacement of the composer | Aggregate Contribution of admitted `CapabilityPack` values | Aligned: exactly one composer binds, while admitted packs remain an ordered aggregate. |
| `command.packs` | Product command policy with Harness pack composition | `single`; Session; turn; Product/OEM/Extension | Exclusive Replacement of the composer | Aggregate Contribution of admitted `CapabilityPack` values | Aligned: exactly one composer binds, while admitted packs remain an ordered aggregate. |
| `interaction.side_question` | Product interaction port with Harness Session binding | optional `single`; Session; sealed; Product/OEM/Extension | Exclusive Replacement | None | Executable: Coding admits active Extension declarations after discovery, profile precedence selects one factory, and Session owns its cancellation/disposal. |
| `continuity.provider_packs` | Harness Continuity composition | optional `ordered`; Process; sealed; Product/OEM | Aggregate Contribution | Each pack contributes one or more continuity providers | Executable: all resolved packs compose in profile order and duplicate provider identities are rejected. |

No current standard runtime slot is classified as Ordered Interception.
Extension-routing interceptor chains are a separate executable surface and must
retain their own ordering, error, and delegation contract rather than borrowing
the semantics of an `ordered` runtime slot.

`RuntimeCapabilitySlot.variation_semantic` is the executable code authority for
this classification. Slots that admit non-Product sources or retain multiple
values must declare it. Shape/semantic compatibility is validated when the
slot is constructed, and the semantic is retained in new runtime-profile
snapshots. Legacy schema-v1 snapshots without the additive field remain
readable and are normalized against the current Product contract during
resume validation.

No standard slot declares automatic provider fallback. A Product default is
the baseline selection; a higher-precedence admitted Exclusive Replacement may
replace it, but a binding failure does not silently retry the baseline.
Introducing such fallback requires a separately declared failure policy,
durable provenance, and lifecycle tests.

## Application To Coding Language Services

A future Coding H3 language-service design should apply the decision as
follows; this is an ownership example, not a claim that H3 is implemented:

| Surface | Contract owner | Admitted sources | Semantic |
| --- | --- | --- | --- |
| `LanguageServiceProvider` | Coding | Product, plus explicitly admitted OEM or Extension layers if opened later | Exclusive Replacement when alternative complete providers are supported |
| language-server definitions | Coding | Product and Extensions carried by admitted Coding Plugins | Aggregate Contribution with duplicate server identities rejected |
| tracing, metrics, or cache wrappers | owning Coding/Harness integration boundary | Product/OEM/Extension as declared, with Plugin provenance where applicable | Decoration without authority widening |
| `AuthorizedProcessLauncher` | Harness | execution-scope binding from Harness | injected public capability, not a Coding replacement slot |
| authorization, required sandbox, limits, and process cleanup | Harness | Harness only | invariant enforcement, not replaceable by a Coding Plugin |

The Coding composition root binds the chosen language provider with an
execution-scope-bound `AuthorizedProcessLauncher`. Harness never imports the
provider or interprets LSP methods.

The current Process Hosting boundary deliberately exposes no public
`ProcessBackend`, transport API, or concrete Host. This decision must not be
used to infer such an extension point. A later backend seam requires its own
boundary decision and trust model.

## Validation

Each implemented variation point requires focused contract tests that prove:

- deterministic aggregate order or exclusive selection;
- duplicate and ambiguous-provider rejection;
- admission before construction and no discovery side effects;
- narrow scope binding and reverse-order disposal;
- failure and cancellation do not skip owned cleanup;
- decorators preserve authority and lifecycle contracts;
- Product adapters consume only Harness public APIs;
- Harness tests use Product-neutral fixtures and Harness does not import a
  Product package.

Import-boundary gates enforce source dependency direction. Runtime tests prove
that injected providers can be replaced without weakening the invariant
enforcement layer.

## Consequences And Non-Goals

- Products can replace semantic providers without forking Harness mechanisms.
- Plugin-carried contributions can participate or decorate only through
  Product/OEM-admitted surfaces.
- Resolution is diagnosable because the semantic, owner, selected source, and
  fallback are explicit.
- Security-sensitive mechanisms stay centrally enforced even when policy or
  provider implementations vary.
- This decision does not create a universal Plugin base class, global service
  locator, public process backend, cross-Session provider pool, or implicit
  dynamic-import convention.
