# Resource Catalog Skill Convergence (RCP5)

## Status and scope

This is the implementation contract for the conservative RCP5 migration. It
refines the Resource Catalog pluginization plan only for Skill consumers.
RCP5.1 implements an internal, exact-generation typed Skill projection and
lazy body-load path. RCP5.2A implements the owner-native body-free candidate
status substrate. RCP5.2B now mounts exact-v4 for the default admitted Coding
Resource Catalog and routes read-only Skill consumers to one captured
generation. It does not yet authorize refresh, explicit body use, or
compatibility-loader deletion.

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

The typed Consumer lives below `loushang.harness.resources`. The eager RCP4
compatibility projection stays owner-private. An opt-in internal
`harness.resources` v3 Provider derives a distinct body-free Skill projection
before Graph publication and exposes it through the existing Catalog facet
together with the load facet. The v2 facet contract remains unchanged. This
keeps Skill semantics with the Resource owner and keeps the Graph free of a
Skill-specific Capability or facet.

## RCP5.1 typed Consumer contract

One Consumer is constructed from a single exact-v3
`ResourceSkillCatalogCapabilityConsumer`. Construction fails closed unless:

- the Catalog snapshot and descriptor projection name the same generation and
  snapshot fingerprint;
- every selected Skill descriptor is bound to an effective Skill candidate;
- descriptor identity and candidate identity agree; and
- every body-bearing Skill has discovery-bound digest and length evidence.

The first Consumer exposes immutable effective `SkillCatalogSummary` values. A
summary carries identity, canonical naming, effective/model-invocation result,
typed Catalog diagnostics, provenance, media type, and expected body identity.
It deliberately carries neither Skill body nor an opaque metadata bag; source
frontmatter is projected only through the explicit typed fields. RCP5.1 does
not expose inactive candidates: RCP5.2 must add a Catalog-owned status
projection before activation-status or all-Skills listing can move off the
legacy path.

`load_handle(summary-or-name)` resolves only a summary owned by this Consumer
and wraps the exact Resource load handle as a Skill handle. `load(handle)`
rejects foreign generation, snapshot, candidate, and non-Skill handles. Before
delegating, it re-mints the canonical Resource handle from the captured owner
and requires full handle equality, including source generation, locator,
schema, media type, digest, and length. A successful load returns UTF-8 Skill
content only after the receipt is independently rebound to that handle and the
summary. The receipt, not a mutable path or later rediscovery, is the evidence
for the body.

RCP5.1 remains internal and opt-in. Its rollback is removal of the new Consumer
and private v3 contract; v2, persisted state, and Product defaults are unchanged.

## RCP5.2 admission and status contract

RCP5.2 is admitted only after the RCP5.1 source-backed architecture,
correctness/security, and Product/test reviews approve the implementation and
the full Harness gate passes. It is delivered as two ordered, separately
reviewable commits; the first commit does not authorize Product cutover.

### RCP5.2A — owner-native status substrate

The owner generation builds one immutable, body-free Skill status projection
before publication. Its only inputs are the exact Catalog snapshot and the
complete set of source-validated descriptor bindings already admitted into
that generation. It does not derive inactive state from the effective-only
compatibility projection.

The projection contains one record per valid Skill candidate, including
inactive, shadowed, and conflict-rejected candidates. Every record is pinned to
the Catalog generation and snapshot fingerprint and contains:

- Resource identity and candidate fingerprint;
- explicit, typed naming, description, provenance, source path, diagnostics,
  media type, and expected body digest/length fields;
- declared-enabled, effective, primary, and model-invocable facts; and
- one finite status plus the Catalog merge-decision reason.

The finite candidate statuses are `effective`, `inactive_activation`,
`inactive_declaration`, `shadowed`, and `rejected_conflict`. The projection
maps these statuses exclusively from the Catalog candidate, effective entry,
and merge decision. It preserves the decision's candidate order and never
re-runs source precedence, activation matching, conflict resolution, or merge
policy in a Consumer. A candidate must have exactly one matching descriptor
binding; missing, duplicate, foreign, or fact-inconsistent bindings fail owner
generation construction.

No status record contains body content, prompt text, an opaque locator, or a
generic metadata bag. A status record does not grant load authority. Existing
exact-v2 and exact-v3 Graph contracts remain unchanged during RCP5.2A, and the
default Product continues to use v2.

### RCP5.2B — exact-v4 read-only cutover

