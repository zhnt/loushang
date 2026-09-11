# Architecture Review Method

## Status

- Authority: normative — supporting method for architecture review
- Design status: accepted
- Implementation status: not-applicable
- Owner: Loushang architecture method

This method defines review inputs, views, findings and closure. The
[canonical method](README.md) governs scope ownership and the
[decision method](architecture-decisions.md) governs acceptance. Use
[change tailoring](change-tailoring.md) to select the required depth and the
[review template](templates/architecture-review.md) to record the result.

Architecture review contributes to the broader
[verification and validation framework](verification-and-validation.md), which
also governs implementation checks, regression and system evaluation.

## Review Frame

Identify the question being reviewed, document revision, affected scopes,
accepted constraints, decisions affected, and expected conclusion. Distinguish
design feasibility/consistency from implementation conformance. Provide the
relevant contracts and evidence without requiring the full conversation or
unrelated research history.

For significant reviews, identify scenario sources and check for missing concerns
from affected users, callers, operators and maintainers. Seek their actual tasks
and constraints rather than relying only on designer-selected scenarios. AI role
simulation may suggest questions; label it as such, not as stakeholder input or
confirmation. Record unavailable input and its effect on the review conclusion.

For a small change, this can be a section of the ARD or existing review record.
A broad change may group related decisions, with links to their shared inputs.
Review depth follows risk; views do not imply a fixed number of reviewers or
mandatory parallel agents.

For key designs and high-risk changes, prefer an independent reviewer agent or
subagent with separate context and access to source evidence. Provide the review
frame above; require evidence-backed findings and verify their closure. Small
changes need not spawn a separate reviewer. Review conclusions do not replace
acceptance by the accountable architecture owner.

