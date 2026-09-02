# Harness Tool Governance

## Status

- Design status: reviewed target contract; runtime implementation is
  incremental and is not completed by this document.
- Tracking issue: `#517`.
- P0 prerequisite: `#516` preserves deferred positive Tool Intent when a local
  contributor performs Additive Activation.
- Canonical vocabulary: [Tool Governance Glossary](tool-governance-glossary.md).
- Primary owners: `loushang.harness.capabilities.tools`,
  `loushang.harness.session.tool_runtime`, the Harness tool registry and
  execution seams, `loushang.agent` Model Call preparation, and the narrow AI
  Provider tool-projection seam.

This document is normative for new tool-governance APIs. Compatibility names
remain supported during migration, but they do not redefine the terms below.

## Decision Summary

Loushang will govern Tools through four distinct layers:

```text
owner publications --------> Tool Catalog --------------------+
                                  |                            |
                                  v                            |
Product default profile -> Default-Selection Reconciler        |
                                  | separate Intent CAS         |
                                  v                            v
user/session editor --------> Tool Intent State -> Resolved Tool Intent
                                                               |
Tool Policy <----- principal / workspace / mode / effect ------+
       |                                                       |
Provider Support ----------------------------------------------+
                                                               v
                                                     immutable Tool Plan
                                                               |
                                                               v
                                                          one Model Call
                                                               |
                                                               v
                                                invocation-start revalidation
                                                               |
                                                               v
                                                         Tool Execution
```

The governing equation for one Model Call is:

```text
Effective Tools = Catalog availability
                  intersect resolved positive Intent
                  intersect exposure Policy
                  intersect Provider Support
                  after conflict and budget resolution
```

The intersection is ordered and provenance-preserving, not a set operation in
the implementation. Every exclusion remains explainable.

The main decisions are:

1. Publication changes Catalog availability and never changes Tool Intent.
2. Tool Intent survives temporary unavailability and temporary Policy denial.
3. Explicit Disable is a retained suppression keyed by session and Tool Name;
   withdrawal, reconnect, owner change, and republish cannot resurrect it.
4. Local contributors may add or explicitly subtract only what they name and
   only through a separately granted narrow capability. Tool ownership alone
   grants no intent authority. Exact replacement is reserved for a
   Complete-Truth Holder and one declared scope.
5. An Owner Generation atomically replaces only that Owner Key's Catalog
   slice. No plugin or pack reconstructs the global Catalog from its local
   view.
6. Product default composition and user Explicit Intent use different narrow
   capabilities. Installing multi-agent or another Product capability does not
   fabricate a user Explicit Enable.
7. Every Model Call receives one immutable Tool Plan. Catalog, intent, policy,
   or Provider changes during the call affect only a later plan.
8. Execution revalidates revocation, invocation Policy, and Approval without
   widening the frozen plan. Hard Revocation is linearized before handler
   start; it cannot promise rollback of side effects that already occurred.
9. A Tool Binding Pin is a read-only use claim. It is never a Registration
   Lease or Plugin artifact-retention pin.
10. `Agent.tools` is a compatibility projection, not an authority or durable
   state store.

## Problem Statement

The current runtime has useful but incomplete separation:

- `available_names` records a filtered registry view;
- `requested_names` preserves positive requests across missing definitions;
- `active_names` resolves requested names against current availability;
- `allowed_names` is applied while positive requests are retained; and
- `Agent.tools` is rebound whenever the resolved view changes.

P0 fixed one concrete violation: collaboration-tool registration previously
rebuilt an exact request from the currently resolved `active_names`, erasing
base-tool requests whose definitions had not yet been published.

Three broader risks remain:

1. **Negative intent is absent.** A Tool removed after a user disables it can
   be treated as new when republished and automatically selected again.
2. **Policy and intent are conflated.** Eager allowlist filtering can erase a
   request instead of preserving it for a future policy revision.
3. **Model exposure is mutable.** The session has no first-class immutable
   record proving which schemas, definitions, and bindings one Model Call saw.
4. **Legacy control paths hold excessive authority.** `/tools`, RPC,
   ExtensionContext, and Product composition can all reach positive-list exact
   replacement or the same additive API despite having different intent.
5. **Registry `enabled` is overloaded.** Today it is default/on-demand
   selection metadata, not publication availability; treating it as a Catalog
   gate would make Arch/LSP on-demand Tools impossible to select manually.

Without a common contract, future plugin publication, MCP reconnect, role
changes, or Product composition work can reintroduce last-writer-wins behavior
even when each local API appears correct.

## Goals

- Make Catalog, Intent, Policy, Provider Support, and per-call exposure
  independently observable and revisioned.
- Preserve user and Product intent across owner publication order, withdrawal,
  republish, and temporary denial.
- Make additive, subtractive, reset, and exact-replacement authority explicit.
- Enforce replacement authority with narrow capabilities rather than caller
  convention.
- Give dynamic owners an atomic, owner-scoped publication lifecycle.
- Freeze the schema-to-binding relationship for one Model Call.
- Retain Product control of defaults, admission, policy, prompt wording, and
  presentation while keeping coordination Product-neutral.
- Provide a migration path from the existing coordinator without a global
  rewrite or a second tool registry.
- Preserve child-agent policy ceilings and on-demand Tool behavior while
  migrating user and Product control paths.

## Non-Goals

- Replacing workspace Tool implementations or moving Product selection into
  Harness.
- Defining MCP transport, plugin Package acquisition, or physical artifact
  deletion.
- Persisting executable callables or Provider schemas in transcripts.
- Treating Approval as durable Tool activation.
- Guaranteeing that a withdrawn or security-revoked Tool remains executable
  merely because an older plan exposed it.
- Introducing source-pinned user intent in v1. Intent is keyed by logical Tool
  Name; provenance remains visible in plans and diagnostics.
- Extracting a universal Owner Generation publisher before the governance
  state model is implemented and proven.

## Ownership Boundaries

### Harness Owns

- Tool Catalog mechanics and owner-scoped atomic publication;
- revisioned Tool Intent storage and mutation mechanics;
- deterministic selection and exclusion records;
- immutable Tool Plan construction and lease/pin lifecycle;
- compatibility Agent rebinding;
- execution-plan identity validation and revocation hooks;
- Product-neutral snapshots, diffs, audit drafts, and explanation records.
- narrow capability types that make intent and publication authority
  unforgeable by ordinary contributors.

### Products Own

- default Tool profiles and automatic-new-tool selection policy;
- source admission and conflict policy;
- allowed Tool ceilings, role/workspace/effect Policy, and Approval rules;
- Product prompt wording and Tool descriptions;
- Provider/Model choice and budget policy;
- session persistence choice and user-facing commands or UI;
- Product composition changes to the bound default profile;
- migration of a session from one default-profile revision to another; and
- mapping startup flags, multi-agent types, extensions, and RPC commands onto
  the narrow governance capabilities.

### Tool Owners Own

