# <Scope> Domain And Data Model

> Template: use the relevant sections within a scope document or split substantial
> content into `domain-model.md` / `data-model.md`. Remove unused sections; a
> short concept graph and rule table may suffice. Follow the
> [modeling method](../domain-data-modeling.md).

## Status And Scope

- Authority: normative
- Design status: draft
- Implementation status: not-started
- Owner / scope: `<accountable model owner and governed scope>`
- Requirements / use cases / system context: `<canonical links>`
- Glossary / inherited contracts: `<canonical links>`
- Governing decisions / acceptance evidence: `<references when available>`

Select implementation status from evidence. Label candidates and unknowns;
source code or a database inventory does not by itself accept a model.

## Domain Meaning

Explain whose problem the concepts address and which rules remain independent
of implementation technology. Separate domain facts and confirmed constraints
from assumptions. Link canonical term definitions.

| Concept | Identity / lifecycle | Relationships / cardinality | Important behavior and invariants | Requirement / contract source |
| --- | --- | --- | --- | --- |
| ... | ... | ... | ... | ... |

Use a graph or state diagram when it clarifies a consequential relationship.
Do not invent cardinalities or turn every noun into an entity or component.

## Data Lifecycle And Authority

| Data / fact | Authoritative source and owner | Creation / updates | Derivation / synchronization / use | Persistence / maintenance / retention / deletion |
| --- | --- | --- | --- | --- |
| ... | ... | ... | ... | ... |

State scale, growth, access rates, hot spots, bursts and workload assumptions
where significant. Identify consistency boundaries, allowed staleness, conflict
handling, versions and reconstruction rules. Distinguish authoritative facts,
copies, snapshots and derived data, including external ownership.

## Logical Model

Define necessary structures, names, identifiers, types, units, time and missing
value meanings, relationships and integrity rules. State expected variations
and compatibility rules. Map domain meaning to interface, runtime and storage
representations when different; identify conversions or information loss.

## Physical Model (When Relevant)

Explain physical representation/access choices against workload and quality
criteria, with evidence and limits. Include performance, resource, durability,
recovery and maintenance consequences. Link schemas/migrations and key designs;
explain synchronization, invalidation and rebuilding for additional copies.

## Component / Data Responsibilities (When Useful)

| Component | `<Data A>` | `<Data B>` |
| --- | --- | --- |
| `<component>` | `<C/R/U/D or none; qualify delegation>` | ... |

C = Create, R = Read, U = Update, D = Delete. Declare each data object's fact
owner above. Distinguish logical authority from physical persistence performed
on its behalf. Link command contracts; an Update cell permits no arbitrary
state change.

| Additional lifecycle operation | Source -> target | Responsible component | Trigger / consistency or freshness rule |
| --- | --- | --- | --- |
| `<derive / replicate / synchronize / archive / repair>` | ... | ... | ... |

## Validation And Open Questions

Trace selected creation, modification, use and retirement scenarios through
the model and component responsibilities. Add risk-relevant concurrent, failure
or evolution cases. Link checks and actual results; identify missing evidence,
owners and closure/reconsideration conditions. Keep planned checks distinct.

## Acceptance And Evolution

Record or link the accepting owner, date, reviewed revision and exact scope.
Before material changes, assess affected rules, consumers, derived data,
compatibility/migrations and checks. Keep the effective model distinct from
candidate revisions and preserve historical decisions and evidence.
