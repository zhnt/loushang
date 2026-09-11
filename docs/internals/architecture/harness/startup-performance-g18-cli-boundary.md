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
Status: structural baseline verified; lazy/version optimization and new paired
performance measurement remain pending.
