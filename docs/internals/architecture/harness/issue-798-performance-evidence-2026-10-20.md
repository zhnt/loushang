# Issue 798: startup and Working evidence, 2026-10-20

## Status and scope

- Authority: informative — local measurement and regression evidence
- Implementation status: partial
- Tracking: [#798](https://github.com/zhnt/loushang/issues/798)
- Baseline: `2de1359c31d540913df11a7f4705f5a1b54624ba`, before the issue's changes
- Candidate: `ea64899df6b1ad94c0313a9eb8e01a2f4a2166e5`, merged PRs
  [#799](https://github.com/zhnt/loushang/pull/799) and
  [#800](https://github.com/zhnt/loushang/pull/800)
- Later correction: `3f0be917` retains terminal input completed during render
  waiter cleanup. The performance wheels precede this input-only correction.

The requested 50% total startup improvement is **not established**. Keep that
objective open. Session construction and tool-output processing improvements
must not be substituted for whole-CLI readiness.

## Installed CLI startup

Both wheels were built from clean Git archives and installed into private
Python 3.14.7 environments with the same 34 dependency versions. The local host
was macOS x86_64. Each sample had a new private home and workspace. One
unrecorded startup per build primed bytecode before the eleven alternating A/B
rounds. No model request or LSP use occurred. OS caches and host load were not
controlled.

| Measurement | Baseline median | Candidate median |
| --- | ---: | ---: |
| Welcome visible | 1.6090 s | 0.8658 s |
| Idle visible | 7.0293 s | 4.3112 s |
| Child CPU through exit | 7.2863 s | 4.7812 s |

The nominal idle difference is 38.67%. Within-build idle spread ratios were
1.515 and 1.368, exceeding the diagnostic's 1.2 threshold. Its result explicitly
warns against attributing the difference. Neither these samples nor an earlier
incremental A/B prove the requested 50% target. Earlier incremental comparisons
also used a baseline that already deferred LSP; their percentages do not
describe the complete issue's changes.

Reproduction uses `scripts/benchmarks/benchmark_cli_ready.py` with installed
`--baseline` and `--candidate` console paths and `--rounds 11`. See the
[complete CLI samples](issue-798-measurement-samples-2026-10-20.md#installed-cli).

## First LSP result: expose the deferred cost

Five alternating installed-SDK samples used a private ephemeral Session, the
default `on_demand` mode, and the repository's real stdio fake LSP server.
Imports were timed separately. Session readiness includes construction and
`prepare_model_call_runtime()`. Demand includes enabling `document_outline`
and obtaining its first result. No language server started before demand.

| Measurement, excluding module imports | Baseline median | Candidate median |
| --- | ---: | ---: |
| Session ready | 8.1839 s | 0.8932 s |
| Demand through first result | 0.1354 s | 4.0292 s |
| Session construction through first result | 8.3181 s | 4.8251 s |
| Second result | 0.0080 s | 0.0088 s |

These are exploratory cost-location measurements, not eleven-sample startup
acceptance. Provider assembly moved into first activation; it was not removed.
The first and second outline result details matched in every sample. Each
server recorded initialization, one document open, two outline requests, and
shutdown/exit. The host used its retained macOS SDK route; these measurements
do not validate the Linux fenced Product route. See the
[first-use samples](issue-798-measurement-samples-2026-10-20.md#first-lsp-result).

## Output pressure and exact metadata parity

Three alternating runs per installed build appended 2,000 interleaved stdout
and stderr chunks of 1,024 bytes each, totaling 2,048,000 bytes. Only
`_BashPartialOutput.append()` was timed. Canonical serialization and hashing
occurred outside each append interval.

| Measurement | Baseline median | Candidate median |
| --- | ---: | ---: |
| Sum of append intervals | 9.483295 s | 2.536643 s |

The measured reduction is about 73%. The fingerprint of displayed text and
every metadata field matched across all 2,000 updates in all six runs:
`a93eac6a9b863853b3c261cfa469a395868704654453689a060e4108b5df5312`.
Separate untimed verification serialized the complete `AgentToolResult`
dataclass, including all content fields, for every update. Both builds produced
`1cce09ba2c395be448f93e123d26c85accfdc5e8bbfd03f2e5af3f5f7e9d00da`.
That verification is an equality check, not another timing comparison.

The local diagnostic is retained at
`.artifacts/benchmark_bash_partial_output.py`; it can be run with each installed
build's Python from a neutral directory with `PYTHONPATH` unset. The workload is
`ExecOutputChunk(stream="stdout" if index % 2 else "stderr",
text="x" * 1023 + "\n")` for indices 0 through 1999. The versioned
`test_bash_partial_output_preserves_truncation_across_chunk_boundaries` adds
CRLF, Unicode, very long lines, and mixed chunk boundaries. See the
[pressure samples](issue-798-measurement-samples-2026-10-20.md#output-pressure).

## Additional input regression and validation

The terminal read loop previously inspected the completed-task snapshot from
`asyncio.wait()` after awaiting render-waiter cleanup. Input could finish during
that await and then be discarded when the loop returned a turn-completion or
terminal-deadline wakeup. `3f0be917` inspects the input task's current state
before returning either wakeup.

Six deterministic cases coordinate that ordering with Events, without timing
sleeps or an `asyncio.wait` mock. They cover Escape, text, and EOF at both
wakeups. All six failed before the correction and passed afterward; each also
checks that no read/render task remains. Local validation included:

- Terminal input: 31 passed, including the six new cases.
- POSIX/Windows input backend and handoff regressions: 45 passed.
- Screen loop, startup, and playback integration: 66 passed, including silent,
  continuous, and burst command output with input and Working timer observation.
- Coding UI: 602 passed, 68 deselected; Ruff and mypy passed.
- TUI units: 1312 passed, 168 deselected.
- Render contracts: 240 passed, 7602 deselected.
- Changed-scope HarnessTUI: 1051 passed, 14 deselected, two existing macOS PTY
  restore failures. Both failures reproduce before this correction; no Product
  workaround for the host terminal flag difference was added.

A later expanded `make check-changed` run also passed AI checks and coverage
thresholds, plus 153 Agent tests. Its broad Coding selection produced 3350
passes, 283 skips, 55 deselections, 128 failures, and 39 fixture errors on this
macOS host. Replaying the 167 failing/error node IDs in an isolated clean
`ea64899d` worktree reproduced 127 failures and all 39 fixture errors. Most
involved Linux-only managed or fenced Product operations. The sole differing
node was grep's existing 0.5-second process-stop timing assertion. Running that
node separately, without another test process, passed on both revisions.
The broad local gate is therefore **not green**; this record does not turn
unsupported-host failures or a timing rerun into full-suite acceptance.

## Visible Escape acknowledgement during deferred activation

An additional real Coding action-host regression holds LSP composition in a
controlled worker thread. It observes editable draft text and Working timer
frames at one and two seconds before releasing composition. The successful
activation path passed; the Escape variant initially failed because its
`Stopping…` acknowledgement was dropped from the crowded status footer. The
runner had received Escape, but the user could not see its acknowledgement.

The screen now retains an explicit presentation-only `stopping` state and
renders the stopping label in the elapsed-time line. Footer priority and
visibility no longer determine whether the acknowledgement is visible. The
state resets on completion, interruption, and the next run; cancellation and
Provider ownership still use their existing settlement paths.

Both action-host cases now pass. The Escape case also observes further draft
editing while composition is still held, and both cases finish with exactly
one Worked divider and a closed LSP slot. Four render regressions cover 30/80
columns, long labels, and visible/hidden status footers. The final focused
selection passed 26 cases; Coding UI passed 602, TUI units passed 1312, and
render contracts passed 244. Subsequent native evidence is recorded below.

The later broad Coding run passed 3353 cases, skipped 283 and deselected 55;
its 127 failures and 39 fixture errors matched the baseline's failing/error
node IDs exactly. The grep timing case passed in this full run. HarnessTUI
passed 1051 cases, with 18 deselections and the same two macOS PTY failures.

## Native Actions verification

[PR #801](https://github.com/zhnt/loushang/pull/801) passed all selected checks
at `6649edd0d05ce878d81ac2241de9fc2d6e803a42` and merged as
`02df224d5ba84b9159ff46e4f3bba0afd171e16f` with the same source tree.
The [Actions run](https://github.com/zhnt/loushang/actions/runs/39408549038)
included Coding module shards, HarnessTUI/Coding UI, deterministic rendering,
POSIX PTY, Windows ConPTY, and resume E2E on Ubuntu, macOS, and Windows.

The downloaded `targeted-0.xml` report confirms six passing LSP vertical cases,
zero skips, zero failures, and zero errors on Ubuntu. In particular,
`test_product_selected_deferred_lsp_executes_and_reopens_dormant` passed in
4.094 seconds. This proves that the new case actually executed; it is not
inferred from a green workflow aggregate. The native Product case activates
the real selected Provider, executes an outline, closes its generation,
reopens persisted history with a dormant slot, activates again, and retires
both language-server processes. Its parent graph snapshot remains unchanged.

This closes the supported-Linux vertical-test and later-input/native-check
items in the earlier local report. It does not accept the whole architecture
decision or establish the remaining total-startup performance target.

## Remaining acceptance work

1. Establish the requested whole-CLI startup reduction with sufficiently stable
   measurements. The current total-startup evidence does not reach 50%.
2. Complete the Product/resume acceptance review for
   [ARD-010](../decisions/draft/ARD-010-deferred-capability-provider-slot.md).
   Its draft/partial status is retained.