- definitions and execution bindings in their own Owner Generation;
- stage, commit, withdrawal, and retirement of that generation;
- source-specific health and lifecycle evidence;
- compatibility with in-flight plan pins according to the retirement contract.

A Tool Owner does not own Product activation, Policy, another owner's Catalog
slice, or the global session tool list.

### Agent And AI Seams Own

The Agent model-call owner prepares one finalized Model context and retains the
Tool Plan Execution Lease through the corresponding Assistant response and
emitted Tool Call batch. It routes calls only through that plan.

The AI Provider adapter owns translation from the provider-neutral Tool schema
to the exact Provider request schema and returns a projection receipt and
fingerprint. It does not choose Tools or look up newer Catalog state.

### Plugin Lifecycle Owns

For Plugin-backed Tools, the Plugin lifecycle remains the sole authority for
Plugin Instance drain, security revocation, retirement completion, and artifact
retention. Tool governance projects those facts; it does not create a competing
Plugin lifecycle or release Package retention pins.

## Canonical State Model

### Tool Catalog Snapshot

The Catalog is an immutable snapshot assembled from committed Owner
Generations. A future public record should carry at least:

```text
ToolCatalogSnapshot
  catalog_epoch
  catalog_revision
  entries[]
    tool_name
    definition_fingerprint
    owner_key
    owner_incarnation
    owner_generation
    source_provenance
    publication_state = current
    legacy_default_selection_eligible
    binding_revision
    catalog_order
  bounded_last_seen[]
```

The concrete registry may remain mutable internally. Readers consume immutable
snapshots and never infer ownership from a plain list of definitions.

Catalog identity is split deliberately:

- `catalog_epoch` fences one session-local Catalog realization across process
  reconstruction;
- `catalog_revision` identifies one global observation;
- `owner_generation` identifies one owner's replacement unit;
- `definition_fingerprint` detects schema/metadata replacement under the same
  Tool Name; and
- `binding_revision` identifies the execution binding that a Tool Plan pins.

No one counter substitutes for all four facts.

The current registry `enabled` field maps only to
`legacy_default_selection_eligible`. Existing on-demand Arch and LSP Tools stay
Catalog-available and manually selectable when it is false. Any future
publication-level availability gate uses a new, differently named field and an
explicit migration; P1 must not reinterpret legacy `enabled`.

Admission failures are not current Catalog entries. A separate immutable
snapshot retains bounded, source-level evidence when plan explanation needs to
distinguish a rejected candidate from a name that was never published:

```text
ToolAdmissionSnapshot
  catalog_epoch
  admission_revision
  admission_policy_revision
  outcomes[]
    tool_name
    source_provenance
    owner_key
    owner_incarnation
    candidate_generation
    candidate_fingerprint
    outcome
    reason_code
```

If a winner for the same Tool Name exists, its plan entry is not
`conflict_rejected`; the losing source appears only in source-level admission
diagnostics. If no candidate is admitted, a requested name may use the bounded
admission outcome as its exclusion evidence.

### Default Profile And Tool Intent State

Tool Intent is session-scoped and independent of Catalog visibility. Product
defaults and user overrides are separate inputs. A bound profile contains its
ordered static names even when their definitions are not published, so base
Tools become Pending Requests instead of disappearing during bootstrap:

```text
DefaultToolProfileSnapshot
  profile_id
  profile_revision
  static_default_names[]
  automatic_selection_policy_fingerprint
  automatic_selection_enabled
```

Product composition may publish a new profile revision, for example when
multi-agent capabilities are installed. That revision adds Product defaults;
it does not call the user Explicit Enable capability.

Composition is owner-scoped inside the Product profile. Base, multi-agent, LSP,
and other Product capabilities receive namespace/contributor-bound handles and
replace or withdraw only their own ordered fragments. The Product profile
assembler is the sole Complete-Truth Holder: it combines current fragments
under explicit namespace priority, rejects unresolved conflicts, and publishes
one complete profile revision by compare-and-swap. Concurrent base and
multi-agent updates cannot reconstruct or overwrite each other's fragments.

The target source state is:

```text
ToolIntentSnapshot
  session_id
  intent_revision
  bound_profile_id
  bound_profile_revision
  selection_mode = inherit_defaults | explicit_only
  explicit_enabled[]
    tool_name
    mutation_sequence
  explicit_disabled[]
    tool_name
    mutation_sequence
  automatic_decisions[]
    tool_name
    first_seen_sequence
    decision_profile_revision
    candidate_fingerprint
    selected_by_default
  observed_catalog_cursor = (catalog_epoch, catalog_revision)
```

For one Tool Name, the decision is exactly one of:

- **inherit default:** no explicit override; use the session-bound default
  profile and automatic-selection history;
- **explicitly enabled:** positive intent regardless of the default profile;
- **explicitly disabled:** negative intent regardless of the default profile.

Explicit Enable clears Explicit Disable for the same name. Explicit Disable
clears Explicit Enable. Intent Reset clears both and returns the name to
inherit-default behavior.

`selection_mode=explicit_only` is the complete user-owned form used by a true
`/tools only` operation and by an explicit no-tools selection. It selects only
the ordered `explicit_enabled` entries and prevents future unknown Tools from
appearing through defaults. Per-name suppressions remain available for
explanation. Resetting the complete mode returns to `inherit_defaults` only
through the Complete-Truth Holder.

Intent is keyed by `(session_id, tool_name)`, not Owner Generation. This is the
safer v1 rule: a disabled logical capability cannot return merely by changing
plugin revision or owner provenance. A future source-pinned selection feature
must be a separate, explicit contract.

The Product default profile is bound to a session by revision. Resume must
rehydrate its exact ordered snapshot and fingerprint or run an explicit,
audited migration; an ID alone is insufficient. Product composition changes
also use an audited profile-revision transition. Tool Plans capture the
revision so historical calls remain explainable.

An Automatic Selection Decision records both `true` and `false` outcomes.
A logical Tool Name is first-seen once per session, not once per profile
revision. Withdrawal and republish reuse the recorded outcome. Profile
migration never makes existing names “new”; it retains decisions unless the
migration receipt explicitly transforms named decisions.

The automatic decision is computed independently of Explicit Disable.
Suppression masks the result. Therefore a name first published while disabled
may record `selected_by_default=true`, remain ineffective, and return to that
default after Intent Reset.

### Default-Selection Reconciliation

Catalog commit only publishes availability. It emits a Catalog diff; a
Product-owned Default-Selection Reconciler observes the committed Catalog and
bound profile, then records missing Automatic Selection Decisions through a
separate, idempotent Intent compare-and-swap. Publication, reconciliation, and
plan construction are different authorities.

The reconciler advances `observed_catalog_cursor` only after every genuinely
new name in that epoch/revision has a recorded outcome. A reconstructed live
Catalog uses a new epoch; replayed decisions are reused and the cursor advances
without making old names new. Plan construction requires the Intent snapshot
to have observed its Catalog cursor. The Model Call
preparation path waits for bounded reconciliation; timeout or failure returns
`default_selection_pending` and fails preparation closed. The Tool Plan Builder
never mutates Tool Intent and never silently omits an unreconciled new name.

