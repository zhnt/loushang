# Explicit Model Selection During Resume

## Status And Review Frame

- Authority: descriptive — review evidence
- Design status: not-applicable
- Implementation status: complete
- Owner: Loushang architecture; Coding and Harness session integration
- Tracking: [#949](https://github.com/zhnt/loushang/issues/949)
- Reviewed baseline: `51c3bd1bdc354e1812880d8f950a9fc201414d27`
- Reviewed implementation: wheel SHA-256
  `55e2515b7dcf182059ab530105e1194b2471554ff9edb1597adc9660cc37b864`
- Reviewer and accepting role: Codex, acting as the implementation agent for
  Coding/Harness integration, 2026-11-27
- Local method revision: `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`

## Current Contract

Coding CLI passes an explicit model selection into session construction before
the transcript context is installed. The Coding factory forwards the resolved
model through `initial_model_override` to the Harness Agent Product adapter.
That override applies only to initial context installation. Branch navigation
and resource refresh continue to resolve the selected branch's recorded model.

The CLI's existing post-resolution model operation records the replacement in
the transcript and persists the configured default. Transcript messages and
session identity remain intact. An absent override retains saved-model
restoration; an unavailable saved model still requires an explicit replacement.
An unavailable replacement produces a selection-specific error and does not
fall back to another provider. Opaque provider compaction checkpoints still
require their original model route.

## Findings And Disposition

| Finding | Disposition and evidence |
| --- | --- |
| CLI model selection ran after construction had already rejected an unavailable saved model | Selection now reaches construction; real CLI regressions cover `--resume`, `--session`, and `--continue`, with both removed and available saved models. |
| Moving selection earlier exposed an uncaught catalog `KeyError` | Shared explicit-model resolution reports a `ValueError` naming the selection; unit and real CLI failure tests verify no fallback. |
| An override must not bypass checkpoint compatibility or rewrite failed history | The original checkpoint guard remains before context installation; CLI failure cases verify unchanged transcript bytes. |
| Model replacement must survive the next restart | Success cases reload the persisted transcript and verify the replacement model record and retained messages. |

## Acceptance And Evidence Limits

Accepted within the delegated Coding/Harness integration scope. This extends
the existing construction inputs and retains the existing model catalog,
transcript selection operation, lifecycle, and checkpoint owners; it adds no
runtime component, storage schema, or provider alias migration.

Focused CLI, Coding runtime/context, Harness session, and CLI configuration
regressions: 826 passed, 7 skipped. Ruff and generated package dependency checks
passed. The touched CLI application has 45 pre-existing mypy errors, also
present at the reviewed baseline; the other five changed source modules passed
the focused mypy invocation. These results do not claim the complete
`check-changed` plan, cross-platform, hosted client, or live-provider validation.

A read-only check of an existing persisted history reproduced the saved-model
failure without an override and successfully installed its context with the
replacement. Source size and modification time were unchanged. The installed
wheel was compared against the previous installation: only the six reviewed
source modules differ; dependencies were retained.

Automatic model replacement and a recovery picker for unavailable saved models
without an explicit choice remain follow-up work. This change enables the
existing explicit CLI recovery command while preserving the recorded history.