Status publication uses a new private exact-v4 `harness.resources` contract.
It is not added to exact-v3: exact contracts are immutable even when private.
The v4 Catalog facet exposes the effective projection and status projection
from the same captured owner generation; `resource.load` remains unchanged.

Only after RCP5.2A receives fresh source-backed review may the default Product
mount v4 and capture one typed Skill Consumer. In the same cutover slice:

- CLI all-Skills listing reads status records and deletes the
  `resource_bundle.skills -> resource_loader.get_skills()` fallback;
- activation display reads declared/effective/status facts without consulting
  settings or a second disabled-name store;
- prompt Skill summaries and command enumeration read only effective summaries
  and declared descriptions; and
- missing or incompatible v4 capture fails with a finite construction error,
  never a legacy fallback.

Command execution and explicit Skill body use remain on their current
compatibility path until RCP5.3; RCP5.2 moves enumeration and summaries, not
body authority. Refresh remains RCP5.4 debt. This prevents a read-only cutover
from silently expanding into body or generation-replacement semantics.

RCP5.2 exits only when tests prove deterministic status classification for
activation-disabled, declaration-disabled, shadowed, and same-precedence
conflict cases; exact-v2/v3/v4 negotiation isolation; no metadata operation
loads a body; Product construction captures one generation; CLI and command
enumeration use no legacy Skill fallback; and rollback can remove v4 wiring
without changing persisted settings or v2/v3 behavior.

RCP5.2A is implemented owner-private in
`loushang.harness.resources._skill_catalog_status`. The prepared Resource owner
generation retains the projection under the same custody as its Catalog
snapshot and drops access when that generation retires. RCP5.2A adds no public
staged-candidate accessor or Graph facet; publication remains exclusively an
RCP5.2B exact-v4 concern.

The RCP5.2B implementation is wired for every admitted initial
Resource Catalog. Such a Product Session mounts exact-v4, captures one typed
Consumer, and uses it for CLI status listing, prompt Skill summaries, and
command enumeration. The CLI has no bundle-or-loader fallback. Missing,
incompatible, or malformed v4 state fails with a finite error. Explicit command
and body execution remain on the compatibility bundle, as frozen for RCP5.3.

RCP5.2B default ingress is complete. Coding uses `catalog_required` by default,
and verified local or materialized remote Plugin Resource declarations compile
through exact Product owner admissions from the same discovery receipt.
Unverified package paths and receipt-less custom ResourceLoader inputs are
available only behind caller-selected `legacy_explicit`; neither case can
trigger a forbidden silent legacy fallback. Source-backed entry, CLI, SDK,
architecture, and lifecycle tests pass together with the full Harness gate.
RCP5.3 body authority and RCP5.4 refresh authority remain separate work.

### RCP5.2B default ingress authority

Coding construction has exactly two explicit Resource authority modes. There
is no input-sensitive or exception-driven `auto` mode:

- `catalog_required` is the public default. The default Coding ResourceLoader
  must transfer one unclaimed, source-complete discovery receipt, and Product
  construction must mount exact-v4 from that receipt. A missing receipt,
  unverified source, missing admission, or incompatible composition fails with
  one finite construction error; it never produces a legacy-only Session.
- `legacy_explicit` is a caller-selected compatibility boundary for custom
  ResourceLoader implementations and legacy package inputs that have not yet
  migrated to verified Product admission. It does not attempt Catalog
  construction, does not capture exact-v4, and cannot be combined with Catalog
  composition inputs. Its name is deliberately visible at the construction
  boundary so compatibility debt cannot masquerade as the Product default.

The mode is Product policy, not a ResourceLoader type test. The Product does
not infer it from `isinstance`, receipt-method presence, discovery output,
package diagnostics, or a caught Catalog exception. A custom loader used with
`catalog_required` implements the same one-shot receipt protocol as the
default loader; otherwise its caller selects `legacy_explicit` before
discovery.

Verified Plugin sources enter the Catalog only through the exact published
revision, finalized declaration selection, Product owner admissions, and the
receipt candidates for that same revision. Coding compiles those admissions at
its ingress boundary. Missing, invalid, or disabled configured Plugin sources
remain diagnostics and contribute no Catalog candidate; they do not switch the
Session to another authority. Package-owned extension candidates remain with
the Extension authority and do not themselves block Catalog ownership of
separately admitted Resource declarations.

