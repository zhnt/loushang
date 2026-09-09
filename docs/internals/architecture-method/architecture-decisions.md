# Architecture Decision Method

## Status

- Authority: normative — supporting method for architecture decisions
- Design status: accepted
- Implementation status: not-applicable
- Owner: Loushang architecture method

The [Architecture Design And Governance Method](README.md) is authoritative for
scope ownership, truth planes and Target acceptance. This supporting method
defines how to prepare, review, accept and organize Architecture Record
Documents (ARDs). Use the [ARD template](templates/architecture-decision.md).

## Record Content

An ARD answers one consequential decision question. Scale its detail to the
impact and uncertainty; small decisions may combine sections. The following
content must remain identifiable even when the headings are combined.

An option is not an ARD lifecycle state. The chosen option and the reasons for
not choosing the others coexist in one accepted record. Choosing to retain
Current or not introduce a mechanism is an accepted decision too; it need not
create an implementation gap. Do not create rejected records for each losing
option.

| Content | Required answers |
| --- | --- |
| Background, problem and architectural drivers | Why decide now? Which outcomes, quality requirements, constraints and principles influence the choice? Which inputs are facts, assumptions or unresolved questions? |
| Options and comparison | Which feasible options exist? How does each perform against the relevant drivers, and what does each cost? Consider retaining Current or making a smaller change when viable. |
| Decision and rationale | Which option is selected, for what exact scope, and why are its trade-offs preferable? Before acceptance, label this as the recommended decision. |
| Consequences, risks and trade-offs | What benefits, disadvantages, residual risks and compatibility or operational responsibilities follow? Who owns necessary follow-up? |
| Validation evidence and reconsideration conditions | Which evidence supports the choice, what remains uncertain, and which new facts would justify another decision? |
| Status, review and acceptance records | Who owns the decision? Which revision was reviewed, what findings remain, and who accepted or rejected which scope and when? |

Drivers, comparison and rationale are parts of the decision record. Link to
canonical requirements, principles, specifications and validation rather than
duplicating them. Keep detailed implementation sequencing in a delivery plan.

Distinguish non-negotiable constraints from preferences, and state the relative
priority of conflicting drivers. Give quality requirements observable criteria
when they determine the choice. A claim such as "more extensible" should name
the expected variation, the mechanism that accommodates it, and its cost.
Separate evidence-backed conclusions from assumptions that still need testing.

