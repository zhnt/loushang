# <Scope> Architecture Decisions

> Template: create only the sections and state directories that contain
> records. Link each record at its current path; do not duplicate it here.

## Status

- Scope: `<scope>`
- Parent: `<parent>`
- Authority: descriptive — decision index
- Design status: not-applicable
- Implementation status: not-applicable
- Owner: `<scope decision owner>`

## Placement And Participation

Identify this scope's decision ownership and link the parent index. Cross-scope
decisions belong at the nearest common parent. Link the project's adoption
profile and identify customer confirmation requirements when applicable.

## Proposed — Awaiting Decision

| ID / record link | Decision question | Owner | Review / next decision |
| --- | --- | --- | --- |
| ... | ... | ... | ... |

## Draft — Exploring

| ID / record link | Decision question | Owner | Open question |
| --- | --- | --- | --- |
| ... | ... | ... | ... |

## Accepted — Effective

| ID / record link | Accepted boundary | Owner | Acceptance evidence |
| --- | --- | --- | --- |
| ... | ... | ... | ... |

## Deferred Candidates

Optional: list deferred candidates separately from active decision requests;
retain their actual `draft` or `proposed` directory/status and record the reason,
owner and reconsideration trigger.

## Superseded

| ID / record link | Previous boundary | Accepted replacement |
| --- | --- | --- |
| ... | ... | ... |

Optional legacy/disposition section: add `Rejected` only when whole-record
rejections are retained. Unselected options remain inside their ARD, including
when the accepted choice is to keep Current.

## Maintenance

Keep directory, document status and this index consistent in the same change.
Preserve IDs and filenames during `git mv`; update inbound references and
relative links within moved records. A review or directory move alone does not
accept a decision. A superseding proposal leaves the prior decision effective
until replacement acceptance.
