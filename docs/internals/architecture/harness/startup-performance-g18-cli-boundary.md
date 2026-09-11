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

## Next installed comparison

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
the small-sample comparator must remain `not-evaluated`. Installed measurement
is still pending; no speedup is claimed for this candidate yet.
