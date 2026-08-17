# 2026-05-02 Gap Alignment Report

This report tracks the current loushang coding alignment state against reference coding agent after the current
runtime/RPC/diagnostics/tool hardening pass.

## Overall Completion

| Scope | Completion | Gap | Notes |
| --- | ---: | ---: | --- |
| Non-method / non-interactive / non-TUI MVP | 99%+ | <1% | Headless session/runtime/RPC/extension/tool main path is usable; remaining gaps are edge UX or deferred remote package behavior. |
| Including method but excluding interactive/TUI | 90-92% | 8-10% | Method registry/selection/injection is intentionally deferred. |
| Including interactive/TUI | 78-82% | 18-22% | Interactive command consumer, autocomplete UI, theme/rendering are not part of the current MVP. |

## Component Snapshot

| Component | reference implementation Completion | Remaining Gap |
| --- | ---: | --- |
| session | 99% | Minor SDK edge cases and HTML interaction polish. |
| runtime | 98% | Remaining gaps are narrow lifecycle stress cases and rare cross-session operation error paths. |
| store | 96-97% | Explicit session index cache/query APIs exist; reference implementation delayed flush implementation details are still not replicated. |
| rpc | 98% | Minor command coverage edges remain. |
| commands/slash | 97% | Interactive builtin command consumer and TUI autocomplete are not implemented. |
| extensions | 96-97% | Real TUI consumption layer, theme rendering, and minor runtime hook edge cases. |
| tools | 98-99% | Some rich tool display details still trail reference implementation. |
| diagnostics | 98-99% | Remaining gaps are mostly presentation and policy-specific warning grouping. |
| loader/resource | 98-99% | Deeper theme validation and optional package trust hardening remain. |
| prompt/skill | 99% | Minor command enablement and advanced ignore syntax edges. |
| compaction | 99% | Remaining gap is summary quality polish under real model workloads. |
| control/settings | ~100% | Aligned for headless MVP; provider/model config intentionally diverges. |
| provider/model | intentionally divergent | Continue using loushang AI Provider -> Endpoint -> Model; do not replicate reference implementation flat provider config. |
| method | low | Deferred by product decision. |
| interactive/TUI | low | Not part of the current headless MVP. |

## Completed On 2026-05-02

- Tool active boundary:
  - `allowed_tool_names` and CLI `--tools` / `--no-tools` map to session tool visibility.
  - Default active built-ins are narrowed to `read`, `bash`, `edit`, `write`.
- Tool source provenance:
  - `ToolRegistry` can store `source_info`.
  - Extension tools project real source metadata in `AgentSession.getAllTools()`.
- Extension registry/resource alignment:
  - Message renderer headless registry added.
  - `resources_discover` accepts reference-style `promptPaths`, `skillPaths`, `themePaths`.
  - Bad extension resource paths generate a resource-scoped `DiagnosticDraft`
    instead of being silently ignored.
- Command surface alignment:
  - Session/RPC command listing returns all registered extension commands.
  - `RegisteredCommand.hidden` and `ExtensionAPI.register_command(hidden=...)` were removed.
  - Queued extension command errors now match reference-style message semantics.
  - Builtin slash command descriptions now match reference-style metadata for future CLI/RPC/autocomplete projection.
- Extension UI headless state:
  - `RpcExtensionUIContext` now records status, widget, title/editor, working indicator, autocomplete provider count, and tools expanded state.
  - RPC `get_extension_ui_state` returns this snapshot for headless clients.
- Loader/theme diagnostics:
  - Theme discovery skips non-`.json` files and records `unsupported_theme_entry`.
- Exec backend alignment:
  - `ExecService(backend=...)` provides a stable custom execution backend seam.
  - This covers the reference implementation bash operations custom backend use case without copying the reference implementation's tool-layer structure.
- Resource collision diagnostics:
  - Collision metadata now includes `winner_path`, `candidate_paths`, and `loser_paths`.
  - This makes loushang diagnostics closer to the reference implementation's winner/loser path reporting while retaining richer source-kind metadata.
- JSONL session export:
  - Default JSONL exports now use cwd-local `session-<timestamp>.jsonl` paths.
  - Current-branch export explicitly re-chains `parentId` values into a linear sequence.
- Settings load-error handling:
  - `SettingsManager` records load/reload errors instead of failing startup.
  - `reload()` preserves the last valid scope patch when a settings file becomes invalid.
  - `drain_errors()` exposes pending settings errors for diagnostics layers.
- Settings scope introspection:
  - `SettingsManager` now exposes global, project, and session patch snapshots.
  - Returned patches are defensive copies, so callers cannot mutate manager state.