Resolved Tool Intent is an immutable projection identified by
`(intent_revision, bound_profile_revision)`. In `inherit_defaults` mode its
ordered positive names are:

```text
static default names
+ automatic decisions where selected_by_default
+ explicit enabled names
- explicit disabled names
```

In `explicit_only` mode, only ordered Explicit Enable entries are positive.
Both modes retain suppressions and Pending Requests for explanation.

### Tool Policy Snapshot

Selection and execution policy share Product ownership but remain distinct
decisions:

```text
ToolPolicySnapshot
  policy_revision
  principal_revision
  workspace_revision
  mode_revision
  hard_revocation_epoch
  exposure_decisions[candidate identity]
  hard_revocations[tool_name or binding identity]
```

- **Exposure Policy** decides whether a requested Tool may enter a new Tool
  Plan.
- **Invocation Policy** evaluates one Tool Call, arguments, effect, workspace,
  and current principal.
- **Approval** resolves a particular invocation when Invocation Policy requires
  it.
- **Hard Revocation** blocks new pins and any call that has not crossed the
  Invocation-Start Gate. For an already running handler, it revokes later
  protected capability acquisition and requests cancellation/termination, but
  cannot promise rollback of effects that already occurred.

Temporary denial never mutates Tool Intent. Restoring Policy can therefore
make the Tool effective again without inventing a new activation request.

### Provider Capability Snapshot

The selected Provider/Model contributes a revisioned capability snapshot:

- supported Tool schema dialect and name constraints;
- maximum Tool count and schema/context budgets;
- parallel Tool Call support where it affects exposure;
- Product-selected overflow strategy.

Provider incompatibility excludes a Tool from the plan and produces a stable
reason. It never disables or withdraws the Tool.

The current AI capability surface exposes only coarse Tool-use support. P1C0
must add a narrow Provider tool-projection contract. Plan construction first
freezes provider-neutral definition/schema fingerprints, then asks the selected
adapter to return exact request schemas plus a projection receipt. The finalized
plan records both canonical and actual Provider schema fingerprints. An adapter
that cannot describe limits uses conservative Product defaults; it does not
silently truncate.

### Tool Plan

One `ToolPlan` is immutable and belongs to exactly one Model Call:

```text
ToolPlan
  plan_id
  model_call_id
  session_id
  revision_vector
    catalog_epoch
    catalog_revision
    admission_revision
    admission_policy_revision
    intent_revision
    default_profile_revision
    policy_revision
    principal_revision
    workspace_revision
    mode_revision
    hard_revocation_epoch
    provider_capability_revision
    provider_projection_revision
    binding_set_fingerprint
  entries[]
    tool_name
    definition_fingerprint
    owner_key
    owner_incarnation
    owner_generation
    canonical_schema_fingerprint
    provider_schema
    provider_schema_fingerprint
    binding_identity
    binding_revision
    exposure_policy_evidence
  exclusions[]
    tool_name
    reason_code
    provenance_if_known
    relevant_revisions
```

The durable/audit projection records identities, fingerprints, revisions, and
reasons, never live callables, pins, or leases. `model_call_id` identifies one
Provider invocation; a Provider `tool_call_id` identifies one invocation inside
the Assistant response and is not interchangeable with it.

A plan freezes:

- Tool order and Provider schemas;
- exact definition fingerprints;
- exact execution-binding identities;
- the Tool-derived prompt section for that call; and
- bounded exclusion evidence for requested, candidate, conflict-relevant, or
  budget-relevant Tools.

A plan does not freeze unconditional permission to execute. Invocation Policy,
Approval, binding validity, and Hard Revocation are checked when a Tool Call is
received.

### Tool Binding Pins And Plan Execution Lease

A Tool Binding Pin is acquired internally by
`try_pin(binding_identity, binding_revision, owner_incarnation)` at a
linearization point shared with owner retirement and Hard Revocation. It:

- prevents physical Disposal of that exact binding while held;
- does not keep the binding Catalog-visible;
- exposes only identity, validity observation, and idempotent release;
- cannot activate, deactivate, withdraw, retire, or dispose a registration;
- cannot be serialized; and
- is not exposed on a Tool Plan entry or to hooks/diagnostics; and
- does not replace a Plugin Instance/session-family lease or PLC9B artifact
  transaction/dependency retention pin.

One Tool Plan Execution Lease exclusively owns every pin in a plan. The Tool
Call router resolves a plan entry through that lease; no consumer can release
an individual pin. Acquisition is all-or-nothing. Release is idempotent and
cancellation-atomic after the Provider response and all Tool Calls emitted by
that response reach a terminal result. Parallel Tool Calls share the execution
lease without releasing it early.

From the first successful pin until `PreparedModelCall` handoff, the builder
attempt owns a provisional Tool Plan Execution Lease. Any exception,
cancellation, Provider projection failure, invalid projection receipt, revision
mismatch, or final-context construction failure releases it in a
cancellation-atomic `finally`. Successful handoff is the only ownership
transfer point; afterward the Agent model-call owner releases the lease.

For Plugin-backed Tools, pin acquisition must be nested below the exact live
Plugin Instance/family reference. The Tool layer cannot mint liveness after the
Plugin lifecycle has started draining.

## Deterministic Selection And Ordering

The Tool Plan Builder operates over immutable inputs and produces an ordered
result:

1. Load the session-bound Default Profile and Tool Intent Snapshot.
2. Require Default-Selection Reconciliation through the observed Catalog
   revision; plan construction itself does not perform the mutation.
3. Build Resolved Tool Intent in this order:
   - Product preferred names in profile order;
   - other default-selected names in stable first-seen order;
   - explicitly enabled names in intent mutation order.
4. In `explicit_only` mode use only explicitly enabled names; otherwise remove
   Explicitly Disabled names while retaining an exclusion record.
5. Resolve each remaining name against the Tool Catalog and bounded Tool
   Admission snapshots.
6. Apply Exposure Policy and Provider Support to exact candidate identities.
7. Apply Product-declared Tool count/schema budgets using a deterministic,
   explainable overflow rule. Silent truncation is forbidden.
8. Materialize and pin exact execution bindings.
9. Ask the Provider adapter for exact request-schema projection and receipt.
10. Re-read the complete revision vector. On equality, emit one Prepared Model
    Call containing final context, options, Tool Plan, and Tool Plan Execution
    Lease.

Duplicate names retain their first position. Explicit Enable of a default name
does not reorder it. Disabling and then explicitly re-enabling a non-default
name appends it at the new intent mutation position. Intent Reset returns the
name to the default profile's ordering behavior.

If any required snapshot or binding revision changes while a plan is being
built, construction retries from fresh immutable snapshots within a bounded
attempt budget. Exhaustion fails the Model Call closed with a diagnostic; it
does not publish a mixed-revision plan.

