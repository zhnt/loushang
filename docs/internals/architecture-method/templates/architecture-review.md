# <Scope Or Decision> Architecture Review

> Template: embed in an ARD for a small review; use a separate record when the
> review spans several decisions. Remove inapplicable instructions and sections.

## Status And Review Frame

- Authority: descriptive — review evidence
- Design status: not-applicable
- Implementation status: not-applicable
- Owner: `<review record owner>`
- Subject / decision IDs: `<canonical links>`
- Reviewed revision: `<commit, version or immutable evidence reference>`
- Review question: `<design question or implementation claim being assessed>`
- Reviewers / roles and date: `<actual participants and review date>`

State the affected scopes, governing contracts and relevant evidence. Identify
the selected review views and explain material exclusions.

Identify scenario sources and missing affected-role input. Distinguish actual
stakeholder contributions from designer assumptions and AI-simulated concerns.

For quality-driven reviews, reference requirement scenario IDs and record
business importance, technical difficulty and selection rationale. Identify
who confirmed priorities; AI-proposed priorities remain recommendations.

## Scenario Walkthrough (When Relevant)

Follow the [walkthrough method](../architecture-review.md#scenario-walkthrough).
Record the trigger, initial state, expected outcome, material steps and contract
references, including selected risk branches. Link gaps and contradictions to
the findings below; keep proposed remedies distinct from the reviewed design.
Label this as design analysis, not an executed test. Remove this section when
unused.

When deployment matters, record the environment/profile and link significant
steps to physical-context ports/connections, components/units and nodes/zones.
Follow the [deployment review](../deployment-views.md#deployment-aware-walkthrough-and-review)
for reachability, authority, resource, failure, data and evolution concerns.
Keep profile-specific evidence limits explicit and recheck mappings after changes.

## Quality Attribute Analysis (When Relevant)

Follow the [analysis method](../architecture-review.md#quality-attribute-analysis).
Record material sensitivity/tradeoff points through the chain: choice or
parameter -> mechanism -> affected scenarios and response measures -> evidence
and conditions. Keep unknowns distinct from findings supported by evidence;
link consequential choices to their ARDs. Remove this section when unused.

## Findings And Disposition

| Finding / affected claim | Evidence and impact | Blocks acceptance? Why? | Owner / next action | Closure evidence or remaining question |
| --- | --- | --- | --- | --- |
| ... | ... | ... | ... | ... |

Distinguish demonstrated defects, assumptions needing investigation and advisory
preferences. A correction to prose closes a design ambiguity, not an unexecuted
behavioral test. Do not fabricate findings or acceptance evidence to fill rows.

## Synthesis And Remaining Risk

Check whether related decisions still compose consistently after edits. Record
coverage limits, assumptions, unresolved findings and owned follow-up. This can
be one sentence when the review covers a small independent decision.

Where related risks form a theme, identify its shared cause or threatened goal,
supporting findings, affected scopes, owner and next action. A bounded finding
of no identified risk is not general assurance or an implementation claim.

## Review Conclusion

State whether the reviewed revision is ready for the owner's decision or needs
revision/investigation, and why. Link the ARD's separate acceptance record when
one exists. Semantic changes require rechecking affected evidence and decision
relationships; unchanged material can retain its prior evidence.