- Queue mode settings:
  - `steering_mode` and `follow_up_mode` are now first-class control settings.
  - `AgentSession.set_steering_mode()` and `set_follow_up_mode()` persist settings, matching the reference implementation's session/settings behavior.
  - Bootstrap applies configured queue modes when constructing the underlying agent.
- Settings/control breadth:
  - Added theme, shell path, shell command prefix, npm command, quiet startup, changelog collapse, install telemetry, skill command enablement, thinking budgets, terminal preferences, markdown preferences, warning preferences, and provider retry cap settings.
  - Added enabled model cycling, double-escape action, tree filter mode, hardware cursor, editor padding, and autocomplete max-visible settings with reference-style defaults and bounds.
  - Added stable getter/setter accessors for resource roots, package roots, plugin sources, disabled skills, and disabled plugins.
  - Bootstrap now passes thinking budgets and provider retry delay cap to the underlying agent. A later AIF-009 cleanup removed the coding-level transport setting; transport selection remains provider/contrib-owned.
  - Bootstrap now maps configured `enabled_models` patterns into `AgentSession.scopedModels`, preserving per-model thinking-level suffixes such as `model-id:high`.
  - Added branch-summary `skip_prompt` and stable query facades for compaction, branch summary, image, terminal, markdown, and warnings settings.
  - This closes settings/control for the non-interactive headless MVP while preserving loushang's non-reference provider/model configuration decision.
- Package/resource diagnostics:
  - Loader now reports `missing_package_root`, `invalid_package_root`, and `empty_package_root` instead of silently ignoring broken package roots.
  - Loader exposes filtered resource diagnostics and package resource summaries for CLI/RPC/TUI projection.
- Compaction stale usage guard:
  - Auto-compaction now ignores assistant messages older than the latest compaction boundary.
  - This matches the reference implementation's protection against stale pre-compaction usage/error messages retriggering compaction after context rebuild.
- HTML session export:
  - Exported HTML now embeds base64 JSON session data with header, full entries, leaf id, stats, and tree summary.
  - Exported session data now includes current `systemPrompt` and reference-style tool definition metadata (`name`, `description`, `parameters`).
  - Export template JS now decodes embedded session data into `window.loushangSessionData`, matching the reference implementation's runtime data loading seam for future sidebar/search/filter work.
  - Transcript rendering now displays branch summary, compaction summary, and custom messages instead of falling back to unknown message reprs.
  - Session tree summary includes entry types, active leaf, and labels, closing the non-interactive data-completeness gap with reference implementation export.
- Package list UX:
  - CLI now exposes `--list-packages` and `--list-packages-format tsv|json`.
  - The package list combines configured `package_roots` and plugin-provided package roots.
  - Output includes settings scope, source path, resolved package path, enabled state, version, prompt / skill / extension / theme counts, and package diagnostics count.
  - Disabled plugins remain visible but are not loaded into the active resource plane.
  - CLI now accepts reference-style headless aliases: `list` for installed plugin sources, `install <source>` for adding a local plugin source, and `remove <source>` / `uninstall <source>` for removing a local plugin source.
- Skill frontmatter semantics:
  - `SKILL.md` frontmatter now populates structured skill `name`, `description`, and `disable-model-invocation`.
  - Skill command descriptions prefer frontmatter `description`.
  - System prompt assembly emits an `available_skills` summary for enabled skills with descriptions, and excludes explicit-only skills marked `disable-model-invocation: true`.
  - Loader reports stable diagnostics for invalid skill frontmatter `name` and `description`.
  - Skill discovery now recursively finds nested `SKILL.md` roots, stops descending once a directory is a skill root, skips hidden directories plus `node_modules`, and applies `.gitignore` / `.ignore` / `.fdignore` directory/path/glob patterns.
- Package/settings diagnostics:
  - Package/plugin/skill settings management CLI surfaces now drain `SettingsManager` load errors and print reference-style warnings to stderr.
  - Settings load warnings do not fail otherwise successful package list or toggle operations.
  - Removing a missing plugin source now returns a stable CLI error instead of reporting a false successful removal.
  - Adding a duplicate plugin source now returns a stable CLI error instead of reporting a false successful add.
- Runtime/RPC diagnostics hardening:
  - `DiagnosticsService` now exposes `DiagnosticSummary` with total/error/warning/info counts, byCode/bySource/byPhase maps, and latestError.
  - `AgentSession` and `AgentSessionRuntime` expose global and current-session diagnostic summary facades.
  - RPC now supports `get_diagnostics_summary` and `get_session_diagnostics_summary` with the same filter surface as diagnostics listing.
