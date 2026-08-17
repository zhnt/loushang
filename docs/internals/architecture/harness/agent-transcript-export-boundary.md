# Agent Transcript Export Boundary

## Status

Implementation complete for integration into `lane/harness` on
`harness/agent-transcript-export`.

## Decision

`loushang.harness.transcript.export` owns portable export of the current
Native Agent transcript profile:

- standalone JSONL export of a selected branch, with parent links linearized;
- self-contained HTML document composition, Conversation JSONL header/record
  encoding, transcript tree, standard transcript-kind rendering, ANSI and
  Markdown rendering, and default tool-call/result presentation;
- `TranscriptExportRequest`, the strict snapshot contract between a live
  Product session and the exporter;
- `TranscriptHtmlExportProfile`, which binds Product-owned theme,
  custom-application-message renderer, and tool-definition renderer.

This is an optional Agent/AI profile. `harness.conversation` remains neutral
and does not import Agent or AI types. The export runtime may consume stable
Agent message values and the existing Harness tool-presentation contract, but
does not call models, discover providers, resolve authentication, or open a
Product store.

## Binding Contract

A Product first creates an immutable `TranscriptExportRequest` from its active
transcript state. The request contains the current header, all records, the
selected branch, leaf, context messages, serializable statistics, system prompt,
tool metadata, and an output-safe working directory. Harness then owns file
writing and document encoding.

The Product supplies a `TranscriptHtmlExportProfile` only where it has real
semantics:

- visual theme values;
- custom application-message renderer;
- product tool-definition resolver;
- destination selection and product command/API projection.

This keeps an export runnable for another Product without an `AgentSession`,
`SessionManager`, Coding extension, or Coding tool implementation. A Product
may omit all hooks and receive the standard HTML document and fallback tool
rendering.

## Session Adapter

`loushang.harness.session.export` is the live-session adapter. It selects
default filenames, gathers a `SessionFacade` snapshot, and passes the bound
theme, extension message renderer, and tool resolver as profile hooks.
`loushang.harness.transcript.export` remains independent of
`harness.session` and owns JSONL encoding, HTML assets, record-kind disposition
tables, ANSI/Markdown conversion, transcript-tree rendering, and default
tool-result markup. Coding inherits the standard session methods and retains
only its command/API presentation.

The prior `coding.session.export_html` package and
`coding.session.export_jsonl` implementation have been removed. This is an
internal ownership cutover, not a legacy exporter compatibility layer.

## Non-goals

This boundary does not define Product artifact schemas, a generic reporting
product, web hosting, channel transport, PDF/PPT export, Product-specific
themes, or extension renderer contracts. `loushang.channel` remains responsible
for transport hosts; file export belongs with the optional transcript profile.

## Verification

- Harness tests build both HTML and JSONL exports from a transcript snapshot
  with no Coding imports.
- Coding export tests exercise its adapter, extension renderer, theme, branch,
  tool, and output-path behavior through the shared runtime.
- Import-boundary tests require the export runtime to remain Coding-free and
  prohibit restoration of the removed private Coding exporters.
