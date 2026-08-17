# KD-014: Tool Transcript Visual Styling

Tool transcript rows must stay readable as plain text while using color as a
secondary scanning aid. The visual styling layer is a presentation concern:
display records and tool projection still produce semantic plain text, and the
shared Harnesstui conversation styler applies theme tokens after transcript
lines are mapped to the product-facing prompt vocabulary.

## Scope

This design covers tool and activity transcript rows such as:

```text
• Ran git status --short --branch
  └ ## feat/tui-terminal-capabilities...origin/feat/tui-terminal-capabilities

• Ran bash git status took 0.60s
  └ ... (6 earlier lines)
     docs/product-definition-draft.md
    nothing added to commit but untracked files present (use "git add" to track)

• Explored
  └ Read theme.py
    Search transcript in src/loushang/tui
```

It does not change tool execution, output truncation, transcript caching, or
scrollback policy.

## Visual Rules

- The tool marker `•` uses the accent color and bold weight.
- Tool verbs such as `Ran`, `Explored`, `Edited`, and `Tested` use bold default
  foreground color.
- Header timing metadata such as `took 0.60s` uses dim neutral gray.
- Shell flags such as `-u`, `-m`, `--short`, and `--branch` use the accent
  color.
- Activity actions such as `Read` and `Search` use the accent color.
- Native coding tool bodies use a small rail: command detail rows start with
  `│`, and the first output row starts with `└`. Later output rows align under
  the output body instead of the tool header.
- Structural connectors such as `│`, `└`, `├`, `┌`, `┐`, `└`, and `┘` use dim
  neutral gray.
- Truncation metadata such as `… +4 lines`, `... (3 more lines)`,
  `... (3 hidden lines)`, and `(no output)` uses dim neutral gray.
- Tool timing metadata such as `Took 0.6s` and `Elapsed 250ms` uses dim neutral
  gray.
- If a tool command detail row duplicates the heading command, the native coding
  transcript hides the `$ ...` detail row.
- If a tool body ends with timing metadata that duplicates the heading elapsed
  time, the native coding transcript hides that body timing row.
- Git no-op summaries such as `nothing added to commit ...` use dim neutral
  gray.
- Normal command names, file names, paths, search text, and stdout keep the
  default foreground color.
- Failed tool markers use the error marker token instead of the normal accent
  token.

## Theme Tokens

The native coding transcript theme owns these tokens:

- `transcript.tool.marker`
- `transcript.tool.error_marker`
- `transcript.tool.verb`
- `transcript.tool.flag`
- `transcript.tool.action`
- `transcript.tool.connector`
- `transcript.tool.meta`
- `transcript.divider`

Default colors should use named ANSI colors so they degrade cleanly without
truecolor:

- Accent: `bright_cyan`
- Connector/meta/divider: `bright_black` with `dim`
- Error marker: `red` with `bold`
- Verb: `bold` with default foreground

## Rendering Boundary

`loushang.harnesstui.conversation.transcript_style` applies styling after
Coding's `_coding_line()` maps generic transcript rows into the native coding
vocabulary. Harnesstui owns semantic-span recognition and theme-token
application. Coding owns glyph and rail mapping, default theme values, path
compaction, and duplicate command/timing suppression. This preserves the
lower-level transcript renderer as a semantic renderer and avoids embedding
product-specific ANSI codes inside tool projection.

The styling function must preserve visible width. It may insert ANSI SGR
sequences only around already-rendered text segments. Plain text produced by
`strip_control_sequences()` must remain unchanged.

## Acceptance

- `• Ran git status --short --branch` strips to the same text.
- The bullet is accent-colored and bold.
- `Ran` is bold but keeps default foreground color.
- Header `took ...` metadata is dim gray.
- `--short` and `--branch` are accent-colored.
- `└`, `│`, truncation metadata, and `(no output)` are dim gray.
- Tool command detail rows render as `│ $ ...`, and the first output line
  renders as `└ ...`.
- Duplicate `$ ...` command detail rows are hidden when the heading already
  contains the same command.
- Duplicate body timing rows are hidden when the heading already contains
  elapsed timing.
- `Took ...`, `Elapsed ...`, and git no-op summaries render as dim gray when
  present.
- Worked dividers render with dim gray line styling.
- Cached transcript render keys include the theme signature so style changes do
  not reuse stale lines.