- Tool stream projection:
  - Tool result JSON serialization now preserves `AgentToolResult.terminate` in update/end event payloads.
- Store session index:
  - `SessionManager` now exposes explicit `.session-index.json` cache APIs: `refresh_index`, `load_index`, `list_indexed_summaries`, `find_indexed_sessions`, and all-session variants.
  - Missing or invalid index files are rebuilt by the indexed query path.
  - Default `list_summaries` / `find_sessions` still scan JSONL directly, avoiding hidden stale-cache behavior in the core runtime.
  - `AgentSessionRuntime` now exposes matching indexed summary facades so CLI/RPC/TUI can opt into the cache without duplicating store policy.
  - CLI `--session-index` / `--refresh-session-index` and RPC `useIndex` / `refreshIndex` expose that opt-in cache path without changing default list/search behavior.
  - `AgentSessionRuntime(auto_refresh_session_index=True)` now provides an opt-in delayed flush scheduler: session replacement and indexed list queries schedule coalesced index flushes with debounce/backpressure, and `dispose()` drains pending flushes.
  - Runtime rename/delete now schedule auto index flushes, and store rename/delete keep the primary operation successful even if auxiliary index refresh fails.
- Extension services parity:
  - `create_agent_session_services(...)` now loads extension registry metadata, exposes `extension_runner`, applies `extension_flag_values`, and reports unknown/missing flag values as creation diagnostics.
  - `create_agent_session_from_services(...)` carries service-resolved extension flag values into the actual session runner.
- Extension diagnostics correlation:
  - Resource diagnostics now preserve `resource_id`, `resource_type`, `source_kind`, and descriptor metadata in normalized diagnostic details.
  - Extension command failures now include `invocation_name`, `command_name`, `extension_name`, and structured `source_info` in diagnostic details.
- Extension headless projection:
  - `ExtensionRunner.list_message_renderers()` / `listMessageRenderers()` exposes custom message renderer registrations with source info.
  - `ExtensionRunner.get_diagnostic_snapshot()` exposes extension diagnostic counts and serialized resource diagnostics for RPC/TUI inspection.
- Extension bash operations:
  - `user_bash` handlers can now return `{ operations: ... }`, letting the default bash execution chain continue with a custom backend.
  - Direct `{ result: ... }` replacement remains supported for extensions that fully handle execution themselves.
- Package conflict projection:
  - `--list-packages --list-packages-format json` now marks same-name multi-version entries with `versionConflict` and `conflictVersions`.
- Offline package catalog projection:
  - `--package-catalog <json>` merges local catalog entries into `--list-packages` output without performing network install/update.
- HTML export polish:
  - Static HTML exports now include transcript search, message type filtering, and visible/total message counts.
  - Static exports now include sidebar navigation and richer tool call/result metadata including tool status.
  - Static exports now include lightweight JSON syntax highlighting, CSS variable theme injection, and custom message renderer support via extension renderer registry.
- Package remote lifecycle observability:
  - Remote package install/update/remove/check paths are covered by `PackageMaterializer`.
  - Package lifecycle failures now surface as failed CLI/RPC responses instead of successful commands with failed records.
  - Materializer progress events now cover policy-denied installs, removals, and update checks in addition to install/update backend runs.
- Python package update checks:
  - `pypi:` package records now participate in update checks, mirroring the reference implementation's npm/git split with loushang's Python package source model.
  - Pinned Python package sources are skipped during update checks, matching pinned git/ref behavior.
- Package scope resource resolution:
  - Active package resource roots now use the same configured-source merge path as package update/check operations.
  - Project and user package sources can coexist in the active resource plane instead of project settings replacing user packages.
  - Configured package dedupe now uses package identity rather than exact source string, so pinned version/ref variants resolve with project-over-user precedence.
  - Local relative package sources are resolved against their settings scope before dedupe, so same relative paths in user/project settings do not collapse incorrectly.
- Compaction cut-point alignment:
  - Compaction preparation now starts from the previous compaction's `first_kept_entry_id` boundary instead of re-summarizing older entries.
  - Entry-aware cut-point selection supports split-turn preparation with `turn_prefix_messages`.
