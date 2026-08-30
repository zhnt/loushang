# Plugin Lifecycle PLC6: `coding.base` Production Contract

## Status and scope

This contract freezes the conservative production migration of the
document-backed `coding.base` Plugin after Resource Catalog RCP5 and the
`coding.lsp.default` PLC5 Graph proof. `coding.base` is a Product-owned Plugin
ID, not a Capability ID, Graph node, Resource registry, or Session owner.

PLC6 is complete only after Prompt, Skill, Tool, and Command contributions use
their existing exact owners and every peer CLI/bootstrap publisher is deleted.
PLC6 does not publish the general Plugin SDK, implement `coding.arch.default`,
or move Product identity, safety, workspace ceilings, Session correctness, or
Model Input commit out of the Coding Kernel.

Implementation checkpoint (2026-08-30): PLC6A through PLC6E are implemented. The
checked-in data-only package is selected by the default `coding-standard`
request and enters Resource discovery through an independent verified lease,
without a hidden settings source. The Catalog-owned production path now uses
the Kernel Prompt and publishes the standard Prompt and Skill from the exact
package generation. A combined Product selection preserves configured
Resource Plugin compatibility while retaining the Composition Set policy and
trust provenance for `coding.base`. The configured Resource receipt first joins
its verified packages with `coding.base` and optional `coding.lsp.default`; one
prepared Product compilation then feeds Resource Catalog and the same base-only
or combined base/LSP Session without recompiling owner admission. The admitted Tool and Command packs stage
through `tools.workspace` and `commands.session`, publish atomically with the
usable Session, enter effective-runtime provenance, and retire through their
exact generations. The peer CLI Tool registrar and unconditional standard
Command publication are absent from the Catalog-owned production path.
PLC6D now intersects the standard request with the one durable Coding Product
management snapshot. A truly unseen first-party Installation is installed and
enabled only by idempotent `PluginManagementService` commands; a retained
disabled or removed Installation is never resurrected. New Sessions activate
and lease the exact selected Instance Revision, while an existing Session pins
its old family and reports `coding_base_management_restart_required` after an
update, disable, or remove. Selected content-addressed revisions reopen from
the durable binding lock without consulting a deleted mutable source. PLC6E
removes the Coding Resource-authority type, SDK/CLI parameter, peer CLI Tool
registrar, legacy Method adaptation, and conditional bootstrap/LSP/refresh
branches. Every Coding Session now requires one Catalog input receipt and one
Catalog-owned publication. Final production review remains.

## First principles

1. The Coding Kernel boots without an optional Plugin and makes no claim about
   an absent Tool, Command, Skill, prompt section, process, or Provider.
2. A Composition Set is an inert Product policy request. It cannot install,
   enable, select, admit, publish, refresh, retire, or remove a Plugin.
3. `PluginManagementService` remains the only durable desired-state command
   authority. The existing Plugin selection path consumes one resolved desired
   state; a Composition Set cannot override an explicit disable or removal.
4. Each contribution is published and retired only by its existing exact
   owner: Resource Catalog for Prompt/Skill, Tool owner for Tool definitions,
   and Session Command owner for Command definitions.
5. Package, declaration, owner admission, Product compilation, generation,
   Model Input, and management provenance remain one reconstructible chain.
6. Compatibility adapters may forward reads from the owner projection but may
   not select, merge, register, publish, refresh, or dispose the same object.

## Composition Sets

The Product recognizes exactly three names:

| Set | Flattened request |
| --- | --- |
| `coding-minimal` | Kernel plus mandatory Harness capabilities; no optional Plugin |
| `coding-standard` | minimal plus required `coding.base` and optional `coding.lsp.default` mounted `on_demand` |
| `coding-architecture` | standard plus optional `coding.arch.default` mounted `on_demand` |

Expansion occurs once and produces a canonical, fingerprinted Product request
with the exact expansion chain. It is not persisted as management state and is
not a Runtime Profile. A later Product assembly step intersects the request
with the exact durable management snapshot and available verified package
revisions before the existing selection authority constructs one
`PluginSelection`.

The default Product request is `coding-standard`. `coding-minimal` never
silently falls back to direct built-in registration. Selecting a set does not
self-enable a disabled Plugin. First-party default installation, when needed,
is an idempotent Product bootstrap command submitted through
`PluginManagementService`, not a special selection branch.

## Prompt boundary

The mandatory Kernel retains Product identity, domain goals, project
instruction handling, risk/approval/Sandbox/workspace ceilings, Session and
turn correctness, transcript/compaction/artifact semantics, recovery,
diagnostics, presentation policy, and complete Model Input commit.

Statements that standard Tools can read/write files, edit code, or execute
commands, plus Tool-specific preference text, belong to an admitted
`coding.base` prompt Resource. Tool usage details are still derived from the
selected Tool definitions. The Kernel must remain truthful under
`coding-minimal`, explicit `--no-tools`, disabled `coding.base`, owner admission
failure, and rollback.

PLC6A originally exposed this split as a shadow target while preserving the
compatibility prompt byte-for-byte. PLC6B atomically changed the Catalog-owned
production default to the Kernel and supplies the standard fragment through
the Catalog generation; there is no interval in which both fragments publish.
PLC6E deletes the former Coding rollback selector, so the compatibility Prompt
cannot become a second production writer.

## Owner cutover order

1. Check in the exact data-only `coding.base` package and prove declaration,
   trust, admission, Product compilation, and package-revision custody without
   live publication.
2. Publish Prompt and Skill through the sole Resource Catalog and delete their
   direct default inputs in the same atomic cutover.
3. Stage admitted Tool and Command packs through their exact owners, publish
   only with the usable Product Session, and delete direct CLI/bootstrap
   registration in the same atomic cutover.
4. Bind Composition Set selection to management desired state, including
   disable, update, remove, active-Session `restart_required`, and exact replay
   after source removal.
5. Delete the Coding legacy Resource-authority selector and every production
   caller of legacy discovery or direct Tool publication.

No slice may retain two effective writers for rollback convenience.

## Required production evidence

- `coding-minimal` starts, has a truthful Kernel prompt, and publishes no base
  Resource, Tool, or Command contribution;
- `coding-standard` preserves the supported Prompt, Skill, Tool, and Command
  behavior through the production Plugin chain;
- disabled or removed `coding.base` changes only new Sessions while existing
  sealed Sessions retain their pinned generation and report the exact restart
  requirement;
- a failed owner stage leaves no partial Resource, Tool, or Command publication
  and never falls back to a direct registrar;
- update and remove preserve package-to-generation and Model Input evidence
  after mutable source deletion; and
- source scans prove no old caller can independently publish or dispose a base
  Prompt, Skill, Tool, or Command.

After implementation, PLC6 receives fresh architecture, correctness/security,
and Product/test reviews. All P0-P2 findings are fixed before the complete
Harness and relevant Coding gates pass.
