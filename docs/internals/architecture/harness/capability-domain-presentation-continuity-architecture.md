# Capability, Domain, Presentation, And Continuity Architecture

## Status

Accepted and implemented for V1 on 2026-07-24.

Phases 0-3 are implemented in `harness.continuity`,
`harnesstui.continuity`, the non-rebuilding transcript projection-index read,
the Coding Product adapter, and the CLI pre-session bootstrap. The temporary
`tui_startup_command="/resume"` path and legacy SessionPicker types are removed.
Phase 4's cross-Experience Host coordinator remains intentionally deferred
until a real mixed OEM needs atomic runtime/channel switching; independent,
unified, and hybrid provider layouts are covered as composition contracts
without claiming that coordinator exists.

This document defines the cross-product relationship between domains,
capabilities, OEM experiences, presentation projections, durable summaries, and
session continuity. `/resume` is the first reference workflow, not the reason
for inventing a separate product framework.

It extends, rather than replaces:

- [Shared Capability Boundaries](shared-capability-boundaries.md);
- [Product Capability Composition Core](product-capability-composition-core.md);
- [Capability Composition Binding](product-runtime-injection/components/capability-composition-binding.md);
- [OEM And Extension Architecture](oem-extension-architecture.md);
- [Conversation Persistence Refactor](conversation-persistence-refactor.md).

## Problem

The first `/resume` implementation exposes Coding assumptions in a nominally
shared picker:

- `current`, `repository`, and `all` scopes assume a filesystem and Git;
- `Ctrl+W worktrees` and branch/worktree labels assume Coding;
- all rows are eagerly materialized before the first frame;
- the picker receives ready-made strings, so another channel cannot reuse the
  meaning of the fields;
- activation assumes that every selected item can be restored inside the
  already active Coding runtime.

Moving those assumptions into Harness would make PPT, Design, Research, and
Products composed by a mixed OEM Profile pretend to be Coding. Moving the whole
picker into Coding would duplicate search, pagination, focus, preview, and
activation mechanics in every product.

The design therefore needs to answer a broader question:

> How can one host compose several domain capabilities, expose them through
> different channels, and preserve independent or unified continuity without
> teaching Harness any product's artifact or workspace semantics?

## Four Independent Axes

The word "capability" must not carry four unrelated meanings. The architecture
uses four explicit axes.

### Domain

A domain owns vocabulary, artifact semantics, and domain policy.

Examples:

- Coding owns repositories, branches, worktrees, code changes, and coding
  completion criteria.
- Presentation owns decks, slides, speaker notes, and slide-generation policy.
- Design owns canvases, assets, layers, and design collaboration semantics.

A domain is not a plugin slot and is not necessarily a separately launchable
application.

### Runtime capability

A runtime capability selection is a composable implementation selected through
the existing `RuntimeCapabilitySlot`, `RuntimeProfileLayer`, admission,
resolution, and binding machinery.

Examples include a resource runtime, prompt-section composer, skill-activation
policy, tool/command-pack composition mechanism, approval resolver, and the
continuity provider-pack factory. Concrete Product tool, command, and
prompt packs remain contribution data consumed by their bound composition
mechanisms. A continuity provider-pack selection is different: it is an
admitted runtime implementation whose bound value is a
`ContinuityProviderPack`. V1 does not add a second live contribution/composer
path for continuity providers. A capability can be shared by several domains.
Installing a capability does not imply that it owns a session.

This design does not add another capability registry.

### Experience

An experience is the user-facing composition root selected by a Product or OEM.
It chooses domains, runtime profiles, navigation, branding, commands, and
channels.

Examples:

- Coding CLI: one Coding domain in a terminal experience.
- Slide editor: one Presentation domain in a graphical experience.
- OEM Studio: Coding, Presentation, and Design domains in one shell.

The experience is where policy is applied. Harness can describe and compose it,
but must not decide which domains an OEM exposes.

### Continuity unit

A continuity unit is the smallest durable aggregate that can be listed,
previewed, and activated independently.

Examples:

- one Coding agent conversation;
- one presentation-generation session associated with a deck;
- one Design collaboration session;
- one OEM Studio project that intentionally resumes Coding, Presentation, and
  Design state together.

Capability, domain, experience, and continuity unit are deliberately
many-to-many:

```text
domain ──uses──> runtime capabilities
experience ──selects──> domains + capabilities + channels
continuity unit ──belongs to──> one activation owner
continuity unit ──may reference──> several domain artifacts
```

A multi-capability OEM must choose its continuity semantics explicitly:

- **independent**: Coding, PPT, and Design each contribute their own resumable
  units;
- **unified**: the OEM contributes a Studio continuity provider that restores
  the aggregate;
- **hybrid**: both appear, with distinct provider and target identities.

Harness must not infer this choice from installed capabilities.

Product adapter and OEM are ownership/source concepts, not additional axes. A
Product adapter owns domain semantics and policy. An OEM supplies admitted
overrides or may define a new Product adapter. An Experience is the immutable
user-facing composition produced from one Product plan plus channel and
presentation bindings; it is not another executable registry.

