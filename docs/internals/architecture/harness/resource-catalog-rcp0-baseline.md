# Resource Catalog RCP0 Baseline

## Status And Authority

- Authority: executable migration baseline for RCP0 of the
  [Resource Catalog And Source Pluginization Plan](resource-catalog-pluginization-plan.md).
  It records the implemented legacy runtime; it is not the target Catalog
  contract and grants no new public API.
- Frozen source baseline: `0de16c72`, tracked by issue `#495`.
- Implementation status: RCP0 baseline only. No Catalog engine, source
  component, owner-component lifecycle, or `harness.resources` v2 facet exists
  yet.
- Cutover rule: an inventory entry may change only in its named phase, with its
  replacement parity green in the same change. Moving a call without removing
  the old authority does not satisfy a disposition.

The parent plan remains normative for target records, ownership, lifecycle,
security, and sequencing. This companion answers four narrower questions:

1. where current discovery and effective-selection authority lives;
2. which production callers and sinks still depend on it;
3. which current behaviors must remain equal through shadow/cutover; and
4. in which phase each legacy path is adapted or deleted.

## Current Authorities

| Implemented symbol/path | Current authority | Target disposition |
| --- | --- | --- |
| `harness.resources.loader.ResourceLoader` | Owns discovery request construction, mount verification/swap, committed `ResourceSnapshot`, reload, and compatibility getters. | Shadow-adapt in RCP1; project from the captured Catalog generation in RCP4; forwarding-only and then deleted in RCP5. |
| `harness.resources._loader_pipeline` | Aggregates source discoveries and constructs the authoritative `ResourceSnapshot`. | Becomes the RCP1 parity oracle; no production effective-selection import after RCP5. |
| `harness.resources._loader_resolution` | Resolves same-identity winners and emits `ResourceMergeDecision`. | Move the behavior into the owner-supplied policy/validator in RCP1; no production import after RCP5. |
| `harness.resources._loader_precedence` | Owns the implemented priority and stable candidate ordering. | Freeze unchanged into the RCP1 owner policy; no production import after RCP5. |
| `harness.resources.types.ResourceSnapshot` | Holds current candidates, winners, diagnostics, and merge decisions. | RCP1 shadow input only; compatibility projection source in RCP4; no production effective authority after RCP5. |
| `harness.resources.types.ResourceBundle` | Mutable-list compatibility projection consumed by Session/Product code. | Project from one captured Catalog generation in RCP4; never regain discovery or winner authority. |
| `harness.resources.skills.SkillLoader` | Wraps `ResourceLoader` and owns a private disabled-name overlay. | Narrow Skill Consumer adapter in RCP5, then delete private discovery/cache/activation state. |
| `harness.extensions.resources.ExtensionResourceRuntime` | Runs `resources_discover` and directly appends contributions with `ResourceBundle.merge()`. | Normalize one Extension-owner-generation source snapshot and join the RCP4 publication transaction; remove direct merge authority by RCP5. |
| `harness.resources.packages.catalog._summarize_package_resources` | Constructs a Resource loader, performs effective discovery, and derives an inventory summary. | Replace with a pure inventory/summarization port in RCP3. The Package Catalog remains distinct from the Resource Catalog. |
| `harness.resources.packages.mounts.PackageResourceMount` | Carries package roots, filters, optional verified revision leases, contained reads, and close. | Transfer exact handles to RCP3 source generations; never expose raw mount/path authority to the engine. |

## Frozen Production Caller Inventory

The architecture test uses AST-qualified call sites. Definitions are not
counted. Dynamic compatibility access is listed separately because it is
intentionally not a normal typed call.

### `discover_resources`

| Qualified caller | Disposition |
| --- | --- |
| `harness.bootstrap.ResourceBootstrapRuntime.discover` | RCP4 captures the mounted Catalog generation. |
| `harness.bootstrap.create_standard_resource_bootstrap_runtime` | RCP4 replaces the loader port with the Catalog bootstrap port. |
| `resources.loader.ResourceLoader.reload_resources` | RCP5 forwarding-only, then delete. |
| `resources.packages.catalog._summarize_package_resources` | RCP3 replace with pure package inventory summary. |
| `resources.skills.SkillLoader.discover_skills` | RCP5 Skill Consumer, then delete. |
| `method.loader.MethodLoader.discover_methods` | RCP5 typed Resource Consumer; no independent Method discovery. |

