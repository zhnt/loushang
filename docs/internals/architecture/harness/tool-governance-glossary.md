# Tool Governance Glossary

## Status And Scope

This glossary defines the canonical vocabulary for tool identity, publication,
selection, policy, model exposure, and execution across Harness and Products.
It is normative for new architecture documents and APIs. Existing names are
mapped below where compatibility prevents an immediate rename.

The governing state model and migration contract are defined in
[Harness Tool Governance](tool-governance.md).

The vocabulary deliberately separates four questions:

1. **Catalog:** which Tool Definitions currently exist?
2. **Intent:** which Tool Names does the session want enabled or disabled?
3. **Policy:** which requested Tools may be exposed and executed now?
4. **Tool Plan:** which exact definitions, schemas, and execution bindings are
   frozen for one Model Call?

Publication is not activation, activation is not permission, and permission is
not proof that a Tool was included in a particular Model Call.

## Identity And Definition Terms

| Term | Canonical meaning | Must not mean |
| --- | --- | --- |
| **Tool** | The complete callable capability as understood by the Product: identity, definition, presentation, execution binding, and governance state. Use a narrower term whenever only one facet is meant. | Only a JSON schema, only a Python function, or every Tool with the same display label. |
| **Tool Name** | The stable, session-visible logical identifier used for selection, conflict detection, Model schema naming, and Tool Call routing, such as `read` or `spawn_agent`. | A display label, owner identity, Package identity, or implementation class name. |
| **Tool Definition** | A Product-neutral declaration of one Tool Name, description, input schema, and materialization metadata before it is bound to one Agent or Model Call. | Proof of publication, activation, policy admission, or executability. |
| **Tool Implementation** | The reusable code that validates arguments and performs or delegates the operation behind a Tool Definition. | Product selection policy or publication ownership. |
| **Tool Execution Binding** | The session- and scope-bound callable plus context needed to execute one admitted Tool Definition. | The Provider-facing schema or a durable Tool identity. |
| **Materialized Agent Tool** | The Agent-runtime representation created from a Tool Definition and a Tool Execution Binding. | The Catalog entry or durable activation intent. |
| **Tool Call** | One Model-requested invocation of a Tool Name with arguments and a call identity. | Tool activation or Tool publication. |

## Source, Ownership, And Publication Terms

| Term | Canonical meaning | Must not mean |
| --- | --- | --- |
| **Tool Source** | The provenance of a Tool Definition, such as a built-in Product plugin, extension, MCP server, or runtime contributor. | The authority to activate the Tool or bypass Product policy. |
| **Tool Contribution** | A candidate Tool Definition plus source metadata submitted for admission and conflict resolution. | A published Catalog entry. |
| **Tool Pack** | An ordered Product selection or contribution group. A pack is convenient composition input and has no independent authority unless it also has an explicit Owner. | An implicit replacement boundary for the whole Catalog. |
| **Tool Owner** | The lifecycle authority permitted to publish, replace, withdraw, and retire one identified slice of the Catalog. | A caller that merely contributes one Tool or requests activation. |
| **Owner Key** | The stable identity that scopes an Owner's replacement authority, including the required Product/session/plugin/contribution dimensions. | A Tool Name alone or a mutable object identity. |
| **Owner Incarnation** | A fencing identity for one live realization of an Owner Key. A stale incarnation cannot commit or withdraw a newer owner's generation. | An Owner Generation or process ID alone. |
| **Owner Generation** | One immutable, ordered publication set for an Owner Key. A newer committed generation atomically replaces only that Owner's prior generation. | A global Catalog replacement or a Model Call revision. |
| **Registration Revision** | A monotonic change identifier for registry or activation observations. It supports comparison and diagnostics but is not itself an Owner Generation. | Proof that a specific Model Call used the revision. |
| **Registration Lease** | A bounded lifecycle handle through which its holder may activate a staged registration, deactivate it, roll it back, or dispose it according to the registration contract. | Durable activation intent or unrestricted ownership of the Catalog. |
| **Admission** | Validation and conflict resolution that decides whether a contribution is eligible to enter an Owner's staged generation. | Activation, policy authorization for execution, or publication commit. |
| **Tool Admission Snapshot** | A bounded revisioned record of candidate admission outcomes and source-level conflicts used for commit revalidation and explanation. | The current Tool Catalog or positive Tool Intent. |
| **Stage** | Prepare admitted registrations and their leases without making them Catalog-visible. | Partial publication or early Model exposure. |
| **Publication** | The atomic commit that makes one Owner Generation Catalog-visible. Publication changes availability only. | Activation, policy approval, Agent rebinding, or Model exposure. |
| **Owner-Slice Replacement** | Atomic replacement of exactly one Owner Key's published generation while preserving every other Owner's slice. | Rebuilding and replacing the global Catalog from a contributor's local view. |
| **Withdrawal** | Remove an Owner Generation or Tool Definition from current Catalog availability while preserving independent session intent. | Explicitly disable the Tool for the user. |
| **Retirement** | Permanently stop a generation or runtime owner from accepting new use and begin its defined disposal lifecycle. | Physical artifact deletion or erasure of session intent. |
| **Disposal** | Release the resources and registrations owned by a lease or retired runtime after lifecycle safety conditions are met. | A policy decision or implicit reset of Tool selection. |
| **Cleanup Debt** | Exact, retryable retirement/disposal work left after a successor generation committed. It is Catalog-invisible and cannot accept new pins. | A reason to roll back a committed successor or forget the predecessor handle. |