- Restore/import filesystem resilience:
  - JSONL import no longer overwrites an existing same-basename session in the target `session_dir`; it creates a unique imported filename instead.
  - Copy-time destination races now retry with the next unique imported filename instead of failing the import.
  - Import `session_before_switch` now observes only the final copied destination, and cancellation removes the copied import artifact.
  - Failed imports after copy, such as missing stored cwd validation, clean up the copied destination and leave the current session unchanged.
  - Import of a source file already inside the target session directory still avoids self-copy and preserves the original file.
  - Restore/import failures now record stable `session_restore_failed` / `session_import_failed` runtime diagnostics while still surfacing the original exception to callers.
- Runtime/store stress hardening:
  - Indexed session queries now rebuild `.session-index.json` when cached summaries point at session files that disappeared outside `SessionManager`.
  - Nested all-session indexed queries inherit the same stale-cache healing for child session directories.
  - Runtime rename/delete failures now record stable `session_rename_failed` / `session_delete_failed` diagnostics while still surfacing the original exception to callers.

## Recommended Next Gaps

1. `export_html polish`
   - HTML data completeness and runtime data loading are covered, including session tree, current system prompt, and tool definitions.
   - Static transcript search/filter is covered.
   - Static sidebar navigation and richer tool status metadata are covered.
   - Syntax highlighting, theme CSS variables, and custom message renderer projection are covered.
   - Remaining non-UI gap is production-grade syntax highlighting. Full TUI theme parity is deferred with TUI.

2. `compaction/branch summary strategy`
   - Branch summary and auto-compaction APIs exist.
   - Compaction summarization now uses reference-style serialized `<conversation>` prompts instead of direct conversation continuation.
   - Previous compaction summaries are passed through `<previous-summary>` and use an update prompt.
   - Split-turn prefix summaries and lightweight file operation summaries are covered.
   - Branch summaries now use the same serialized conversation path, reference-style branch preamble, and file operation details.
   - Entry-aware cut-point selection, previous-compaction boundary handling, and split-turn preparation are covered.
   - Summary quality harness is covered by `validate_summary_contract(...)` and `evaluate_summary_case(...)`: fixed sections, missing sections, leftover prompt placeholders, required phrases, and expected file-operation tags can now be checked consistently for compaction and branch summaries.
   - Remaining gap is running this harness against real model workloads and tuning prompts based on measured failures.

3. `runtime/store lifecycle stress`
   - Explicit index APIs are covered.
   - Opt-in runtime auto-refresh policy is covered.
   - Opt-in runtime debounce refresh policy is covered.
   - Opt-in delayed flush scheduler with coalescing/backpressure and dispose drain is covered.
   - Runtime rename/delete auto-refresh and store auxiliary-index failure resilience are covered.
   - Indexed query stale-cache healing is covered for externally deleted session files, including nested all-session indexes.
   - Runtime rename/delete failure diagnostics are covered.
   - Replacement callback failure paths are covered: replacement remains current, errors bubble, and runtime diagnostics record the failed callback.
   - Extension lifecycle failure observability is covered for `session_before_switch`, `session_before_fork`, and `session_shutdown`.
   - Import JSONL stress is covered across `session_before_switch` failure diagnostics, delayed index flush, same-basename collisions, copy-time destination races, failed-copy cleanup, and operation-failure diagnostics.
   - Remaining non-UI gap is narrower restore/import matrix coverage under rare OS-level permission races; interactive/TUI debounce tuning is deferred.

4. `package manager hardening`
   - Package root diagnostics and summaries are covered.
   - Local list UX is covered for direct package roots and plugin package roots, including settings scope projection.
   - Settings load warning projection is covered for package/plugin management commands.
   - Local source add-duplicate and remove-not-found error semantics are covered.
   - reference-style local CLI aliases for `list` / `install` / `remove` / `uninstall` are covered.
   - Version conflict projection is covered for local package listing.
   - Offline catalog projection is covered.
   - Remote install/update/remove/check lifecycle and failure projection are covered for headless MVP.
   - Python package install/update/check semantics are covered through `pypi:` sources rather than npm.
   - Active resource-plane package source merging is covered across project and user scopes.
   - Package identity dedupe covers project-over-user pinned version/ref conflicts.
   - Local relative source dedupe is scoped by settings base directory.
   - No explicit custom package signature verification has been confirmed in reference coding agent; remaining package trust work is optional hardening, not a reference parity blocker.

5. `interactive/TUI consumption`
   - Headless UI state now exists.
   - Real TUI rendering, autocomplete UI integration, and theme consumption remain deferred.

## Explicit Non-Alignment

- Provider/model config should not blindly align to reference implementation.
- Coding should continue to consume `loushang.ai` `models.json` and the Provider -> Endpoint -> Model layering.
- Python dict config may remain as a convenience input, but it should not become a reference-style flat provider compatibility contract.