### `reload_resources`

| Qualified caller | Disposition |
| --- | --- |
| `resources.skills.SkillLoader.reload_skills` | RCP5 remove private reload. |
| `session.resource_refresh.SessionResourceRefreshRuntime._load_resource_bundle` | RCP4 stage/classify/publish a next Catalog generation. |

### `get_resource_snapshot`

The current calls are
`ResourceLoader.get_diagnostics`, `ResourceLoader.get_extensions`,
`ResourceLoader.get_package_resource_summaries`,
`ResourceLoader.get_resource_bundle`,
`ResourceLoader.get_resource_diagnostics`, `ResourceLoader.get_skills`, and
`SkillLoader.list_skills`. RCP4 moves compatibility projection to one captured
Catalog generation; RCP5 removes the loader/Skill peer getters.

### `get_resource_bundle`

The current calls are:

- `ProfiledResourceLoader.get_system_prompt`;
- `ResourceLoader.get_agents_files`, `get_append_system_prompt`, and
  `get_prompts`;
- `ResourceCommandSourceRuntime.execute`, `list_descriptors`, and
  `preflight_user_input`;
- `SessionResourceRefreshRuntime.__post_init__`, `_commit_resource_bundle`,
  `get_prompt_templates`, and `reload_extension_generation`; and
- `create_tool_prompt_rebuilder.rebuild`.

RCP4 changes these to a read-only captured-generation projection or focused
Consumer. RCP5 removes Resource/Skill compatibility getter authority.

### Skill list and eager-body sinks

The CLI dynamically reads `session.resource_bundle.skills` and falls back to
`getattr(session.resource_loader, "get_skills")`. The fallback is RCP5 deletion
debt, not an alternate supported Catalog route.

Files that both know `ResourceBundle` and directly load a `.skills` attribute
currently contain these qualified sites:

- `commands.resources.list_resource_command_descriptors`;
- `extensions.resources._merge_contribution`;
- `resources.activation.ResourceActivation.active_skills`;
- `resources.activation.apply_disabled_skills`;
- `resources.types.ResourceBundle.merge`;
- `session.agent_adapter.AgentSessionAdapterMixin._before_agent_start_system_prompt_options`;
- `session.agent_adapter.AgentSessionAdapterMixin._resource_watch_paths`; and
- `session.agent_product.AgentProductSession._composition_ports`.

Three production sites directly read an eager Skill body:
`capabilities.prompt_preflight._preflight_resource_input` and
`commands.resources.command_description_from_skill` read `SkillDescriptor`,
while `method.skill_adapter.method_from_skill` reads the compatible
`SkillResourceLike` projection. RCP5 moves all three to an exact Catalog load
receipt; summaries and Method projection must not silently read a changed body.

### Package mounts and Extension merges

`PackageResourceMount` is constructed only by
`resources.loader._package_mounts_from_legacy_roots` and
`resources.packages.roots.resolve_package_resource_roots`. RCP3 makes the
second path the source-generation input and removes the legacy loader mount
constructor after parity.

Direct Extension Resource merges are currently limited to
`ExtensionResourceRuntime._finish` and `_merge_contribution`. These are
explicit migration debt. RCP4 replaces their publication role with one
Extension-generation `ResourceSourceSnapshot`; RCP5's final gate requires zero
direct Extension `ResourceBundle.merge()` publication sites.

## Frozen Behavior Parity

### Precedence and resolution

The implemented source priority is exactly:

```text
temporary > project_local > user_global > external_package > built_in
```

Within one source class, lower `source_root_order` wins before canonical name
and source path ordering. Disabled candidates cannot win. Every collision
retains candidate evidence and one winner/reason in `ResourceMergeDecision`.
RCP1 shadow output must match this behavior before any caller moves. A proposed
canonical tie-break difference needs an explicit Product-approved exception;
it cannot arrive as incidental refactoring.