## Catalog And Availability Terms

| Term | Canonical meaning | Must not mean |
| --- | --- | --- |
| **Tool Catalog** | The ordered, conflict-resolved view of all currently published Tool Definitions, partitioned by Owner Key and generation. | A user's requested Tool list or the Provider schema for one call. |
| **Catalog Epoch** | The fencing identity of one session-local Catalog realization. A reconstructed Catalog starts a new epoch even if its contents are equivalent. | A durable Plugin generation or Catalog revision counter. |
| **Catalog Entry** | One currently published Tool Definition together with its Tool Name, Owner Key, generation, source provenance, publication state, legacy default-selection eligibility, and registration revision. | A Materialized Agent Tool. |
| **Available Tool** | A Tool whose Catalog Entry is current and Catalog-visible. An on-demand Tool may be Available without being selected by default. | Requested, default-selected, policy-allowed, executable, or exposed to the current Model Call. |
| **Unavailable Tool** | A Tool Name with no currently visible eligible Catalog Entry. Intent for the name may still exist. | Explicitly disabled or permanently invalid. |
| **Catalog Visible** | A publication state in which an entry participates in the current Catalog snapshot and may be selected. | Selected by default, requested, or Policy-allowed. |
| **Legacy Default-Selection Eligibility** | The current registry `enabled` flag, which affects default/on-demand selection while the definition remains Catalog-available and manually selectable. | A target publication-level availability gate or Explicit Enable. |
| **Conflict** | Two or more contributions that cannot simultaneously own the same Tool Name under the Product's declared resolution rules. | Permission to use last-writer-wins silently. |

## Intent Terms

| Term | Canonical meaning | Must not mean |
| --- | --- | --- |
| **Tool Intent State** | The session's revisioned source state for Tool selection: selection mode, explicit overrides, automatic-selection decisions, and the bound default profile. It is independent of current Catalog availability and current Policy. | The list of currently materialized Agent Tools or an already resolved requested-name list. |
| **Resolved Tool Intent** | The immutable ordered positive and negative selection derived from Tool Intent State plus its bound Default Profile. | Catalog availability or a Tool Plan. |
| **Intent Selection Mode** | Either `inherit_defaults`, where defaults and automatic decisions participate, or `explicit_only`, where only explicitly named positive intent participates. | A Tool Policy ceiling. |
| **Intent Engine Mode** | The session-level authority selector `legacy_positive` or `governed_v1`. Exactly one engine accepts mutations or supplies resolved intent at a time. | Intent Selection Mode inside the governed engine. |
| **Default Tool Profile** | A Product-owned immutable snapshot of ordered static defaults and automatic-selection policy, bound to a session by identity, revision, and fingerprint. | User Explicit Intent or a Catalog Owner Generation. |
| **Default Profile Contribution** | One namespace- and contributor-bound ordered fragment submitted to the Product profile assembler. A contributor may replace or withdraw only its own fragment. | Authority to publish the complete Default Tool Profile. |
| **Default Selection** | Product-supplied positive selection for a Tool Name when the session inherits defaults and has no explicit enable or disable decision for it. Static default names are independent of current Catalog availability. | A policy grant, user Explicit Enable, or an Owner's publication default. |
| **Requested Tool Name** | A Tool Name in Resolved Tool Intent because of default, automatic, or Explicit Enable state. A request survives temporary unavailability. | Proof that the Tool is effective in the current call. |
| **Pending Request** | A Requested Tool Name that cannot currently resolve to an Available Tool. The current implementation calls this a `missing_requested_name`. | An error that should erase the request. |
| **Explicit Enable** | A session/user decision that positively selects a Tool Name and overrides Product default selection until reset. | Publication or a permanent policy grant. |
| **Explicit Disable** | A session/user decision that suppresses a Tool Name and overrides both Product defaults and automatic new-tool activation until reset. | Withdrawal from the Catalog. |
| **Suppression** | The retained negative intent created by Explicit Disable. Suppression survives withdrawal and republish of the same logical Tool Name within its defined scope. | Policy denial, registration disablement, or artifact deletion. |
| **Intent Reset** | Remove the explicit enable or disable decision for selected Tool Names so Product defaults apply again. | Enable every Tool or clear the Catalog. |
| **Automatic Selection Decision** | The Product selector's durable, first-seen decision for one logical Tool Name, including the profile revision, stable sequence, and whether it was selected. It is computed independently of suppression. | An Explicit Enable or a decision recomputed on every republish. |
| **Default-Selection Reconciler** | The Product-owned observer that converts a committed Catalog diff and bound Default Profile into separate revisioned Automatic Selection Decisions. | The Catalog publisher or Tool Plan Builder mutating intent as a side effect. |
| **Additive Activation** | Add user/session positive intent for the supplied names through an explicitly granted intent capability while preserving every unmentioned decision. Product default composition is a separate Default Profile operation. | Exact replacement from the caller's partial view or Product default composition. |
| **Exact Intent Replacement** | Replace the complete ordered Tool Intent for a scope. Only a caller holding authoritative complete intent may use this operation. | A normal plugin/tool contribution or additive activation. |
| **Automatic New-Tool Selection** | A Product policy that records one positive or negative default decision when a logical Tool Name is first seen. The decision is computed independently of suppression, which may mask it until reset. | Permission to recompute on republish or resurrect an explicitly disabled Tool. |

