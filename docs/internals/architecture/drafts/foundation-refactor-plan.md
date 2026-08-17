# Foundation Refactor Plan

## Status

Completed. Phases 0 through 6 are implemented. `loushang.foundation.json` is
the sole strict JSON owner; `records`, `projection`, and `_router` own the
canonical Observability internals; every production consumer uses Foundation;
and the former top-level Protocol and Observability compatibility packages are
retired. `ai.structured` uses strict schema validation, while diagnostic
projection remains an explicitly separate policy.

The refactor is intentionally limited to package ownership, dependency
direction, API clarity, and compatibility. It does not add new logging,
telemetry, serialization, or runtime features.

## Decision Summary

The two former product-neutral, standard-library-only substrate packages were
consolidated under one level-two package:

```text
loushang.protocol       --\
                           >-- loushang.foundation
loushang.observability  --/
```

The target has two cohesive capability areas:

```text
loushang.foundation.json
loushang.foundation.observability
```

`foundation.json.JSONValue` is the single authoritative JSON value algebra.
Observability reuses that type but retains an explicitly named diagnostic
projection policy. Unifying type ownership does not mean making strict wire
validation, diagnostic normalization, and trace-sink fallback behave alike.

The target package is a shared substrate, not a new orchestration layer:

```text
AI / Agent / Channel / Harness / HarnessWork / Method / Ontology / Products
                                  |
                                  v
                         loushang.foundation
                                  |
                                  v
                           Python standard library
```

Foundation must not depend on any other `loushang` level-two package. It must
not be moved into Harness because AI, Agent, Channel, and other lower or sibling
packages already need these contracts independently.

## Why Consolidate

The former packages had the same architectural position but exposed that
position inconsistently:

- `loushang.protocol` owned only the strict JSON value algebra; the
  package name is broader than its implemented responsibility.
- `loushang.observability` was also a standard-library-only substrate consumed
  by AI, Agent, Harness, Coding, and TUI.
- both packages are valid dependencies of several level-two subsystems and
  therefore belong below, rather than inside, any one of them.
- Observability declared a second structural `JSONValue` alias,
  which makes ownership unclear even though callers should see one JSON value
  type.

At the Phase 0 baseline, 60 production files directly imported one or both
former packages: 43 imported `loushang.protocol` and 18 imported
`loushang.observability`, with one file importing both. This breadth requires
a compatibility-first migration rather than a repository-wide rename in one
change.

## JSON Semantics

### One Value Algebra

The only canonical definitions will be:

```python
from loushang.foundation.json import JSONPrimitive, JSONValue
```

`JSONPrimitive` and `JSONValue` remain descriptive structural aliases. They
will not be renamed to `LSJsonValue` or `LSJsonPrimitive`: the package path
already establishes ownership, and a brand prefix would imply a distinct JSON
format or nominal runtime type that does not exist.

### More Than One Ingress Policy

The Phase 0 code contained three different behaviors:

| Policy | Phase 0 owner | Purpose | Tuple | Unknown object | Non-finite float |
|---|---|---|---|---|---|
| strict JSON validation | `protocol.json_value` | wire, schema, event, journal, persistence | reject | reject | reject |
| diagnostic projection | `observability.problem` | Problem, log, and debug details | convert to list | reject | reject |
| trace-sink fallback | `observability.trace` | best-effort JSONL output | convert to list | stringify | stringify |

The target makes these policies explicit:

```python
from loushang.foundation.json import require_json_value
from loushang.foundation.observability.projection import (
    project_diagnostic_value,
)
```

- `require_json_value()` remains strict, validates and copies the JSON value,
  and is the default for wire and persistent boundaries.
- `project_diagnostic_value()` performs a deliberately limited normalization
  for diagnostic data and returns the same canonical `JSONValue`.
- trace fallback remains private to `trace_sink.py` during the compatibility
  migration. It is not a third public JSON API.

The first migration must preserve current behavior. Tightening enum,
container-subclass, cycle, invalid-surrogate, large-integer, or arbitrary
stringification behavior is a separate semantic change after characterization.

### Semantic Routing Rule

Callers choose a policy by the meaning of the boundary, not by selecting a
different JSON type:

| Caller responsibility | Required API |
|---|---|
| Channel/RPC envelope | strict `foundation.json` |
| event, journal, transcript, snapshot | strict `foundation.json` |
| tool output and structured-output schema | strict `foundation.json` |
| Problem details and debug/log data | diagnostic projection |
| human-readable rendering | an Observability formatter or sink |

In particular, `ai.structured` currently uses the Observability diagnostic
normalizer for JSON Schema. Its target is strict
`foundation.json.require_json_mapping()`, but that semantic correction must be
made in a dedicated migration step rather than hidden inside file movement.

## Target Package Structure

```text
src/loushang/foundation/
├── __init__.py
├── json.py
└── observability/
    ├── __init__.py
    ├── context.py
    ├── records.py
    ├── projection.py
    ├── logger.py
    ├── _router.py
    ├── debug_sink.py
    ├── trace_sink.py
    ├── runtime.py
    ├── identity.py
    ├── problem_text.py
    └── _time.py
```

Do not add an `observability/sinks/` package while only two concrete sink
implementations exist. Do not add generic `utils`, `common`, `types`, or
top-level `runtime` packages.

### `foundation.__init__`

The Foundation root is deliberately minimal. Importing
`loushang.foundation.json` causes Python to execute `foundation.__init__`, so
the root must not import Observability or initialize its process state.

New code imports the owning module explicitly:

```python
from loushang.foundation.json import JSONValue
from loushang.foundation.observability import get_log
```

### `foundation.json`

Owns the strict JSON value contract:

```text
JSONPrimitive
JSONValue
JsonValueError
require_json_value()
require_json_mapping()
dump_json_value()
```

The module depends only on the Python standard library. Internally, it should
import the standard-library module as `json` or `stdlib_json`; callers always
use the fully qualified `loushang.foundation.json` path.

### `observability.context`

Owns correlation context only:

```text
LogContext
current_context()
log_context()
```

It does not emit records, own sinks, or perform runtime setup.

### `observability.records`

Owns stable structured observation records:

```text
ProblemSeverity
ProblemRecord
DebugEventRecord
```

Moving `DebugEventRecord` out of the current `sinks.py` is required so concrete
sinks can consume records without depending on the router and its global
state. All record fields use `foundation.json.JSONValue`.

### `observability.projection`

Owns diagnostic input normalization:

```text
project_diagnostic_value()
project_diagnostic_mapping()
```

Projection is a policy boundary, not a record model and not an alternative
JSON algebra. The name must communicate that conversion may occur.

### `observability.logger`

Owns the application-facing emission facade:

```text
ObservabilityLog
get_log()
```

It reads context, projects diagnostic details, constructs records, and submits
them to the router. It does not open files or own configuration.

### `observability._router`

Owns the single process-local Observability state and fan-out path:

```text
sink protocols
InMemoryProblemStore
configuration capture/restore/reset
scope filtering
emit_log(), emit_problem(), emit_debug_event()
best-effort sink failure isolation
```

The leading underscore marks the routing machinery as an implementation
boundary. Normal callers must use `logger`; runtime integration uses selected
configuration functions. This refactor does not declare a new public custom
sink extension API.

Explicit integration code may import `InMemoryProblemStore` and
`get_problem_store()` from `_router`. The canonical router is the only owner of
the lock, configuration, scopes, and store; the root API stays deliberately
small.

### `observability.debug_sink`

Owns `DebugLogSink`, the human-readable rotating text-file sink. “Debug” here
describes the product debug log and does not mean it accepts only debug-level
messages. It is diagnostic output, not an authoritative event store.

### `observability.trace_sink`

Owns `TraceJSONLSink`, the structured rotating JSONL sink. It writes already
normalized observation records. Any best-effort payload fallback remains a
private, bounded sink concern during migration.

### `observability.runtime`

Owns Observability host-lifecycle composition:

```text
temporary context and sink binding
configuration capture and restoration
debug/trace file enabling and disabling
scope parsing needed by that binding
```

The module must not become a generic Foundation runtime. Current helpers such
as argument/environment lookup, path selection, and session-log labels may move
unchanged during the mechanical migration, but remain boundary-calibration
candidates. Product- or CLI-specific policy should ultimately live in the
Harness/Product adapter that consumes Foundation.

### `observability.identity`

Owns diagnostic runtime-environment identity collection and formatting. It is
the target of the former `runtime_identity.py`; the enclosing Observability
package makes the shorter name unambiguous.

