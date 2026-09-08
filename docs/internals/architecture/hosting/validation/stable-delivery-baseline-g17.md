# G17.0 Stable Delivery Baseline

[Hosting](../README.md) ·
[G16 delivery](../../appserver/detachable-local-workspace-g16.md#final-delivery-acceptance) ·
[Tracking #569](https://github.com/zhnt/loushang/issues/569)

Native acceptance has passed; see the [accepted evidence](#native-acceptance).
The local checkpoint and first failed publication below are historical records,
not the current native acceptance status.

## Scope And Diagnosis

This slice changes test evidence and current architecture indexes only. It does
not change Hosting's production inheritance list, introduce an API, activate
G15's launcher/picker, or extend the G16 deployment profile.

The Windows job in [post-merge Hosting run 34177069952](https://github.com/zhnt/loushang/actions/runs/34177069952)
failed `test_native_windows_endpoint_process_round_trip`: `010PING` instead of
`000PING`. The child successfully exchanged application bytes, but reported a
valid handle at the parent's write-handle number. The old untyped ctypes call
to `GetHandleInformation` cannot establish cross-process object identity.

Windows [handle values are process-private](https://learn.microsoft.com/en-us/windows/win32/fileio/file-handles).
A child may independently allocate the same number for a different object.
The production spawn already supplies `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`
through `STARTUPINFOEXW`, retaining only child stdin/stdout/stderr; parent pipe
ends are non-inheritable. This is not evidence of a production inheritance
defect. Conversely, the historical child's object table is gone, so numeric
reuse is a plausible explanation, not a retrospectively proven diagnosis.

## Corrected Evidence Boundary

`tests/hosting/_windows_handle_probe.py` is test-only. It binds pointer-width
Win32 signatures, validates the source process and parent reference, then
[duplicates](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-duplicatehandle)
the child's candidate into the parent with `DUPLICATE_SAME_ACCESS`. It compares
that owned duplicate against the retained parent reference using
[CompareObjectHandles](https://learn.microsoft.com/en-us/windows/win32/api/handleapi/nf-handleapi-compareobjecthandles).
It never closes the child source or injects a handle into the child. Every
successful duplication has a local close attempt, including on comparison failure.
Only an absent candidate handle is negative evidence; invalid process/reference,
access denial and cleanup errors fail the test rather than reporting isolation.

The native child sends readiness, then waits for parent input so its process
and inherited handles stay live during comparison. The test handles partial
reads and bounds the exchange; process cleanup is registered at spawn handoff,
and an exit stack attempts all remaining resource cleanup on failure.

Evidence has two distinct layers:

- Deterministic fake handle tables reproduce a same-number/different-object
  collision, detect genuinely shared objects, cover wide handle values and
  fail-closed probe errors. These are not native Windows evidence.
- The native Windows endpoint test retains the production allowlist case and
  adds three deliberate test-only leaks: parent read, parent write and ambient
  sentinel. Each control must report the exact shared object while the other
  references remain isolated. An always-negative probe cannot pass the controls.

The native cases run in the existing Hosting Quality matrix. No skip is removed,
failure is retried into a pass, or production isolation rule is weakened.

## Validation And Acceptance

The pre-change Linux endpoint/process selection passed 17 tests with five
native-Windows skips. The new deterministic probe selection passed nine tests.
The new G16 inventory/index regressions failed twice against the stale status
before the documentation correction. Current indexes now link one final G16
delivery record, while preserving G15's unimplemented launcher and all historical
G16 checkpoints.

Final local verification on 2026-09-08:

- Focused endpoint/process/probe and corrected G16 design selection: 29 passed,
  eight native-Windows skips.
- `make check-hosting` (offline dependencies, `not live`): Ruff passed, mypy
  passed for 26 source files, 382 tests passed and 48 platform-only cases skipped
  in 262.19 seconds. The three additional Windows positive controls account for
  three additional skips on Linux; no existing selector was loosened.
- `make check-architecture-docs`: static checks and all five tests passed.
- Adjacent G15/G16 boundary/design/evidence selection: 15 passed.
- The test-only probe passed Win32-targeted mypy; changed Python files passed
  Ruff and the delta passed `git diff --check`.

Local non-Windows checks do not settle the original native failure. Publication
and a corrected-head native Windows Hosting run remain required before closing
#569 or declaring G17.0's cross-platform baseline accepted. Publication is
deferred at this local checkpoint under weekday push quiet hours; native
acceptance remains open, without weakening the isolation assertion.

## Native Loader Correction

The first published [PR #570](https://github.com/zhnt/loushang/pull/570) head
`3114d767` passed Linux/macOS Hosting, but its
[Windows job](https://github.com/zhnt/loushang/actions/runs/34179928549/job/101916772852)
failed all four endpoint cases during probe construction: `CompareObjectHandles`
is exported by the documented `Kernelbase.dll`, not `Kernel32.dll`. That run
reported four failures, 359 passes and 75 platform skips; it never established
native object-isolation results.

The helper now binds comparison from Kernelbase and keeps the other functions
in Kernel32. A default-construction regression models distinct DLL exports,
reproduced the missing-symbol failure before the correction, and checks both
collision rejection and real-sharing detection after loading. Injected fakes
no longer constitute the only loader coverage. Missing DLLs or symbols remain
hard failures; there is no numeric fallback, skip or production change.

The local `loushang --help` and `loushang-mux --help` startup smoke checks also
passed. Native acceptance still requires the corrected PR head's green matrix.

## Native Acceptance

On 2026-09-08, corrected feature head
`fe20c1bea5451ad457f16049f8e78e94632df909` passed all 33 checks on
[PR #570](https://github.com/zhnt/loushang/pull/570) and merged into
`lane/harness` as `0ffe6d5249cf95753069faa007485294646ff3f9`.
The [Hosting run](https://github.com/zhnt/loushang/actions/runs/34180343960)
completed successfully on all three native platforms:

| Platform | Full Hosting contract suite | Native job |
| --- | --- | --- |
| Ubuntu 24.04 | 392 passed, 47 platform/profile skips | [Linux evidence](https://github.com/zhnt/loushang/actions/runs/34180343960/job/101917980290) |
| macOS 15 | 369 passed, 70 platform/profile skips | [macOS evidence](https://github.com/zhnt/loushang/actions/runs/34180343960/job/101917980481) |
| Windows Server 2022 | 364 passed, 75 platform/profile skips | [Windows evidence](https://github.com/zhnt/loushang/actions/runs/34180343960/job/101917980456) |

All four native Windows endpoint parameters ran successfully: `isolated`,
`leaked-parent-read`, `leaked-parent-write` and `leaked-sentinel`. None is among
the platform skips. The helper's ten deterministic regressions, including its
default DLL loading path, also passed. The corrected local focused selection
passed 30 tests with eight Windows-only skips, plus Ruff and Win32-targeted mypy.
CI's contract selection and platform expectations differ from the local Make
selection, so their aggregate pass/skip counts are not interchangeable.

This closes the native evidence gap without changing production inheritance,
retrospectively clearing the original failed run, or activating G15. Main
promotion uses its own final-head PR checks; this record does not substitute
feature-head evidence for the promotion gate.