## Policy And Effective-Plan Terms

| Term | Canonical meaning | Must not mean |
| --- | --- | --- |
| **Tool Policy** | Product/OEM/session rules that admit or deny a Tool for model exposure or execution under a specific principal, workspace, mode, effect, and policy revision. | Catalog availability or durable Tool Intent. |
| **Allowed Tool Name** | A Tool Name admitted by the applicable selection-policy ceiling. Long-term contracts preserve intent when policy temporarily denies the name. | A Tool guaranteed to be included in a Model Call or approved for every invocation. |
| **Provider Support** | The selected Provider/Model's ability to represent the Tool Name and schema within its current limits. | Product policy approval. |
| **Effective Tool** | A Tool included in one immutable Tool Plan after Catalog, Intent, Policy, Provider, and conflict checks. | Bare `active` state detached from a particular plan or revision. |
| **Tool Plan** | An immutable per-Model-Call record containing the exact ordered Effective Tools, Provider schemas, execution bindings, relevant revisions, and exclusion explanations. | A mutable session registry or a durable intent store. |
| **Plan Revision Vector** | The Catalog, intent, policy, Provider-capability, and binding revisions captured by a Tool Plan. | One global counter that can prove all underlying states are unchanged. |
| **Tool Binding Pin** | An internal read-only, process-local use claim on one exact execution binding. It is owned and released only by its Tool Plan Execution Lease and is never exposed through a Tool Plan entry. | A Registration Lease, independently releasable caller token, or Plugin artifact-retention pin. |
| **Tool Plan Execution Lease** | The exclusive, idempotently releasable owner and resolver of all Tool Binding Pins acquired for one Tool Plan and Model response/tool-call batch. | Catalog ownership, an individual pin surface, or a durable transcript object. |
| **Prepared Model Call** | The Agent-owned immutable bundle of final Model context, call options, Tool Plan, and Tool Plan Execution Lease passed to one Provider invocation. | A session-global mutable Agent context. |
| **Invocation-Start Gate** | The linearization point that validates plan membership, binding identity, Hard Revocation, and invocation Policy before a Tool handler may begin side effects. | A promise that already completed side effects can be rolled back. |
| **Hard Revocation** | A monotonic lifecycle/security fact that blocks new pins and calls that have not crossed the Invocation-Start Gate. For Plugin Tools it is projected from the authoritative Plugin lifecycle. | Ordinary Catalog withdrawal, Explicit Disable, or guaranteed rollback of an already running handler. |
| **Exclusion Reason** | A stable diagnostic reason explaining why a known or requested Tool Name is absent from a Tool Plan, such as `not_published`, `explicitly_disabled`, `policy_denied`, `provider_unsupported`, or `conflict_rejected`. | An exception message intended for end-user presentation. |
| **Rebind** | Replace the mutable Agent tool view and prompt projection from a newly resolved session view or Tool Plan boundary. | Mutation of Catalog ownership or Tool Intent. |
| **Execution Revalidation** | The required check at Tool Call execution that the frozen binding remains valid and invocation-level Policy/Approval requirements are satisfied. | Rebuilding the Tool Plan opportunistically during a call. |

