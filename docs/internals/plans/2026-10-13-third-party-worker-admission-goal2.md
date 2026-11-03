# Third-party Worker admission delivery

## Scope

Goal 2 delivers an explicit author/operator flow for self-contained native
read-only query Workers on Linux x86-64 and Windows AMD64. The existing Package
Product owns installation and selected revisions; Hosting owns the mandatory
native containment profile; Coding owns each Session's receipt, graph and query.
No additional registry, installation service or execution authority is needed.

The admitted shape is one `capability.query` Provider with no requested file
or network authority. Dependency execution, effectful operations, macOS, remote
services and default Worker selection remain outside this release. Installed
dependency-bearing candidates must continue to refuse activation. These limits
are distinct from the complete PLC9 acceptance and Issue #509 closure in Goal 3.

## Delivery evidence

| Requirement | Existing owner and delivery test |
| --- | --- |
| Independent author source and inert build | `examples/plugins/coding_worker_query/query_worker.c`; public `build-coding-worker-candidate` command with digest and unchecked-use assertions |
| Capture, disabled installation, selected enablement, exact native approval and per-install authorization | Linux `test_worker_native_operator_cli_reopens_product_across_processes`; Windows `_exercise_windows_worker_wheel_transaction` through the existing Product owner |
| Actual Direct and Hosted Coding Session query | Linux and Windows public/hosted Session cases use the independent author source; the Direct cases also exercise persisted ordinary turn Tool results |
| Disable and revoke while pinned | Public Session lifecycle cases fence the next query and settle the native attempt on disposal |
| Update and explicit new-version use | Linux cross-process operator journey builds both author Wheels through the public command; Windows update/GC journey uses real version 1 and 2 native Workers and queries version 2 after old-version GC |
| Crash recovery | Native public Session crash/reopen cases, exact orphan/attempt recovery and retained cleanup evidence |
| Stage retirement and Package deletion | Product's existing retirement/GC owners; Windows update journey retires actual Session stages and deletes both version roots without manufacturing C5 settlement records |
| Refusal diagnostics | Operator reports distinguish an allowed revision that must be revoked from unavailable recovery; exact inventory/selection and native review changes retain their own refusal boundaries |

The old #678 reports describe its former head only. They do not validate this
delivery's merged base, updated lifecycle tests or diagnostics. Final evidence
must correspond to the delivery commit and include non-skipped Linux and
Windows native reports. Passing author smoke establishes inert admission and
selection only; it never substitutes for a Session query.

## Completion gates

- Local changed-scope checks and focused author/operator/Session regressions
  pass with retained reports.
- Windows native Session, normal retirement/update/GC and crash-recovery reports
  pass on the final delivery commit with their required counts and no skips.
- The operator guide matches the actual platform commands and separately
  explains candidate installation, native release approval, per-install
  authorization, Session use, recovery, retirement and GC.
- Support claims are updated only after their corresponding native evidence;
  the final PR is merged and the control lane is synchronized.

## Local validation checkpoint: 2026-10-13

The code lane's isolated editable installation passed the Linux authored
Direct Session regression, including same-boot and prior-boot ordinary-turn
crash recovery (1 test, no skips), and the cross-process native operator
lifecycle (1 test, no skips). Authored disable, update, Hosted first Session
and public-builder reproducibility also passed (4 tests, no skips).

The Windows command regression passed four portable cases; its one native
Windows case was skipped on Linux and remains a CI requirement. Ruff,
the changed Windows command's typecheck and documentation invariants passed.
The full changed-scope checks are still running at this checkpoint. A prior
Direct run exceeded its unchanged 90-second crash-child deadline; the passing
rerun retains stage diagnostics and does not establish the earlier timeout's
cause. This checkpoint is not final Windows admission or PR acceptance.

Goal 3 remains paused. This delivery neither accepts the separately proposed
Windows journal authority-cutover stack nor closes Issue #509.
