# Independent Review Brief: Capability Composition Lifecycle Authority

Review
`docs/internals/architecture/harness/composition-lifecycle-authority-plan.md`
as an independent architecture reviewer. Do not inherit prior conversation
conclusions and do not modify files.

Verify claims against the current `src/` and `tests/` tree. Also compare the
decisions with the accepted Harness boundary documents and, where useful, the
read-only `deepseek-harness/` reference after reading its root `AGENTS.md` and
`docs/architecture.md`. Treat reference patterns as evidence, not requirements
to copy.

Answer these questions:

1. Does the plan eliminate duplicate construction/publication authority, or
   merely add a facade above existing binders?
2. Is “one authority per owned live object” precise enough to preserve Profile,
   Mount, Registration, Extension/Resource, and Model Input fact clocks?
3. Is the proposed synchronous-candidate to asynchronous-Mount ownership
   transfer sound, exactly-once, cancellation-safe, and compatible with every
   supported Product entrypoint?
4. Is `harness.resources` the smallest useful first vertical slice, is Session
   graph ownership a genuine prerequisite, and is workspace production mounting
   correctly deferred as an independent follow-up?
5. Does the plan preserve the distinction between immutable declarations and
   live registrations?
6. Are Extension content refresh and graph-owned Provider replacement separated
   honestly, without claiming unsupported cross-authority atomicity?
7. Does the PR order permit independent review, rollback, and behavior
   preservation?
8. Are the acceptance gates executable and sufficient to detect double
   construction, leaked ownership, stale leases, false Mount churn, and
   incomplete persistent explanation?
9. Which proposed abstractions duplicate existing
   `RuntimeCapabilityGraphPlan`, `RuntimeCapabilityGraphBinder`,
   `RegistrationScope`, `CapabilityFacetSet`, or `EffectiveRuntimeView`?
10. Which decisions are unnecessarily broad and should be deleted or deferred?

Return:

- an overall verdict: Approve, Approve with required revisions, or Request
  changes;
- findings ordered P0 through P3, each with source/document evidence and a
  minimal correction;
- a retain / rewrite / defer list;
- a revised dependency-ordered PR sequence if needed;
- explicit acceptance gates for the first production PR; and
- a workload estimate for CLA0-CLA4 and the first substantive PR.

Review posture: preserve Product neutrality, typed least-authority Consumers,
reversible ownership, and the existing multi-clock fact model. Do not propose a
global service locator, a second graph/projector, a generic plugin microkernel,
or unrelated feature expansion.
