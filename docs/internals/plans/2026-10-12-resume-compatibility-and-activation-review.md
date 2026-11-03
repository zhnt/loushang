# Resume Compatibility And Activation Review

## Review Frame

- Authority: descriptive — design review evidence.
- Design status: not-applicable.
- Implementation status: not-applicable.
- Subject: [Resume Compatibility And Background Activation Design](2026-10-12-resume-compatibility-and-activation-design.md).
- Date: 2026-10-12.
- Initial reviewed revision: R1, SHA256
  `bdcf57e35051c7e27224c41880ae264a5b9bcf3be9f37109367a0af5d345d8ad`.
- Source baseline: `5c148849976de4d1ef94466852c0abfdffbf1324`.
- Local architecture method: `5b31521605ce12e20134de74fa3877b5717127e4`;
  no upstream verification, per the user's workspace instruction.
- Reviewer model: three independent `gpt-6-astra` instances with separate context.
- Selected views: architecture and performance; security and correctness;
  compatibility, product experience and Hosted integration.
- Review question: is the candidate consistent, appropriately scoped, and ready
  for the governing owners to decide implementation contracts?
- Review status: initial reviews and bounded R2 rechecks complete; R2.1 applies
  the final compatibility wording corrections.
- Acceptance: none; this is design-analysis evidence, not runtime validation.

The user requested compatibility after environment changes, preparation while
history displays, LMUX/AppService support and avoidance of duplicate prepare
abstractions. Reviewer roles simulate engineering perspectives; they are not
stakeholder acceptance or executed runtime evidence.

## Independent Architecture And Performance Review

Reviewer: `/root/astra_resume_architecture_r3`, model `gpt-6-astra`, separate
initial context. R1 conclusion: **revise**, with durable representation and
performance benefits requiring **investigate**. No demonstrated P0 finding.

| ID / severity | Finding and evidence | Impact / owner | Required closure |
| --- | --- | --- | --- |
| A1 / P1 | R1 preparing facade lacks canonical live-binding lifecycle mapping. [AppHost registry](../../../src/loushang/apphost/runtime.py) publishes after factory creation; [Coding adapter](../../../src/loushang/coding/appservice_adapter.py) immediately needs live control. | Could block first view behind activation or create a second registry; AppHost/Coding/Service owners. | One continuity runtime identity, deferred internal execution, original generation/attachment/close chain; two-client and retirement tests. |
| A2 / P1 | New envelope changes physical message identity, not only Profile. [request_evidence.py](../../../src/loushang/harness/session/request_evidence.py) requires AGENT_MESSAGE_KIND; [interaction.py](../../../src/loushang/harness/transcript/interaction.py), [HTML export](../../../src/loushang/harness/transcript/export/html.py) and catalog inspect kind directly. | Missing evidence/fork/export and rollback input visibility; Harness transcript owner. | Canonical message/evidence ID defined, consumer matrix tested; preserve known message kind if possible. |
| A3 / P1 | Double-read equality does not prove which bytes were imported. [Extension loader](../../../src/loushang/harness/extensions/loader.py) executes mutable entry paths and callbacks. | Proof/actual contents can diverge before final check; Package/Extension owners. | Consume pinned snapshot/guarded closure, define dynamic unsupported/trusted scope; ABA/import/symlink tests. |
| A4 / P2 | Scheduler lacks shared-task cancellation and budget contract. | Cache hit alone does not prove fair first view; scheduler/resource owners. | Isolated singleflight keys, reference cancellation, bounded work units and priority; 1/2/8 Session measurements. |
| A5 / P2 | Fast Open does not remove full activation read/decode. [Writer lifecycle](../../../src/loushang/harness/transcript/writer_lifecycle.py) still calls full UoW load. | Duplicate decode/RSS or long first transport; transcript owner. | Detached snapshot adoption proof and cold/hot fallback cost measured separately. |

Walkthroughs: view old history and exit; immediate input during AGENTS change;
two LMUX clients attach one persisted Session; commit followed by publication
failure. A1–A3 leave R1 paths ambiguous. Static planning is a defensible tradeoff,
but dynamic activation remains on the user continuation path.

The narrow follow-up favors RuntimeBinding in existing AGENT_MESSAGE_KIND
record metadata for the user-message slice. [UoW](../../../src/loushang/harness/transcript/unit_of_work.py)
supports metadata and prebuilt record commit; the codec stores metadata with
the same payload/ID/parent. This reduces the envelope consumer changes, provided
the existing message-commit owner merges binding and resource evidence and
delivers the canonical ID to the response flow. Ordinary append creates a new
ID; process-local message-object deduplication is not restart idempotency.

## Independent Security And Consistency Review

Reviewer: `/root/astra_resume_security_r3`, model `gpt-6-astra`, separate
initial context. R1 conclusion: **revise**, continuation representation
requires **investigate**. No demonstrated P0 finding.