A mixed OEM can therefore take two different forms:

- one `oem-studio` Product plan composes Coding, Presentation, and Design domain
  modules into one Experience;
- a Host exposes several separate Product plans and switches between their
  Experiences.

The second form cannot use `RuntimeProfileBinder.rebind()` to cross a
`product_id` boundary. It requires a Host-owned catalog and lifecycle for
separately admitted Product bindings.

## General Composition Rule

Continuity is optional. The same four-axis model applies to every capability:

| Question | Owner/model |
| --- | --- |
| Is this reusable mechanism or an implementation choice? | Harness runtime capability slot/mechanism |
| Does it define artifact vocabulary, policy, or completion semantics? | Product Domain adapter |
| Which Domains, channels, branding, and defaults ship together? | Product/OEM Experience composition |
| Can its durable state be discovered and activated independently? | Continuity Provider |

For example, an image-generation tool pack can serve Presentation and Design
without becoming a Domain, page, or resumable unit. Coding Git/worktree policy
stays in the Coding Domain even if its filesystem mechanisms are shared.
Installing a summarizer does not automatically add a summary column or another
session type.

The general Product/OEM bootstrap remains:

```text
Product/OEM selects Domain modules and policy
  -> Domain modules supply Product-owned content and approved pack inputs
  -> ProductRuntimePlan declares selectable mechanism slots
  -> OEM/extension layers pass Product admission
  -> RuntimeProfileResolver + RuntimeProfileBinder bind mechanisms
  -> Product/OEM Host assembles the Experience and channels
```

Commands, prompts, skills, tools, resources, approvals, and configuration keep
using their existing Harness mechanisms and Product-owned semantics. The
continuity provider pack defined below is only one additional optional slot in
that same flow.

## Ownership And Dependency Direction

```text
OEM / Product composition root
  ├── product domains (coding / presentation / design / ...)
  ├── channels, branding, and Product UI bindings
  ├── continuity providers and activation policy
  └── ProductRuntimePlan + admitted contribution layers
                    │
                    v
  harnesstui / web / SDK channel adapters
                    │
                    v
  harness continuity mechanisms
                    │
          ┌─────────┴──────────┐
          v                    v
  provider summary index   runtime/session transition mechanisms
          │                    │
          v                    v
  domain authoritative store   active Product runtime
```

The dependency rules are:

- Harness does not import Coding, Presentation, Design, Git, a concrete TUI, or
  a concrete store.
- `harnesstui` imports neutral Harness list/continuity records and terminal
  primitives. It does not discover sessions or interpret product fields.
- Product continuity adapters project Domain data into the fixed common
  summary/preview contract. A Product-specific history UI, if one is later
  needed, is a separate surface rather than a plugin to the common Resume page.
- Product/OEM continuity providers own authoritative discovery, query
  translation, redacted preview, target validation, and candidate preparation.
- The Product/OEM Host exclusively owns activation policy, serialization,
  commit, runtime switching, and channel rebinding.
- The OEM/Product composition root is the only place that assembles providers,
  policy, and channels.

## Reuse The Existing Capability Runtime

The existing profile runtime remains authoritative for executable capability
selection. This design adds declarations that can be selected by it; it does
not bypass admission or introduce a mutable global service locator.

The first new standard slot should be:

| Slot | Shape | Scope | Refresh | Contents |
| --- | --- | --- | --- | --- |
| `continuity.provider_packs` | ordered | process | sealed | admitted provider-pack implementations |

`process` is the intended lifetime, not a global singleton supplied
automatically by `RuntimeProfileBinder`. The Product composition root creates
one process-level `RuntimeProfileBinding` for its Product plan, and each
`ExperienceComposition` consumes the already-bound, immutable pack values. It
does not trigger another bind. A future Host with several Product plans may own
one such process-level binding per admitted Product plan. `sealed` prevents
in-place rebind of the selected packs; disposal remains owned by the binding
lifecycle.

An OEM can declare additional Product-owned slots for experience navigation or
channel adapters, but those should not become standard until two independent
products need the same lifecycle.

The only provider construction path is:

```text
continuity.provider_packs slot
  -> profile admission and resolution
  -> RuntimeProfileBinder
  -> provenance-bearing ContinuityProviderPack values
  -> flatten packs and reject duplicate provider IDs
  -> ContinuityHub
```

Each bound pack may expose one or more providers. This matters because the
current ordered-slot resolver deduplicates the same implementation/version;
multiple providers must not be smuggled in as duplicate selections with
different configuration. An Experience composition consumes only the bound
pack result and cannot name or resolve another provider factory.

V1 permits Product- and OEM-sourced provider packs only. Extension providers
remain unsupported until history-query, content-preview, and activation
permissions have separate grants and failure contracts.

Continuity summary and preview declarations are fixed JSON-safe data contracts,
not executable authority. V1 has no custom list-column, filter, or renderer
contribution surface. This deliberately avoids inventing renderer admission and
fallback policy merely to implement Resume.