Primary exclusion reasons use this fixed precedence, with other applicable
reasons retained in order:

```text
hard_revoked
explicitly_disabled
conflict_rejected
default_selection_pending
not_published
registry_disabled
policy_denied
provider_unsupported
budget_excluded
binding_unavailable
not_selected_by_default
```

`registry_disabled` is reserved for a future Catalog-visibility state and does
not describe today's legacy `enabled=False`. `not_selected_by_default` applies
only after reconciliation completed and there is no positive intent.

## Mutation API And Authority

The target API is split into construction-time-bound narrow capabilities.
Possessing one does not imply possession of another:

```text
ToolIntentActivator
  activate_tool_names(...)

ToolIntentUserEditor
  activate_tool_names(...)
  deactivate_tool_names(...)
  reset_tool_intent(names)
  set_explicit_only(names, expected_revision)

CompleteToolIntentRestorer
  replace_tool_intent(snapshot, expected_revision)

ToolDefaultProfilePublisher
  publish_profile(snapshot, expected_profile_revision, expected_intent_revision)

ToolDefaultProfileContributorHandle  # namespace/contributor bound
  replace_contribution(fragment, expected_contribution_revision)
  withdraw_contribution(expected_contribution_revision)

OwnerGenerationHandle        # Owner Key/incarnation bound at admission
  publish_generation(...)
  withdraw_generation(...)
```

A Tool Owner receives no Tool Intent capability merely by owning a Catalog
slice. A Policy adapter receives no intent editor. Product composition receives
a namespace-bound Default Profile Contributor Handle, not the complete
publisher or user editor. Only the Product profile assembler receives
`ToolDefaultProfilePublisher`. The target operations are:

| Operation | Semantic effect | Authorized caller |
| --- | --- | --- |
| `activate_tool_names(names, expected_revision=None)` | Clear suppression for the names and set ordered Explicit Enable; preserve every unmentioned decision. | `ToolIntentUserEditor`, or a deliberately narrower user-intent activator. |
| `deactivate_tool_names(names, expected_revision=None)` | Clear positive explicit override and set Explicit Disable; preserve every unmentioned decision. | `ToolIntentUserEditor`; never a Tool Owner or Policy adapter by implication. |
| `reset_tool_intent(names=None, expected_revision=None)` | Remove explicit overrides for named Tools, or all Tools when the complete session intent owner requests it. | Session intent owner; global reset requires Complete-Truth Holder authority. |
| `set_explicit_only(names, expected_revision)` | Enter `explicit_only` and commit the exact ordered positive selection, including an empty no-tools selection. | `ToolIntentUserEditor` operating from an authoritative intent snapshot. |
| `replace_tool_intent(snapshot, expected_revision)` | Replace the entire intent state for one session with a typed complete snapshot. | Restore/import/migration owner holding complete session intent. |
| `replace_contribution(fragment, expected_revision)` | Replace only the handle-bound Product default-profile contribution and ask the assembler to publish a new complete profile. | Exact `ToolDefaultProfileContributorHandle`, such as the base or multi-agent Product composition owner. |
| `publish_profile(snapshot, expectations)` | Bind a complete Product profile revision, preserve user overrides and seen-name decisions, and schedule reconciliation without making seen names new. | Product profile assembler through `ToolDefaultProfilePublisher`. |
| `publish_generation(generation, entries, admission_receipt, expectations)` | Atomically replace only the handle-bound Owner Key's Catalog slice. | Exact `OwnerGenerationHandle`; caller cannot supply its own Owner identity. |
| `withdraw_generation(expected_generation)` | Remove only the handle-bound Owner generation from availability. | Exact `OwnerGenerationHandle` or lifecycle supervisor capability. |
| `build_tool_plan(call_context)` | Read immutable snapshots and create one call-scoped plan. | Model invocation owner. |

The existing `request(names)` and `apply_active_tools(names)` retain an isolated
`LegacyPositiveIntentState` with exact positive names and caller order during
migration. They cannot be mapped losslessly onto inherit/default/explicit
three-state Intent: `[]` currently suppresses defaults, and a supplied list can
reorder default Tools. New code must not call these APIs. Each caller migrates
to a narrow capability before the compatibility state is removed.

Every intent mutation returns previous/current snapshots and a diff. Mutations
support optimistic `expected_revision` checks so concurrent UI, extension, and
restore actions cannot silently overwrite each other.

## Append Versus Replace Rules

| State | Append/subtract authority | Replacement authority |
| --- | --- | --- |
| Catalog | An owner stages entries only for its next generation. | An Owner Generation replaces that Owner Key's slice; only the Catalog assembly owner can replace a complete restored Catalog snapshot. |
| Tool Intent | Explicit activation, deactivation, and reset mutate named entries. | Only the session intent owner may replace a complete typed snapshot using an expected revision. |
| Product default profile | Product capability composition contributes through declared profile namespaces. | Only the Product profile assembler publishes the complete revisioned profile snapshot. |
| Tool Policy | Narrow policy providers contribute decisions within declared namespaces. | The Product policy owner replaces its complete revisioned policy snapshot. |
| Tool Plan | No append or mutation after construction. | Never replaced in place; build a new plan for a new Model Call. |
| Agent compatibility view | Rebind from a complete resolved projection. | The session projection owner may replace `Agent.tools`; contributors may not. |
| Legacy positive intent | No new callers. | Only the isolated compatibility adapter retains exact-list behavior until migrated. |

The universal rule is: **only the holder of complete truth for an explicit
scope may replace that scope**.

## Owner Generation Publication Contract

Publication follows one lifecycle:

```text
contribute -> admit against Catalog/policy revisions
           -> stage complete generation
           -> validate and prepare retirement evidence
           -> owner-current-pointer CAS
              new: staged -> current
              old: current -> superseded
           -> Catalog revision -> outcome record -> notification

withdraw: current -> withdrawn -> retiring -> disposed | cleanup_debt
replace:  current -> superseded -> retiring -> disposed | cleanup_debt
```

Required properties:

1. Every generation is complete and immutable after commit.
2. A failed stage or validation leaves the prior generation visible.
3. Commit is one Catalog owner-current-pointer compare-and-swap. The complete
   new slice becomes visible and the complete old slice becomes invisible in
   the same Catalog revision. Per-entry lease activation is not an atomic
   owner-slice cutover.
4. The commit linearization point revalidates expected owner generation,
   Catalog revision, admission-policy revision/fingerprint, owner incarnation
   or fencing epoch, content fingerprint, and every cross-owner Tool Name
   conflict. A stale admission result returns a typed conflict for restage.
   An unresolved conflict never becomes silent last-writer-wins state.
5. Same generation plus same content/admission fingerprint is idempotent.
   Same generation plus different content, a stale owner incarnation, or an
   ABA attempt fails closed.
6. Commit emits one Catalog revision and provenance-preserving diff.
7. Withdrawal preserves Tool Intent and records affected Pending Requests.
8. Republish resolves pending positive intent but cannot bypass suppression,
   Policy, Provider Support, or plan construction.
