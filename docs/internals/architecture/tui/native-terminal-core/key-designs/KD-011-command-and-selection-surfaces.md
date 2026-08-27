# KD-011: Command And Selection Surfaces

## Purpose

Define the interaction contract for transient command completion and product
selection surfaces, including slash command suggestions and model selection.
These surfaces are temporary input UI, not transcript content.

## Surface Classes

Two bottom-frame interaction classes share the same selection grammar:

- **Inline command completion** appears while the composer contains a slash
  command prefix such as `/`, `/c`, or `/q`.
- **Product selection surfaces** appear after a command opens a focused selector,
  such as `/model`.

The product adapter owns command semantics, model availability, descriptions,
and side effects. The TUI owns focus, visual selection, navigation, cancellation,
and terminal-stable rendering.

## Inline Slash Command Completion

Inline slash command completion stays attached to the live composer. It renders
below the composer input line and never creates transcript records.

Default shape:

```text
› /

> /model    choose model
  /quit     quit loushang
  /compact  compact conversation
```

Rules:

- The composer input line remains visible.
- Typing `/` immediately opens the slash command list.
- Typing a prefix such as `/c` filters the list by slash command prefix.
- There is exactly one blank row between the composer input line and the first
  suggestion row.
- No group header such as `Commands` is shown.
- No `->` marker is used.
- The selection marker is `>` in a fixed gutter.
- Unselected rows use the same fixed gutter with a blank marker cell.
- The marker does not shift the command column. Selected and unselected rows
  align command labels and descriptions at the same columns.
- The default visible candidate count is at most 8 items.
- Candidate rows are visually indented by the fixed gutter. The command label
  starts at the same column for selected and unselected rows.
- Command labels and descriptions are column-aligned. Descriptions begin at a
  fixed column derived from the visible command label width.
- The selected row is bold and uses the active selection color across both the
  command label and description.
- `Up` and `Down` move the highlighted item without modifying composer text.
- `Tab` applies the highlighted completion without submitting.
- `Enter` applies and submits the highlighted slash command.
- `Esc` closes completion and preserves the current composer text.
- Completion is part of the current bottom UI. It must not be appended to
  terminal scrollback as historical transcript content.
- While completion is open, the ordinary status row is hidden. It returns after
  completion closes.
- Completion close must release the suggestion rows immediately. The render
  loop clears the stale rows and keeps its cursor estimate synchronized while
  the ordinary separator and status rows return.
- When `/quit` or another exit command is submitted, the runtime must clean the
  current completion/status area so the shell prompt starts on a clean new line.

## Model Selection Surface

Model selection is a focused selection surface, not inline completion. It
captures input and replaces the ordinary composer/status bottom frame while it
is active.

Default shape:

```text
Select Model and Effort
Access legacy models by running loushang --model <model_name> or in your config.

> 1. moonshot/kimi-for-coding (current)  Coding-focused model.
  2. moonshot/kimi-k2-thinking          Reasoning model.
  3. openai/gpt-5                       General coding model.

Press enter to confirm or esc to go back
```

Rules:

- The focused selector must not render the live composer input row underneath.
- The focused selector must not render the ordinary status row underneath.
- The hint line belongs to the surface and replaces composer/status help while
  the surface is active.
- The title is `Select Model and Effort` when effort selection is part of the
  surface. If only models are supported, the title may be `Select Model`.
- A short secondary line may explain legacy or manual model access.
- The item rows use a fixed marker gutter followed by a left-aligned ordinal.
- Ordinals use Arabic numerals with a dot, e.g. `1.`, `2.`, `10.`. The ordinal
  column is left-aligned within the list's ordinal width.
- The `>` marker does not shift the ordinal column. Selected and unselected rows
  align ordinals, model names, current markers, and descriptions at the same
  columns.
- The selected row is bold and uses the active selection color across the full
  row, including ordinal, model name, current marker, and description.
- The current model marker is `(current)` after the model name.
- No `Models` header is shown.
- No `->` marker is used.
- No pagination footer such as `(1/15)` is shown by default. If the list is
  longer than the available height, the surface scrolls internally and may show
  a subtle scroll affordance only when it does not compete with the confirmation
  hint.
- The confirmation hint is `Press enter to confirm or esc to go back`.
- The confirmation hint aligns with item content, not with the selection marker
  gutter.
- `Enter` selects the highlighted model and emits a product intent.
- `Esc` closes the selector and returns focus to the composer without submitting
  composer text.
- `Up` and `Down` move the highlighted item.
- If the product exposes a scoped model list, the selector opens in `scoped`
  mode and shows a scope row such as `Scope: scoped | all` above the items.
- `Tab` toggles between `scoped` and `all` model lists when scoped models are
  available.
- The active scope label is bold and uses the active selection color. The scope
  row is selector chrome, not an item row, and does not change the ordinal
  alignment of model items.
- Scope changes preserve the active search query and reapply it to the new
  model list.

## Layout Contract

Inline completion and focused selection surfaces have different bottom-frame
ownership:

- Inline completion is part of the composer region. The composer remains focused
  and visible.
- Focused product selection uses the formal `bottom-exclusive` surface
  presentation. The composer and status rows are suppressed while the surface is
  active.
- Non-exclusive bottom surfaces use `bottom` and may coexist with ordinary
  composer/status rows.

Neither surface may append historical rows to terminal scrollback while the user
is navigating. Updates are in-place logical screen updates controlled by the
render loop.

Closing either surface must leave the terminal cursor anchored to the active
composer or next focused surface. A shrink in the logical line count must not
leave the render loop's hardware cursor estimate below the actual terminal
cursor; otherwise the next key event can rewrite the status area.

## Theme Tokens

Implementations should expose theme tokens for:

- selected row foreground/accent color
- selected row bold emphasis
- secondary description text
- hint text

When no theme is configured, selected rows should remain readable on ordinary
light and dark terminal palettes. Bold is part of the selected state, not a
replacement for the selection color.

## Test Obligations

- `/` renders command suggestions without a `Commands` header.
- `/` renders exactly one blank line before suggestions.
- `/` opens the command list immediately.
- `/c` filters suggestions by command prefix.
- slash completion shows at most 8 visible candidates by default.
- command suggestion rows use `>` rather than `->`.
- command suggestion rows align command labels and descriptions.
- selected command rows are bold and colored across command and description.
- `Enter` executes the highlighted slash command.
- `Tab` applies the highlighted slash command without submitting.
- `Esc` closes completion while preserving composer text.
- `Up` and `Down` move selection without changing composer text.
- slash completion hides ordinary status and restores it after close.
- slash completion updates in place and does not enter scrollback history.
- slash completion exit commands leave the shell prompt on a clean line.
- closing inline completion releases its rows and leaves the cursor on the
  composer.
- model selection suppresses ordinary composer and status rows.
- model selection uses `>` without shifting ordinal/content columns.
- model selection aligns ordinals, model names, current markers, descriptions,
  and confirmation hint.
- selected model rows are bold and colored across the whole row.
- model selection defaults to scoped models when scoped models are available.
- model selection `Tab` toggles between scoped and all models.
- model selection preserves active search text across scope changes.
- `Enter` selects the highlighted model.
- `Esc` returns from model selection to the composer.
- render-loop shrink handling keeps hardware cursor diagnostics synchronized
  with the actual terminal cursor after stale rows are cleared.