| ID / severity | Finding and evidence | Impact / owner | Required closure |
| --- | --- | --- | --- |
| S1 / P1 | Actual code closure and legacy dynamic load admission unspecified; loader reads paths, then executes register/factory. | Post-validation cannot undo top-level effects; Package/Extension trust owners. | Consume proven contents; distinguish code-load admission from contributed-tool authority; bounded refinement or reject. |
| S2 / P1 | Expansion baseline and trusted configuration confirmation unspecified. [Plugin activation approval](../../../src/loushang/harness/approval/plugin_activation.py) already has package/dependency/policy/revocation/authority subject digest. | A configuration value could bypass confirmation or repeatedly prompt; Policy/Approval owners. | Reuse verifiable active subject confirmation, define unknown/incomparable scope and revoke/change behavior. |
| S3 / P1 | Use FAILED is not effect settlement. Existing plugin recovery marks prior-boot STARTING/STARTED as FAILED without proving no side effect. | Automatic retry may duplicate non-idempotent activation; Approval/Extension/Worker owners. | Preserve effect-unknown, independent settlement evidence/debt, crash injection after actual effect. |
| S4 / P1 | Transport request, queue, input operation and execution identities not mapped across restart/controller change. [Remote client](../../../src/loushang/appserver/remote_client.py) uses connection-local numeric IDs. | Commit notification loss can create duplicate input; Hosted protocol and Product durable lookup owners. | Stable logical input/record ID, digest+ancestry binding, authorized reconciliation, mutation fencing and edit cutoff. |
| S5 / P2 | Envelope/Blob atomicity needs explicit backend and GC proof. | Unknown commit must not cause live Blob collection; transcript/artifact owners. | Same record or proven group visibility, restart lookup and old-reader/writer matrix. |
| S6 / P2 | Cache isolation does not itself isolate running singleflight jobs. | Shared errors/results/cancellation can cross principals; scheduler owner. | Same isolation domain for computation and cache; waiter cancellation and private data tests. |
| S7 / P2 | Response retry must use durable model-attempt boundary. [model-call projection](../../../src/loushang/harness/transcript/model_call.py) already detects missing outcomes. | No assistant message is not proof of unsent request; model-call owner. | No attempt allows preparation; existing attempt without reliable outcome remains unknown; explicit retry uses new attempt. |

Walkthroughs include plugin replacement, permission change, effect then crash,
commit then lost acknowledgement, model transport unknown, controller takeover
and competing Writers. They are design analyses, not executed tests.

Narrow follow-up also favors record metadata over new envelope. It retains
known message identity and selected-path evidence, but a single JSONL record
still needs partial-tail/unknown/fsync validation. Binding is a historical fact,
never Grant or proof of a live runtime; typed namespace, bounded JSON and
redacted projections are required. Its atomic scope does not cover automatic
Continue/commands lacking a UserMessage; those paths need separate decisions.

## Independent Compatibility And Product Review

Reviewer: `/root/astra_resume_compatibility_r3`, model `gpt-6-astra`, separate
initial context. R1 conclusion: **revise**, continuation physical format
requires **investigate**. No demonstrated P0 finding.

| ID / severity | Finding and evidence | Impact / owner | Required closure |
| --- | --- | --- | --- |
| C1 / P1 | R1 describes Started/Queued as existing, while [AppService](../../../src/loushang/appservice/runtime.py) returns Ack and [execution registry](../../../src/loushang/appservice/execution_registry.py) implements ACCEPTED with submission ledger. | Parallel queues or misleading admission; AppService/AppServer/Coding adapter. | Source-current vs candidate mapping, existing execution owner, capability negotiation/old-client behavior. |
| C2 / P1 | Client ID/text preservation is insufficient after queue loss, commit acknowledgement loss, edit or takeover. | Duplicate response/input or editable committed text; execution/continuity/client owners. | Reconcile durable input before re-admission; unknown differs from verified absent; fixed digest and new ID after acknowledged cancel. |
| C3 / P1 | Product-known legacy and Hosted canonical identity are different. [hosted_catalog.py](../../../src/loushang/coding/hosted_catalog.py) excludes missing Hosted metadata. | Embedded resumes but LMUX cannot discover it; Coding identity/AppHost owners. | Identity matrix and explicit migration/same-ID support scope, no default Product guess. |
| C4 / P1 | Unknown envelope retention does not preserve old-reader message semantics or safe old-writer behavior. | Silent input loss or unsafe rollback write; transcript/product release owners. | Preserve message kind where feasible; real N/N+1 read/export/write support matrix. |
| C5 / P1 | Development steps could be read as independent release slices; gates are removed before binding/admission/recovery is complete. | Premature writable current rollout; delivery owner. | Separate merge/development order from vertical release gate; readonly can release alone, writable requires full safety dependencies. |
| C6 / P2 | View target, actual execution and pending ownership unclear during A→B→A and publication failure. Existing [Mux shell](../../../src/loushang/harnesstui/mux/shell.py) fences presentation and isolates editor state. | Text/action delivered to wrong Session; client/Coding owners. | Explicit target semantics, committed irreversible boundary, text/accessible state and no focus stealing. |

Walkthroughs compare package/resource upgrades, legacy identity combinations,
Session switching, queue loss/commit loss/model unknown, rollback and active
LMUX attach. Current/exact defaults, three-layer coverage and inert extensions
are already clear in R1 and are not reported again as missing.