The resolved runtime snapshot stores provider implementation IDs, versions, and
JSON configuration. It never stores factories, credentials, live catalogs, or
channel/UI objects. A resumed unit can therefore validate compatibility before
creating executable objects.

## Composition Contracts

The Product or OEM creates one immutable Experience composition during
bootstrap. The following shapes are illustrative:

```python
@dataclass(frozen=True)
class ExperienceDescriptor:
    experience_id: str
    label: str
    domain_ids: tuple[str, ...]
    default_domain_id: str | None


@dataclass(frozen=True)
class ExperienceComposition:
    experience: ExperienceDescriptor
    capability_profile: ResolvedRuntimeProfile
    continuity_providers: tuple[BoundContinuityProvider, ...]
```

These are design shapes, not a mandate for these exact class names. The
important properties are:

- immutable after admission and resolution;
- provider packs resolved only by the existing runtime binder;
- each bound provider retains its resolved-selection provenance;
- provider descriptors use stable IDs rather than imported Product types;
- deterministic priority and provenance;
- no arbitrary runtime registration after a session starts.

An OEM Studio composition might select three independent providers plus one
aggregate provider:

```text
oem-studio
  ├── coding.conversation
  ├── presentation.deck-session
  ├── design.canvas-session
  └── oem-studio.project          # optional unified continuity unit
```

The UI can show all four or apply OEM policy to hide redundant views.

Phases 1–3 define one `ExperienceComposition` and federate only its admitted
providers. Cross-experience discovery is not implied. Phase 4 may add a
Host-owned `ExperienceCatalog` containing admitted, lazily activatable
Experience descriptions and factories. Until that exists, the design does not
claim cross-experience federation.

## Continuity Contracts

### Opaque target

The shared layer routes a selected item without interpreting its identity:

```python
@dataclass(frozen=True)
class ContinuityTarget:
    provider_id: str
    opaque_id: str
    revision: str | None = None
```

`opaque_id` may be a conversation ID, a database key, a deck session ID, or an
OEM aggregate ID. It is not assumed to be a path. `revision` supports
optimistic validation between listing and activation. `provider_id + opaque_id`
is the authoritative route; duplicating a domain ID in the target would allow
it to conflict with the provider descriptor.

### Query

```python
@dataclass(frozen=True)
class ContinuityQuery:
    text: str = ""
    provider_ids: tuple[str, ...] = ()
    domain_ids: tuple[str, ...] = ()
    sort_id: Literal["updated", "created"] = "updated"
    descending: bool = True
    page_size: int = 25
    cursor: str | None = None
```

There is no standard `repository`, `worktree`, `deck`, or `team` field.
V1 deliberately has no Product-specific filters in the common page. Providers
translate common text search into their private index semantics. A Product that
needs branch, worktree, deck-owner, or canvas-team filtering can provide a
separate Product history surface over its Domain catalog.

The Hub validates this external query and creates a narrower `ProviderQuery`
for each selected provider. It enforces the page-size limit, intersects Domain
membership, unwraps only that Provider's cursor, and passes a common sort the
Provider supports. Changing text, sort, or Provider/Domain selection invalidates
the old cursor.

### Provider

```python
class ContinuityProvider(Protocol):
    descriptor: ContinuityProviderDescriptor

    async def query(self, request: ProviderQuery) -> ProviderPage: ...
    async def preview(self, target: ContinuityTarget) -> ContinuityPreview: ...
    async def prepare(
        self, target: ContinuityTarget
    ) -> PreparedActivationLease: ...
```

`query()` returns summary rows only. `preview()` is lazy and cancellable.
`prepare()` validates the target and returns an owned opaque activation lease;
it does not publish it as current. The lease can be consumed once and has an
idempotent `abort()`/`close()` operation. Cancellation, Host validation failure,
or an unconsumed candidate must release it.

Provider descriptors declare:

- a stable provider ID, Experience ID, one-or-more Domain IDs, optional primary
  Domain ID, and user-facing labels;
- supported common sorts;
- whether startup and in-place activation are supported;
- the provider implementation/profile versions needed for resume.

Independent providers normally declare one Domain. An aggregate provider may
declare several. Harness must not force an aggregate continuity unit to invent
a synthetic Domain merely to satisfy routing. A Domain query selects a provider
when their Domain-ID sets intersect. Product/OEM policy may mark an aggregate
provider as visible only in the All view or hide it when its independent
providers are also visible; Harness does not infer that display policy.

For V1, one Product/OEM provider may implement `query`, `preview`, and
`prepare`. These operations nevertheless represent distinct authority:

```text
continuity.query
continuity.preview
continuity.prepare
```

These are audit/ownership boundaries, not three separately enforced V1 grants.
A Product default is declared directly on its `ProductRuntimePlan`; an OEM
layer is admitted to the whole slot only when its `RuntimeProfileLayerGrant`
allows `continuity.provider_packs` and carries the single slot permission
`continuity.provider`. That V1 grant authorizes the pack's three operations
together. If extension-sourced providers are introduced later, the catalog and
activation protocols should be split and the operations granted independently.

### Federated hub

`ContinuityHub` is a Harness mechanism over already admitted providers:

- validates during composition that every Provider's declared
  `experience_id` matches the active `ExperienceComposition`; a mismatch is an
  admission/composition diagnostic, never a runtime routing choice;
- fans out a query only to selected providers;
- merges pages by the selected common sort;
- returns stable provider-qualified targets;
- isolates one provider's query/preview failure as a diagnostic;
- uses a bounded composite cursor containing opaque per-provider cursors and
  the query/composition snapshot;
- never opens a transcript, deck, or canvas itself.

Federated paging must not advance a Provider past candidates that the Hub did
not emit. Each `ProviderPage` therefore supplies a keyset cursor after every
item. The Hub fetches bounded candidates from each Provider, merges them, and
advances only the cursor belonging to each emitted item. Unconsumed candidates
may be fetched again on the next page, but cannot be lost. A stateful deployment
may retain bounded merge buffers as an optimization, not as a correctness
requirement.

Only normalized common sorts such as `updated` or `created` may be federated.
Provider-local relevance is available only in a single-provider scope unless a
future contract defines comparable scores. A Provider's total order is
`(normalized_sort_value, opaque_id)`; the Hub adds `provider_id` as the final
tie-breaker. Timestamps are timezone-aware UTC and null ordering is declared by
the common sort contract. The UI offers only the sort intersection supported by
all selected Providers; `updated` is mandatory, while `created` is optional.

The Hub always wraps cursors, including for one Provider. Its cursor records:

- schema version and expiry;
- normalized query hash;
- Experience-composition and Provider-set fingerprints;
- sort and direction;
- each Provider's index generation/snapshot and last emitted keyset cursor.

`index_generation` identifies a published index generation and changes on
rebuild/generation swap, not on every ordinary upsert. A Provider cursor also
contains a query snapshot/watermark so records written after the query began do
not destabilize that traversal. The Hub strictly compares the recorded
generation with the Provider's current generation; a mismatch returns an
explicit restart result. Per-item authority freshness remains
`ContinuityTarget.revision`, not the page generation.

A changed query, expired generation, changed snapshot contract, or changed
Provider set returns an explicit restart result rather than silently
continuing. A failed Provider keeps its previous cursor and the page is marked
partial. In the default strict ordering mode, that page may display temporary
candidates but carries no canonical `next_cursor`; retry starts from the prior
composite cursor because the failed Provider may contain an earlier item. A
future best-effort mode may continue only with `ordering_complete=False` and
must not present its results as globally ordered. Cursors crossing a process or
trust boundary must be authenticated; local-only cursors may be structurally
validated, but still have strict size, nesting, and page limits.

The Hub fans out concurrently under Host-supplied overall and per-Provider
deadlines and a concurrency limit. Query and preview requests carry generation
tokens; late results from an older generation are discarded even when the
underlying blocking task cannot be cancelled. Search debounce, preview
debounce, and committed activation have separate cancellation scopes.

The portable page contract makes partial and index state observable:

```python
ContinuityPage(
    items=...,
    next_cursor=...,
    provider_diagnostics=...,
    partial=False,
    ordering_complete=True,
    provider_states={
        provider_id: ProviderPageState(
            index_state=...,   # fresh | stale | rebuilding | unavailable | unknown
            index_generation=...,
            query_snapshot=...,
            diagnostic=...,
        ),
    },
    aggregate_index_state="fresh",
)
```

An unavailable Provider is not represented as an empty successful result.
The aggregate state is display-only and never validates continuation; cursors
use each Provider's generation. Totals are optional; a renderer must support an
unknown total.

Preview is a structured, bounded, JSON-safe projection rather than
pre-rendered terminal text:

```python
ContinuityPreview(
    target=...,
    revision=...,
    heading=...,
    sections=(...),            # text, key/value, artifact/file references
    stale=False,
)
```

The Provider owns redaction and content policy. Terminal, Web, plain, and SDK
channels render the same fixed section kinds. Product-specific information may
appear as text, key/value, or artifact references, but the common UI neither
knows nor executes Product renderers.

## Summary, Projection, And Index

### Authoritative data stays in the domain

The transcript, deck, design document, or OEM project store remains the source
of truth. A Resume surface reads a rebuildable summary projection, never the
full durable object set.

Redis, SQLite, JSON projection files, and remote search services are optional
index implementations. Redis is not the assumed authoritative transcript
store. Loss of an index may reduce query performance but must not lose the
domain object.

### Common envelope

```python
@dataclass(frozen=True)
class ContinuitySummary:
    target: ContinuityTarget
    domain_ids: tuple[str, ...]
    primary_domain_id: str | None
    title: str
    updated_at: str
    created_at: str | None = None
    subtitle: str | None = None
    excerpt: str | None = None
    status: str | None = None
```

Only cross-product facts with stable semantics belong in this envelope.
Coding branch/worktree/model, Presentation slide count/owner, and Design
canvas/team/type do not become generic summary fields. A Provider may expose
them as bounded key/value rows in the lazy preview, while the common UI treats
those rows uniformly.

