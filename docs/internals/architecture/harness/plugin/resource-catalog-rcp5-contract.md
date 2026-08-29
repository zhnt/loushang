# Resource Catalog Skill Convergence (RCP5)

## Status and scope

This is the implementation contract for the conservative RCP5 migration. It
refines the Resource Catalog pluginization plan only for Skill consumers. The
RCP5.1 slice introduces an internal, exact-generation typed Skill projection
and lazy body-load path. It does not change the default Coding bootstrap, CLI,
Session publication, refresh, activation, or compatibility loader behavior.

Production cutover starts only after the RCP5.1 contract and implementation
receive a fresh source-backed review. Stable public Resource authoring remains
deferred to RCP6/PAP7.

## First principles

1. A Skill is a Resource, not a Plugin and not a second Capability.
2. The `harness.resources` Catalog is the sole effective-selection authority.
3. A Consumer observes one immutable Catalog generation for its whole use.
4. Listing metadata never grants body-read authority.
5. A body is read only through an opaque handle minted by the captured
   generation and returns a receipt for the exact observed bytes.
6. Compatibility shapes may be projected from the Catalog, but cannot merge,
   select, activate, refresh, or rediscover Resources.
7. Product policy owns activation inputs; the Skill Consumer only reports the
   resulting Catalog state.

No top-level `harness.skills` package, Skill registry, ambient service locator,
or Product-specific Resource path is introduced.

## Authority and dependency direction

```text
Product policy + admitted source handles
  -> harness.resources owner generation
  -> immutable Resource Catalog + descriptor projection
  -> exact Graph capture of resource.catalog + resource.load
  -> typed Skill Catalog Consumer
       -> metadata summary
       -> Skill-only opaque load handle
       -> validated body + receipt
  -> Product presentation / Model Input / compatibility adapters
```

The Resource owner generation is the sole writer of Catalog selection,
generation identity, load handles, and load receipts. The typed Skill Consumer
is a read-only projection. CLI, prompt, command, and Model Input code are
downstream Consumers and never write Catalog state.

The typed Consumer lives below `loushang.harness.resources`; Capability code
only exposes the already-owned projection together with the existing Catalog
and load facets. This keeps Skill semantics with the Resource owner and keeps
the Graph free of a Skill-specific Capability.

## RCP5.1 typed Consumer contract

One Consumer is constructed from a single captured
`ResourceCatalogCapabilityConsumer`. Construction fails closed unless:

- the Catalog snapshot and descriptor projection name the same generation and
  snapshot fingerprint;
- every selected Skill descriptor is bound to an effective Skill candidate;
- descriptor identity and candidate identity agree; and
- every body-bearing Skill has discovery-bound digest and length evidence.

The first Consumer exposes immutable effective `SkillCatalogSummary` values. A
summary carries identity, canonical naming, effective/model-invocation result,
provenance, diagnostics, media type, and expected body identity. It deliberately
carries no Skill body. RCP5.1 does not expose inactive candidates: RCP5.2 must
add a Catalog-owned status projection before activation-status or all-Skills
listing can move off the legacy path.

`load_handle(summary-or-name)` resolves only a summary owned by this Consumer
and wraps the exact Resource load handle as a Skill handle. `load(handle)`
rejects foreign generation, snapshot, candidate, and non-Skill handles before
delegating to `resource.load`. A successful load returns UTF-8 Skill content
plus the validated Resource receipt. The receipt, not a mutable path or later
rediscovery, is the evidence for the body.

RCP5.1 remains internal and opt-in. Its rollback is removal of the new Consumer
and projection facet accessor; no persisted state or Product default changes.

## Ordered cutover

RCP5 proceeds in independently reviewable steps:

1. **RCP5.1 — typed read path:** add the exact-generation Skill Consumer and
   lazy body-load proof without changing Product callers.
2. **RCP5.2 — read-only projections:** add a Catalog-owned inactive/status
   projection, then move CLI listing, activation status, prompt summaries, and
   command enumeration to the Consumer. Delete the
   `resource_bundle.skills -> resource_loader.get_skills()` fallback in the
   same slice.
3. **RCP5.3 — body and evidence:** move explicit Skill load and Model Input
   evidence to the receipt-bearing lazy path. Preserve current-request
   immutability during refresh and uninstall.
4. **RCP5.4 — refresh authority:** route Resource refresh through next Catalog
   generation publication; remove duplicate Skill/Resource watcher refresh and
   independent disabled-name state.
5. **RCP5.5 — peer deletion:** make `SkillLoader` and `ResourceLoader`
   forwarding-only while compatibility callers remain, then remove the
   adapters and production effective-selection imports when inventory reaches
   zero.

No step may retain a silent fallback to the previous authority. A compatibility
adapter must either forward to one captured Catalog Consumer or fail with a
finite unsupported-state error.

## Compatibility and non-goals

RCP5.1 intentionally does not:

- enable the RCP4 Catalog bootstrap by default;
- alter Skill precedence, activation, discovery roots, or CLI output;
- remove eager bodies from the existing RCP4 compatibility projection;
- implement refresh, live generation replacement, or Model Input persistence;
- migrate Coding built-ins into `coding.base`; or
- publish an SDK.

The eager compatibility projection is explicit deletion debt. It may remain
only until RCP5.3 because current prompt/command/session compatibility paths
still consume `ResourceBundle`. New RCP5 consumers may not use its body as
authority.

## Exit gates

RCP5.1 is complete when focused tests prove:

- metadata listing contains no body;
- same-generation lazy load returns the original bytes as UTF-8 plus the exact
  receipt;
- foreign summary/handle and non-Skill handle use fail closed;
- disposal invalidates later body loads through the owner generation; and
- the default Product and public SDK surfaces remain unchanged.

Full RCP5 is complete only when every Skill operation uses one Catalog path,
legacy discovery and disabled-state peer writers are gone, direct Extension
`ResourceBundle.merge()` publication is forbidden, and current-request plus
replay evidence is proven across refresh and uninstall. Only then is PLC6
unblocked.
