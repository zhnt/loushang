# Resource Catalog RCP0 Baseline

## Status And Authority

- Authority: executable migration baseline for RCP0 of the
  [Resource Catalog And Source Pluginization Plan](resource-catalog-pluginization-plan.md).
  It records the implemented legacy runtime; it is not the target Catalog
  contract and grants no new public API.
- Frozen source baseline: `0de16c72`, tracked by issue `#495`.
- Implementation status: the RCP0 legacy baseline remains authoritative, and
  RCP1 through RCP3 remain private foundations. RCP4 now has ten unpublished
  slices: pure Catalog records/engine, owner-component lifecycle,
  native/package/embedded/Extension sources, the v2 Catalog/load Provider, and
  one private optional Agent Session bootstrap plus its reusable
  native/package/embedded Product input adapter, plus a private Coding initial
  shadow over a same-discovery single-take input receipt. That Coding seam
  supports project/context, user, built-in, and exact owner-admitted
  verified-package inputs. Package inputs must now exact-match the Resource
  admissions in one existing compiled Product composition; no raw parallel
  admission ingress remains. A private Session/Product assembly root now
  derives that compilation from a finalized Plugin selection and explicit exact
  Resource/Tool/Command owner bindings, and the Coding shadow consumes that
  assembly request with one evaluation time. It still rejects conventional or
  incompletely admitted packages, package diagnostics/Extensions, temporary
  inputs, kind switches, and disabled Skills. No Product invokes
  them by default; the private Coding migration seam is explicit. Therefore the
  v1 legacy loader remains the default Resource authority and no cutover or refresh
  route exists yet. RCP3 also removed Package Catalog's effective
  discovery-summary bridge in favor of a pure inventory port.
- Review status: the first freeze re-review rejected commit `811f0fdb` with no
  P0 because its Skill oracle and executable inventories were incomplete.
  Corrections at `ed364062` and candidate-provenance closure at `b387d542`
  passed final independent architecture, lifecycle, and security rechecks with
  no P0/P1. The RCP0 gate is complete. RCP1 is implemented and locally green,
  but has not yet received an independent RCP1 code re-review.
- Cutover rule: an inventory entry may change only in its named phase, with its
  replacement parity green in the same change. Moving a call without removing
  the old authority does not satisfy a disposition.

RCP5.4 disposition note: the frozen chain below remains executable only for
caller-selected `legacy_explicit`. Catalog-backed Sessions now use one async
next-generation transaction: settings/package-root preparation, one fresh
loader receipt, exact Product input minting, joint Extension/Resource prepare,
and atomic owner-generation publication. Watcher, package, ordinary refresh,
and Extension reload converge on that route. Disabled names compile into the
new Catalog activation policy and are not applied by the legacy commit overlay.
The remaining `ResourceLoader.reload_resources` call at the Coding ingress is
receipt production, not effective selection or publication authority.

The parent plan remains normative for target records, ownership, lifecycle,
security, and sequencing. This companion answers four narrower questions:

1. where current discovery and effective-selection authority lives;
2. which production callers and sinks still depend on it;
3. which current behaviors must remain equal through shadow/cutover; and
4. in which phase each legacy path is adapted or deleted.

## RCP1 Shadow Additions With No Runtime Authority

| Private module | RCP1 role | Explicit non-authority |
| --- | --- | --- |
| `harness.resources._catalog_records` | Immutable v2 identity, provenance, candidate, source/Catalog snapshot, decision, activation, handle, body, and receipt records with canonical fingerprints, exact producer/content-origin matching, generation-scoped diagnostics, and proposal accounting. | Not exported from `harness.resources`; owns no store, loader, Graph, Session, or disposer. |
| `harness.resources._catalog_engine` | Pure deterministic strict/permissive/additive merge proposal over canonical source snapshots. | Performs no discovery, body load, filesystem access, refresh, or publication. |
| `harness.resources._catalog_shadow` | One-way `ResourceSnapshot` normalization, parity report, and disposable compatibility projection. | Requires caller-supplied generation/content provenance and owner source facts, validates them against legacy evidence, and is imported only by tests; it cannot mint live provenance or replace the committed Bundle. |

