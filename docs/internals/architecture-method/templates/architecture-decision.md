# <OWNER-ARD-NNN>: <Decision Question Or Title>

> Template: use within the owning scope's `decisions/<design-status>/`.
> Combine sections for small decisions, replace placeholders, and remove
> inapplicable instructions. Link existing requirements and evidence.

## Status

- ID: `<stable owner-qualified ID>`
- Scope: `<owning architecture scope>`
- Parent: `<parent scope>`
- Authority: normative
- Design status: draft
- Implementation status: not-started
- Owner: `<accountable decision owner>`

Choose the actual implementation status independently of design status. A
candidate can describe existing implementation. Review completion is recorded
below and does not change design status by itself.

## Background, Problem And Architectural Drivers

State the decision question and why it matters now. Link the affected boundary,
requirements and principles. Identify outcomes, quality criteria, constraints
and their priorities. Distinguish Current facts from assumptions and open
questions.

When quality goals drive the choice, link canonical requirement scenarios and
their priorities. Keep missing response criteria explicit rather than inventing
thresholds or presenting proposed criteria as accepted requirements.

## Options And Comparison

| Option | Fit against the important drivers | Costs, risks and evidence |
| --- | --- | --- |
| <Option A> | ... | ... |
| <Option B, Current or a smaller change when viable> | ... | ... |

Use only feasible alternatives. Explain eliminated options or why just one
option is feasible; do not invent alternatives or scores to fill the table.

For material quality trade-offs, compare options against the same scenarios
and conditions. Explain which choice or parameter affects which response,
through what mechanism, with what evidence and limits. Link detailed
[sensitivity and tradeoff analysis](../architecture-review.md#quality-attribute-analysis)
when it belongs in a separate review record.

## Decision And Rationale

Before acceptance, state the recommended option explicitly as a recommendation.
After acceptance, identify the selected option, exact scope and exclusions.
Explain why the trade-offs are preferable under the stated drivers.
Keeping Current or deciding against a new mechanism is a valid accepted
outcome. Leave unselected options and their reasoning in Options And Comparison;
do not create rejected records for them.

## Consequences, Risks And Trade-Offs

State benefits, accepted disadvantages, compatibility/operational consequences
and remaining risks. Identify the owners of necessary follow-up; link a delivery
plan for implementation sequencing rather than embedding it here.

## Validation Evidence And Reconsideration Conditions

Link supporting tests, experiments or analysis and state their limits. Identify
unverified assumptions, planned validation and the new facts that would trigger
reconsideration. Review the original reasoning after implementation when the
expected architectural benefit can be checked.

## Review And Acceptance Records

Use the [review template](architecture-review.md) when a broader review needs
its own record; a small review can remain in this section.

Record the reviewed revision/commit, reviewers or roles, findings, evidence and
disposition. Material findings need an owner and closure condition. A concise
self-review is sufficient for a small personal-project decision.

When accepted, record the accepting person/role, date, reviewed revision or
evidence reference, exact accepted scope, closure of blocking findings, and
owners of remaining non-blocking follow-up. Add customer confirmation only when
required by the project's adoption profile, with its scope stated separately.
Remove this instruction after completing the record; do not fabricate review
or acceptance evidence.

When replacing an accepted decision, link the prior decision; update
the prior record with the replacement link upon acceptance. Record the exact
clauses when a replacement is partial. A superseded record has historical
authority. If an exceptional whole-record rejection is retained, record its
rejecting owner and rationale separately from unselected options.