Executable parity anchors are:

- `tests/harness/resources/test_catalog_rcp0_parity.py` for all five source
  classes and current Extension append behavior;
- `tests/harness/resources/test_loader_pipeline.py` for immutable request,
  candidate/diagnostic order, revision-race non-publication, and atomic mount
  swap/lease close;
- `tests/coding/test_resource_loader.py` for native Skills, temporary inputs,
  package filters, same-precedence conflicts, reload, and current snapshots;
- `tests/harness/extensions/test_runtime.py` and `test_routing.py` for hook
  normalization, ordering, diagnostics, async handling, and `fail_chain`; and
- `tests/harness/resources/packages/test_catalog.py` for Package Catalog
  Product-profile summaries.

### Current Extension publication chain

The implemented chain is intentionally recorded as legacy behavior:

```text
ResourceLoader produces base ResourceBundle
  -> PreparedExtensionGeneration.discover_resources_async(bundle)
  -> ExtensionResourceRuntime appends hook output to a new ResourceBundle
  -> candidate.activate(bindings)
  -> candidate.publish(lambda: _commit_resource_generation(discovered))
  -> prior Extension generation retires
```

This is already one staged Extension publication boundary, but it is not yet
the target single Catalog composition. RCP4 must preserve rollback and visible
output while moving hook output before the final Catalog proposal and publishing
Extension state, Catalog generation, and read-only projection in one no-await
commit. No intermediate Bundle is a second Catalog generation.

## Frozen Target Contract Surface

RCP0 freezes names and fields, not public Python classes. The normative records
remain: `ResourceIdentity`, `ResourceSourceGenerationRef`,
`ResourceSourceSnapshot`, `ResourceCandidateSummary`, `ResourceBodyRead`,
`ResourceCatalogSnapshot`, `ResourceLoadReceipt`, and `LoadedResource`.

The exclusive custody path is:

```text
root_owned -> graph_constructing -> graph_owned -> retiring -> disposed
```

`PreparedResourceOwnerGeneration` is only a child of
`StagedResourceCompositionCandidate`; a failed transfer returns to exactly one
root owner, and successful Graph adoption has only the Provider/Binder disposer.

The minimum diagnostic taxonomy is frozen in the parent plan. Codes are stable;
specific reason, producer/source identity, phase, and redacted cause belong in
structured metadata rather than new per-implementation code names.

## Forbidden Peer Routes

RCP0 freezes these as architectural violations, including synthetic fixtures
before the target symbols exist:

- a top-level `harness.skills` Capability or second Skill Catalog;
- raw admitted `resource_item` candidates entering the engine without one
  exact-generation `ResourceSourceSnapshot`;
- a Catalog engine invoking discovery, body reads, Plugin selection, admission,
  activation, disposal, or self-replacement;
- Package Catalog choosing effective Resources or aliasing Resource Catalog;
- Extension output merging effective Resources after final Catalog composition;
- a mutable `ResourceBundle` serving as effective Catalog state;
- a Consumer falling back to loader/filesystem discovery after cutover; and
- an owner component creating another Graph, registry, nested Plugin host, or
  MCP route.

RCP0 does not forbid the explicitly inventoried legacy sites before their named
cutover phase. It forbids adding another site or declaring the existing debt a
new extension point.

## RCP0 Exit Gate

RCP0 is complete only when:

- the caller, sink, legacy-module, Package-mount, and Extension-merge
  inventories are executable and exact;
- the five-source precedence/decision and Extension output parity fixtures pass;
- every inventory item has one RCP3/RCP4/RCP5 disposition;
- the record set, diagnostic taxonomy, custody states, synchronous initial
  discovery, pure refresh classification, provenance, content identity, and
  handle narrowing contracts are executable documentation gates;
- current focused Resource, Extension, Package Catalog, and architecture tests
  are green; and
- a narrow independent freeze re-review finds no P0/P1 before RCP1 begins.
