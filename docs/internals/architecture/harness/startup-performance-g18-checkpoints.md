# G18 Native Collection Checkpoints

Status: implementation passed three-view code re-review; opt-in Linux native
fixed-slot collection. Functional delivery validation is recorded below.
Authority: [G18 plan](startup-performance-plan.md). This protocol preserves execution
progress; it does not relax performance gates or authorize new Product behavior.

## Use

Keep the original complete native command, including its pinned source/wheel,
A/A2/B/observer installations, cache mode, requirements, case order, counts,
private environment and exclusive output path. Add these options:

| Operation | Options |
| --- | --- |
| Start a checkpoint-enabled run | `--checkpoint` |
| Stop after cumulative observation N | `--checkpoint --pause-after N` |
| Continue a safely paused run | `--resume` with the same original arguments |
| Stop the next segment at a later cumulative count | `--resume --pause-after M`, where M exceeds the completed count |

Counts include declared warmups, but not setup, identity probes or seed
preparation. For the full native plan, 14 observations finish the first block's
warmup window; total completion is 308 observations, including 28 warmups.
To resume without another planned pause, remove the prior `--pause-after` option.
Repeated completed observations are never skipped by count alone: the entire
ordered prefix is validated. The last observation always proceeds through the
original final identity/helper checks and comparator, not an early pause.

To ask a running collector to pause after its current complete observation, use
the same isolated Python runner to execute this separate command:

```sh
uv run python scripts/dev/measure_g18_native.py --request-pause /absolute/path/to/output
```

`pause requested` means only that a request was published. Wait for the original
collector to exit and `report.json` to say `status: paused`. Do not send SIGINT
or kill the process to request a resumable pause. Requests are bound to the run
and segment, retained separately, and do not interrupt the process owner.

Default collection remains schema v2 and non-resumable. Checkpoint-enabled
collection uses schema v3 plus `checkpoint.json` and a stable `checkpoint.lock`.
Only native `--fixed-slot` warm/absent is supported; inert and correctness-only
modes retain their existing behavior.

## Safety And Evidence

The lock spans the coordinator lifetime and is not inherited by child processes.
Only a durable `paused` generation can resume. Before any reopened state,
interpreter probe, slot switch, reset or cache preparation, that generation is
durably consumed as `inflight`. A failed or interrupted run cannot roll back to
the old generation. Unknown schemas, v2 reports, partial writes, failed/complete
states, altered plans, wrong hosts/boots or competing writers are rejected.

A pause is published only after the existing process owner physically settles,
all postchecks pass, and the slot/recovery guards return idle. Report and checkpoint
publication use file fsync, atomic replacement and directory fsync. Restoration
validates the exact completed prefix, raw/cache receipts and source/helper plan,
then the original slot layout and directory identities, both installed/external
cache trees, reference and observer installation trees, recovery seed archives
and current post-observation subjects. Drift is rejected before probes or cleanup;
the collector never recreates an old slot, regenerates seeds, resets counts or
adds warmups to repair a checkpoint. Missing durable state fails closed.

Only controlled pauses are resumable in this version. SIGINT, power loss or a
crash inside an observation/setup/checkpoint write retain evidence but do not
automatically recover unknown owner or filesystem state. These are not hidden
retries. Preserve the output, slot and scratch directories until the campaign
has been audited; do not move them to another path or machine.

## Statistical Qualification

Every segment records start/end times, its observation range and startup load.
Existing observations are retained exactly as serialized, including timing values;
no cross-campaign import, outlier removal or selection of passing cases is allowed.
The original comparator still requires the complete original 41 metrics.

Every resumed campaign sets
`segmented_acceptance.eligible_for_automatic_acceptance = false`. A comparator
`pass` is therefore descriptive until the segmented measurement schedule and
environment have received their own calibration/audit. Pausing between A/B sides
or changing seed age can alter measurement conditions even when all file identities
match. Freeze the intended segmentation strategy for corresponding A/A and A/B
before claiming performance acceptance. This feature does not reclassify the
accepted uninterrupted inert baseline or historical inconclusive reports.

## Legacy Interrupted Attempt

User-requested checkpoint development stopped native warm session 61168 with
SIGINT through the original owner path; it exited 130. The v2 report
`.artifacts/g18-linux-delivery/native-aa-warm-exclusive-02/report.json` retains
25 attempts: 24 complete/valid (14 warmups, 10 formal) and one interrupted attempt.
Its SHA-256 is
`20bd527396722f84eb2cc61045054a922a02b3c6cc96b13699083b5e37146f71`.
The slot is marked failed. This is neither a Product regression nor a performance
result; it is intentionally not migrated into the new checkpoint protocol.

## Delivery Validation

Three independent read-only re-reviews (architecture/lifecycle, evidence contract,
and compatibility/testing) found no remaining P1/P2. Review fixes cover cumulative
pause targets, raw receipt and seed-manifest sealing, segment-bound pause requests,
single durable final publication, and preservation of the original failure when
checkpoint failure publication also fails.

The focused checkpoint suite passes 47 tests, including warm/absent coordinator
round trips, multiple pause boundaries, drift rejection, lock contention, and a
complete 308-observation CLI fixture using the original 41-metric comparator.
Those fixtures use a controlled process owner, not measured Product performance.
The final full G18 collector regression passes 466 tests with 4 platform skips;
its JUnit receipt is
`.artifacts/g18-linux-delivery/checkpoint-regression.xml` (terminal exit 0).
CI-selection unit tests pass all 46 cases; the AI gate, pinned actionlint v1.7.12
and documentation checks also pass. Real installed smoke evidence is kept
separate from formal A/A or A/B performance acceptance.
The broad AppService gate process finished, but its terminal output was not
retained; this delivery does not claim that full gate passed. The scoped final
collector regression above is the independently retained verification result.

The first installed smoke, `native-checkpoint-smoke-warm-01`, exited 1 during
recovery seed preparation: the original TUI readiness predicate timed out before
any observation/checkpoint boundary. The report and checkpoint remain failed,
the slot remains poisoned, and the observed child PID was gone after controller
exit. Report SHA-256:
`c61df3f30c2f384cc38b56820bde50558036a896051f607166cf9b8d49a49755`.
This attempt overlapped local gate/compilation work; it establishes neither a
checkpoint round-trip success nor the cause of the TUI timeout. It is retained,
not resumed or overwritten.

After the gate and compilation workloads ended, installed warm smoke
`native-checkpoint-smoke-warm-02` completed its two-case plan (`foreground`,
`recovery-cwd`; one block, one pair): pause after 3 observations, then resume to
8 complete/valid observations. Both invocations exited 0. The original three
serialized observations, seed-setup records and slot directory identities are
unchanged; segment ranges are `[0, 3)` and `[3, 8)`. The same private environment,
reference/observer installs, slot and scratch were retained across invocations.

- Paused report SHA-256:
  `662b8317b2f6499b75ae99253a8e70245313b7d0b019a884dd9a145c5f45344c`.
- Final report SHA-256:
  `de9de68a1eacc2fe3d4135ea42bd53d4db27ebf8b430934760767578a5d09cf4`.
- Evidence:
  `.artifacts/g18-linux-delivery/native-checkpoint-smoke-warm-02/report.json`.

This is a functional warm-mode round trip, not a full native calibration or A/B
comparison. The comparator remains `not-evaluated` for the shortened plan and
automatic segmented acceptance remains false. Absent-mode round trips are
covered by the controlled coordinator/CLI tests, not this installed smoke.