9. A normal withdrawal blocks new plans but lets already pinned plans retain
   their exact binding until release. Hard Revocation is the explicit exception.
10. A superseded or withdrawn generation is Catalog-invisible and rejects new
    pins. Its exact registrations may remain only to serve existing pins.
11. Retirement waits for plan pins and executions or follows accepted Hard
    Revocation termination evidence; disposal never guesses.
12. Cleanup failure never rolls back a committed successor. It creates bounded,
    retryable `cleanup_debt` with the exact retirement handle.

This contract may later be implemented by a generic
`OwnerGenerationPublisher[T]`. The generic mechanism must not know Product
default selection or mutate Tool Intent. `coding.base` continues to decide
which workspace Tool pack to publish and how it is presented; Harness owns how
an admitted generation is published safely.

### Plugin Lifecycle Integration

Tools own Catalog publication state, not Plugin Instance lifecycle. Every
Plugin-backed Owner Generation records the exact Plugin Instance and session
family reference from which its definitions and bindings were captured.

- PLC remains the sole authority for `ACTIVE -> DRAINING/REVOKING -> RETIRED`,
  owner retirement evidence, and artifact retention.
- Ordinary management disable/update follows the accepted Product/PLC drain
  or `restart_required` contract; it is not upgraded to Hard Revocation by the
  Tool layer.
- Only a durably accepted PLC security revocation may project a Plugin Tool
  Hard Revocation.
- PLC retirement completion waits for RegistrationScope disposal, the final
  Tool Plan Pin, and every running invocation to complete or produce accepted
  termination evidence.
- A Tool Plan Execution Lease cannot release, transfer, or replace PLC9B transaction or
  dependency pins and therefore cannot create a zero-pin artifact interval.

## State-Transition Matrix

| Event | Catalog | Intent | New Tool Plan | Existing Tool Plan |
| --- | --- | --- | --- | --- |
| Requested name is not published | unchanged | positive request retained | excluded as `not_published` | unchanged |
| Owner publishes requested name | owner slice/generation changes | unchanged | included if Policy/Provider permit | unchanged |
| User explicitly disables available name | unchanged | suppression recorded | excluded as `explicitly_disabled` | plan unchanged; Product serializes by cancelling/restarting an active Model Call when immediate user effect is required |
| Name is disabled before first publication | later publication remains independent | suppression retained; automatic decision is recorded independently | excluded as `explicitly_disabled` | unchanged |
| User resets a name first seen under suppression | unchanged | suppression clears; recorded automatic outcome remains | follows the recorded outcome/default | unchanged |
| Owner withdraws explicitly disabled name | entry removed | suppression retained | excluded as `explicitly_disabled` with unavailable provenance context | unchanged unless hard-revoked |
| Owner republishes explicitly disabled name | new generation available | suppression retained | still excluded as `explicitly_disabled` | unchanged |
| Owner republishes a name with automatic decision `false` | new generation available | recorded decision remains `false` | excluded as `not_selected_by_default` absent Explicit Enable | unchanged |
| User explicitly enables missing name | unchanged | positive request recorded | excluded as `not_published` | unchanged |
| User resets name | unchanged | explicit override removed | follows bound default profile | unchanged |
| Product migrates default profile | unchanged | named automatic transforms only when migration receipt says so; seen names do not become new | later plan uses new profile revision | unchanged |
| Exposure Policy denies requested name | unchanged | unchanged | excluded as `policy_denied` | unchanged; invocation policy still revalidates |
| Exposure Policy permits name again | unchanged | unchanged | included in a later plan if otherwise eligible | unchanged |
| Provider cannot represent schema | unchanged | unchanged | excluded as `provider_unsupported` | unchanged |
| Owner replaces schema/binding | owner generation and fingerprints change | unchanged | later plan pins replacement | older plan retains old pin unless revoked |
| Hard Revocation arrives | new pins denied; entry may remain as diagnostic tombstone | unchanged | excluded/failed closed | not-started calls are denied; running calls report cancel/termination disposition without promising rollback |

## Concurrency And Failure Semantics

### Snapshot Discipline

Catalog, Intent, Policy, and Provider capability owners publish immutable
snapshots. Plan construction does not hold one owner's lock while calling
another owner. It reads revisions, resolves, pins bindings, then verifies the
complete revision vector, including admission, binding, and Hard Revocation
epochs. A mismatch releases pins and retries.

### Intent Compare-And-Swap

Concurrent intent writers use `expected_revision`. A stale exact replacement
fails with `tool_intent_revision_conflict`. Named additive/subtractive actions
may retry by reapplying the same idempotent mutation to the latest snapshot.
They never translate a stale resolved view into exact replacement input.

### Publication Failure

Publication recovery has three explicit phases:

```text
prepare exact successor and predecessor-retirement receipt
  -> Catalog owner-current-pointer cutover
  -> record publication outcome and notify observers
```

- Failure before cutover rolls back provisional state and leaves the prior
  generation current.
- Failure after cutover but before outcome recording leaves the successor
  current. Exact generation/retirement handles remain reachable so recovery can
  record the same outcome idempotently.
- Failure retiring or disposing the predecessor does not roll back the
  successor. The predecessor stays invisible in `cleanup_debt`, rejects new
  pins, and retains its exact retry handle.
- If rollback/deactivation itself cannot prove restoration, the system does
  not claim that the prior view is complete. Plan construction fails closed
  until it can rebuild from the authoritative Catalog snapshot.

The Tool Catalog is a session-local live projection, not a durable Plugin
lifecycle ledger. Process recovery reconstructs it from Product composition
and exact PLC owner evidence. Notifications are idempotent hints, never commit
authority or recovery evidence.

### Plan Pin Failure

If any binding cannot be pinned, the builder releases all pins obtained for the
attempt. Product policy decides whether to exclude that Tool with a stable
reason or fail the entire call; Tools whose prompt semantics require all-or-
nothing composition must fail the call closed.

### In-Flight Withdrawal And Revocation

Ordinary withdrawal affects new plans. An existing plan may execute only its
pinned binding and still passes current invocation Policy and Approval.

Hard Revocation is monotonic and linearizes with the Invocation-Start Gate:

- calls not past the gate return `denied_before_start`;
- a running handler receives cancellation/termination and later protected
  capability acquisitions are denied;
- its terminal disposition distinguishes `cancellation_requested`,
  `completed_before_revocation`, and `termination_failed`; and
- no status promises rollback of external effects already produced.

The owner generation reaches Disposal only after every invocation completed or
termination is proved. A call never resolves by Tool Name against a newer
generation.

### Intent Mutation During A Model Call

An intent change does not rewrite an immutable plan. When a user requires an
immediate `/tools` change, the Product session operation serializes the change
with the running turn: cancel the active Model Call, wait for its plan lease to
settle, commit the intent mutation, then allow a new call. A Product that elects
not to cancel must label the mutation as applying to the next Model Call; it
cannot quietly execute under a half-updated plan.

