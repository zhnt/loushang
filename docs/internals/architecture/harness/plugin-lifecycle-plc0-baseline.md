# Plugin Lifecycle PLC0 Baseline

## Status

- Slice: PLC0 Baseline And Authority Inventory.
- Source baseline before PLC0: `862fae8f`.
- Implemented resolve-once and inert-selection chain:
  `52d205ac` -> `a2325422` -> `1fc6bcbc` -> `0965fa29`.
- PLC0 executable baseline commit: `25cfc170`.
- Result: implemented locally; PLC0 focused gates are green.
- Tracking issue: not yet bound. GitHub authentication was unavailable during
  local execution. Do not open or merge PLC1 without attaching the work to a
  tracking issue as required by the high-risk lifecycle workflow.

This baseline supports the
[Unified Plugin Lifecycle And Coding Pluginization Delivery Plan](plugin-lifecycle-coding-pluginization-plan.md)
and the
[Unified Plugin Authoring Primitives Delivery Plan](plugin-authoring-primitives-delivery-plan.md).
It records source-backed facts only; it does not claim that PLC1 declaration
codecs or any executable Plugin evaluator exist.

## Resolved Baseline Failures

The pre-PLC0 architecture suite had 14 passing tests and three failures.
PLC0 classified and resolved each failure without a directory-level exemption:

| Failure | Classification | Resolution |
| --- | --- | --- |
| Architecture phrase expected `one manifest parser` | Stale prose assertion; the accepted document already states the stronger `Every manifest format has one parser` invariant | Assert the accepted invariant instead of changing architecture prose to satisfy a stale phrase |
| `revisions.py` contained another static `plugin.json` literal | Avoidable path re-derivation after canonical parsing | Project the published manifest locator from `ResolvedPluginPackage.manifest_path.relative_to(package.root)` |
| Verified revision and Package mount reads appeared as unowned boundary sinks | Legitimate immutable revision publication/verification and Resource mount reads, not manifest parsers | Retain exact qualified function sites and assign a named boundary owner to each |

The `plugin.json` static-site inventory therefore remains limited to the
canonical Plugin parser and the Package manifest adapter. Verified revision
projection consumes the already resolved descriptor and does not recreate the
manifest path literal.

## Qualified Plugin/Package Boundary Owners

The architecture test freezes exact `(file, qualified function)` sites. The
current owner classes are:

| Owner classification | Authorized responsibility |
| --- | --- |
| `plugin-manifest-parser` | Parse/revalidate the canonical Plugin manifest |
| `package-manifest-parser` | Parse Package manifests and delegate Plugin manifests to the canonical parser |
| `package-materializer` | Read trusted-source, lockfile and remote-version materialization inputs |
| `package-catalog` | Read the Package catalog input |
| `verified-revision-publisher` | Copy and digest source files into one immutable revision |
| `verified-revision-boundary` | Open no-follow verified directories/files and recheck identity |
| `package-resource-mount` | Read a contained Resource through the verified revision handle |

Adding any new read/open/JSON sink under the Plugin or Package roots fails the
architecture inventory until its exact function is reviewed. A broad package-
directory exemption is forbidden.

## Frozen Foundation Public Surface

PLC0 freezes the current semantic foundation used by later slices:

- Capability: `CapabilityDefinition`, `CapabilityRequirement`,
  `CapabilityBundleProvider`, `CapabilityProviderContext`,
  `CapabilityBundleProviderBinding`, `RuntimeCapabilityGraphPlan`, Planner and
  Binder;
- Runtime: `RegistrationOwner`, `RegistrationLease`, and `RegistrationScope`;
  and
- Plugin: contribution reservation/index, `PluginDeclaration`, published
  package, verified revision handle, resolution authority, inert selection
  candidate, and `PluginSelectionResolver`.

The following target symbols remain absent from the public Plugin surface until
their accepted delivery gates: `PluginDefinition`, evaluator/builder,
`CapabilityComponentHost`, `ProductCapabilityProviderResolver`,
`PluginManagementService`, and any mutable `PluginContext`.

This is a compatibility baseline, not a promise that every current Plugin
symbol is a stable third-party SDK. PLC8 remains the stable SDK gate.

## Forbidden Peer Routes

The executable inventory now fails when:

- the inert `harness.resources.plugins` layer imports Coding, Session,
  Registration, Provider binding, Graph planning/binding, or Graph runtime
  modules;
- the inert Plugin layer adds an executable loading call such as
  `import_module`, `exec_module`, `run_path`, or `__import__` before PLC3's
  reviewed Approval/import-start path;
- a second `RuntimeCapabilityGraphBinder` construction site appears outside the
  Session composition root;
- a new raw Plugin/Package read or JSON parse site appears without an exact
  boundary owner;
- another Graph private-state mutation appears outside the existing qualified
  owner inventory; or
- pre-SDK Plugin Definition, Component Host, management, Product Provider
  resolver, or mutable Plugin context symbols appear on the public Plugin
  surface.

Future accepted slices must revise the exact inventory and add behavioral tests
at the new owner seam. They may not disable the guard or exempt a directory.

## Published Synthetic Plugin Fixture

`tests/harness/resources/plugins/conftest.py` now provides one reusable
`published_synthetic_plugin` fixture. It:

1. creates an executable-shaped `capability_provider` reservation;
2. includes an entrypoint whose import would write a marker outside the package;
3. resolves through `PluginResolutionAuthority`;
4. publishes an immutable content-addressed revision;
5. locks its dependency closure and creates a durable source binding; and
6. proves the marker remains absent and no public evaluator exists.

The fixture intentionally stops before executable preflight/evaluation and
before any owner admission or Graph binding. PLC1 may reuse it for strict
payload/builder tests; PLC3 must extend the fixture only after durable Approval
consumption exists.

## Verification Evidence

PLC0 completed with:

```text
.venv/bin/python -m pytest \
  tests/architecture/test_unified_plugin_architecture.py \
  tests/harness/resources/plugins/test_revisions.py \
  tests/harness/resources/packages/test_mounts.py \
  -q --skip-host-runtime
# 29 passed

.venv/bin/python -m pytest \
  tests/harness/resources/plugins \
  -q --skip-host-runtime
# 70 passed

.venv/bin/ruff check <PLC0 changed Python files>
# All checks passed

git diff --check
# passed
```

The final combined focused rerun is required after this status document is
indexed. PLC0 does not authorize PLC2 or later security/lifecycle source work.

## PLC1 Entry Gate

PLC1 is technically eligible when the final combined focused rerun remains
green and the tracking issue is attached. Its first change must remain inert:

- no Plugin import, process launch, owner admission, Graph bind, Resource
  publication, or public stable SDK;
- one typed `capability_provider` payload codec over existing semantic types;
- one reservation-bound internal builder;
- strict canonical JSON, locator containment and duplicate rejection; and
- rollback by deleting the codec/builder with no live-state cleanup.