## Synthesis And R2 Disposition

The three reviews converge on four themes: actual content proof; Hosted
identity/admission/request ownership; message representation compatibility;
and separation of development order from safe release gates. They support
background pure planning, one Plan with existing owners, current authority and
same-ID continuation within proven identity scope.

R2 changes made by the primary agent:

- Maps AppHost canonical live binding, Service projection and internal Coding
  execution to one continuity owner and existing attachment/close lifetime.
- Preserves AGENT_MESSAGE_KIND and proposes a bounded Binding metadata key,
  co-committed with existing Resource evidence by the existing message owner.
  New envelope is no longer preferred; commands without UserMessage are not
  covered by the first writable slice.
- Distinguishes double-read detection from actual pinned content consumption;
  treats unprovable dynamic closures as unavailable unless existing trust owner
  explicitly admits a defined trusted-code scope.
- Reuses verifiable approval subjects for scope comparison and repeat-prompt
  avoidance; configuration values alone cannot prove acknowledgement.
- Distinguishes use FAILED from effect settlement and references existing
  durable model-attempt projection for unknown outcomes.
- Separates transport/execution/service identities from stable logical input
  and canonical record IDs; defines reconciliation, frozen payload, controller
  fencing and old-client admission behavior.
- Adds Hosted legacy identity scope, singleflight reference/cancellation,
  view/execution target semantics and independent release slices.

These edits address design ambiguity. They do not establish runtime correctness,
performance, ABI compatibility or acceptance. Reviewers rechecked only the
affected R2 semantics; unchanged R1 analysis remains applicable.

## Bounded Followup Review And Final Disposition

All three reviewers verified R2 SHA256
`05b8bf141773a6fafbdac8de1bb52af75e8784362056b6a3fd87da3eb79b635a`.
The independent rechecks did not run tests or approve scope-owner acceptance.

| Perspective | R2 outcome | Findings disposition |
| --- | --- | --- |
| Architecture/performance | Ready for decision on reviewed semantics; feasibility and performance investigate | A1–A3 design ambiguities closed; A4 scheduler definition closed at design level; A5 remains measurement/snapshot-reuse investigation. No new blocking contradiction. |
| Security/consistency | Ready for decision on reviewed semantics; implementation proof pending | S1–S4 design ambiguities closed; S5 message commit/Blob/restart proof still investigate; S6 isolation definition closed; S7 existing durable attempt boundary clarified. No new design blocker. |
| Compatibility/product | Ready for decision after exact old-Ack wording; format/read/lookup investigate | C2/C3/C5/C6 design ambiguities closed; C4 envelope replaced by known message metadata path with explicit test gate; C1 requires preserving original completion/error timing. |

R2.1 SHA256:
`3f89ff3256048892afd751bd7fff73c115b5bd3562492b6a5ba7378705a52aea`.
It differs from the reviewed R2 only in revision metadata and two reviewer-requested
clarifications: old Ack retains original operation completion/error timing,
and cross-Session forked Binding remains origin evidence rather than target
activation or duplicate-input authority. Those differences do not change the
message schema candidate or introduce a new persistence mechanism.

The compatibility reviewer independently verified the R2.1 digest and confirmed
both exact corrections: C1's remaining design ambiguity is closed and the fork
origin refinement is complete. Its conclusion is ready for decision. Architecture
and security conclusions apply to their reviewed R2 semantics; this record does
not claim all reviewers independently reran the entire R2.1 design.

Design conclusion: **ready for the governing owners' decision within the stated
scope**, with named investigation and implementation gates retained. The first
writable slice is user-message-triggered and identity-qualified; commands without
UserMessage, implicit Embedded-to-Hosted adoption, unproven plugin code closures
and safe downgrade writing are not covered by that slice.

The single-message metadata proposal simplifies persistence but does not remove
stable-ID reconciliation, original message-owner integration, Blob safety or
actual-content proof obligations. These are release gates, not reasons to add
another general prepare family or bypass existing ownership.

## Remaining Verification And Decision Gates

| Gate | Owning scope | Required evidence |
| --- | --- | --- |
| Message Binding schema/commit and stable IDs | Coding/Harness transcript | Existing evidence merge, canonical ID no double append, restart reconciliation, partial tail, Blob/GC, ancestry/compaction/export |
| Hosted continuity factory and admission | AppHost/AppService/AppServer/Coding | One owner/two clients, generation retirement, negotiated old/new client behavior, restart/takeover/cancel |
| Actual code/data proof and effects | Package/Extension/Approval/Worker | Snapshot/guard consumption, dependency replacement/ABA, effect vs use terminal, settlement/debt |
| Performance benefits | Harness transcript/resources and Coding | First frame/Plan/input durable/transport separately; cold/hot decode, memory, singleflight and cancellation under multiple Sessions |
| Rollback | Product release owner | Tested reader/export range; explicit minimum writer version and unsupported downgrade write scope |

Reviewers did not run runtime or network tests. Document edits can resolve
definitions; the above mechanisms require owner contracts and implementation
evidence before release. No owner acceptance is recorded by this review.