## Persistence And Resume

Durable Products add versioned records rather than persisting the in-memory
coordinator:

```text
ToolIntentMutationV1
  session_id
  mutation_id
  expected_intent_revision
  operation
  bounded names or complete snapshot reference
  actor/provenance
  resulting_intent_revision

ToolIntentSnapshotV1
  complete bounded Tool Intent State
  exact DefaultToolProfileSnapshot + fingerprint
  codec/schema version
```

The codec rejects duplicate names, invalid order sequences, unsupported
versions, and records beyond Product-declared size/count bounds. The reducer is
deterministic and validates every expected revision.

Mutation ordering is durable-first:

1. validate and prepare the mutation against the current revision;
2. append the durable mutation/snapshot transaction;
3. only after durable commit publish the new in-memory Intent Snapshot; and
4. emit idempotent projection notifications.

Append failure leaves the live snapshot unchanged. A crash after durable commit
but before live publication is recovered by reducer replay.

The durable session projection stores:

- explicit enabled/disabled decisions and stable mutation order;
- Intent Selection Mode;
- the complete ordered bound Default Profile snapshot, revision, and
  fingerprint;
- Automatic Selection Decisions, including selected and rejected outcomes;
- intent revision and migration receipts; and
- audit-safe Tool Plan identities, revision vectors, entry fingerprints, and
  exclusion reasons when call auditing is enabled.

It does not store Tool Definitions, callables, leases, credentials, or live
Owner handles.

Resume ordering is intentional:

1. restore Tool Intent before Product multi-agent installation and before
   dynamic owners publish;
2. represent unresolved positive names as Pending Requests;
3. restore the exact Product default-profile snapshot or perform an explicit
   migration;
4. reconstruct Catalog state from live owners/PLC evidence;
5. run separate Default-Selection Reconciliation through that Catalog
   revision; and
6. build a fresh Tool Plan for the next Model Call.

Historical plans are evidence, not executable recovery objects. Plan audit is
attached to the existing `ModelInputSnapshotV2` and
`ModelCallOutcome.invocation_id`; it must not create a competing Model Call
fact stream.

### Continuity And Multi-Agent Rules

- Resume and clone restore the exact Tool Intent state of the selected
  continuity point.
- Fork and branch copy Intent state by value at the branch point. Later parent
  and child mutations are isolated and retain distinct revisions.
- Import validates the versioned records and either preserves the bound profile
  snapshot or requires an explicit migration receipt. Export carries only the
  durable data projection.
- A newly spawned subagent receives a fresh child Tool Intent State from its
  Agent type/Product profile; it does not inherit the parent's mutable user
  Intent implicitly.
- `allowed_tools` in a subagent specification or context plan is a delegated
  Policy ceiling. The effective child ceiling is an intersection with the
  parent's admissible delegation and can never widen it. Child intent may
  retain a denied name for explanation but cannot bypass the ceiling.
- A non-persistent child keeps the same in-memory revision/CAS semantics and
  discards its Intent state only when that child session is disposed.
- Collaboration Tool installation updates the Product default profile. It does
  not create user Explicit Enable records.

Startup compatibility is explicit:

- `--tools <names>` initializes `explicit_only` with the supplied order;
- `--no-tools=all` initializes `explicit_only` with an empty list;
- `--no-tools=builtin` is a Product default-profile overlay that excludes the
  builtin namespace but does not become a permanent user suppression for every
  future name;
- `allowed_tool_names` remains a Policy/delegation ceiling and never erases
  restored Intent; and
- a resume/import intent record takes precedence over create-only startup
  defaults unless the user requests an audited replacement.

## Model Call And Execution Lifecycle

```text
prepare call
  -> snapshot Catalog / Admission / Intent / Policy / Provider
  -> reconcile default selection through Catalog revision
  -> resolve and explain candidates
  -> try-pin exact bindings
  -> project exact Provider schemas and receipt
  -> verify complete revision vector
  -> create PreparedModelCall(final context, options, Tool Plan,
                              Tool Plan Execution Lease)
  -> invoke Model with prepared schemas and tool-derived prompt section
  -> associate Assistant response with plan_id + model_call_id
  -> route returned Tool Call batch by plan + provider tool_call_id + Tool Name
  -> verify definition/binding identity
  -> Invocation-Start Gate: revalidate revocation + Policy + Approval
  -> execute pinned binding or return governed failure
  -> finally release Tool Plan Execution Lease after the Tool Call batch settles
```

Tool Call routing must never look up only the current Catalog entry by Tool
Name. Otherwise a model that saw generation N could execute generation N+1
with a different schema or effect.

P1C requires an Agent boundary change. The current loop builds its model
context before the prepare hook and later looks up Tool Calls by name in a
run-scoped mutable context. The target hook returns a `PreparedModelCall`, not
only call options. Its finalized context is the sole source for prompt and
Provider schemas, and its plan is the sole source for execution binding lookup.

A `before_tool_call` hook may rewrite arguments or target another entry in the
same Tool Plan. A rewrite to a Catalog-only, Agent-view-only, or later-generation
Tool is rejected as `tool_not_in_plan`.

## Observability

Harness exposes structured explanation records; Products choose presentation.
A Product command such as `/tools explain [name]` should be able to show:

```text
read
  catalog: available
  owner: coding.base / generation 12
  definition: sha256:...
  intent: explicitly_enabled
  policy: allowed / revision 41
  provider: supported / revision openai-responses-v3
  latest_plan: included / plan 9b7...
```

For an excluded Tool, the response includes one primary stable reason and
ordered contributing reasons using the precedence defined by the Plan Builder.
Required reason families include:

- `hard_revoked`
- `explicitly_disabled`
- `conflict_rejected`
- `default_selection_pending`
- `not_published`
- `registry_disabled`
- `policy_denied`
- `provider_unsupported`
- `budget_excluded`
- `binding_unavailable`
- `not_selected_by_default`

Diagnostics carry source provenance and revisions but redact secrets,
credentials, raw Policy internals, and unrestricted callable details.

`ToolExplanation` joins the current Catalog entry, a bounded optional last-seen
entry, Resolved Intent/default/automatic decision, Policy/Provider observation,
and the latest applicable Tool Plan. Contribution conflicts remain source-level
admission diagnostics when a same-name winner exists.

Tool Plans do not embed exclusions for every item in a large MCP Catalog. They
retain only requested, candidate, conflict-relevant, and budget-relevant
exclusions under Product bounds. `/tools explain <name>` may compute a bounded
point query from current snapshots and tombstones. Unnamed listing endpoints
are paginated and never expose an unbounded diagnostics history.

## Compatibility And Migration

Every session has exactly one `IntentEngineMode`:

```text
legacy_positive | governed_v1
```

Only the selected engine accepts mutations and supplies resolved intent. There
is no dual read, dual write, mirroring, or last-write-wins merge between legacy
and governed state.