The exact `ResourceSnapshot` constructor inventory therefore contains one new
private test-projection site in `_catalog_shadow` beside the two frozen
production constructors. The RCP1 architecture gate keeps that distinction
executable rather than treating all three sites as runtime authority.

## Current Authorities

| Implemented symbol/path | Current authority | Target disposition |
| --- | --- | --- |
| `harness.resources.loader.ResourceLoader` | Owns discovery request construction, mount verification/swap, committed `ResourceSnapshot`, reload, and compatibility getters. Its one discovery result now also carries the private single-take Coding shadow input receipt, including observed package candidate facts from that same discovery; the receipt has no selection or publication authority. | Shadow-adapted by the private RCP1 test bridge; project from the captured Catalog generation in RCP4; forwarding-only and then deleted in RCP5. |
| `harness.resources._loader_pipeline` | Aggregates source discoveries and constructs the authoritative `ResourceSnapshot`. | Serves as the RCP1 parity oracle; no production effective-selection import after RCP5. |
| `harness.resources._loader_resolution` | Resolves same-identity winners and emits `ResourceMergeDecision`. | Behavior is mirrored by the RCP1 pure policy/validator; no production import after RCP5. |
| `harness.resources._loader_precedence` | Owns the implemented priority and stable candidate ordering. | Priority is frozen in the RCP1 policy; no production import after RCP5. |
| `harness.resources._loader_discovery*`, `_loader_descriptor_parsing`, `_loader_package_policy`, and `_loader_types` | Own native/package/context/temporary discovery, parsing, filtering, and legacy intermediate records below the pipeline. | Adapt pure parsers behind RCP2/RCP3 source generations; remove legacy discovery authority/import edges in RCP5. |
| `harness.resources.types.ResourceSnapshot` | Holds current candidates, winners, diagnostics, and merge decisions. | RCP1 shadow input only; compatibility projection source in RCP4; no production effective authority after RCP5. |
| `harness.resources.types.ResourceBundle` | Mutable-list compatibility projection consumed by Session/Product code. | Project from one captured Catalog generation in RCP4; never regain discovery or winner authority. |
| `harness.resources.skills.SkillLoader` | Wraps `ResourceLoader` and owns a private disabled-name overlay. | Narrow Skill Consumer adapter in RCP5, then delete private discovery/cache/activation state. |
| `harness.extensions.resources.ExtensionResourceRuntime` | Runs `resources_discover` and directly appends contributions with `ResourceBundle.merge()`. | Normalize one Extension-owner-generation source snapshot and join the RCP4 publication transaction; remove direct merge authority by RCP5. |
| `harness.bootstrap.ResourceBootstrapRuntime` | Initial Session first discovers a base Bundle, then creates the Extension runtime and calls the `rediscover_resources` port. | RCP4 replaces the two-stage visible path with the joint unpublished Extension/Catalog candidate. |
| `harness.resources.refresh.RuntimeResourceDiscovery` | Dynamically probes `discover_resources`/`discover_resources_async` and lets active refresh append Extension output after reload. | RCP4 routes this adapter into the joint transaction; no post-Catalog dynamic rediscovery remains. |
| `harness.resources.packages.catalog.summarize_package_resources` / `summarize_profiled_package_resources` | Delegates read-only conventional-layout counting to `PackageResourceInventoryPort`; it owns no effective winner or loaded body. | RCP3 complete. Keep the Package Catalog distinct from the Resource Catalog and retain only inventory/materialization responsibility. |
| `harness.resources.packages.mounts.PackageResourceMount` | Carries package roots, filters, optional verified revision leases, contained reads, and close. | Transfer exact handles to RCP3 source generations; never expose raw mount/path authority to the engine. |