For domain/data concerns, use the [modeling method](domain-data-modeling.md) to
check meaning, lifecycle, fact ownership, consistency, scale and component/data
responsibilities. Use [deployment-aware review](deployment-views.md#deployment-aware-walkthrough-and-review)
to assess physical paths and placement. Full physical system context guidance
remains pending; use its [interim prompts](README.md#15-guidance-pending-refinement)
and record unanswered architectural questions explicitly.

## Select Relevant Views

| View | Questions | Typical evidence |
| --- | --- | --- |
| Outcomes and complexity | Does the design address the actual need? Are its abstractions and costs justified by the drivers? | Requirements, Current constraints, alternatives and rationale |
| Ownership and contracts | Who owns state, decisions and lifetime? Are collaboration, exclusions and observable behavior precise? | Boundary/specification, component model, interfaces and dependency rules |
| Runtime and failure | What happens under concurrency, cancellation, retry, partial failure, exhaustion and recovery? | State transitions, critical sequences, failure cases and resource bounds |
| Deployment and physical paths | Do actor/connection mappings, unit placement and shared dependencies support the scenario's authority, resource and failure assumptions? | Physical context, unit/node/zone mappings, communication contracts and profile-specific evidence |
| Trust and authority | Can identity, permissions or side effects cross a boundary without the intended admission? | Trust flows, authority rules and adversarial scenarios |
| Evolution and operation | How are compatibility, migration, rollback, diagnosis and retirement handled? | Version/migration contracts, deployment constraints and operational evidence |
| Verification and scope | Does the evidence establish the claimed behavior under the relevant conditions? What remains assumed or untested? | Requirement-to-evidence mapping, experiments, test results and their limits |

Select relevant views and explain material exclusions. A fixed set of headings
does not require an exhaustive report for a low-impact change. Follow important
interactions across component boundaries instead of reviewing each component
only in isolation.

Use [design judgment questions](design-guidance.md#common-design-judgment) to
review cohesion, coupling and granularity against concrete scenarios. Connect
findings to change propagation, ownership or quality effects rather than object
counts or preferred diagram shapes.

## Overall, Focused And Synthesis Review

1. Establish the overall problem, scope, accepted constraints and open decisions.
2. Review one decision or a related group against the relevant views; record
   findings and update the proposed revision.
3. After related decisions change, check the combined design for contradictory
   contracts, ownership, ordering, dependencies and assumptions.

For example, two locally reasonable cleanup contracts can form a wait cycle
when composed. Passing their individual reviews does not establish that their
composition is sound. A small independent decision may complete all three
steps in one short review.

## Scenario Walkthrough

Use a scenario walkthrough to assess a design by tracing a concrete scenario
through its contracts. It can support focused or synthesis review. Select
scenarios in proportion to risk; a small review needs no separate ceremony or
document.

1. **Frame the scenario:** identify the reviewed revision, trigger, initial
   state and expected outcome or invariant.
2. **Trace the path:** follow actors, calls/events, state changes and transfers
   of responsibility step by step across the relevant boundaries.
3. **Explore risk branches:** where relevant, introduce failure, cancellation,
   concurrency, retry or recovery and check ordering and observable outcomes.
4. **Check the basis:** cite the contract supporting each consequential step.
   Record undefined behavior, contradictions and unsupported assumptions as
   findings; identify proposed remedies separately as candidates.
5. **Record and revisit:** retain the scenario, material steps, contract
   references and findings in the review record, with owners and closure
   conditions. After related designs change, repeat affected paths and their
   relevant interactions.

For example, walk through cancellation arriving after an external operation
has succeeded: who decides the final result, who cleans up, and what does the
caller observe? This tests whether state, authority and interaction contracts
compose consistently.

Human and AI reviewers must not invent missing mechanisms to make a walkthrough
succeed. If a step cannot be determined from the design, expose that gap; a
plausible completion is not evidence. A walkthrough provides design-analysis
evidence, not an executed runtime test or design acceptance.

When placement matters, map significant steps from physical-context actor and
connection through the boundary port to component/unit, node/zone and next hop.
Use the [deployment walkthrough](deployment-views.md#deployment-aware-walkthrough-and-review)
for the selected profile/revision, including response/data paths and shared
failure dependencies. After a placement or connection change, revisit affected
scenario paths and mappings together; do not infer reachability or isolation
from a logical interaction alone.

## Quality Attribute Analysis

For consequential quality trade-offs, extend the walkthrough with analysis of
the mechanism supporting each selected requirement scenario. Use
[scenario prioritization](change-tailoring.md#prioritize-quality-scenarios) and
reference canonical scenarios rather than creating a second requirements list.
This analysis draws on [SEI ATAM](https://www.sei.cmu.edu/library/architecture-tradeoff-analysis-method-collection/)
within the existing review and decision lifecycle.

| Concern | Analysis question |
| --- | --- |
| Sensitivity point | Which architectural choice or parameter materially affects a quality response, and under what conditions? |
| Tradeoff point | How does the same choice affect multiple quality attributes, including improvements, costs and conflicts? |
| Risk | Which choice or assumption may prevent a scenario from being satisfied, under what conditions, and on what basis? |

Record the causal chain: **choice/parameter -> mechanism -> affected scenarios
and response measures -> evidence and applicable conditions**. Compare relevant
ARD options against the same scenarios and conditions; identify evidence gaps
instead of assigning unsupported scores. A sensitivity or tradeoff point is an
analysis finding, not automatically a defect or acceptance blocker.

For example, queue capacity can affect burst absorption, waiting time and memory
use. Increasing it may absorb a short burst while increasing waiting and resource
costs; it cannot by itself resolve sustained arrivals above processing capacity.
Analyze the actual workload and backpressure/rejection rules before drawing a
conclusion. This is a generic analysis example, not a prescribed project design.

Use analysis, models, experiments or executed checks appropriate to the claim.
A walkthrough alone does not establish a quantitative latency or capacity bound.
Record unresolved questions, evidence limits and conditions that would change
the conclusion. Capture consequential choices in the ARD, mechanism details in
the key design and follow-up in the existing findings record.

During synthesis, group related risks into themes when they share a cause or
threaten the same goal. Link the supporting findings, affected goals/scopes,
responsible owner and next action. For example, several unclear cleanup paths
may indicate an unresolved resource-ownership model; substantiate that theme
against the contracts rather than merely grouping similar words.

Keep potential risks, unknown assumptions and demonstrated defects distinct.
"No risk identified" is bounded by the reviewed scenario, revision, assumptions
and evidence; it does not establish general safety or implementation completion.
Risk themes use existing review follow-up, not new lifecycle states. A risk
becomes a Current/Target delta only when evidence establishes a difference from
an accepted contract under the normal delta rules.

## Findings And Evidence

Each material finding records:

- the affected claim or contract and its revision/location;
- the problem, evidence or reproducible scenario, and expected impact;
- whether it blocks the requested acceptance, with a reason;
- a responsible owner, correction or next investigation, and closure evidence.

Distinguish a demonstrated defect from an unverified assumption or advisory
preference. A preference needs an applicable driver/principle and cost argument
before it can justify blocking acceptance. Projects may use a local severity
scale; severity and whether a finding blocks this decision must remain clear.

Evidence must match the claim: an import check establishes a dependency fact,
a document revision can resolve a design ambiguity, and an executed scenario
can support behavior within its tested conditions. A mock, one platform or one
delivery slice must not be generalized into broader implementation acceptance.
Record limitations and missing evidence explicitly.

## Closure And Revalidation

The review record identifies the reviewed revision, covered views, findings and
dispositions, remaining risks, and whether the design is ready for the owner's
decision or needs revision/investigation. It is descriptive evidence, not a new
design state or acceptance authority. Blocking findings must be resolved before
acceptance; non-blocking follow-up needs an owner and a closure/review trigger.

Semantic edits require rechecking affected findings, dependent decisions and,
where relevant, the combined design. Reuse unaffected evidence; editorial-only
changes do not force a full repeat. An old review's conclusion does not silently
extend to a materially different revision. Reconsidering an accepted contract
follows the decision replacement rule; it does not reopen the old record as a
draft or erase its acceptance.

After implementation, revisit important assumptions and expected architectural
benefits when evidence becomes available. Record the result against the original
decision; propose a replacement when the reasoning no longer holds. This
revalidation does not rewrite historical rationale or substitute design review
for implementation evidence.
