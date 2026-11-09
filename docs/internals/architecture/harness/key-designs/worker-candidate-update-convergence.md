# Worker Candidate Update Coordination

- Authority: bounded design and implementation record under COD-RESP-GOAL-002.
- Design status: accepted for reversible implementation on 2026-11-09.
- Implementation status: implemented; bounded technical acceptance on 2026-11-09.
- Owner: existing Harness Package Product; Coding retains operator policy and output.
- Source baseline: `b155b4b03`; local clean archmethod master
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`.

## Complete Scenario And Existing Reuse

Both operator CLIs repeat the complete candidate-update program: read the
original Lifecycle request, derive and read its exact Management command,
prove a completed retry, validate the original Desired CAS and source/from/to
revision, require revoked Product opt-in, run the existing candidate lifecycle,
then project its result. A27 already shared the actual factory/activate/route/
post-selection/dispose mechanism; this change reuses it rather than rebuilding it.

The full shared update coordinator belongs beside that mechanism in the
existing `harness.package_product.product_worker_candidate` module. It reads
the original PackageLifecycleJournal, Management operation and Desired facts.
It owns no additional journal, state machine, manager, platform dispatcher or
authority. The five-field request Protocol describes the existing parsed
operator request; no input DTO is copied, eagerly read or newly admitted.

Coding retains parsers, product ID, labels, classified errors, JSON fields,
candidate matching and the different pre-entry selection policy. A single
deferred `require_revoked()` guard performs only the original Product opt-in
owner construction/current-read/classified refusal at the original point.
It is an atomic product-policy input, not a lifecycle-stage handler.

## Preserved Contracts

- Linux may enter with no selected installation, read the request and possibly
  the Management operation, then refuse stale. Windows refuses any count other
  than one before entering the shared coordinator.
- Completed retry still proves V2 request type/action/plugin/source, derived
  command identity, terminal succeeded/restart-required, exact installation,
  original expected inventory/from digest, staged source/digest, committed
  selection and current inventory. An operation ID alone is not evidence.
- Retry success still requires revoked opt-in. Otherwise original CAS/selection
  refusal precedes the guard; the guard precedes random ID and runtime creation.
- Keep `worker-candidate-update-`, token length16, request fingerprint and
  command identity, factory/create/activate/route/post-read/dispose ordering and
  the original exception graph. Linux post-selection failure retains its
  classified stale error; Windows retains ValueError.
- Install, enable, disable and remove remain on their original branches with
  their original tombstone behavior, guard ordering, errors and output.
- Code keeps the two original result projections; the shared program returns
  only lifecycle, inventory revision and whether the exact update was replayed.

## Independent Design Review And Acceptance

The separate `/root/responsibility_review`, `/root/runtime_review` and
`/root/compatibility_review` agents reviewed the complete original programs and
the concrete request/guard/real-owner interface. All found this direction
suitable for reversible implementation with the constraints above. They did
not run tests or accept the future code. The implementation agent accepts this
bounded design within the existing Package Product ownership direction.
Pending KD011/A33 diagrams are not adopted.

Hosted canonical scanning and Resume read-task lifetime were also investigated.
Their existing owners have materially different cancellation, admission or
failure contracts; neither is substituted by a convenient summary/scheduler.
They remain separate residual work, not deleted capability or completed scope.

## Evidence And Delivery Conditions

The clean baseline and all 1,953 production-source hashes were frozen outside
Product, along with the three complete original modules. Before implementation,
capture original full CLI behavior using real validated Desired/Management DTOs
and physical journals, controlled runtime/native ports and original output.
Fixed observations include exact record-byte hashes, call traces and error
graphs. Source guards forbid capturing replacement code as an old expectation.

Compare both new full CLI paths with those immutable observations; select
existing staged-update, candidate and CLI consumer tests without bypassing
native/host-runtime selectors. Review actual code from three independent
perspectives, report all receiving/interface/guard costs and close identified
failures before acceptance. Roll back the whole shared update substitution and
its two callers together; persistent schemas and installation identities remain
unchanged. The complete P1–P4/15K Goal stays active.

## Actual Implementation, Cost And Acceptance

The complete update program now resides only in the existing candidate module.
Both Code branches retain their pre-entry selection policy and response shape.
The other actions' ASTs and all original Core definitions' ASTs are unchanged;
the added declarations are the five-property input Protocol and shared program.
The complete frame of 1,953 source files confirms that only these three
production files change.

| Source | Before | After | Difference |
| --- | ---: | ---: | ---: |
| Linux CLI | 1,012 | 936 | −76 |
| Windows CLI | 799 | 732 | −67 |
| Existing candidate module | 255 | 375 | +120 |
| Total | 2,066 | 2,043 | −23 |

All guard/interface/import/format cost is included. Code is 118,668 lines; the
full system is 644,478 lines. This slice removes repeated coordination and saves 23 system lines;
the entire Goal remains larger than its original 634,794-line baseline.

Three separate code reviews by `/root/responsibility_review`,
`/root/runtime_review` and `/root/compatibility_review` found no remaining
blocker in the bounded change. They checked original source hashes, unchanged
other actions, complete retry proof, deferred guard and error differences.
The Core's final parentheses cleanup has an identical whole-module AST;
its final cost of 375 lines was independently rechecked after the intermediate
value of 387.
The implementation agent `/root` accepts this slice after checking those
reports, final sources and actual test terminal results.

Original capture initially failed 96 probe setups before CLI execution because
the probe omitted required manifest admission and used an invalid failure enum.
Only the probe fixtures were corrected; Product sources stayed at the guarded
baseline. The corrected before run passed 97 (96 fixed observations plus one
existing CLI unit) in 10.12s. The replacement passed the same 97 in 17.05s.
The durable explicit local probe preserves the 96 original observations and
source provenance, has no capture path, and passed 96 in 7.84s. These overlapping
runs are not independent additive coverage.

The original CLI, physical Management staged-update and Product epoch/lifecycle
consumer selection passed 83, skipped one native-Windows case and deselected
one host-runtime case (94.29s). A preceding launcher selected a nonexistent
architecture node and exited 4 with no tests run; the corrected command retained
the same safety selectors and the actual existing boundary node. Historical
failure logs are retained rather than relabeled as passing runs.

All three source files pass mypy; changed Python passes Ruff and formatting.
Existing doc validation, dependency freshness, check-plan generation and diff
checks pass. The earlier offline AI result is retained because AI sources and
its inputs have no relevant new change; passing suites are not repeated.
CI catalogs, routes, workflows, assertions and platform selectors are unchanged.

The original Linux full native operator test remains host-selected; the real
Windows update/GC integration requires Windows. Controlled ports are not proof
of those native chains, full interruption coverage, ABI or performance.
