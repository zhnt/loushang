# Coding Conversation Adapter Extinction

This wave removes reusable conversation presentation mechanics from
`loushang.coding` without creating a second HarnessTUI application or
projection engine.

## Ownership

| Source region | Existing shared owner | Coding injection |
| --- | --- | --- |
| normalized session-event ordering, message/tool lifecycle, retry and compaction projection | `harnesstui.conversation.projection` | Agent tool-result extraction and Product visibility choices |
| queue normalization | `harnesstui.conversation.runtime_view` | explicit Session queue sources |
| tool call/result mapping, transcript state, standard workspace verbs and body visibility | `harnesstui.conversation.tool_transcript` | Agent tool-result content/details and optional Product renderer |
| standard Agent transcript kind filtering and terminal-record projection | `harnesstui.conversation.history` | persisted-session acquisition and tool projection binding |
| abort/follow-up/steer/local/dispatch routing | `harnesstui.conversation.host` | Coding intent parser, local-action map and command catalog |
| plain and screen target behavior | existing `harnesstui.conversation.plain_target` and `.screen_target` | title, glyphs, status copy, theme, tool display and final wording |

HarnessTUI remains independent of `loushang.agent`, `loushang.ai`, and every
Product package. Agent-shaped values are consumed structurally or through
callbacks supplied by the Product binding.

## Reuse Rules

- Extend the existing `ConversationProjector`,
  `ToolTranscriptProjectionBinding`, `ConversationHistoryProjector`, and
  `ConversationHostProfile`; do not add synonymous projector, controller,
  runtime, or application classes.
- Reuse `stable_string_queue_reader` and the existing projection targets; do
  not create a second queue adapter or plain/screen event engine.
- Keep raw Agent construction and model types outside HarnessTUI.
- Keep terminal rendering primitives in `loushang.tui`.
- Delete a Coding implementation after its production consumers use the shared
  owner. Do not leave a re-export compatibility facade.

## Deletion Conditions

- `coding.presentation.tui.events` is absent.
- Standard event sequencing is tested under HarnessTUI with no Coding import.
- Coding tool transcript code contains only Agent result adaptation and
  Product presentation callbacks.
- Coding history code contains only persisted-session acquisition and binding
  to the standard shared history projector.
- Coding interaction code contains intent/action declarations and a builder
  that binds them to `ConversationRoutingProfile`; it owns no routing state
  machine.
- Existing Coding plain, screen, playback, PTY, and transcript tests preserve
  behavior.