`identity.py` depends only on the standard library and must not depend on
logger, router, runtime, Harness, authentication, Agent identity, or user
identity concepts.

### `observability.problem_text`

Temporarily owns current Problem text reading and formatting. It is not
re-exported from the new canonical `observability.__init__` initially. Current
usage is narrow, so its long-term placement in Foundation versus a
Harness/Product presentation adapter remains a bounded follow-up decision.

### `observability._time`

Owns private wall-clock and monotonic-clock helpers shared by record emission
and sinks. It is not public API.

## Internal Dependency Direction

The target dependency graph is:

```text
foundation.json
  -> no Foundation dependency

observability.context
observability.records       -> foundation.json
observability.projection    -> foundation.json
observability._time

observability._router       -> context + records
observability.logger        -> context + records + projection + _router + _time
observability.debug_sink    -> context + records + foundation.json + _time
observability.trace_sink    -> records + foundation.json
observability.runtime       -> context + _router + concrete sinks
observability.problem_text  -> records
observability.identity      -> standard library only
```

Mandatory rules:

- `_router` does not import `logger`, `runtime`, or a concrete sink.
- concrete sinks do not import `_router` merely to obtain record types.
- `json` does not import Observability.
- `identity` remains independent of Observability process state.
- no Foundation module imports another `loushang` level-two package.

## Public API Policy

### Canonical Imports

Ordinary callers use:

```python
from loushang.foundation.json import JSONValue, require_json_value
from loushang.foundation.observability import get_log, log_context
```

Explicit integration code may use:

```python
from loushang.foundation.observability.records import ProblemRecord
from loushang.foundation.observability.runtime import (
    observability_runtime_context,
)
from loushang.foundation.observability.identity import collect_runtime_identity
```

Diagnostic projection remains visibly exceptional:

```python
from loushang.foundation.observability.projection import (
    project_diagnostic_mapping,
)
```

### Root Exports

The new `foundation.observability.__init__` should initially export only the
stable daily surface:

```text
get_log
ObservabilityLog
log_context
LogContext
ProblemRecord
ProblemSeverity
```

It must not export `JSONValue`; callers obtain that type from
`foundation.json`. Runtime setup, identity, text formatting, and concrete sinks
remain explicit leaf-module imports.

The retired compatibility root's former wide surface was not copied into the
canonical package.

## Foundation Admission Rule

A capability may enter Foundation only when all conditions hold:

1. multiple level-two subsystems need it or its placement is required to keep
   the dependency graph acyclic;
2. it has a stable, product-neutral contract and a clear long-term owner;
3. it depends only on the standard library and Foundation's lower modules;
4. it does not own Product policy, workflow, authoritative Work facts, Agent
   orchestration, provider behavior, UI presentation, or domain semantics; and
5. an import-boundary test can express and enforce its dependency direction.

Reuse by two callers is not sufficient by itself. Helpers without a durable
contract remain with their current semantic owner. Do not create `utils`,
`common`, or a generic Foundation `runtime` namespace.

## Adjacent Boundaries

### HarnessWork EventLog

HarnessWork EventLog records authoritative Work operations and events with
ordering, query, subscription, and replay semantics. It is not Observability,
must not move into Foundation, and must continue using strict JSON boundaries.

### Harness Diagnostics

Harness Diagnostics owns Session/Product diagnostic policy, storage, query,
deduplication, export, and presentation semantics. It may adapt a Foundation
`ProblemRecord`, but Foundation must not import Harness or absorb those
policies.

### AI Trace

AI Trace owns provider-event selection, redaction, summarization, and semantic
projection. Foundation `TraceJSONLSink` only writes normalized observation
records. Moving the sink does not move provider trace policy into Foundation.

### Journal, Transcript, and Channel

These are authoritative or boundary-facing data paths. They use strict
`foundation.json`, never diagnostic projection or trace fallback.

## Compatibility Retirement Outcome

Temporary forwarding packages preserved symbol identity, exception identity,
the single ContextVar/router state, and existing JSON/log/trace wire shapes
during the ownership migration. After all repository consumers adopted the
canonical paths, the forwarding packages and their compatibility-only tests
were removed. Architecture tests now reject any import that reintroduces
`loushang.protocol` or `loushang.observability`.

## Migration Plan

### Phase 0: Freeze Behavior and Inventory

Status: complete.

Before moving files:

1. record the complete public symbol and direct-submodule import inventory;
2. run the current Protocol and Observability suites as a baseline;
3. add characterization coverage for strict JSON edge cases;
4. characterize diagnostic tuple/Mapping conversion and failure behavior;
5. characterize trace fallback and exact JSONL/text output;
6. cover context isolation, sink scope filtering, sink failure isolation, and
   configuration capture/restore/reset; and
7. identify external examples, plugins, and documentation that use old paths.

Characterization tests protect the mechanical migration. They do not make
every accidental edge behavior a permanent architectural promise.

### Phase 1: Establish `foundation.json`

Status: complete.

1. create a minimal `loushang.foundation` root;
2. move the strict JSON implementation to `foundation/json.py` without changing
   behavior;
3. make `loushang.protocol` and `loushang.protocol.json_value` pure forwarding
   modules;
4. verify old/new `JsonValueError` identity and strict behavior; and
5. add a gate proving that importing `foundation.json` does not load
   `foundation.observability`.

Do not migrate all consumers in this phase.

### Phase 2: Establish Canonical Observability Without Restructuring

Status: complete.

Move the current implementation under `foundation/observability` using its
existing internal file structure first:

```text
context.py
problem.py
logger.py
sinks.py
debug_log.py
trace.py
runtime.py
runtime_identity.py
problem_text.py
_time.py
```

Then:

1. change its duplicate JSON aliases to imports from `foundation.json`;
2. install pure forwarding modules for every old Observability path;
3. verify class identity, ContextVar identity, and single router state; and
4. preserve log, Problem, Trace, and runtime behavior exactly.

This phase deliberately separates package ownership movement from module
splitting.

### Phase 3: Restructure Canonical Observability

Implementation status: complete. `records.py`, `projection.py`, and `_router.py`
own their focused responsibilities; compatibility-only `problem.py` and
`sinks.py` are removed; and the concrete modules use the canonical
`debug_sink.py`, `trace_sink.py`, and `identity.py` names.

With callers still protected by compatibility facades, split and rename only
inside the canonical package:

```text
problem.py          -> records.py + projection.py
sinks.py            -> records.py + _router.py
debug_log.py        -> debug_sink.py
trace.py            -> trace_sink.py
runtime_identity.py -> identity.py
```

Keep `context.py`, `logger.py`, `runtime.py`, `problem_text.py`, and `_time.py`.
Update relative imports and repeat state-identity and output-format tests after
each small move.

The public diagnostic APIs are `project_diagnostic_value()` and
`project_diagnostic_mapping()`; the migration-only names are retired.

### Phase 4: Migrate Consumers by Semantics

Implementation status: complete. All production imports use canonical
Foundation paths, including the dedicated strict `ai.structured` schema
change.

Migrate production callers in narrow batches:

1. type-only imports move directly to `foundation.json.JSONValue`;
2. AI, Agent, Channel, Harness, HarnessWork, and Ontology wire/persistence paths
   move to strict `foundation.json`;
3. logger users move to `foundation.observability`;
4. Problem and debug detail producers move to explicit diagnostic projection;
5. `ai.structured` receives a dedicated strict-schema conversion change; and
6. Coding/Harness runtime adapters move to explicit Observability leaf modules.

Each batch should leave compatibility facades intact, pass focused tests, and
be independently revertible.

### Phase 5: Update Live Architecture and Gates

Status: complete. Live architecture names Foundation as the owner, enforces its
standard-library-only dependency direction, and rejects retired imports.

After canonical imports are adopted:

1. replace the two level-two package entries with `loushang.foundation` in the
   architecture overview and subsystem documentation;
2. update documents that currently state that `loushang.protocol` owns
   `JSONValue`;
3. document diagnostic projection as a canonical policy rather than a JSON
   ownership compatibility exception;
4. add Foundation standard-library-only and no-upward-dependency tests;
5. prohibit new production imports from old packages; and
6. require explicit allowlisting only for the forwarding modules themselves.

Do not weaken existing architecture gates by adding broad transitional
allowlists. Use a ratchet that can only reduce old imports.

### Phase 6: Retire Compatibility Separately

Status: complete. Retirement was performed after canonical ownership and
consumer migrations had landed, as a separately tracked final phase.

Compatibility deletion is not part of the ownership migration. Remove the old
packages only after:

- production, tests, examples, documentation, and known integrations no longer
  use them;