### Legacy module disposition ledger

| Module | Current role | Named phase |
| --- | --- | --- |
| `_loader_discovery.py` | Coordinates project/user/package discovery and switches. | Split native work into RCP2 and package work into RCP3; delete the legacy coordinator in RCP5. |
| `_loader_discovery_builtin.py` | Reads import-package built-ins. | Adapt as embedded/OEM source in RCP3; delete the legacy entry in RCP5. |
| `_loader_discovery_context.py` | Walks AGENTS/compatibility context files. | RCP2 implements the bounded handle-scoped native shadow route; keep this production oracle until the RCP4 single-publication cutover and delete its legacy entry in RCP5. |
| `_loader_discovery_filesystem.py` | Scans prompt/Skill/Extension/theme directories. | RCP2 implements the bounded native shadow route and shares pure prompt/Skill parsing plus Skill-ignore semantics; keep this production oracle until the RCP4 cutover and delete its legacy entry in RCP5. |
| `_loader_discovery_temporary.py` | Scans Product-supplied one-session paths. | Adapt as a Host-approved native/temporary source mode in RCP3; delete the legacy entry in RCP5. |
| `_loader_descriptor_parsing.py` | Legacy import adapter to the shared pure prompt/Skill text parser. | RCP2 moved implementation to `_descriptor_parsing.py`; remove this compatibility edge with the legacy discovery route in RCP5. |
| `_loader_package_policy.py` | Normalizes package filters, diagnostics, and counts. | Move pure inventory/filter work to the RCP3 package source/summary port; remove effective-selection coupling in RCP5. |
| `_loader_types.py` | Defines legacy discovery/intermediate records. | RCP1 parity input only; replace with canonical source/candidate records and remove production use in RCP5. |
| `_loader_pipeline.py` | Builds the effective `ResourceSnapshot`. | RCP1 parity oracle; remove production construction/import in RCP5. |
| `_loader_resolution.py` | Applies strict, permissive, and additive kind policies. | Freeze into RCP1 owner policy/validator; remove production import in RCP5. |
| `_loader_precedence.py` | Applies source precedence and ordering. | Freeze into RCP1 owner policy/validator; remove production import in RCP5. |

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
| `resources.skills.SkillLoader.discover_skills` | RCP5 Skill Consumer, then delete. |
| `method.loader.MethodLoader.discover_methods` | RCP5 typed Resource Consumer; no independent Method discovery. |

RCP3 removed the former Package Catalog call to `discover_resources`; package
summary functions now use only the pure package inventory port and therefore no
longer appear in this effective-discovery caller table.

### `reload_resources`

| Qualified caller | Disposition |
| --- | --- |
| `coding.bootstrap._create_agent_session._create_session.prepare_resource_catalog_refresh` | RCP5.4 produces one source-complete receipt and transfers it to the exact next Catalog bootstrap; it does not commit the loader snapshot. |
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
  `get_prompt_templates`, `refresh_async`, and `reload_extension_generation`;
  `refresh_async` reads only the previous compatibility projection identity to
  distinguish committed Catalog publication from rollback on cancellation or
  cleanup failure; and
- `create_tool_prompt_rebuilder.rebuild`.

RCP4 changes these to a read-only captured-generation projection or focused
Consumer. RCP5 removes Resource/Skill compatibility getter authority.

### Skill list and eager-body sinks

The CLI dynamically reads `getattr(session.resource_bundle, "skills")` and
falls back to `getattr(session.resource_loader, "get_skills")`. The executable
inventory freezes both receiver/operation pairs and also freezes that there are
zero direct `get_skills()` production calls. The fallback is RCP5 deletion debt,
not an alternate supported Catalog route.

