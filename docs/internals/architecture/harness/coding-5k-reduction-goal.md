# Coding Package 5K Reduction Goal

Goal: reduce `src/loushang/coding` from ~21,000 LOC (Python source, blanks and
comments included, `__pycache__` excluded) to **~5,000 LOC (hard cap 6,000)** by
migrating every mechanism that can be parameterized into `loushang.harness` /
`loushang.harnesstui`, leaving Coding as product policy, wire wording, and thin
adapters.

This document is the handoff contract. Execution must also follow
[coding-shared-layer-migration-plan.md](coding-shared-layer-migration-plan.md)
and record every completed slice in
[coding-shared-layer-migration-ledger.md](coding-shared-layer-migration-ledger.md).

## Baseline (2026-07-21, lane/harness worktree)

| Region | LOC | Final target | Delta |
| --- | ---: | ---: | ---: |
| top-level modules (`bootstrap.py`, `sdk_surface.py`, `work_*`, ...) | 4,564 | ~800 | -3,700 |
| `cli` (`__main__.py` 3,358, `args.py` 739) | 4,100 | ~1,000 | -3,100 |
| `session` (`agent_session.py` 1,769 + two controllers) | ~2,434 | ~400 | -2,000 |
| `control` (`settings_manager.py` 1,403) | 1,904 | ~450 | -1,450 |
| `ui` + `presentation` + `interaction` | 2,935 | ~1,500 | -1,400 |
| `mode` (rpc already collapsed to 117) | 840 | ~700 | -150 |
| `runtime` (`agent_session_runtime.py` 781) | 794 | ~100 | -700 |
| `policy` / `platform` / `compaction` / `extensions` / `workflow` / `domain` | 2,531 | ~1,800 | -700 |
| **Total** | **21,285** | **~5,200–6,750** | |

Measure with: walk `src/loushang/coding`, count lines of every `*.py`,
excluding `__pycache__`. Tests do not count.

## Ownership Rules (updated)

1. **Parameterizable means movable.** Any mechanism may move to a shared owner
   when every product difference can be supplied through a port, profile,
   callback, projection, or plan. This explicitly supersedes the ledger's older
   "RPC model/auth, package, bash, extension UI handlers — Retained by design"
   row: the mechanism behind those handlers moves; Coding keeps only the wire
   contract, error wording, and compatibility fields as injected projections.
2. **Proven pattern: projection-port injection.** `coding/mode/rpc_mode.py`
   (2,758 → 117 LOC) is the reference: `harness.host.rpc.RpcHost` owns all
   handler mechanics; Coding injects `RpcEventProjection` and
   `RpcDiagnosticsProjection`. Replicate this shape for CLI handlers, session
   controllers, and settings mechanics.
3. **No wire or behavior drift.** RPC/CLI/JSONL wire fields, slash-command
   syntax, error text, and event schemas must not change. Migration is
   invisible to users and to RPC clients.
4. **Deletion condition.** A slice is done only when the old implementation is
   deleted or reduced to declared product data and ports. A growing facade is
   not a migration.
5. **Neutral-core rule.** `harness` core stays independent of Agent/AI;
   declared integration packages (`harness.session`,
   `harness.transcript`, `harness.host`) may use stable public Agent/AI
   value contracts only.
6. **Compression-ratio tracking.** Each slice records deleted vs added LOC in
   the ledger. Target ratio ≥ 0.7 (deleted/added). If a slice lands below 0.5,
   stop and re-cut the boundary before continuing — glue is outrunning
   deletion.

## Migration Waves (remaining)

Execute in order; each slice is one commit or PR with ledger accounting.

### Slice A — Finish Wave 4: `agent_session.py` teardown (~-1,400)
- Source: `coding/session/agent_session.py` (1,769), `coding/runtime/agent_session_runtime.py` (781).
- Move generic session orchestration (prompt/queue/turn mechanics, event
  forwarding, extension runtime binding) into `harness.session` behind ports.
- Coding retains: model/auth/provider policy, CWD and session-file acceptance,
  diagnostics wording, final construction callbacks.
