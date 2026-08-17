# Runtime And Event Dependency Direction

## Status

Implementation complete for `lane/harness`.

## Decision

Harness runtime/event/session packages form a directed acyclic graph:

```text
host (RPC, channel, mode adapters)
  -> session (Agent-session composition and projections)
       -> transcript (Agent transcript codecs and mechanics)
       -> runtime (execution, queue, retry, turn behavior)
       -> events (facts, envelopes, bus, generic projection)
  -> transcript
  -> events

transcript -> runtime -> events
transcript ----------> events
```

The ownership test is semantic:

| Owner | Owns |
| --- | --- |
| `events` | Immutable host/session facts, runtime envelopes, bus/publisher, generic selectors and JSON normalization |
| `runtime` | Host execution, queue ledger, turn orchestration, retry coordination, runtime snapshots |
| `transcript` | Agent message codecs, transcript persistence mechanics, compaction/navigation/catalog/export engines |
| `session` | Agent-session composition, typed session dictionaries, transport views, live-session export adapter |
| `host` | RPC/channel/mode adapters and adapter result values |

Event payload records do not import the runtime behavior that emits them.
Session-specific projections do not live in `events`, because they require
Agent message codecs and presentation/tool rendering. The live export adapter
does not live in `transcript`, because it consumes `SessionFacade`.

## Enforced Boundaries

- `events` must not import `runtime`, `transcript`, `session`, or `host`.
- `transcript` must not import `session` or `host`.
- `session` must not import `host`.
- Compatibility re-exports must not recreate a reverse edge.
- `tests/architecture/test_import_boundaries.py` computes strongly connected
  components across top-level Harness owners. It includes ordinary imports,
  imports under `TYPE_CHECKING`, and literal module targets in
  `_EXPORT_MODULES`.

This guard is intentionally broader than the files moved by this refactor: any
future Harness subpackage cycle fails architecture validation.