When quality trade-offs drive the choice, reference the prioritized requirement
scenarios and use [quality-attribute analysis](architecture-review.md#quality-attribute-analysis)
to compare mechanisms under consistent conditions. Record material sensitivity
and tradeoff points, supporting evidence and the conditions that would change
the decision; detailed findings may remain in the linked review record.

Do not invent alternatives or numeric scores for documentary symmetry. If only
one feasible option remains, explain which constraints excluded the others.

## Lifecycle And Entry Conditions

| Transition | Required condition |
| --- | --- |
| `draft -> proposed` | The decision question, scope, drivers, viable options, recommendation and important uncertainties are clear enough for review. |
| `proposed -> draft` | Further exploration is required; retain the review findings that explain the return. |
| `proposed -> accepted` | Required review and confirmation are complete, blocking findings are resolved, and the owner records the accepted scope, rationale and evidence. |
| `accepted -> superseded` | A replacement has been accepted; both records identify each other and the boundary being replaced. |

For a small decision, `draft -> accepted` is allowed when review and acceptance
are completed together. A personal-project owner may perform both. The record
must still identify the choice, reasoning, evidence and accepting owner.

Review completion is independent of design status. There is no `reviewed/` or
`decided/` stage: a review can request changes, recommend rejection, or support
acceptance. An accepted decision may be reviewed again after implementation.

`rejected` is an optional whole-record disposition for an explicitly rejected
proposal or an existing historical record, not part of the normal decision
path. When such a record is retained, identify the rejecting owner, rationale
and disposition of the question; use `rejected/` only for those records. Do not
reclassify an accepted decision to `rejected` because one of its options lost.

Deferral is not acceptance or rejection by default. Record why the candidate is
deferred and its reconsideration trigger in the index; retain its actual
`draft` or `proposed` maturity while excluding it from active decision requests.

## Review And Acceptance Records

Use the [Architecture Review Method](architecture-review.md) for view selection,
findings, synthesis and revalidation. A small review may stay inside this ARD;
broader reviews can use the [review template](templates/architecture-review.md).

Record the reviewed revision or commit, reviewer identity/role, conclusions,
and findings. Each material finding identifies the affected claim, evidence,
impact, owner and closure condition. Review depth follows the decision's risk;
use relevant boundary, failure, security, compatibility or operational views
without requiring separate reviewers for every view.

An acceptance record identifies:

- the accepting person or accountable role and the acceptance date;
- the reviewed revision or another unambiguous reference to the accepted text;
- the selected option and exact accepted contract, including exclusions;
- required review/confirmation evidence and disposition of blocking findings;
- any remaining non-blocking risk or follow-up and its responsible owner.

Use a prior reviewed commit/revision or linked review record rather than a
self-referential placeholder for the accepting commit. Evidence supports
acceptance; a date, directory location or completed review does not create it.

The project adoption profile identifies which decisions need customer
confirmation and which role provides it. Internal technical review and customer
confirmation may cover different concerns; record both scopes when applicable.
This does not require customers to approve unrelated internal decisions.
Unresolved blocking findings keep a record `proposed`. Acceptance of the design
does not itself assert implementation completion, customer delivery acceptance
or permission to activate a runtime route.

## Directory And Index Contract

Place decisions within their owning Architecture Scope. A decision crossing
scopes belongs at their nearest common parent; child indexes link to that
record instead of maintaining copies.

```text
<scope>/decisions/
  README.md
  draft/
  proposed/
  accepted/
  superseded/
```

Create state directories only when they contain records; add `rejected/` only
for the exceptional whole-record disposition described above. Use singular
`draft/` and the exact design-status names. General exploration or delivery plans
may remain in a separate architecture `drafts/` area; once material is an
identified ARD, its lifecycle belongs in the owning scope's decision directory.

The [decision index template](templates/decision-index-README.md) groups records
by status and identifies their ID, decision question, owner and next decision
or replacement. Keep deferred candidates visibly separate from active requests.
The document declares its status as well, so an exported copy remains legible.
Directory, index and document disagreements are governance defects to repair;
do not infer acceptance from any one conflicting representation.

An owner-qualified ID is stable. Existing scope-local `ARD-NNN` identifiers may
remain, qualified by their owning scope in cross-scope references. Numbering
spans all states within one scope; never reuse a number in another state or
renumber records during a move. Keep filenames stable after assignment.

## State Migration And Supersession

For a tracked record, use `git mv` between state directories. In the same
change:

1. update its design status and review/acceptance/rejection metadata;
2. update the scope index and any parent/child routing entries;
3. repair incoming links and path references, including test and tooling paths,
   and relative links inside the moved record;
4. update affected Target summaries and deltas only for the accepted contract;
5. run the relevant documentation/link checks and path-sensitive gates.

`git mv` changes paths; it does not repair references or confer acceptance.
Retain reproducible revision references for material shared with customers or
external reviewers. Initial migration of a legacy record preserves its existing
decision and status; adoption policy must not manufacture a new acceptance.

An accepted record preserves its rationale and accepted contract. Editorial,
link and status maintenance may be recorded without changing that decision.
Reconsideration creates a new ID in `draft/` or `proposed/`; the previous record
stays in `accepted/` until replacement acceptance. At that point move it to
`superseded/` and link both directions. If only part of a decision is replaced,
identify the surviving clauses explicitly; retain the old record as accepted
until its remaining contract is superseded as well.

Implemented decisions remain in `accepted/` while effective. Superseded and
rejected records retain their rationale under their state directories and stay
outside the active Target reading path; do not create duplicate historical
copies with a second lifecycle.
