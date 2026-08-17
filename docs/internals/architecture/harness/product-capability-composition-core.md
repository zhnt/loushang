# Harness Product Capability Composition Core Boundary

## Status

Implementation complete for integration into `lane/harness`.

Capability-composition primitives live under `loushang.harness.capabilities`;
the command descriptor, catalog, parsing, dispatch, and local-catalog
composition core lives under `loushang.harness.commands`. Coding adopts both
through its product profile and controllers. Standard prompt assembly and
resource preflight are canonical Harness implementations. The packages are
deliberately not re-exported from the top-level `loushang.harness` namespace.

## Purpose

Products need the same mechanics and useful defaults for composing commands,
prompts, and tools. Product adapters should be small and retain only
irreducibly domain-specific content and policy. This core separates those
concerns:

```text
Harness: describe, resolve, compose, dispatch, project standard resources, diff
Product: override defaults and contribute product-exclusive content and policy
```

Coding is the compatibility adapter. Product-neutral Harness fixtures using
research and design vocabulary provide the independent contract probe; a
second production Product is not required by the neutrality evidence gate.

## Bound Behavior Semantics

The values bound through Capability Slots use the behavioral semantics from the
[Capability Variation And Replacement Boundary](capability-variation-and-replacement-boundary.md):

- command and tool pack composers use Exclusive Replacement, while the
  admitted packs passed to the selected composer are Aggregate Contributions;
- the prompt-section composer uses Exclusive Replacement, while its admitted
  sections are an ordered aggregate whose ordering is supplied by the Product
  and recorded in the prepared result;
- injected prompt parsing, expansion, activation, and callback behavior is
  Protocol Injection at the Product composition root;
- same-name resource or tool behavior follows the owning catalog's documented
  precedence and conflict contract; it is not a general last-write-wins rule.

This core does not publish a universal exclusive-provider registry. A Product
that exposes Exclusive Replacement behavior must declare its Runtime
Capability Shape, selection, fallback, lifecycle, and diagnostic behavior
explicitly.

## Harness Ownership

### Commands

`loushang.harness.commands` owns:

- generic command descriptors with opaque source metadata;
- name normalization and slash-command parsing, including the accepted MCP
  marker form;
- aliases, deterministic precedence, conflict reporting, and catalog lookup;
- completion projection from neutral descriptor metadata;
- ordered synchronous and asynchronous dispatch with opaque results.

Harness does not assign semantic precedence to builtin, extension, prompt, or
skill commands. The Product supplies descriptor order and precedence values.
Aliases belong to their primary descriptor: when that descriptor loses its
primary-name conflict, its aliases are inactive too. Active aliases participate
in completion and resolve to the canonical descriptor.

### Prompts

`loushang.harness.capabilities.prompt` owns:

- ordered prompt-section and prepared-prompt records;
- deterministic composition with included and omitted section trace entries;
- injectable argument parsing, placeholder detection, substitution, and
  argument-appending policy;
- the accepted default positional and sliced placeholder expansion mechanism.

`loushang.harness.capabilities.prompt_assembly` and
`loushang.harness.capabilities.prompt_preflight` own:

- the canonical `PromptAssembly` result;
- an overridable neutral system-prompt default;
- standard base, project-context, prompt-fragment, visible-skill, tool, and
  runtime-footer projection and ordering;
- standard `/skill:<name>` and `/<prompt>` resource preflight, diagnostics,
  frontmatter stripping, and argument expansion;
- injection points for a Product base prompt, resource activation, tool
  definitions, prompt text, template expander, and section composer.

Harness may author a neutral, broadly useful default and standard resource
projection. Products override only the parts that differ; they do not copy the
assembly engine merely because it emits user-facing text or currently has one
production consumer.

### Tools

`loushang.harness.capabilities.tools` owns:

- available, allowed, requested, active, and missing-name accounting;
- ordered tool resolution and activation snapshots;
- deterministic activation diffs and revision tracking;
- refresh behavior for additions, removals, reorderings, and same-name
  replacements;
- injected new-tool activation and rebind callbacks.

The coordinator carries opaque tool definitions. It does not materialize Agent
tools, create execution context, rebuild prompts, or emit Product events.

## Product Ownership

Coding and future Product adapters retain:

- concrete builtin, extension, prompt, and skill command definitions;
- command source precedence choices, handlers, routing, diagnostics, and UI;
- Product-exclusive system prompt text and any domain-only prompt sections,
  resource conventions, diagnostics, or preflight behavior;
- default tool packs, allowed/default-active policy, Product-tuned tool
  metadata, and extension activation choices;
- Agent tool materialization, `ToolContext` construction, prompt rebuilding,
  audit events, approval/risk policy, and presentation;
- model registry, authentication resolution, settings fields and defaults,
  transcript schema, compaction prompts, artifact semantics, channels, and UI.

These are Product semantics or integration effects, not composition mechanics.

## Coding Adapters

Coding retains product adapters while importing shared mechanics directly:

- slash parsing, completion, descriptors, and catalog composition come from
  `harness.commands`;
- standard session command descriptors and result projection come from
  `harness.session.command_pack`; Coding binds only its session ports and
  wraps the neutral result mapping;
- prompt template expansion comes from `harness.capabilities.prompt`;
- standard assembly and resource preflight come from
  `harness.capabilities.prompt_assembly` and
  `harness.capabilities.prompt_preflight`;
- `coding.prompt` preserves Coding's public imports and injects
  `DEFAULT_CODING_SYSTEM_PROMPT` while sharing canonical Harness type
  identities;
- Coding controllers inject handlers, policy, materialization, diagnostics,
  and Product-only prompt additions into the Harness mechanisms.

The migration preserves command dispatch order, prompt output, and tool
activation behavior without retaining legacy shared-utility submodule paths.

## Import And Validation Rules

- `loushang.harness.capabilities` must not import Product, method, work, TUI,
  AI, provider, or product storage packages.
- Capability symbols must not become top-level Harness exports.
- Harness tests must use Product-neutral fixtures rather than importing Coding.
- Coding behavior tests cover command compatibility, prompt parity, dynamic
  tool registration, allowlists, same-name replacement, and prompt rebinding.
- Architecture import boundaries, Ruff, mypy, and the full non-live repository
  suite remain merge gates.
