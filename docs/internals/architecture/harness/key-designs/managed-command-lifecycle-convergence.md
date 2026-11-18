# Managed Command Lifecycle Convergence

- Authority: bounded implementation under COD-RESP-GOAL-002.
- Design status: accepted for complete A205 managed command lifetime.
- Implementation status: implemented with bounded local technical acceptance.
- Owner: existing optional AppHost integration and its managed resource components.
- Baseline: `8e759f34f66ee7f23006b61ff2281bfbe16cb92b`.
- Method: clean local archmethod master
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`; no upstream revision claim.

## Complete Lifetime And Existing Owners

The existing actual `ManagedMuxCommand` now inherits a fixed optional AppHost
lifetime implementation. Eight complete operations cover run/close/probe, probe
snapshot and pending observation, failed/unentered Runner cleanup, and native
parent release. Thirty-five original resource/state anchors move into that same
object's initializer; four Code bindings remain Code. All thirty-nine fields,
values, ordering and binding/copy behavior remain unchanged. There is no extra
command, Task engine, registry, manager, resource cache or progress state.

Existing admission, coordinator, connection, creation, stop/batch, probe and mux
manager owners perform the real IO. The new program calls them directly instead
of calling back a Code operation coordinator. Their existing engines and A156/
A180 implementation gains are reused, not counted again. Generic CloseGroup or
foreground-client control is not a drop-in: their cleanup debt/exception order,
UI/settlement and ownership contracts differ from this command's fixed sequence.

Code retains synchronous admission, confirmation, selection, command formatting,
JSON/trace/error policy and real UI bindings. Thirteen narrow ports include late
application/endpoint properties, output/value leaves, two lazy UI resolvers and
the existing Code Runner bridge. Output leaves perform IO or update result status
and can fail; they are not advertised as pure. The Code probe bridge still invokes
its original Runner/exit policy; that bridge is not claimed as migrated. Two
structural UI roles and two TypeVars express actual borrowed values, not a phase
callback framework. Existing terminal settlement contracts are not interchangeable.

## Original Failure And Compatibility Contracts

Close continues to inspect its frozen permission, issue/read at most the original
RPC effect, verify the result, output, record and output reconciliation in the
original order. A visible-output failure can leave a verified result unrecorded;
ordinary rejoin reads the existing permit/result without another close RPC.
Nested finally blocks preserve exception replacement and cleanup ordering.
Shell/connection close failure can leave `active` true and native parents retained;
no shield, rollback, unconditional flag reset or retry-state repair is introduced.
The existing native-close barrier and borrowed-journal release order are unchanged.

The actual Code class, six public signatures/resolved hints, virtual test hooks,
constructor fields and Code selection/output methods remain. Private MRO,
implementation module/qualname, extra binding frames and generic/private hints
evolve. Arbitrary module-global replacement or whole live-command pickle behavior
is not promised. Parent import/constructor inspection is not an import-IO audit.

## Full Cost And Historical Decision

A193 kept the same complete shape external after a value rejection; it did not
establish a runtime failure or permanent domain floor. A205 re-evaluates complete
ownership under the user's explicit permission for necessary modest shared/adaptor
growth without requiring another duplicated engine to exit. The old decision and
static history remain historical; the new run evidence is separately recorded.

Final raw Code 829→682 (−147), new AppHost 439, system +292. Uniform format gives
Code 1310→1063 (−247), AppHost 439, system +192. The hundred-line difference is old
compact formatting, not another mechanism deleted. All thirteen ports, constructor,
profile, roles/types, imports, output/UI/Runner bindings are included. Existing
unmodified compact Code regions are retained; full-Code format success is not
claimed. Ruff checks, the new Core's full format and selected mypy are separate.

## Bounded Validation

The current old and installed suites each pass 276 original nodes, including real
CLI/process/RPC consumers, managed components and architecture checks. Two local
gaps plus one repeated original help node pass before/after: output-before-record
recovery, and actual caller Task cancellation combined with controlled shell and
connection cleanup errors. These controlled ports do not prove every native
failure. The distinct union is 278, not 279 or a sum of repeated executions.

A final installed-context lint correction removed only two import-group blank
lines from the tested 684-line intermediate version. The full module AST and all
sixteen recursive executable code fields across forty-two code objects match,
excluding the three line-position fields. The 276-node guard pins the intermediate
source; it is not represented as a full run at the final 682-line SHA. Final-source
local three-node replay, fresh API/constructor inspection and selected static checks
pass. This is explicit equivalence evidence, not an invented final full-suite run.

The combined import/inert-constructor probe observes 249→251 Loushang modules,
adding only the optional integrations package and implementation. Parent guards
pin declared programs, not generated code, all globals or child-process provenance.
Two exact optional inventory paths coordinate A03's AppServer consumer and the
AppHost private implementation list. Existing scanners/assertions/required sets,
stdlib core/facade, source budgets and test routes are not expanded. See the
[A205 execution record](../coding-responsibility-convergence-progress.md).
