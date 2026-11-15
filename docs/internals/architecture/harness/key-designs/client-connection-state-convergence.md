# Client Connection State Convergence

- Authority: bounded implementation under COD-RESP-GOAL-002.
- Design status: accepted for the complete A203 connection workflow.
- Implementation status: implemented with bounded local technical acceptance.
- Owner: existing optional AppHost client preferences/navigation module;
  existing Harness Config atomic JSON writer for publication.
- Baseline: `c0c012277bc6dd844fd56c846d137b8eba3bdb96`.
- Method: clean local archmethod master
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`; no upstream revision claim.

## Complete Workflow And Reuse

The existing `apphost.client_preferences` module now owns the complete shared
connection configuration workflow: read and validate `connections.json`, remember
workspace, serialize mutations through the existing SQLite lock, publish through
the existing Config atomic writer, and project the local/remote connection list
from the original Host/endpoint records. These are Host client navigation facts,
not Coding models, Session construction or execution policy.

The original `ClientPreferences` class and its separate
`data/client-preferences.sqlite3` protocol remain unchanged. Connection serialization
continues to use `state/connection-config-lock.sqlite3`; the JSON file remains the
configuration authority. No store/schema merge, migration, runtime object, lock
manager, callback recipe, Protocol, TypeVar or extra owner instance is introduced.
A149 already shared the atomic writer: it is reused, not newly migrated or credited.

Coding retains its exact `settings_request` dispatcher, Linux support declaration,
`@temporary` policy and workspace input limits. Five explicit same-name reexports
preserve existing Coding attribute/import entrypoints without five forwarding
bodies. The actual function objects and their globals now belong to AppHost.
Their public arguments and existing resolved hints remain unchanged; function
`__module__`, new pickle targets and internal monkeypatch locations evolve. Five
old function pickle references separately load to those same actual reexports;
this is finite backward lookup evidence, not a promise about arbitrary reflection.

## Original Failure And Storage Contracts

Home resolution and directory creation retain their original call points. A
mutation acquires its original SQLite transaction, reads current JSON, executes
the caller's mutation and publishes JSON before leaving the transaction context.
A callback can change the environment so that the writer resolves a different
home: no newly captured path, rollback or cross-file transaction is invented.
Direct reads/writes remain unlocked. SQLite context exit is not an explicit
connection close, and JSON publication can survive a later context-exit failure.

Connection version/schema checks, unknown fields, URL parsing and endpoint errors
retain their original behavior, including permissive or raw-error cases. Remote
URL and local endpoint admission remain distinct. The writer import remains local
to `write_connections`; import remains lazy and the static list call graph has
no writer import. The cold observer covers fresh import and metadata/pickle
inspection, not execution of every read/query path.
No security policy tightening or error normalization is bundled with this move.

## Cost And Bounded Evidence

Full raw cost: Coding 173→66 (−107), existing AppHost 57→180 (+123), system +16.
Uniform Ruff format gives Coding 175→66 (−109), AppHost +123, system +14.
All reexport/import costs are included; Code-specific dispatch remains attributed
to Coding. This is complete responsibility convergence, not duplicate-engine removal.

Five complete function ASTs, Coding dispatch and the original preference class
are unchanged. Original 40 tests pass before and after, including Config and the
existing five A149 byte/error comparisons. Seven additional local observations
match, covering callback/publish failure, an injected error after a real SQLite
context commit, malformed reads/list projections, dynamic home and twelve actual
SQLite-serialized mutations. The local eighth node repeats an original GUI test.

Fault ports are controlled; the post-commit injection is not a native SQLite
commit-failure proof. Concurrent observations compare semantic final JSON, not
nondeterministic insertion order or universal scheduling. Parent source guards,
six public signatures/hints, five old pickle loads and the unchanged thirteen
cold Loushang module names bound the evidence. Selected mypy uses silent followed
imports and dynamic dictionaries/callbacks; it is not a full strict-type proof.
Native Windows, arbitrary private globals and all compound native errors remain
outside these local claims. See the [A203 execution record](../coding-responsibility-convergence-progress.md).