Raw `package_roots` and non-Plugin `package_sources` have neither a verified
revision nor Product admission. RCP5.2B does not bless mutable paths by
re-reading or hashing them after discovery. Callers using those compatibility
inputs must select `legacy_explicit` until a later source-ingress migration
publishes a verified revision and exact admission. Likewise, temporary
Resource paths and per-kind discovery switches remain finite
`catalog_required` errors rather than implicit fallback signals.

Default-ingress exit requires tests for default cwd and user-global native
roots, admitted local and materialized remote Plugin Resources, disabled and
invalid Plugin sources, an admission mismatch, a custom receipt-capable loader,
an explicitly legacy custom loader, and a real CLI all-Skills listing. Tests
must also prove `catalog_required` cannot construct a legacy-only Session and
`legacy_explicit` cannot consume Catalog composition inputs.

### RCP5.3 — body and Model Input evidence

RCP5.3 removes eager `SkillDescriptor.content` as an authority in three
independently reviewable slices. It does not add refresh or replace the
captured Catalog generation; those semantics remain exclusively RCP5.4.

#### RCP5.3A — exact asynchronous body preflight

An admitted Catalog Session resolves `/skill:<name>` only through its captured
`SkillCatalogConsumer`: resolve the effective summary, mint the exact
generation-bound handle, load through the owner, validate the receipt and
UTF-8 body, strip frontmatter, and construct the model-visible Skill block.
The preflight result carries the immutable loaded-Skill value for the next
evidence slice; metadata-only enumeration still performs no load.

The Catalog path is asynchronous because source loading and generation drain
are asynchronous. Product-neutral prompt preflight receives a narrow body-load
port and does not import a source, Catalog engine, Session, or Product. A
missing effective Skill produces the existing finite unresolved diagnostic.
The selector retains the Consumer's established `name`, stable id,
`canonical_name`, and source-path forms; an empty selector is unresolved and
does not call the loader. The loaded summary must bind to that selector, but
its display name need not equal a stable id or canonical path.
An owner load, receipt, digest, encoding, or disposed-generation failure is not
translated into an unresolved reference and never retries through the
compatibility Bundle.

In a Catalog Session, `skill:` is a Resource-owned command namespace. Exact
Skill preflight precedes a generic command executor, Extension command, or
builtin command with the same name. This reservation applies only while the
Catalog body-load port is present; it does not change legacy command priority.

Synchronous Resource command/preflight APIs cannot borrow eager body authority
for a Catalog Session. They fail with a finite asynchronous-load-required
error for `/skill:*`; callers use the existing asynchronous prompt/command
path. Existing synchronous command-source dispatch shape remains compatible
for prompts and `legacy_explicit`; only Catalog Skill execution requires its
new asynchronous counterpart. `legacy_explicit` Sessions retain their
synchronous compatibility path until RCP5.3C, and prompt-template bodies
remain unchanged in this slice.

RCP5.3A exits when tests prove exact lazy loading for project, user, package,
embedded, and Extension-backed effective Skills already covered by Catalog
source conformance; no Catalog preflight reads `ResourceBundle.skills`; stale
or disposed generations fail closed; unresolved names do not load; metadata
operations remain body-free; and explicit legacy mode remains isolated.

RCP5.3A is implemented. Catalog-backed Product Sessions now use the captured
exact-v4 Consumer for asynchronous Skill command/preflight body loads, carry
the validated immutable loaded value on the preflight result, and fail finite
sync callers instead of consulting the compatibility Bundle. Exact preflight
tests exercise project-local, user-global, admitted package, embedded, and
Extension-backed Skill sources, in addition to selector binding, receipt
binding, unresolved and disabled names, compatibility Bundle divergence,
lifecycle closure, load failure/cancellation, streaming queue preparation, and
explicit legacy isolation. Durable request evidence and final eager-body sink
deletion remain RCP5.3B and RCP5.3C.

#### RCP5.3B — request-bound durable evidence

The loaded-Skill value is projected into JSON-safe evidence bound to the exact
prepared user message. The evidence records Catalog generation and snapshot
fingerprint, activation-policy fingerprint, candidate and source-generation
identity, schema/media facts, expected and observed digest/length, and the
exact model-visible text or its durable content component. The durable Model
Input logical projection commits this evidence beside the message before
transport; transcript reconstruction therefore never reopens the original
path or source Plugin.

Evidence association is per prepared message, not ambient Session state.
Queued prepared messages retain their own evidence; tool-loop model calls may
reuse evidence for the same retained message; cancellation or a preflight that
never queues/starts a turn publishes no evidence. A refresh or uninstall may
retire the source only under the existing generation drain, while already
committed request evidence remains immutable.

