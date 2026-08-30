# PLC7 `coding.arch.default` Second-Provider Contract

## Status And Authority

- Authority: frozen PLC7 delivery contract under Plugin Architecture V2 and
  the accepted Capability dependency/mount lifecycle.
- Baseline: PLC6 production validation on `main` at `7c542e59` plus the owner-
  accepted Plugin architecture baseline at `a76eb658`.
- Delivery status: implementation candidate complete under issue `#507`;
  terminal three-view review is pending.
- Scope: the first-party `coding.arch.default` Provider, its sibling Tool pack,
  private indexed state, and Coding Product composition. This contract does not
  publish the PLC8 author SDK or add a second Graph, Plugin, Tool, or state
  authority.

## Decision

`coding.arch.default` is the second complete-Bundle Capability Provider. It
uses the same package resolution, declaration, execution Approval, exact-owner
admission, Component Host, Session Graph, owner-generation, Product Session,
and retirement path as `coding.lsp.default`.

PLC7 must replace the LSP-shaped Product composition seam with one Coding
Capability-Plugin composition that accepts an ordered set of first-party
Provider specifications. LSP and Arch may keep private Product adapters, but
they cannot own peer composition roots or independently publish Session graphs.

The Arch Bundle is independent of LSP in PLC7:

```text
coding.arch -> harness.workspace(read, list, search)
```

Review found that LSP's current `semantic` facet is a session-control surface,
not a neutral architecture-fact protocol. PLC7 therefore does not declare a
synthetic peer dependency. A later tranche may add an optional edge only after
Coding accepts a narrow consumer-owned fact port and an LSP adapter for it:

```text
coding.arch -. optional .-> coding.lsp(semantic)
```

## Exact Identities

| Concern | Identity |
| --- | --- |
| Plugin | `coding.arch.default` |
| Provider contribution | `coding-arch-default` |
| Capability | `coding.arch` contract v1 |
| Tool contribution | `coding-arch-tools` |
| Tool catalog | `coding.arch.tools` revision 1 |
| Tool | `inspect_import_graph` |
| Provider source | checked-in verified first-party package revision |
| Product scope | exact Coding Session scope |

The Capability exposes only consumer-relevant typed facets:

- `analysis` for deterministic analyzer operations;
- `tool-runtime` for the admitted sibling Tool pack; and
- `diagnostics` for bounded analyzer/cache diagnostics.

Language providers, fact cache records, index files, migration locks, and quota
accounting remain private Bundle internals. They do not become ambient services
or public Plugin facets.

## Product Configuration And Private State

The Provider receives one strict versioned binding document containing the
absolute workspace root, an absolute Product-owned private-data root, the
private-state schema version, and a positive byte quota. Unknown, missing,
relative, boolean-as-integer, or out-of-range values fail before activation.

Private indexed state follows these rules:

1. its path comes only from Product binding inputs and is never derived from
   mutable Plugin source bytes;
2. every durable file is schema-versioned and atomically replaced;
3. an incompatible schema is fenced and rebuilt or migrated by an explicit
   versioned operation, never interpreted optimistically;
4. a failed write retains the last complete version;
5. quota is checked before publication and cannot be bypassed by cache refresh;
6. disable, remove, retirement, and private-data deletion remain distinct; and
7. the Provider disposer closes only its own generation and never deletes
   private data.

## Provider And Tool Ownership

The Provider factory receives only declared dependency facets and immutable
binding inputs. It returns one Bundle whose facets share one runtime owner. The
disposer rejects a foreign or mixed-owner Bundle and is idempotent for the exact
owner generation.

The document-backed sibling `tool_pack` requires only the `tool-runtime` facet.
The Tool owner stages `inspect_import_graph` invisibly, commits it only after
the Capability generation is usable, and retires it before Provider disposal.
`on_demand` controls initial Tool activation, not Provider identity or trust.

No CLI/bootstrap caller may directly call `register_coding_arch_tools()` after
the cutover. Compatibility exports may remain only if they cannot construct,
register, publish, or retire a live Tool.

## One Composition And Lifecycle

For a `coding-architecture` Session, Product compilation performs one ordered
operation:

```text
resolve Base/LSP/Arch package revisions
  -> compile one Product Plugin plan and selection
  -> approve executable Definition groups
  -> admit both Capability Providers and sibling Tool packs by exact owner
  -> construct one Component Host
  -> bind Workspace, LSP and Arch in one Session Graph
  -> capture typed Tool consumers
  -> stage and atomically publish all owner generations
  -> publish the usable Product Session
```

Failure at any point rolls back staged Tool generations and constructed
Providers in reverse dependency order. No failure falls back to direct Arch
construction or Tool registration.

Active Sessions pin their exact Arch package, Instance, private-state schema,
Capability generation, and Tool admission. Update/disable/remove affect only
new Sessions and yield the same restart-required evidence used by the common
Plugin lifecycle. Retirement is complete only after Tool and Capability owner
receipts settle; cleanup retry cannot report a false terminal state.

## Ordered Delivery

1. **PLC7A — contract and source inventory.** Freeze identities, facets,
   configuration, private-state rules, peer callers, and executable gates.
2. **PLC7B — inert package and Provider seam.** Add strict package declarations,
   typed Provider/Consumer adapters, and unit conformance without production
   selection.
3. **PLC7C — shared Coding Capability composition.** Generalize the LSP-shaped
   composer into one multi-Provider Product composition and prove one Graph.
4. **PLC7D — production cutover.** Select Arch through `coding-architecture`,
   bind its Tool owner, and delete every direct Tool publication caller.
5. **PLC7E — private-state and dependency-boundary proof.** Close quota,
   migration fencing, rollback, absent-LSP behavior, and prove that no private
   LSP implementation dependency substitutes for a neutral fact port.
6. **PLC7F — production validation and three-view review.** Run cross-platform
   gates, then architecture, correctness/security, and Product/test review;
   fix and re-review every blocking finding before PLC8.

## Exit Gate

PLC7 is complete only when executable evidence proves:

- a second Capability required no new Plugin lifecycle or Graph path;
- Arch works deterministically with LSP absent or disabled;
- Arch declares no LSP dependency until a neutral semantic-fact port exists;
  any future edge must be typed and cannot use an ambient lookup;
- `inspect_import_graph` is never visible without its exact live Arch runtime;
- direct `register_coding_arch_tools()` production callers are deleted;
- private state is versioned, quota-bounded, rollback-safe, and not implicitly
  deleted by disable/remove;
- update, disable, remove, Session pinning, retirement, and recovery evidence
  use the common lifecycle; and
- all focused/full gates and the final three-view re-review pass.
