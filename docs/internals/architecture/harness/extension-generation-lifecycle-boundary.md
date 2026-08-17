# Extension And Resource Generation Lifecycle Boundary

## Status

Status: implemented for integration into `lane/harness`.

## Decision

One session keeps one stable `ExtensionRunner`. Reload builds an unpublished
candidate generation rather than mutating that runner in place. The ordered
pipeline is:

1. reload Extension and resource declarations;
2. let the candidate discover its resource contributions;
3. stage candidate live contributions under exact Extension/generation owners;
4. publish the candidate runtime state and resource bundle at one synchronous
   boundary; and
5. reverse-retire the replaced generation after publication.

The stable runner is the only Extension dispatch/runtime owner. Candidate
generations reuse its composition state and existing registration primitives;
they are not a second plugin container, service locator, Capability graph, or
event bus.

## Registration Ownership

Each admitted Extension has a `RegistrationOwner` containing Extension ID,
stable runtime ID, and generation. `ExtensionGenerationRegistrations` collects
the exact `RegistrationLease` values produced during admission and any later
hook/API mutation. Admission uses one setup `RegistrationScope`; post-publish
mutations use committed one-entry scopes. Unload disposes scopes and owners in
reverse order, joins asynchronous cleanup before cancellation wins, and never
removes a same-name registration belonging to another owner.

Tool and Provider registries preserve their compatibility facades. The live
generation path uses exact identities, invisible staged layers, and layered
winner restoration. `RegistrationScope.commit()` activates staged leases at
the synchronous publication point; partial activation rolls back in reverse
order before the error escapes. A generation-scoped Provider removal is an
owner-scoped tombstone layer, not a call to the compatibility facade's global
name deletion; candidate rollback therefore reveals the previous winner. The
bootstrap Tool compatibility entry can be adopted in place by generation 1
only when both the exact `ToolDefinition` and source provenance match. A
same-name Product Tool rejected during bootstrap conflict resolution is not
adopted or rebound by the Extension runtime. Provider actions from one owner
reduce in call order, including staged register/register and
unregister/register sequences. Owner-scoped Provider tombstones temporarily
detach associated source-scoped API adapters through an opaque AI-owned
restoration token, so rollback restores both surfaces exactly. Commands, hooks,
flags, shortcuts, renderers, and resource declarations remain data in the
immutable Extension composition; publication swaps that composition rather
than inventing live registry tokens for every declaration.

## Publication And Failure Semantics

Before publication, staged Tool/Provider layers are not effective winners.
Synchronous initial admission failure uses each lease's exact non-awaiting
rollback and resets the setup scope, so retry cannot inherit hidden staged
entries. Failure or cancellation of an asynchronous candidate invalidates only
the candidate binding state and reverses every candidate registration. The old
runner state, resource bundle, registrations, and previously issued context
leases remain authoritative and usable.

Publication performs no await. The runner composition and resource bundle are
changed in the same synchronous call. If resource commit or view rebuild fails,
both are restored before the error escapes and candidate registrations are
rolled back. After successful publication, old context leases become stale and
the new generation remains authoritative even when the caller is cancelled
while joining old-generation cleanup. Failed cleanup remains retained for a
later retry; an exact disposer that already succeeded is not invoked again.

When a Product supplies no reloadable resource bundle, the staged session port
activates or refreshes the existing generation instead of manufacturing an
empty replacement. Products with another Extension runtime retain the previous
invalidate-refresh-bind compatibility path unless they explicitly expose the
staged-generation seam.

## Persistence Boundary

Candidate activation through publication or rollback, old-generation
retirement, and shutdown cleanup share one runner-local lifecycle gate.
Shutdown marks the runner disposed before releasing that gate, so an already
prepared candidate cannot publish after cleanup and all later bind/refresh/API
mutations fail closed. The whole shutdown and retirement sweep, rather than
only one disposer, joins cleanup before caller cancellation is re-raised.
Retryable retired-generation cleanup remains owned by the runner until a later
attempt succeeds. Publication failure restores the previous resource and view
after registrations have synchronously rolled back but before asynchronous
candidate disposal begins.

Generation state and live callbacks are not transcript facts. A prepared model
request continues to commit canonical prompt, message, Tool-schema, options,
and Provider payload material through the existing Model Input transcript
protocol. Historical reconstruction therefore uses committed inline facts and
does not read a removed Extension source file or inspect the current live
generation. This change does not introduce an Artifact store.

## Product Binding

Harness owns candidate preparation, exact registration collection, staged
resource publication, rollback, retirement, and shutdown cleanup. Products
supply resource loading, settings activation, Tool/Provider bind ports,
diagnostic projection, and prompt/tool view rebuild. Provider credentials,
Extension trust/admission policy, Product prompts, and presentation remain
outside this boundary.

## Non-Goals

- no arbitrary hot replacement across dependent Capability graphs;
- no generic transaction manager or global plugin context;
- no conversion of each Extension contribution into a top-level Capability;
- no change to hook failure containment; and
- no new Blob/Artifact persistence protocol.

## Verification

- failed and cancelled candidates preserve the old generation and context;
- staged same-name Tool and Provider layers remain invisible until scope
  commit, including partial-activation rollback;
- a successful publication makes the new winner visible before disposing the
  old exact registrations, and repeated retirement is idempotent;
- resource publication failure restores the previous bundle and runtime;
- Tool and Provider layer removal cannot clobber the current same-name winner;
- bootstrap Tool adoption verifies definition and source provenance, initial
  admission retry has no hidden leases, and same-owner Provider actions retain
  call order across tombstones;
- owner-scoped Provider removal masks and restores associated API adapters;
- session shutdown excludes concurrent candidate publication and retains
  retryable cleanup ownership; and
- Tool schemas loaded through an actual Extension and effective Tool registry
  rebuild from committed Model Input facts after unload and source removal.