Timestamps in portable summaries use normalized RFC 3339 strings. An in-process
adapter may parse them into `datetime` values for comparison or rendering, but
transport and index codecs remain JSON-safe.

The transport summary is deliberately data-minimal. It contains bounded title,
subtitle, excerpt, status, and timestamps, not full messages, tool output,
credentials, or the current Agent catalog's `all_messages_text`. A Provider may keep a private
search token/document in its index; that payload is not a
`ContinuitySummary`. Product data-governance policy must explicitly approve
full-text storage in Redis or another remote index. The default remote
projection is metadata-only.

Contracts set limits for title/excerpt length, preview row count and size,
preview section size, and serialized page size. Query, preview, and
prepare all repeat the same tenant/permission visibility check; knowing an
opaque ID never grants access.

The shared envelope is a read model, not another transcript schema. It does not
replace `SessionSummary`; the Coding provider adapts `SessionSummary` into it.
The Agent transcript catalog remains the reusable Agent-profile index below
that adapter.

### Incremental and rebuildable indexes

Each provider owns its projection function and index freshness policy.
Harness may own neutral revision-aware projection-index mechanics. The
continuity paging contract requires a non-rebuilding read:

```python
try_query_index_page(query, *, cursor, limit)
    -> ProjectionPage(
        items,
        next_cursor,
        index_state,
        index_generation,
        query_snapshot,
    )
```

Missing, corrupt, or stale indexes never cause this method to scan the
authority. It returns an empty or last-valid stale page with a
`rebuilding`/`stale` state and schedules repair separately. Rebuild publishes
through monotonic-revision upsert/tombstone or an atomic generation swap; an
older rebuild cannot overwrite newer writes. The Provider consumes the page
API directly rather than first constructing an unbounded list.

Required behavior:

- writes update the authoritative store first;
- index update may be synchronous or queued, according to Product policy;
- every summary records a source revision or equivalent freshness marker;
- a missing/stale index can be rebuilt incrementally;
- opening `/resume` does not synchronously rebuild all roots;
- first page is bounded and available before background repair completes;
- preview loads only the selected target and is debounced/cancelled when
  selection changes.

The existing Coding APIs do not yet satisfy this contract:

- `list_indexed_session_summaries()` synchronously rebuilds a missing, empty,
  or invalid index by scanning authoritative transcripts;
- the current JSON index deserializes all summary rows and has no cursor;
- current all-root helpers enumerate roots and construct a full list.

Phase 2 must first add the non-rebuilding paged query above. The JSON projection
index may remain a small-scale compatibility implementation, but its full-file
cost must be explicit. A scalable implementation needs a pageable index or a
generation-cached in-process projection. Rendering the first Coding page must
not perform an unbounded JSONL scan or enumerate every Git worktree.

`ContinuitySummary.target.revision` is the projected source revision and the
page carries index state/generation/query snapshot. `prepare()` revalidates the
revision against authority; a mismatch returns a stale-target result and causes
the UI to refresh the selected row. A Provider unable to prove freshness
reports `unknown`, never `fresh`.

## Common Presentation Contract

V1 intentionally does not implement dynamic Product columns. The shared Resume
surface displays only stable cross-product semantics:

- Domain/Provider identity when more than one is visible;
- title;
- updated time;
- optional created time;
- optional status;
- bounded excerpt.

Harness owns these meanings in `ContinuitySummary`. `harnesstui` owns their
standard terminal rendering, relative time, full-screen list interaction,
loading/empty/error/stale states, paging, search, preview, and shortcut help.
Web, plain, and SDK channels project the same fixed fields.

Product continuity adapters only map their Domain read model into the common
summary and structured preview:

```text
coding/continuity.py       # Agent SessionSummary -> common summary/preview
presentation/continuity.py # deck session -> common summary/preview
design/continuity.py       # canvas session -> common summary/preview
```

The common page has no branch/worktree/model, slide-count/owner, or
canvas/team/type columns, filters, custom renderers, or Product shortcuts. It
therefore needs no UI contribution registry and does not import Product UI.
Product-specific facts may appear as ordinary bounded key/value preview rows;
the common renderer does not interpret their semantics.

If a Product later needs a rich history browser, it may implement
`coding/ui/history.py`, `presentation/ui/history.py`, or `design/ui/history.py`
over its own Domain catalog. That specialized page may reuse generic TUI
primitives, but it is not an extension of the common Resume contract and does
not expand the cross-product summary schema.

The responsive common terminal contract is:

- narrow: two-line card with title plus updated/Domain context;
- medium: aligned title, updated, and Domain;
- wide: the same common columns plus an optional side preview;
- short: hide preview and secondary chrome before reducing results.

Resize preserves query, selected target, paging frontier, scroll position, and
preview state. Selection has a non-colour marker, errors/disabled states do not
rely on colour, all actions are keyboard reachable, and truncated data remains
available in preview.

## Resume Experience

### Full-screen surface

The standard terminal Resume surface is full-screen, matching the interaction
model used by mature coding clients. It contains:

```text
Resume
Search: [................................................]
Domain: [All | Coding | Presentation | Design]  Sort: [Updated]

  title                                      updated      domain
> ...

Preview/detail pane (lazy)

<resolved keybindings for resume, preview, close, and browse>
```

The domain selector is hidden when only one domain is installed. Product
shortcuts and Product filters do not appear in this common page. Git wording
never appears in the common footer.

"Full-screen" means a root-level page that receives the full current viewport,
not the existing `bottom-exclusive` surface and not a request to enter the
terminal alternate screen. At startup it can be the TUI root. In-session, the
page/modal host mounts it at full width and height and restores the prior focus,
selection state, and conversation view on close. Closing also cancels unfinished
query and preview tasks. The Product Host decides once whether its
`TerminalSession` uses an alternate screen.

This requires an intentional TUI extension. Today
`ScreenSurfacePresentation` exposes only `bottom`/`bottom-exclusive`, while the
lower framework exposes inline/overlay/modal variants but no root page.
Phase 1 adds a `page` presentation (or an equivalent typed page host) to
`loushang.tui` and `harnesstui`: it captures focus, receives 100% of the
viewport, replaces rather than partially overlays the conversation rendering,
and restores the previous view on close. It is not implemented by relabeling
the current `bottom-exclusive` behavior.

Search is Provider-side by default. `harnesstui` owns the input, debounce,
generation token, request trigger, and loading/error states; it does not fuzzy
filter the current page unless the Provider explicitly declares local mode.
Search/sort/Domain changes reset the cursor. Loading another page appends
results and preserves selection by `ContinuityTarget`, never by row number.
Initial loading, loading-more, stale results, partial Provider failure, and
unknown total are distinct view states.

Common interaction uses action IDs resolved by the existing keybinding
mechanism. Footer help is generated from resolved bindings rather than
hard-coded `Space`, `Tab`, or control keys. V1 exposes no Product-specific
actions or shortcuts in the common page.

### Startup and in-session entry

There are two entry points over the same continuity contracts:

- `product --resume` opens the picker before creating an empty active session;
- `/resume` pushes the full-screen surface from an active experience.

Startup must not create and then discard a placeholder session. It has a real
pre-session bootstrap boundary:

```text
resolve Product plan and process-scoped provider packs
  -> bind continuity providers without an active Product session
  -> run standalone continuity picker
  -> select target or exit cleanly on cancel
  -> resolve and validate target runtime/capability profiles
  -> prepare and activate the restored Product runtime
  -> bind the conversation UI
```

Provider query/preview must therefore work without an active session. A startup
activation failure stays in the picker with an actionable diagnostic.
In-session resume reuses the same view model with a different Host adapter and
keeps the prior runtime usable until candidate preparation succeeds.

### Provisional session materialization

Opening a Product's main surface does not by itself create durable continuity
state. A newly composed session starts as **provisional**: it has a stable
session ID, header draft, runtime binding, and optional planned store locator,
but no authoritative transcript, file/lock/sidecar, or index row.

Administrative records produced before useful content, such as initial model
or thinking selection and startup diagnostics, remain staged in memory. The
first Product-declared materializing record atomically creates authority with
the header, staged records, and that record. For the standard Agent transcript
profile, a user Agent message or application message is materializing.
Imported and forked sessions that already contain retained records are
materialized immediately.

A provisional session that exits or loses an in-session activation commit is
discarded without a Store delete. This is intentionally deferred creation, not
"create an empty transcript and clean it up later": cleanup-on-exit would still
leak empty authority after process crashes. `has_messages` filtering remains a
defence for pre-existing or malformed data, not the primary retention policy.

The session-local state table is normative:

| Scenario | Required authority and activation result |
|---|---|
| Exit directly from an empty main surface | Discard the provisional session; create no authority or index row. |
| Open `/resume` from an empty surface and cancel | Keep the same provisional session; create no authority. |
| Select a historical target from an empty surface and press Enter | Prepare the historical candidate first; on commit discard the provisional session and activate the target. |
| Historical candidate preparation or activation pre-commit fails | Abort the candidate and keep the provisional session current; create no empty authority. |
| Switch from materialized session A to historical session B | Retain A, publish its index only if its revision changed, then activate B. |
| Switch from untouched historical session A to B | Preserve A byte-for-byte and do not advance its updated time or revision. |
| Select the currently active historical session | Treat as a no-op and close Resume; do not reload or dispose the same authority. |
| Add content to A and then switch to B | Durably append A's content and update its projection, then activate B. |
| Start with `product --resume` | Run the pre-session picker; never construct a placeholder session. |

The `/resume` command itself is Host control input and is not a materializing
conversation record. A failed or cancelled candidate never changes whether the
current session is provisional or materialized.

### Activation transaction

There are also two activation levels:

1. **session-local activation** uses the existing
   `SessionOperationCoordinator`/`SessionTransitionHost` path when the target
   belongs to the active Product runtime;
2. **experience activation** is owned by the OEM/Product Host when the target
   requires a different domain runtime, shell, workspace, or channel binding.

The Provider descriptor states only capability limits. `prepare()` returns a
target-specific disposition such as `in_place`, `relaunch`, `new_window`, or
`unsupported`, plus the single-use candidate lease.