RCP5.3B uses a Session-owned association runtime rather than extending the AI
message schema. Preflight projects each loaded value into an immutable
request-local value. The runtime binds that value to the delivered user
message, and the Agent event boundary replaces the temporary binding with the
exact transcript record id after the message commit. Duplicate message text is
resolved by delivered-message identity for queues; the one immediate
canonicalization handoff may use an exact role/text match only when it is
unique. An ambiguous match fails closed. Clearing a queue or abandoning a turn
removes only its uncommitted binding.

The message commit also carries a JSON-safe evidence anchor in transcript
record metadata under `loushang.request.resource_evidence`. This metadata is
part of the same atomic record append as the user message and contains the
schema version, exact model-visible text and digest, and immutable loaded-Skill
facts; the enclosing record supplies the durable message identity. It closes
the crash window before the first Model Input is prepared without extending the
AI message schema or adding a second journal authority. Model Input remains the
request-level projection and records the logical-message index.

The optional Model Input `resource_evidence` component has schema id
`loushang.model-input.resource-evidence` and schema version `1`. Each message
entry records its exact logical-message index, transcript record id, exact
model-visible text and domain-separated text digest. Each loaded-Skill entry
records the Resource identity, Catalog generation and snapshot fingerprint,
activation-policy and candidate fingerprints, source-generation reference,
schema/media facts, and both expected and observed digest/length. The
component also states whether the final logical context was the complete
transcript context, allowing resume to stop at the newest cumulative snapshot
or continue through partial side requests. The projection is JSON-safe and
contains no live handle, `Path`, source object, or opaque locator.

Before creating a transport committer, the association runtime maps retained
evidence to the final logical context by exact role/text occurrence. A message
absent from a compaction, branch-summary, or side-question request contributes
no evidence to that request. If only an ambiguous subset of duplicate exact
messages remains, association fails closed instead of guessing a record id.
Model Input reconstruction returns the committed component as ordinary logical
data. A resumed Session may recover retained evidence only from verified Model
Input snapshots on its selected transcript path; it never reopens a Resource
source. Compaction and branch selection naturally exclude evidence whose
message record is no longer in the projected context.

Recovery treats both message anchors and Model Input components as untrusted
typed input. It validates exact field sets, SHA-256 facts, Resource and
source-generation shapes, schema agreement, snapshot ancestry, logical-message
indices, duplicate occurrences, and transcript text. A component is parsed
fully into a local value and published to Session recovery state only after all
entries succeed. Queue bindings use one owner per delivered message: consumption
moves that owner from clearable queue state to in-flight state, `message_end`
completes it, and `agent_end` discards an incomplete delivery.

#### RCP5.3C — eager-body sink deletion

After durable evidence review, command execution, description fallback, Method
adaptation, steer/follow-up handling, and compatibility callers either forward
to the captured asynchronous Consumer or remain explicitly
`legacy_explicit`. Production Catalog paths have zero direct reads of
`SkillDescriptor.content`. The eager Skill body may then be removed from the
Catalog compatibility projection without changing prompt-template or refresh
authority.

No RCP5.3 slice may introduce a detached body cache, reconstruct a handle from
a path, hash a fresh path read as substitute evidence, silently select legacy
authority, or keep a load handle beyond the captured generation's lifecycle.

## Ordered cutover

RCP5 proceeds in independently reviewable steps:

1. **RCP5.1 — typed read path:** add the exact-generation Skill Consumer and
   lazy body-load proof without changing Product callers.
2. **RCP5.2 — read-only projections:** first add a Catalog-owned
   inactive/status substrate (RCP5.2A), then use a new exact-v4 contract for
   the Product read-only cutover (RCP5.2B). Move CLI listing, activation
   status, prompt summaries, and command enumeration to the Consumer. Delete the
   `resource_bundle.skills -> resource_loader.get_skills()` fallback in the
   RCP5.2B cutover slice.
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
- materially foreign summary/handle and non-Skill handle use fail closed;
- a value-identical summary from the same exact Catalog evidence remains valid;
- disposal invalidates later body loads through the owner generation; and
- the default Product and public SDK surfaces remain unchanged.

Full RCP5 is complete only when every Skill operation uses one Catalog path,
legacy discovery and disabled-state peer writers are gone, direct Extension
`ResourceBundle.merge()` publication is forbidden, and current-request plus
replay evidence is proven across refresh and uninstall. Only then is PLC6
unblocked.
