# Foundation Phase 0 Inventory

## Status

Recorded baseline for the proposed Foundation refactor. The inventory was
captured from commit `3b01a233` for issue #426. It describes current ownership
and compatibility obligations; it does not make the target package accepted
architecture.

## Current Package Inventory

`loushang.protocol` contains:

```text
__init__.py
json_value.py
```

Its root public surface is:

```text
JSONPrimitive
JSONValue
JsonValueError
dump_json_value
require_json_mapping
require_json_value
```

`loushang.observability` contains:

```text
__init__.py
_time.py
context.py
debug_log.py
logger.py
problem.py
problem_text.py
runtime.py
runtime_identity.py
sinks.py
trace.py
```

Its root public surface is frozen by
`tests/observability/test_public_api.py`. The current root exports 35 names,
including records, logger/context APIs, router configuration, concrete sinks,
runtime binding, runtime identity, and Problem text helpers. The target
Foundation surface may be narrower, but the old root must continue forwarding
all of these names during compatibility.

## Production Consumer Counts

The scan covers Python files below `src/loushang`, excluding the current
packages' relative internal imports.

| Subsystem | Protocol | Observability |
|---|---:|---:|
| Agent | 4 | 1 |
| AI | 2 | 7 |
| Channel | 2 | 0 |
| Coding | 1 | 4 |
| Harness | 30 | 5 |
| HarnessTUI | 1 | 0 |
| HarnessWork | 2 | 0 |
| Ontology | 1 | 0 |
| TUI | 0 | 1 |
| Total | 43 | 18 |

`src/loushang/agent/agent_loop.py` is the only file importing both packages,
so the union is 60 production files.

## Direct Submodule Imports

All 43 Protocol consumers import from `loushang.protocol`; no production file
directly imports `loushang.protocol.json_value`. The submodule remains a
compatibility path because it is importable today.

The following production files bypass the Observability root:

| Import path | Production consumers |
|---|---|
| `loushang.observability.problem` | `ai/errors.py`, `ai/auth/support.py`, `ai/event_stream/raw_parts.py`, `ai/provider/errors.py`, `ai/structured.py`, `ai/trace.py` |
| `loushang.observability.problem_text` | `coding/diagnostics/debug_status.py` |

Repository tests also directly exercise these compatibility paths:

```text
loushang.observability.debug_log
loushang.observability.problem
loushang.observability.runtime_identity
loushang.observability.trace
```

All current non-private Observability modules are included in the
forwarding-path contract even when no production caller currently bypasses the
root. The private `_time` module is not a compatibility path. This prevents a
mechanical package move from breaking an importable repository-local module
without promoting a private helper to public API.

No Python file under `examples/` directly imports either package. Documentation
mentions both ownership paths, primarily in the live architecture overview,
subsystem description, Channel/Harness boundary documents, and the Foundation
refactor plan. External downstream imports cannot be inferred from the
repository and therefore remain a compatibility-release concern.

## Frozen Behavior

The Phase 0 characterization suite records:

- strict JSON copying, exact-container policy, path reporting, cycle rejection,
  finite floats, valid UTF-8 strings, integer encoder bounds, mapping validation,
  and deterministic dumping;
- diagnostic projection of tuples and general `Mapping` implementations,
  rejection of unknown objects and non-finite floats, and the current scalar
  subclass and invalid-surrogate behavior;
- exact `ProblemRecord` and `DebugEventRecord` dictionary shapes;
- exact Problem/debug text output and Trace JSONL fallback/output shape;
- ContextVar nesting, restoration, and copied-context isolation;
- scope filtering, best-effort sink failure isolation, configuration
  capture/restore/reset, and ProblemStore identity; and
- current root exports and direct submodule importability.

These tests freeze behavior for the ownership move. They do not promote every
edge behavior into a permanent API promise; semantic tightening remains a
separate change after the compatibility migration.