Legacy-to-v1 conversion is a serialized, durable, one-way transaction. It
cancels/settles the current Model Call, captures the authoritative legacy
positive names including order and pending names, creates a governed
`explicit_only` snapshot that preserves that exact result, appends the
migration receipt, and changes the engine mode with an expected revision. Once
`governed_v1` commits, every legacy mutation returns
`legacy_tool_intent_disabled`; it cannot reopen or back-write legacy state.

P1A may install the governed engine and characterize conversion while existing
sessions stay fully legacy. P1B migrates all Product and user control paths
needed by one session, then performs the single mode cutover. Product default
composition keeps using the transitional P0 additive path in a legacy session
and uses namespace-bound profile contributions only after governed cutover.
Mixed concurrent legacy/v1 mutation is therefore rejected rather than
reconciled.

The first implementation issue must inventory and migrate these concrete
control paths; changing only `ToolActivationCoordinator` is insufficient:

| Current surface | Target meaning |
| --- | --- |
| `/tools on <name>` | Named Explicit Enable through `ToolIntentUserEditor`. |
| `/tools off <name>` | Named Explicit Disable; never rebuild from current active names. |
| `/tools only <names>` | Authoritative `explicit_only` CAS from the complete Intent snapshot. |
| `/tools reset` | Complete reset to the bound Product profile; named reset remains narrow. |
| Extension `set_active_tools` | Deprecated global replacement; replace with explicitly admitted named capabilities. |
| legacy RPC `set_active_tools` | Bounded compatibility adapter; add revisioned intent RPC v2. |
| constructor `active_tool_names` | Isolated create-time legacy exact state, then migrate to explicit startup Intent. |
| `allowed_tool_names` and subagent `allowed_tools` | Exposure/delegation Policy ceiling that cannot erase Intent or be widened by a child. |
| registry `enabled` | Legacy default/on-demand eligibility, never Catalog availability. |
| base/multi-agent `activate_tool_names` | Product Default Profile composition, never user Explicit Enable. |
| `Agent.tools` and `get_active_tool_names()` | Compatibility projections, never mutation input or call-time authority. |

### Slice P1A: Intent Semantics

- Add typed selection mode, explicit-enable, explicit-disable, reset,
  Automatic Selection Decision, profile snapshot, and revision state to
  `ToolActivationCoordinator` or its successor.
- Preserve P0 Additive Activation behavior.
- Add the separate Product Default-Selection Reconciler and remove implicit
  mutation from `refresh(activate_new=True)`.
- Treat current registry `enabled` only as legacy default-selection
  eligibility so Arch/LSP on-demand Tools remain available and manually
  selectable.
- Remove Coding-specific default Tool names from the Harness controller and
  require an injected, revisioned Product default profile.
- Implement namespace-bound Product profile contribution handles and the sole
  complete Product profile assembler. Governed sessions use those handles;
  legacy sessions retain the transitional P0 path until atomic cutover.
- Isolate `LegacyPositiveIntentState`; grant no new callers exact-list access.
- Retain `active_names` as a compatibility projection with documentation that
  it is not a Tool Plan.
- Add the resurrection and policy-preservation regression matrix.

### Slice P1B: Policy Separation And Explainability

- Stop filtering stored Tool Intent through `allowed_names`.
- Introduce revisioned exposure decisions and stable exclusion reasons.
- Add Product-neutral inspection records and Coding presentation.
- Keep Invocation Policy and Approval in the existing execution host while
  connecting their revision/evidence surfaces.
- Introduce current/last-seen/admission explanation records with fixed reason
  precedence and bounds.
- Migrate `/tools on/off/reset` to named user-editor operations and `/tools
  only` to authoritative `explicit_only` CAS.
- Perform the one-way session `legacy_positive -> governed_v1` cutover only
  after every required Product/user control path is bound to v1; reject every
  legacy mutation afterward.
- Deprecate Extension `set_active_tools`; extensions receive only explicitly
  admitted named capabilities. Add an intent-revisioned RPC v2 while retaining
  legacy RPC as a bounded compatibility adapter.

### Slice P1C0: Catalog, Binding Pin, And Agent Preparation Seams

- Add the owner-aware Catalog read model, Catalog/admission revisions, exact
  binding identities, owner incarnation, monotonic Hard Revocation epoch, and
  read-only `try_pin` API.
- Implement the minimum Tool-specific owner-current-pointer CAS, cross-owner
  conflict revalidation, incarnation fencing, superseded/withdrawn states, and
  cleanup debt required to make Catalog snapshots and pins coherent. P1C cannot
  run on non-atomic per-entry legacy publication.
- Add Tool Binding Pin/Tool Plan Execution Lease lifecycle without reusing
  Registration Lease or PLC artifact pins.
- Change Agent preparation to return `PreparedModelCall` with finalized
  context, options, Tool Plan, and Tool Plan Execution Lease.
- Add the narrow AI Provider schema projection capability and receipt.

### Slice P1C: Immutable Tool Plan And Execution

- Introduce Tool Plan records and a bounded optimistic builder over P1C0.
- Pin definition/binding identity for one Model Call and Assistant Tool Call
  batch.
- Derive Provider schemas and the tool prompt section from the same plan.
- Route Tool Calls through plan identity; constrain `before_tool_call` rewrites
  to the same plan; revalidate at the Invocation-Start Gate.
- Implement hard-revocation before/after-start dispositions without promising
  side-effect rollback.
- Keep `Agent.tools` as a temporary projection until callers consume plans
  directly.

### Slice P1D: Persistence And Resume

- Add versioned `ToolIntentMutationV1`/snapshot codec, bounds, reducer, and
  durable-first mutation transaction.
- Persist intent overrides, selection mode, the complete profile snapshot,
  Automatic Selection Decisions, and migration receipts.
- Restore intent before Product multi-agent composition and dynamic owners
  publish.
- Bind audit-safe plan summaries to the existing Model Input/Outcome records.
- Implement the declared resume/fork/clone/branch/import/export, startup flag,
  and non-persistent child rules.
- Define a fail-closed synthetic baseline for sessions written before intent
  revisions and require explicit migration when exact legacy state is
  ambiguous.

### Slice P2: Generic Publication Mechanism

- Extract the proven Tool-specific owner-scoped staging, current-pointer CAS,
  withdrawal, retirement, fencing, cleanup debt, and receipts into a generic
  mechanism only after P1 invariants are executable.
- Migrate `coding.base` and dynamic tool owners incrementally.
- Do not move Product pack membership, defaults, prompt text, or Policy into the
  generic publisher.

Each slice requires an independent issue and regression-first implementation.
No slice is justified by deleting the current coordinator before equivalent
behavior is covered.

## Acceptance Matrix

At minimum, implementation must prove:

### Catalog And Publication

- **P1C0:** one owner replacement preserves all other owner slices and a
  successor that omits an old name removes it atomically from the current view;
- **P1C0:** a failed generation leaves the prior generation visible, while
  post-cutover predecessor failure becomes `cleanup_debt`;
