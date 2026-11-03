# G18 CLI loading boundary

The user authorized continuing the exploratory mean-startup work on 2026-09-11.
The ordinary CLI help path still discovers extension flags through its original
application/runtime bindings. Returning static help would remove that behavior;
it is not part of this optimization.

## Responsibility split

- `coding.cli.__main__`: the existing console and `python -m` entrypoint,
  process argv, event-loop entry, and KeyboardInterrupt/exit-code policy.
- `coding.cli.application`: the unchanged `run_cli` signature/defaults, Product
  bindings, dependency injection, special dispatch, help discovery, session and
  lifecycle operations formerly in `__main__`.
- `coding.cli`: the existing two-export grammar facade (`CliArgs`, `parse_args`).

Console script targets are unchanged. Historical helper reads through `__main__`
remain available; tests which replace application-owned dependencies inject at
`coding.cli.application`, where the functions' globals now live. No module-class
mutation, global dependency-loader registry or replacement parser is introduced.
Architecture guards follow the moved runtime and continue checking the entrypoint.
Machine-checked package-query inventory pointers move with their existing functions;
counts, operations and authorities do not change.

## Two local steps

1. Move application bindings mechanically, retaining eager entrypoint loading.
   Verify the existing runtime behavior and freeze this structural baseline.
2. Make the grammar facade and entrypoint imports lazy. Only the exact canonical
   `--version` invocation may use a stdlib metadata-only path with the existing
   source-tree fallback version. Mixed arguments, verbose version, errors and
   all help invocations retain the original application path. Keep `asyncio.run`
   and KeyboardInterrupt behavior, including for the metadata path.

The baseline and optimized candidate must share package paths, dependency lock,
entrypoint targets, and unchanged application code. Add cold-process import
guards, forwarding/output/metadata-error tests, and retain existing CLI/extension
flag/architecture checks. Only then run a new small installed mean A/B; preserve
raw data and report regressions as well as wins. Prior exploratory and formal
reports are immutable and are not pooled or promoted to acceptance.

This step does not promise that ordinary help will be faster: preserving dynamic
discovery still requires the runtime. Actual help-path improvements need their
own measured change. No push, merge, dispatcher or lifecycle expansion.

## Structural baseline verification

The application file matches the original module mechanically, excluding its
process `main` and now-unused `asyncio` import. No application handler, callback
default, parser, or lifecycle implementation changed.

- CLI/extension/workspace/LSP/multiagent/activation tests: 300 passed (exec 74455).
- Affected architecture/entrypoint/composition tests: 286 passed (exec 67731).
- CI inventory/selection tests: 47 passed; the application retains AppHost lint
  support, and the resource-catalog contract guard is registered with Harness.
- Shared Makefile selection required `make check-ai`: passed (exec 77641),
  including 61 example tests, 851 coverage tests, and 90.63% total coverage.
- Changed Python lint, dependency-graph freshness and lightweight docs checks
  pass. No Actions files changed; `actionlint` is unavailable locally, so no
  actionlint result is claimed.

These are scoped local checks, not the entire broad shared-Makefile release or
cross-platform matrix. No final performance/release acceptance is claimed.
Structural baseline: `cecb67d83eec1789c098d805abdb7d9cd649d131`.

## Lazy candidate verification

The grammar facade resolves and caches only successful lookups of its two existing
exports. The entrypoint lazily resolves the real `application.run_cli`; historical
helper reads retain function identity. Exact `--version` uses installed metadata,
falling back only on `PackageNotFoundError`. An explicitly materialized or replaced
entrypoint `run_cli` binding is still honored, including for `--version`.

- 26 new cold-process and boundary checks cover import blocking, explicit/process/
  module argv, metadata failures, interrupt behavior, noncanonical argument
  forwarding, overrides, function identity, and successful-lookup-only caching.
- Focused CLI/extension/loading regression: 290 passed (exec 3085).
- The selected `check_changed.py --base cecb67d8...` run (exec 43110) completed
  docs/dependency checks but was interrupted after Coding reported 1544 passed,
  16 skipped and six failures. This invocation is **not a passed gate**. The six
  failures were nested pytest argument errors: the invocation incorrectly put
  the repository-specific `--skip-host-runtime` option in inherited
  `PYTEST_ADDOPTS`, but temporary probes do not load `tests/conftest.py`.
- Keeping the option on the outer pytest command, with offline/host-runtime
  exclusions preserved, resolves all six failures: the whole affected evidence
  file passes, 7 tests (exec 99679). No Product change was needed for this error.
- Remaining Coding coverage was completed by rerunning whole files from
  `test_package_materializer.py` onward, before the interrupted plugin-lifecycle
  boundary. The unchanged selection contains 2477 ordered nodes; the retained
  `.artifacts/g18-cli-entry/coding-collection.txt` records that inventory. Tail
  result: 976 passed, 5 skipped, 2 deselected (exec 5103), with JUnit at
  `.artifacts/g18-cli-entry/coding-tail.xml`. Counts overlap the initial run and
  must not be summed as unique tests or called one uninterrupted gate pass.
- AppHost lint and type checking pass (83 source files; exec 90970).
- Selected TUI checks pass (exec 27876): 1252 unit tests and 179 deterministic
  render/playback tests, with the existing scope exclusions retained.

