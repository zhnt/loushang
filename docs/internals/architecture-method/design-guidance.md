# Architecture Design Guidance

## Status

- Authority: normative — supporting method for design reasoning
- Design status: accepted
- Implementation status: not-applicable
- Owner: Loushang architecture method

Use with the [canonical method](README.md) to connect system outcomes,
decomposition, implementation evidence and design judgment. These guidelines
apply across scopes; concrete project invariants and choices remain in the
owning scope's principles and decisions.

## Combine Design Directions

| Dimension | Directions | How they inform each other |
| --- | --- | --- |
| Level of detail | Top-down / bottom-up | Decompose system goals, quality requirements and responsibilities; use source facts, prototypes, integration and operational evidence to test feasibility and revise the decomposition. |
| System boundary | Outside-in / inside-out | Derive contracts from actors, scenarios and logical/physical environment; check those promises against domain invariants, internal capabilities, resource limits and collaboration mechanisms. |
| Reasoning sources | Reference experience / first principles | Use comparable systems to discover options and failure modes; separate this system's goals, facts, constraints and assumptions to judge which mechanisms apply. |

First-principles reasoning applies to both external needs and internal design.
Reference experience can inform either side of a boundary. Keep these dimensions
distinct rather than treating reference use as outside-in or first principles
as inside-out.

Iterate across directions. A prototype that exposes an infeasible assumption may
require revisiting a contract, quality trade-off or component boundary. Existing
code establishes facts, not automatically the desired architecture; internal
capabilities do not create a stakeholder need. Confirm domain assumptions with
accountable participants. Changes to accepted contracts follow the
[decision and acceptance rules](architecture-decisions.md).

Converge when important outcomes and quality scenarios are supported by coherent
responsibilities, interfaces and evidence, with remaining uncertainty explicit.
Use [change tailoring](change-tailoring.md) to keep this work proportional.

## Common Design Judgment

These are design preferences and review heuristics, not universal numerical gates.
Use concrete change and failure scenarios to compare their benefits and costs.

| Guideline | Questions to make the judgment observable |
| --- | --- |
| Whole-system outcomes | Does a local optimization preserve end-to-end outcomes and quality constraints? What costs or risks move to collaborators or operators? |
| High cohesion | Do the responsibilities serve a coherent purpose and share reasons to change? Are unrelated policies, state or lifetimes forced into the same owner? Shared terminology alone is insufficient. |
| Low coupling | How many collaborators must change, coordinate or be released together? Are dependencies explicit, with stable contracts and clear fact ownership? Localize external volatility; fewer imports alone do not establish loose coupling. |
| Appropriate granularity | Is the unit large enough to own a meaningful responsibility and small enough to understand, verify and evolve? Would splitting improve ownership, change or failure isolation enough to justify extra interfaces, coordination and operations? Would merging combine unrelated responsibilities? |
| Explicit contracts | Can collaborators implement and verify their obligations, including errors, state and lifetime, without relying on hidden implementation knowledge? Stabilize necessary contracts and validate them as design develops. |
| Justified complexity | Which actual or accepted variation needs an abstraction, extension point or infrastructure component? Can a smaller design satisfy the same obligations at lower total cost? |

For granularity, compare `split / merge / keep` using responsibilities, changes,
consistency and failure boundaries. Peers should use a coherent decomposition
view, but need not have equal code size. Object counts can prompt inspection;
they do not impose a target range or justify extra layers. A component boundary
does not by itself require a service, process or deployment boundary.

Apply these questions through [component identification](component-identification.md#refinement-principles)
and [component refinement](component-design.md#refinement-principles), then
check interactions through [architecture review](architecture-review.md).
Record consequential trade-offs in the relevant ARD. If a project adopts a
concrete invariant or enforceable rule, give it scope, rationale, verification
and exception handling under the [principle rules](README.md#64-glossary-versus-architecture-principles).
Do not turn every heuristic into a mandatory project principle.

## Learn From References

Distinguish method sources, which explain an approach, from comparable systems,
which provide concrete experience. For an important reference, identify:

- the source and relevant version, the problem it solves, and evidence for its
  behavior or claimed benefit;
- the conditions that matter: domain, scale, quality goals, team, technology and
  operating environment, including differences from this system;
- the candidate mechanism, its trade-offs and failure modes, and the reason to
  adopt, adapt or decline it;
- the local scenario, prototype or test that can check whether it works here.

Use reference structures as candidates, not accepted designs. Popularity alone
does not establish suitability, and first-principles reasoning does not replace
empirical validation. Keep material adoption rationale and source links in the
relevant ARD or key design; small observations need no separate reference report.
Project-specific reference inventories belong in the adoption profile or scope
materials, subject to the workspace's research-storage rules.