For V1 session-local activation, the Product adapter implements
`PreparedActivationLease` over the existing session-operation model:
`prepare()` stages a `SessionOperationCandidate`, lease `abort()` delegates to
the candidate rollback/cleanup callback, and successful consumption passes the
candidate to `SessionOperationCoordinator.run()`. The lease is deliberately
narrower than the concrete candidate so a future cross-Experience coordinator
can supply another implementation without changing the Provider contract.

The existing session-local transaction has four observable phases:

```text
resolve provider-qualified target
  -> provider.prepare(target)
  -> pre-commit: validate, prepare candidate, persist/release policy
  -> commit: invalidate and dispose previous, set candidate current
  -> post-commit: activate and rebind channel/UI
```

Failure state is classified by phase:

- **prepare/pre-commit**: the previous session remains current and the candidate
  lease is aborted;
- **commit/invalidation**: current may be `None`; the previous session is
  unavailable or partially disposed, and a never-published candidate is
  aborted. The Product enters a typed recovery/fatal state rather than
  pretending either session is healthy;
- **post-commit**: the candidate is current, while activation/rebind failure
  produces a Product-defined degraded state and diagnostic.

The current `SessionTransitionHost` cutover is not reversible: it clears and
disposes the previous session before publishing the candidate, then runs
activate/rebind. It does not promise to restore the previous session. Candidate
rollback applies only before it ever became current.

All activation is Host-serialized. A revision mismatch produces a typed
stale-target result and refreshes the selected row. Starting a newer search or
preview never cancels an activation that has entered commit.

Before preparing a session-local target, the Product adapter compares its
provider-qualified authority reference with the current session reference.
Selecting the current authority returns an unchanged operation result instead
of constructing a second runtime over the same Store key.

If a future cross-Experience transition requires true rollback, Phase 4 must
add a Host coordinator that stages the new runtime and channel, atomically swaps
the active Experience slot, and only then cleans up the old Experience. The
existing session Host must not be described as already providing that
transaction.

An unrelated target need not be resumable in place. A Coding Product may return
a relaunch action for another project; a desktop OEM may open another window;
an aggregate Studio may switch workspaces. The provider declares support and
the Host chooses policy.

## Suggested Package Placement

The first implementation should use narrow packages:

```text
loushang.harness.continuity/
  types.py          # target, common query/page/summary/preview/descriptors
  provider.py       # provider protocol
  hub.py            # bounded federation and composite cursor
  activation.py     # neutral prepared-candidate/result shapes only

loushang.harnesstui.continuity/
  surface.py        # full-screen list/search/page/preview state machine

loushang.coding.continuity
loushang.presentation.continuity
loushang.design.continuity

# Optional future Product-specific browsers, outside common Resume:
loushang.coding.ui.history
loushang.presentation.ui.history
loushang.design.ui.history
```

Do not put these contracts in `conversation`: a deck or design document need
not be a conversation. Do not put them in `transcript`: not every resumable
unit is an Agent transcript. Do not rename the existing context-summary
evaluator: continuity summaries are directory read models, not compaction
summaries.

The current `harness.presentation` is Agent tool-result oriented. Do not add
continuity list contracts to that module merely because both eventually render
something.

## Migration Plan

### Phase 0: freeze the current boundary

- Keep current `/resume` behavior covered by tests.
- Record startup time, first-frame time, files opened, and preview latency.
- Do not add more Git scopes or product fields to
  `harnesstui.conversation.resume`.

### Phase 1: common summary and full-screen list

- Introduce the fixed continuity summary/preview/page records.
- Build a full-screen `harnesstui.continuity` surface over in-memory fake
  providers.
- Add the typed `page` presentation/root-page host to the current surface
  framework.
- Mount it as a viewport page, not `bottom-exclusive`; support bounded async
  pages, request generations, cancellation, and lazy structured preview.
- Keep activation as an injected callback.

### Phase 2: Coding adapter

- Implement a Coding continuity provider over
  `AgentTranscriptDirectoryRuntime` and its projection index.
- First add a non-rebuilding paged index read; do not call the current implicit
  rebuild path on first frame.
- Map Coding title/time/status/excerpt into the common summary. Keep
  repository/worktree/branch/model out of common columns and filters; optional
  details may be key/value preview rows.
- Use `ConversationLocator`/session identity as the opaque target. Filesystem
  paths remain inside the Coding Provider and are validated against admitted
  roots.
- Replace `SessionPickerScope`, `SessionPickerItem`, `items_by_scope`, and
  `build_session_picker_view` with Provider descriptors, queries, and pages,
  then remove those picker symbols from
  `harnesstui.conversation.resume`. Keep no compatibility shim unless a
  consumer inventory proves an external supported use; Product-specific
  history pages should use their own Domain view models.
- Use the existing Coding session-operation coordinator and its real commit
  semantics for same-runtime activation.
- Add a pre-session bootstrap stage so `--resume` launches the picker before an
  empty session is created. This is a new CLI launch entry point. The temporary
  `tui_startup_command="/resume"` compatibility path was removed after the
  standalone picker passed startup, cancellation, activation, and
  activation-failure tests.

