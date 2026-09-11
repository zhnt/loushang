# <Scope> Deployment View

> Template: use only relevant tables/sections; a small scope may combine them.
> Follow the [deployment method](../deployment-views.md). Keep generated Current
> inventories distinct from accepted placement constraints and candidates.

## Status And Scope

- Authority: normative
- Design status: draft
- Implementation status: not-started
- Owner / scope: `<accountable owner and governed scope>`
- Environment / profile: `<intended deployment variant>`
- Physical system context / component model: `<canonical links>`
- Requirements / contracts / decisions: `<canonical links>`
- Current evidence / accepted revision: `<references when available>`

Choose implementation status from evidence. A diagram or named environment does
not establish acceptance or observed deployment.

## Locations, Zones And Nodes

| Location ID | Meaning / parent | Relevant constraints |
| --- | --- | --- |
| ... | ... | ... |

| Zone ID / type | Purpose / owner | Membership / cross-zone rules |
| --- | --- | --- |
| ... | ... | ... |

| Node ID / type | Contains / runs-on | Location / zone membership | Resources and lifecycle owner |
| --- | --- | --- | --- |
| ... | ... | ... | ... |

State overlapping zone types and unknown carrier details. Expand node nesting
only where relevant; groupings alone imply neither isolation nor independence.

## Component And Unit Placement

| Logical components / responsibilities | Unit / optional IO-Control-Compute-Data roles | Instances or replica/placement rule | Carrier / zones | Rationale / contract |
| --- | --- | --- | --- | --- |
| ... | ... | ... | ... | ... |

Explain significant shared resources, co-location/separation, scaling and
environment differences. Link data authority/CRUD rules and lifecycle contracts.
Roles do not require separate units; instances may be dynamic.

## Connections And Scenario Mapping

Link protocols, endpoints, authority and failure semantics to their contracts.
Reuse physical-context IDs and explain one-to-many expansions.

| Scenario / step | Context actor / port / connection | Component / unit | Node / zones and next hop | Contract / evidence |
| --- | --- | --- | --- | --- |
| ... | ... | ... | ... | ... |

Include responses and data changes. Identify internal scenario triggers where
applicable. Retain internal communication mappings without expanding the entire
deployment into the black-box context diagram.

## Walkthrough, Evidence And Acceptance

Link the [deployment-aware review](../deployment-views.md#deployment-aware-walkthrough-and-review)
for the chosen profile/revision. Check relevant reachability, authority, resource,
failure, data and evolution concerns. Record gaps, assumptions, owners and closure
conditions; distinguish design analysis from executed checks and their coverage.

Record acceptance of specific placement constraints/profile and reviewed revision.
Update affected context, mappings, contracts and walkthrough paths when deployment
changes; keep candidates separate from the effective design and observed facts.