## Authority Terms

| Term | Canonical meaning |
| --- | --- |
| **Complete-Truth Holder** | A component that owns the complete state for one precisely defined replacement scope. Only it may perform exact replacement for that scope. |
| **Local Contributor** | A component that knows only the Tools or intent changes it contributes. It may use only the narrow append/subtract capability explicitly granted to it and may replace only its own bound Owner slice; it may not replace global state. Tool ownership alone grants no intent authority. |
| **Product Adapter** | The owner of Product defaults, Tool policy, prompt wording, Tool discovery choices, and presentation over Harness mechanisms. |
| **Harness Mechanism** | Product-neutral coordination for publication, intent resolution, plan construction, rebinding, execution validation, lifecycle, and diagnostics. It does not silently choose Product policy. |

## Current Compatibility Mapping

The current implementation predates the complete governance model. Until the
target APIs land, interpret existing names as follows:

| Current surface | Current meaning | Target interpretation or limitation |
| --- | --- | --- |
| `ToolActivationSnapshot.available_names` | Registry-visible definitions after current filtering | Available Tool Names; it does not carry Owner/generation provenance yet. |
| `requested_names` | Ordered positive requests retained across temporary absence | Positive Tool Intent only; it cannot represent Explicit Disable independently. |
| `active_names` | Requested names that resolve against current filtered availability | A mutable effective-selection candidate, not a complete per-call Tool Plan. New contracts should avoid bare `active`. |
| `missing_requested_names` | Requested names absent from resolved availability | Pending Requests. |
| `allowed_names` | Static Product allowlist applied before requests are retained | A selection-policy ceiling. Its current eager filtering can erase denied intent and must not define the long-term policy model. |
| registry `enabled` | Definition remains listed and manually selectable but is excluded from enabled/default selection views | Legacy Default-Selection Eligibility, not target Catalog visibility. On-demand Arch/LSP Tools must remain Available. |
| `request(names)` / `apply_active_tools(names)` | Exact replacement of positive requested names and caller order | Isolated `LegacyPositiveIntentState`, not a lossless Exact Intent Replacement in the target three-state model. |
| `activate(names)` / `activate_tool_names(names)` | Ordered union with existing positive requested names | Transitional Additive Activation. Current Product-composition callers must migrate to a default-profile capability rather than becoming user Explicit Enable. |
| `refresh(...)` | Republish the legacy available view without changing positive intent | P1A separated publication from legacy default reconciliation; governed sessions use a Catalog observation and `DefaultSelectionReconciler`. |
| `refresh_and_reconcile_default_selection(...)` | Atomic transitional legacy publication plus lock-free-callback, CAS-retried first-seen reconciliation | Still limited to `LegacyPositiveIntentState`; failed view publication uses an exact consecutive checkpoint or revision-attributed delta compensation, not an unfenced whole-state rewind. The separate `refresh(...)`/`reconcile_default_selection(...)` surfaces retain stale-publication checks only for compatibility. |
| `GovernedToolIntentCoordinator` | Revisioned explicit enable/disable/reset, automatic decisions, and bound profile state | P1A opt-in engine; it does not become authoritative for an existing session until the P1B one-way cutover. |
| `Agent.tools` | Mutable materialized tool list | Projection target, never the Catalog or source of durable intent. |

## Required Language Rules

New designs and APIs must follow these rules:

1. Do not use **active** without qualifying whether it means requested,
   effective in a Tool Plan, executing, Catalog-visible, or default-selected.
2. Do not use **enabled** without qualifying legacy default-selection
   eligibility, Explicit Enable intent, or policy-allowed.
3. Do not use **register** as a synonym for stage, publish, activate, or expose.
4. A local contributor must never derive exact replacement input from a
   currently resolved or filtered view.
5. Withdrawal or temporary Policy denial must not silently erase Tool Intent.
6. Publication changes the Catalog; only intent operations change Tool Intent.
7. Model exposure is described only by a specific Tool Plan and its revision
   vector.
8. Do not call a Registration Lease a Tool Binding Pin; publication authority
   and call-scoped use authority are different capabilities.