- **P1C0:** two conflicting Owners admitted concurrently cannot both commit from
  the same stale Catalog/policy revision;
- **P1C0:** same-generation idempotency, content mismatch, stale incarnation, and
  ABA attempts have deterministic outcomes;
- **P1C0/P2:** withdrawal and republish preserve provenance and monotonic
  Catalog/binding revisions;
- **P1C0/P1C:** snapshot-to-pin racing with withdrawal either obtains the exact
  valid pin or retries/fails closed;
- **P1C/P2:** ordinary withdrawal does not break an already pinned plan;
- **P1C/P2:** PLC retirement evidence waits for the last Tool Plan Pin and
  running call; Tool pins never affect PLC9B artifact retention.

### Intent

- **P1A:** static default and Explicit Enable before publication remain Pending
  Requests and become effective after publication/reconciliation;
- **P1A:** Additive Activation never drops existing or pending positive intent
  and never changes negative intent for unmentioned names; suppression for an
  explicitly named activation target is cleared atomically;
- **P1A:** Explicit Disable before or after first publication survives
  withdrawal, reconnect, owner change, and republish;
- **P1A:** first-seen under suppression records an independent true/false
  automatic decision, and reset restores that recorded outcome;
- **P1A:** a rejected automatic decision stays rejected across republish;
- **P1A/P1D:** profile migration retains existing first-seen decisions unless
  its receipt explicitly transforms named decisions;
- **P1B:** Policy denial and restoration never mutate intent;
- **P1A:** reset returns to the exact bound default-profile snapshot;
- **P1A/P1D:** stale exact replacement fails by revision and durable append
  failure leaves memory unchanged;
- **P1A:** Arch/LSP on-demand definitions remain listed and manually activatable
  when legacy registry `enabled=False`;
- **P1A/P1B:** multi-agent Product composition does not create user Explicit
  Enable records;
- **P1A/P1B:** concurrent base and multi-agent default-profile contributions
  preserve both namespaces, and withdrawing either leaves the other intact;
- **P1B:** `/tools`, Extension, and RPC migrations retain pending requests and
  suppressions, including `only` and empty explicit-only mode.
- **P1A/P1B:** legacy-to-v1 preserves exact positive order and pending names;
  v1 rejects later legacy calls, and concurrent legacy/v1 cutover has one CAS
  winner without dual state.

### Tool Plan

- **P1C0/P1C:** one plan contains one coherent complete revision vector;
- **P1C:** the actual prepared Provider request, prompt Tool descriptions, and
  Provider schemas match the plan fingerprints;
- **P1C:** mid-call publication, intent, and Provider changes affect only later
  plans;
- **P1C:** a returned Tool Call executes the binding whose schema the Model saw;
- **P1C:** a direct Tool path or `before_tool_call` rewrite cannot target an
  entry outside the plan;
- **P1C0/P1C:** plan pin failure rolls back every provisional pin;
- **P1B/P1C:** Provider, admission, and budget exclusions are deterministic,
  bounded, redacted, and explained with fixed reason precedence;
- **P1C:** hard revoke immediately before the Invocation-Start Gate denies;
  immediately after it requests termination without claiming rollback;
- **P1C:** Tool Plan Execution Lease releases exactly once after success, Provider failure,
  parallel Tool batch failure, cancellation, and session disposal.

### Product And Security Boundaries

- Harness does not choose Product defaults or destructive-operation policy;
- contributors cannot obtain a global replacement API accidentally;
- no Policy denial, Approval decision, or source conflict becomes durable
  positive intent;
- diagnostics reveal revisions and reasons without leaking secrets;
- Coding base Tools and collaboration Tools coexist on the first Model Call;
- **P1D:** resume, fork, clone, branch, import/export, startup flags, legacy
  sessions, and non-persistent children follow the declared precedence;
- **P1D:** child Agent Policy ceilings cannot widen and child Intent mutations
  do not mutate the parent.

## Independent Review Disposition

Three independent read-only reviews were completed on 2026-09-02 before this
design was marked reviewed:

1. **State semantics and authority:** required durable true/false Automatic
   Selection Decisions, Resolved Tool Intent, exact-mode semantics, narrow
   capabilities, legacy exact-list isolation, admission evidence, and reason
   precedence.
2. **Lifecycle and concurrency:** required Tool Binding Pins and Tool Plan
   Execution Lease,
   Prepared Model Call integration, owner-current-pointer CAS, stale-admission
   fencing, revocation linearization, cleanup debt, and explicit PLC authority.
3. **Migration and operations:** required legacy on-demand `enabled` mapping,
   Product-default versus user-intent separation, `/tools`/Extension/RPC
   migration, real transcript transactions, multi-agent/continuity rules,
   bounded explanation, and slice-tagged acceptance tests.

Every blocking finding is incorporated into the normative sections and
acceptance matrix above. The review does not approve runtime implementation;
each delivery slice still requires regression-first review against this
contract.

After incorporation, all three reviewers independently re-read their affected
sections and returned `APPROVE` with no remaining blocker or high-severity
finding.

## Rejected Alternatives

### Treat The Active Agent List As Truth

Rejected because it loses pending requests, provenance, negative intent, and
the exact schema/binding relationship for earlier calls.

### Let Every Plugin Replace The Tool List

Rejected because plugins hold partial truth. Replacement from a local view is
the direct class of failure fixed by P0.

### Erase Intent When Policy Denies A Tool

Rejected because a temporary role, workspace, or mode decision would become an
unrequested durable user-state mutation.

### Make Withdrawal Equivalent To Disable

Rejected because owner lifecycle and user intent are independent. It would
lose request-before-publication and reconnect semantics.

### Rebuild Tool Bindings By Name At Execution Time

Rejected because a Model can see one schema and execute a newer implementation
with different effects.

### Extract A Generic Publisher First

Rejected because a generic API built before Intent and Tool Plan boundaries
stabilize would encode today's ambiguous activation semantics and require a
second migration.

## Invariants

1. Publication does not mutate Tool Intent.
2. Policy does not mutate Tool Intent.
3. Provider capability does not mutate Tool Intent or Catalog state.
4. Explicit Disable wins over defaults and automatic selection until reset.
5. Owner replacement cannot remove or reorder another owner's slice.
6. A Local Contributor cannot perform global exact replacement.
7. Pending positive intent survives absence and resolves when availability
   returns.
8. Every Model Call has one immutable Tool Plan.
9. Every executed Tool Call is matched to the exact plan binding or denied.
10. Snapshot/revision races fail closed or retry; they never publish a mixed
    Tool Plan.
11. `Agent.tools` and UI output are projections, never governance authority.
12. Every exclusion from a plan is deterministic and explainable.
13. Automatic selection records both selected and rejected outcomes and is
    never recomputed merely because a Tool was republished.
14. A Registration Lease is never exposed as a Tool Binding Pin.
15. Plugin Tool retirement and Hard Revocation cannot outrank or replace the
    authoritative PLC state machine.