- Controllers: migrate `extension_provider_controller.py` (245) and
  `package_controller.py` (231) mechanics into `harness.session` /
  `harness.resources.packages`; Coding keeps wire/result projection only.
- End state: `agent_session.py` ≤ 400 LOC of typed delegation.

### Slice B — CLI collapse (~-3,100)
- Source: `coding/cli/__main__.py` (3,358).
- Move mode-startup mechanics, output guards, stream binding, command-handler
  dispatch scaffolding into `harness.host` / `channel` (extend
  `ProductHostLifecycle`).
- Coding retains: argument grammar (`args.py`), mode selection, startup policy,
  output-format choice, handler registration tables.
- End state: `__main__.py` ≤ 800 LOC.

### Slice C — Settings mechanics (~-1,450)
- Source: `coding/control/settings_manager.py` (1,403).
- Move codec registry, layered merge, removed-field migration mechanics into
  `harness.config` (extend `SettingsRuntime` / `ScopedConfigRuntime`).
- Coding retains: `ControlConfig` schema, field codecs/defaults, typed product
  setters, path defaults.
- End state: `settings_manager.py` ≤ 400 LOC.

### Slice D — Bootstrap & top-level composition (~-3,000)
- Source: `coding/bootstrap.py` (1,503), `resource_runtime.py`, `tool_pack.py`,
  `capability_plan.py`, `work_runtime.py`, `work_executor.py`, `sdk_surface.py`.
- Move capability-pack composition, resource activation assembly, and
  session-construction orchestration into `harness.bootstrap` /
  `harness.capabilities` behind the existing plan/port types.
- Respect the ledger's deferred row: no second bootstrap engine — extend
  `ConfigActivationRuntime` / `BootstrapActivationRuntime` instead.
- Coding retains: prompt/model/resource/tool policy values, package source
  policy, product diagnostics callbacks.
- End state: top-level modules ≤ 800 LOC total.

### Slice E — TUI shared mechanisms (~-1,400, conditional)
- Source: `coding/ui` (1,227), `coding/presentation` (1,115),
  `coding/interaction` (593).
- Only migrate a mechanism when `harnesstui` (or a second product) actually
  consumes it — screen surfaces, history, tool-transcript rendering, intent
  parsing are candidates; wording/layout policy stays.
- If no real second consumer exists, skip rather than relocate: moving code
  Coding-only code into harness does not count toward the goal.
- End state: these three packages ≤ 1,500 LOC combined.

## Per-Slice Workflow

1. Before coding: write or update the boundary doc for the slice in this
   directory, listing source region, shared owner, injection points, deletion
   condition (same table format as existing boundary docs).
2. Baseline: `uv run pytest tests -q` green; record current LOC of the source
   region.
3. Migrate mechanism-first, delete second. Keep wire contracts byte-identical;
   add architecture probes proving the new shared module has no Coding import
   (pattern: `tests/architecture`).
4. Validate: targeted tests for the touched region, then full suite; for
   RPC/CLI slices also run the existing wire/fixture regressions.
5. Ledger: append the slice row with actual deleted/added LOC and the
   compression ratio; update this file's baseline table if regions shift.

## Guardrails

- Do not touch `coding/mode/rpc_mode.py` further unless a handler regresses —
  it is the finished reference, not a target.
- Do not migrate product-only surfaces: prompt wording, changelog content,
  approval wording, `ControlConfig` schema, RPC compatibility fields.
- Do not add duplicate engines (dispatcher, bootstrap, event schema). Extend
  the existing Harness owner.
- Every new shared module gets a no-Coding-import architecture test.
- If a slice cannot meet its deletion condition without changing user-visible
  behavior, stop and report the blocker instead of shipping a behavior change.

## Acceptance

- `src/loushang/coding` ≤ 6,000 LOC, stretch 5,000.
- Full test suite green; architecture ownership tests green.
- Ledger shows every slice with deletion condition met and ratio ≥ 0.7
  average.
- No RPC/CLI wire diff, no slash-command surface diff.