### Phase 3: composition and federation

- Add the admitted `continuity.provider_packs` capability slot.
- Build `ContinuityHub` only from bound, provenance-bearing provider packs in
  the resolved immutable Experience composition.
- Prove neutrality with two fixtures: a deck provider and a design provider.
- Show the domain selector and merge pages only when multiple providers are
  installed.

### Phase 4: OEM activation

- Add a Host-level Experience catalog/coordinator only after a real mixed OEM
  requires cross-Product discovery or switching.
- Prove independent, unified, and hybrid continuity layouts.
- Add OEM contract tests for provider-pack admission, version mismatch,
  multi-Domain aggregate visibility, and staged activation failure. Extension
  providers remain deferred.

## Verification And Performance Gates

Architecture tests must require:

- Harness continuity packages import no Product, Git, TUI,
  Agent transcript, concrete store, AI, Method, or Work packages;
- `harnesstui` imports no Coding/Presentation/Design packages;
- the common summary/page contains no Product fields, filters, shortcuts, or
  renderer callables;
- Product continuity adapters own Domain-to-common projection and redaction;
- provider activation is reachable only through admitted composition;
- a Provider with a mismatched `experience_id` is rejected during composition;
- summaries and cursors contain JSON-safe data and stable opaque IDs.

Behavior tests must cover:

- one-provider and federated queries;
- deterministic merge order and cursor continuation;
- unconsumed Provider candidates surviving the next Hub page;
- strict partial failure withholding a canonical continuation cursor;
- expired query/composition/index-generation cursors;
- ordinary upserts preserving an index generation/query snapshot and a
  generation swap forcing restart;
- duplicate provider IDs and rejected untrusted contributions;
- one process-level pack binding being reused by its Experience composition;
- an OEM layer lacking the `continuity.provider` slot permission being rejected;
- preview cancellation during fast selection;
- stale/missing index behavior;
- prepare failure preserving the current session;
- commit/invalidation failure entering typed recovery with no false current;
- post-commit rebind failure producing the declared degraded state;
- same-domain and cross-domain activation policies;
- narrow, wide, empty, loading, partial-failure, and non-interactive channels.

Initial performance budgets should be measured, then fixed in tests where the
environment permits:

- first frame performs no full transcript loads;
- authority reads are bounded by provider count and page size; compatibility
  JSON index full-file cost is measured separately until replaced;
- only the selected preview is opened;
- opening the Coding Provider does not enumerate all worktrees;
- rebuilding an index never blocks the screen until completion.

## Decisions And Rejected Alternatives

### Accepted

- Reuse the existing runtime capability profile and admission system.
- Model domain, capability, experience, and continuity independently.
- Keep authoritative stores and summary indexes provider-owned.
- Put common semantic fields in Harness and their standard terminal rendering
  in `harnesstui`.
- Keep Product fields, filters, shortcuts, and custom renderers out of the
  common Resume page; expose bounded Product details through generic preview
  sections or a separate Product history UI.
- Use an opaque provider-qualified target and bounded federation.
- Treat `/resume` as the first client of a general continuity mechanism.

### Rejected

- **One universal `SessionSummary` containing every Product field**: it creates
  a permanently expanding cross-product schema.
- **Git scopes in Harness/TUI core**: they make a Coding policy appear
  universal.
- **One provider per installed capability by inference**: capabilities do not
  define continuity ownership.
- **A mutable global capability/service registry**: it bypasses admission,
  provenance, deterministic bootstrap, and resume compatibility.
- **Redis as the authoritative transcript store**: an index implementation
  must not dictate durable domain storage.
- **Eagerly load every candidate and preview**: it makes first-frame latency
  proportional to total history.
- **Put all custom columns in `harnesstui`**: channel reuse improves while
  Product coupling gets worse.
- **Dynamically inject Product columns into the common page**: it adds schema,
  renderer, layout, permission, and conflict contracts that V1 does not need.
- **Put list rendering in Product packages**: it duplicates common interaction
  mechanics.

## External Review Prompt

请评审
`docs/internals/architecture/harness/capability-domain-presentation-continuity-architecture.md`。
请结合仓库现有的 `RuntimeCapabilitySlot/Profile/Admission`、Harness/Product/OEM
边界、conversation/transcript catalog、session transition 以及 TUI surface
实现，重点检查：是否重复发明能力系统；domain、capability、experience、
continuity unit 的关系是否足以支持 Coding/PPT/Design 混合 OEM；摘要索引与
权威存储是否分离；通用 Resume 是否确实只暴露公共摘要字段，并把 Product
字段/过滤器/renderer 排除在公共页面之外；联邦 keyset 游标是否会漏项；索引
缺失时是否能不阻塞首屏；现有 session commit 语义与未来跨 Experience 激活
是否被准确描述。请按“阻断问题 / 重要修改 / 可选改进 / 结论”输出，并为每个
问题给出具体章节和建议改法；本轮只评审设计，不修改代码。