The AST `.skills` candidate inventory is intentionally broader than files that
import `ResourceBundle`, so Protocol/dynamic paths cannot disappear from the
gate. Effective/projection sinks are
`commands.resources.list_resource_command_descriptors`,
`extensions.resources._merge_contribution`, both `resources.activation`
paths, `ResourceBundle.merge`, both `AgentSessionAdapterMixin` paths, and
`MethodLoader.discover_methods`. The same inventory separately records legacy
pipeline/discovery field reads and unrelated configuration/source-filter/port
field reads; those candidates must be classified rather than silently filtered
out by an import-name heuristic.

RCP5.3C removes eager reads from neutral prompt preflight and command
projection. The remaining reads are exact, named boundaries: the
`legacy_explicit` command adapter, the `legacy_skill_adapter` used only when a
Method caller selects legacy authority, and the Extension owner normalization
that freezes exact bytes before handing a body-free descriptor to the Catalog
source. The Catalog Extension source may only validate that the descriptor is
body-free; it loads from the generation-owned byte sidecar. The executable AST
inventory freezes those sites so a new neutral sink cannot appear silently.

`MethodLoader` now defaults to `skill_authority="none"`; ordinary `methods/`
resources remain available, while independent Skill discovery requires the
caller-selected `legacy_explicit` compatibility boundary. Catalog-default
Coding therefore does not create a second Skill body authority merely to
preserve skill-backed Method compatibility.

### Package mounts, refresh mutation, and Extension ingress

The live `PackageResourceMount` is constructed only by
`resources.loader._package_mounts_from_legacy_roots` and
`resources.packages.roots.resolve_package_resource_roots`. The private RCP3
package source receives neither raw mount nor path: sibling Resource
orchestration validates exact owner admission and acquires an independent
verified revision lease. The two live mount constructors remain frozen legacy
authority until the RCP4 cutover, after which RCP5 removes their loader role.

The current active-refresh mutation chain is also frozen:

```text
AgentSessionAdapterMixin._prepare_resource_refresh
  -> settings_manager.reload()
  -> SessionPackageController.configure_package_resource_roots
  -> configure_resource_loader_roots
  -> ResourceLoader.set_package_mounts
  -> close every replaced VerifiedRevisionHandle immediately
  -> ResourceLoader.reload_resources
```

`SessionPackageController.refresh_package_resources` is a second caller of the
same configure-then-refresh sequence. Error construction also closes unresolved
mounts in `resolve_package_resource_roots`/`configure_resource_loader_roots`.
These are honest legacy semantics, not the target. RCP4 replaces the whole
active path with pure classification before mutation; `restart_required`
changes nothing, and an adopted generation closes handles only after Consumer
and load leases drain. The initial bootstrap call to
`configure_resource_loader_roots` remains a distinct legacy pre-publication
path until RCP4 replaces it with source-input preparation and joint
publication.

For a Catalog-backed Session, RCP5.4 replaces the final legacy reload/commit
half of this chain. Root configuration still prepares Product-owned loader
inputs, but the resulting reload is consumed exactly once as a source-complete
receipt. The new Catalog generation, not the loader snapshot or
`SkillActivationRuntime`, selects and publishes the effective view. The old
chain remains only behind `legacy_explicit` until RCP5.5 deletes its peer
authority.

Direct Extension Resource merges are currently limited to
`ExtensionResourceRuntime._finish` and `_merge_contribution`. These are
explicit migration debt. RCP4 replaces their publication role with one
Extension-generation `ResourceSourceSnapshot`; RCP5's final gate requires zero
direct Extension `ResourceBundle.merge()` publication sites.

The dynamic ingress inventory additionally freezes:

- initial `ResourceBootstrapRuntime.activate_extensions -> rediscover_resources`;
- `ExtensionRuntime.discover_resources -> ExtensionResourceRuntime.discover`;
- `ExtensionRuntime.discover_resources_async -> ExtensionResourceRuntime.discover_async`;
- `RuntimeResourceDiscovery.discover/discover_async` probing both method names
  with `getattr`; and
- the Session `ResourceRefreshCoordinator` sync/async callback wiring.