Full AppHost Make/release and native/cross-platform matrices are not claimed by
these scoped checks. The initial selected-check invocation remains non-passing;
its resolved invocation error is not a waiver of unrun release checks.

## Installed comparison — 2026-09-11

Use the structural baseline above and the frozen lazy candidate, not the older
eager-Coding baseline. Both sides already include the prior Coding-facade
optimization; this measures the incremental CLI change. Keep the same ten-case
collector, two blocks and three pairs per block: six measured pairs per case,
120 measured observations plus 40 predeclared warmups. Use new independent wheels
and installations under `.artifacts/g18-cli-entry`, with fresh private parent and
scratch directories. Output: `inert-ab-exploratory-mean-01` under that directory.
No concurrent tests, builds or diagnostics during timing. Stop on failure,
preserve partial evidence, and do not automatically retry or change thresholds.

Follow the descriptive statistics and limitations in the
[previous exploratory comparison](startup-performance-g18-exploratory-means.md),
without pooling its measurements. Report every case, including slower outcomes;
the small-sample comparator must remain `not-evaluated`.

### Frozen result

Exec 5495 exited 0. Collection ran 08:26:54.251564–08:35:55.940348 UTC with
private parent `/var/tmp/lg18-tests-8L8qmq` and retained scratch
`/var/tmp/loushang-g18-baseline-7v3_eeql`. Baseline A is `cecb67d8...` above;
candidate B is `c60887e6526b7144d4912a6bc5fcec8efff1d8e7`.

- A wheel SHA256:
  `c4d7749a88b1e3a0ad08f70685e185b2248093355dd7f2e9c5fd59e7438c4a2d`.
- B wheel SHA256:
  `e9dd6a4a553d346f4a5440aa97f154cef4d49950f46cbceef043290fff5dbb54`.
- Report: `.artifacts/g18-cli-entry/inert-ab-exploratory-mean-01/report.json`;
  SHA256 `424b4d013f660fac1e7ded70efd703c3de925abf0edc3362e64631128d62fcf7`.
  The sibling `means.json` binds that hash and retains unrounded means, medians,
  ranges, block means, CPU means, all paired differences and output hashes.

All 160 observations are valid with exit 0 and no recorded failure. Independent
reconstruction verifies exact case/block/pair/side order, including 120 measured
observations and 40 declared warmups. Every case has identical stdout/stderr
across both installations and all observations, including warmups. Helpers are
unchanged; the collector's before/after installation checks pass. Both sides use
Python 3.11.15, identical dependencies/entry targets/project/lock and 1305 package
paths. Their production-source difference is only the two CLI loading modules;
application code is unchanged. No tests, builds or diagnostics ran during timing.
The machine was not OS-exclusive; its existing long-running user process was
left untouched. These measurements are not pooled with earlier runs.

Arithmetic means are seconds; positive reduction means B used less elapsed time.
All six measured observations per side are included in each row.

| Entry | A mean | B mean | Reduction | B faster pairs |
| --- | ---: | ---: | ---: | ---: |
| import-harness | 0.0543 | 0.0589 | -8.47% | 3/6 |
| import-coding | 0.0557 | 0.0528 | 5.19% | 5/6 |
| import-cli | 5.1046 | 0.0509 | 99.00% | 6/6 |
| cli-help | 8.1599 | 8.1560 | 0.05% | 3/6 |
| cli-version | 4.9936 | 0.1974 | 96.05% | 6/6 |
| tui-help | 8.1093 | 8.1438 | -0.43% | 2/6 |
| hosted-help | 4.1192 | 3.9307 | 4.58% | 5/6 |
| hosted-tui-help | 2.7129 | 0.1834 | 93.24% | 6/6 |
| mux-help | 2.8784 | 0.2837 | 90.14% | 6/6 |
| plugin-help | 0.7450 | 0.6834 | 8.27% | 6/6 |

The clear observed gains are import-cli (5.054 seconds saved), canonical
`loushang --version` (4.796 seconds), hosted-tui-help (2.530 seconds), and
mux-help (2.595 seconds). All four improve in both blocks and all six pairs.
Their mean child CPU times also drop respectively from 4.5675 to 0.0452,
4.5508 to 0.1806, 2.4141 to 0.1455, and 2.5510 to 0.2283 seconds. This supports
a scoped loading-work reduction, not merely a wall-clock scheduling difference.

Ordinary CLI help remains about 8.16 seconds, with only a 3.9 ms mean difference
and three winning pairs; TUI help is slightly slower on average. Neither is an
improvement claim. Keep the other rows as observations rather than assigning all
changes to this optimization: even the unchanged short import-harness control is
4.6 ms slower, while plugin-help has a favorable mean without a direct plugin
implementation change. Small samples, installation paths and uncontrolled OS
cache/load preclude universal or cross-platform conclusions.

Status: implementation and exploratory installed comparison complete; original
comparator remains `not-evaluated`, not formal acceptance. Loading work is
avoided for the version-only path and deferred until needed on other paths; no
claim is made for first turn, model/tool work, TUI readiness, recovery or cleanup
latency. Full release checks remain separate as described above. No push/merge.
The next optimization target is dynamic CLI help discovery, which must retain
extension flags and its existing dispatch/output semantics.