- the no-new-import gate has held across integration;
- downstream compatibility requirements have been checked; and
- release notes identify the canonical replacement paths.

Delete the compatibility facades in a separate, reviewable change.

## Verification Gates

### Import and Ownership Gates

- Foundation imports only the standard library and its own relative modules.
- `foundation.json` import does not load Observability modules or state.
- `_router` does not import concrete sinks, logger, or runtime.
- concrete sinks import record types from `records`, not `_router`.
- no production caller imports old paths after its migration phase.
- retired namespaces have no Python modules and no source, test, example, or
  script imports.

### Behavior Gates

- strict JSON validation retains copying, path reporting, cycle detection,
  UTF-8 validation, finite-float checks, integer bounds, and exact-container
  behavior;
- diagnostic projection retains the explicitly accepted normalization behavior;
- Problem and DebugEvent dictionary shapes do not change;
- debug text and trace JSONL formats do not change;
- sink failures remain isolated from application behavior;
- capture/restore/reset and scope filtering preserve behavior; and
- one canonical ContextVar, router configuration, and ProblemStore exist.

### Test Sequence

For each phase:

1. run Foundation JSON and Observability focused tests;
2. run affected AI, Agent, Channel, Harness, HarnessWork, Coding, TUI, and
   Ontology tests;
3. run architecture import-boundary tests;
4. run Ruff and `git diff --check`; and
5. finish with the repository's non-live regression suite.

## Commit Decomposition

The migration was decomposed into independently reviewable phases:

1. characterization tests only;
2. `foundation.json` plus Protocol forwarding facades;
3. canonical Observability move plus complete forwarding facades;
4. `records`/`projection`/`_router` split;
5. concrete sink and identity renames;
6. consumer migrations in dependency-oriented batches;
7. live documentation and architecture gates; and
8. compatibility removal in the final change.

Broad consumer migration, the semantic JSON-policy correction, and
compatibility deletion were kept as distinct phases.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| duplicate router state during migration | forwarding modules only; cross-entry configuration tests |
| duplicate ContextVar during migration | canonical context module; cross-entry identity tests |
| strict and diagnostic JSON behavior accidentally merged | one type owner, separately named policies, characterization tests |
| import cycles from a broad root facade | minimal Foundation root; direct leaf imports; router inversion |
| trace output silently changes | preserve private fallback initially; exact output tests |
| large 60-file consumer churn hides regressions | compatibility-first migration in small subsystem batches |
| retired direct submodule imports return | AST import gates reject both former namespaces |
| Foundation becomes a dumping ground | admission rule and standard-library-only/import-direction gates |
| `runtime.py` absorbs Product policy | retain only Observability lifecycle; audit helpers after mechanical move |
| `problem_text.py` is promoted prematurely | keep explicit and provisional; do not root-export initially |

## Non-Goals

This refactor does not:

- add OpenTelemetry, metrics, tracing spans, remote exporters, or telemetry
  backends;
- add async logging, a plugin registry, or a new custom-sink API;
- change log levels, Problem semantics, trace schemas, event schemas, or file
  formats;
- move Harness diagnostics, AI trace policy, Work EventLog, journals,
  transcripts, or Channel contracts into Foundation;
- rename JSON aliases with a Loushang brand prefix;
- create a generic `utils`, `common`, `types`, or runtime subsystem; or
- remove old packages before canonical ownership and consumer migration are
  independently established.

## Completion Criteria

The ownership migration is complete when:

1. `foundation.json.JSONValue` is the only JSON value alias definition;
2. all canonical Observability records use that alias;
3. strict and diagnostic policies have distinct, documented APIs;
4. Foundation imports only the standard library and itself;
5. Observability has one ContextVar and one router state;
6. all production callers use canonical paths;
7. live architecture documents and gates identify Foundation as owner;
8. focused and non-live regression suites pass; and
9. compatibility packages are removed and retired imports are gated.

## Bounded Follow-Ups

The following decisions are intentionally deferred until usage evidence is
available:

- whether custom sinks become a supported public extension contract;
- whether argument/environment/path helpers remain in Observability runtime or
  move to Harness/Product adapters;
- whether `problem_text.py` has enough cross-product use to remain in
  Foundation;
- whether the trace sink's permissive fallback can be removed or safely
  narrowed; and

These follow-ups do not block establishing Foundation ownership.
