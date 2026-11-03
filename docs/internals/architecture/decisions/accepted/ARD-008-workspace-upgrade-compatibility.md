# ARD-008: Preserve Workspace Compatibility Across Upgrades

## Status

- ID: ARD-008
- Scope: Loushang
- Authority: normative — accepted compatibility contract
- Design status: accepted
- Implementation status: partial
- Owner: Loushang architecture and Coding
- Acceptance: explicit Product owner instruction on 2026-10-15: existing
  workspaces must start normally and future releases must remain backward compatible.
- Method consultation: local archmethod `master`, commit
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`.

## Problem And Requirements

The ordinary Coding startup required a new Plugin store fence and refused any
unfenced workspace with prior settings, lifecycle journals or Package members.
Normal earlier use of built-in Plugins creates those members. Upgrading could
therefore prevent an otherwise valid workspace from starting.

`WS-COMPAT-001`: New releases must preserve ordinary startup and continued use
of valid existing workspaces, settings, Plugin choices and Session history.
An internal storage generation must not require users to replace their project,
clear their private home or delete previous state. Future storage changes must
provide a compatible reader/writer or a recoverable migration before replacing
the previous ordinary route. Internal generation names are not user decisions.

`WS-COMPAT-002`: Preserve one storage authority per operation. A published new
store fence must never cause fallback to an old writer, including when that
fence is corrupt or the new store fails to open. Existing permission, corruption,
concurrency and execution-admission checks remain applicable.

These requirements supersede the 2026-10-01 fresh-only ordinary-startup boundary
in the [PLC9 historical ledger](../../harness/plugin/plugin-experience-and-plc9-closure-design.md#accepted-pre-b-compatibility-boundary).
They inherit the [recovery and evolution principle](../../loushang-architecture-principles.md#8-default-for-long-horizon-recovery-and-evolution).

## Options And Decision

| Option | Compatibility | Consequences |
| --- | --- | --- |
| Keep fresh-only startup | Existing users lose ordinary startup | Violates WS-COMPAT-001 |
| Automatically convert every old store during startup | Requires complete settings, Source, desired-state and interrupted-migration recovery | The existing bounded adoption tools do not establish this general conversion contract |
| Retain the existing fence-aware storage owner for unfenced workspaces | Reuses existing readers, writers, Plugin management and runtime leases | Selected; keeps old state in place and requires continued compatibility maintenance |

Coding selects its existing compatible Session route when an unfenced workspace
has prior Plugin settings, lifecycle state or Package members. Detection reads
canonical and effective settings and accounts for effective in-memory overrides.
Fresh workspaces keep automatic Product initialization; fenced workspaces keep
their exact Product owner. Existing source-package CLI commands retain their
old route. Product Wheel installation and explicit fresh-only cutover remain
separate operations; this decision does not convert an old store or enable a
new Worker execution route.

Resume records which storage route was selected. For a compatible workspace it
observes the workspace identity, selected state/data roots and absence of a new
fence without writes. An external cutover invalidates that observation. This
fingerprint is a dependency check; the existing Plugin owner and its pre-fence
process registration still enforce actual execution and cutover exclusion.

## Review And Evidence

The implementing agent reviewed Coding startup, compatible Plugin ownership,
Package command selection and Resume observations under the delegated project
responsibilities. No Harness storage protocol or PR gate is changed.

- [Compatibility regressions](../../../../../tests/coding/test_workspace_storage_compatibility.py)
  cover the frozen v4 Package shape, repeated ordinary opening and preserved
  Transcript bytes, plus read-only Resume observation and cutover invalidation.
- [Selection and fresh-store regressions](../../../../../tests/coding/test_package_pre_b_snapshot.py)
  cover global/project/custom settings, old state and Package members, fresh
  initialization, interrupted bootstrap and existing fenced behavior.
- [Hosted Session tests](../../../../../tests/coding/test_hosted_session.py) and
  [Plugin lifecycle tests](../../../../../tests/coding/test_plugin_lifecycle.py)
  cover ordinary old settings and disabled Plugin behavior.
- [CLI tests](../../../../../tests/coding/test_cli.py) cover existing Package
  commands with old settings, preserving their original settings bytes.
- [Resume regressions](../../../../../tests/coding/test_runtime_resume_continuation.py)
  retain native epoch admission, ownership and recovery coverage.

Linux validation on 2026-10-15 passed 78 focused cases with one existing skip,
including real Resume preparation and delivery using compatible storage.
Both affected workspace data copies completed ordinary initialization with
seven active tools. The installed CLI also launched in both original directories
in real PTYs, reached the interactive model status, accepted local `/exit`, and
exited with code zero without a model request. All 144 CI consistency cases passed after updating only
the existing renamed Windows selectors; no trigger or check scope changed.
The CLI application's optional broad mypy run reports the same 45 diagnostics
as clean `main`; the two modified storage modules add no type diagnostics.
The broader module regression was interrupted during concurrent shard execution
on this single-CPU host. Its three identified failing cases all passed in
separate focused runs; no complete module-regression pass is claimed.

Native Windows execution needs
a Windows host; authoring equivalent assertions does not establish a native run.
General automatic conversion of arbitrary old stores remains unimplemented and
is not needed to continue using the compatible storage route.