Every one of these receives an RCP4 joint-transaction disposition. Deleting only
the direct Bundle merges while leaving a dynamic callback is not a cutover.

## Frozen Behavior Parity

### Precedence and resolution

The implemented source priority is exactly:

```text
temporary > project_local > user_global > external_package > built_in
```

Resolution is Resource-kind-specific:

| Kind | Implemented behavior |
| --- | --- |
| Named Skill and prompt template | The sole candidate in the highest source-precedence tier wins with `source_precedence`; two enabled candidates in that tier reject the identity with no winner and `same_precedence_conflict`. Root order does not break this strict conflict. |
| Theme/permissive exclusive | One winner by source precedence, lower `source_root_order`, canonical name, and path; collisions use `precedence_and_tiebreak`. |
| Extension descriptor | Ordered additive: all enabled candidates remain active after precedence sorting; `all_enabled_candidates_active` records the group. |
| Context | Existing nearest-scope/ordered context semantics outside named prompt collision. |

Disabled candidates cannot win or become active. Every collision retains
candidate evidence and one decision/reason. RCP1 shadow output must match these
rules before any caller moves. A canonical tie-break difference needs an
explicit Product-approved exception; it cannot arrive as incidental
refactoring.

The current post-discovery Extension hook path is a separately frozen legacy
behavior: `ResourceBundle.merge()` appends base and hook-produced duplicate
named Resources in route order, including disabled descriptors. At RCP4 the
joint Catalog applies the normal kind-specific policy instead. Extension hook
candidates inherit their owning Extension descriptor's admitted source class,
scope/root-order facts, and exact generation; they receive no special priority.
This duplicate-resolution change is the one Product-approved parity exception,
must be reported by RCP1 shadow comparison, and cannot affect live behavior
before RCP4.

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
- `tests/harness/test_bootstrap.py` for initial discover/flags/Extension
  rediscovery order; and
- `tests/harness/session/test_resource_refresh.py` for active staged publication,
  rollback/restoration, revision restoration, and retirement order.

### Current Extension publication chains

Initial Session bootstrap is a direct two-phase visible path, not an existing
staged joint publication:

```text
ResourceLoader produces base ResourceBundle
  -> ResourceBootstrapRuntime creates ExtensionRuntime from base descriptors
  -> apply Extension flags
  -> rediscover_resources calls ExtensionRuntime.discover_resources(base)
  -> ExtensionResourceRuntime appends hook output
  -> bootstrap returns the appended Bundle and ExtensionRuntime
```

Active Extension replacement uses a different staged chain:

```text
ResourceLoader reloads base ResourceBundle
  -> PreparedExtensionGeneration.discover_resources_async(bundle)
  -> ExtensionResourceRuntime appends hook output to a new ResourceBundle
  -> candidate.activate(bindings)
  -> candidate.publish(lambda: _commit_resource_generation(discovered))
  -> prior Extension generation retires
```

Only the second chain already has a staged Extension publication boundary;
neither chain has the target single Catalog composition. RCP4 replaces both:
initial construction keeps everything unpublished until the Session Graph/joint
commit, while active replacement preserves the existing preflight, rollback,
view/revision restoration, commit-before-retire, and cancelled-cleanup evidence.
Both move hook output before the final Catalog proposal and publish Extension
state, Catalog generation, and read-only projection in one no-await commit. No
intermediate Bundle is a second Catalog generation.

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
new extension point. RCP3 has deleted Package Catalog's former
`_summarize_package_resources -> ResourceLoader.discover_resources` bridge; an
architecture gate now requires the Catalog to use only its pure inventory port
and forbids target `ResourceCatalogSnapshot`, `ResourceSourceSnapshot`,
Catalog-engine, or `resource.catalog` symbols there. Package/embedded source
adapters also have executable gates against Capability reverse imports, raw
package-path reads, and nested Graph/registry/MCP routes.

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
