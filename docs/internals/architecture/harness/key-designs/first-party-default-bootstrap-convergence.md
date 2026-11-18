# First-Party Default Bootstrap Convergence

- Authority: bounded implementation under COD-RESP-GOAL-002.
- Design status: accepted for complete A207 public SDK bootstrap.
- Implementation status: implemented with bounded local technical acceptance.
- Owner: existing Harness Plugin Management assembly and original desired/command owners.
- Baseline: `1a113f02c0db5c4e6ec8a0e95aa039c244b41549`.
- Method: clean local archmethod master
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`; no upstream revision claim.

## Complete Program And Existing Authorities

Three complete original methods (137 physical definition lines) implement
bootstrap, latest-own-install recognition and command submission in the existing
PM assembly. They use the same actual Coding lifecycle object, Desired ledger
and Management service. There is no additional lifecycle or coordination owner
instance, lock, manager, writer, progress flag, rollback or authority. Existing journal/command execution is
reused, not counted as a new engine removed.

Coding keeps its public nominal lifecycle, twelve dataclass fields, constructor,
physical slots and Product facts. A frozen profile carries eight original facts:
Product id/label, actor, policy revision, approval reference, operation namespace,
error namespace and the original error constructor. One read-only scope role and
no TypeVars express the actual existing layout. The plain empty-slot base adds
no instance data. Calls remain `self._submit_default` and
`self._is_own_default_install`; original class monkeypatch and subclass dispatch
remain effective. The error constructor is a value factory, not an IO stage.

This is a retained public SDK entrypoint. Current source has no other internal
production caller; current managed Base uses enablement migration instead. Real
SDK/storage tests consume the original entrypoint. A207 does not claim to replace
Base/Capability's 208/198-line programs or close C01. The larger A51/A183 pool
still has effective source/contribution/finalizer/custody boundaries and is not
mechanically rebuilt under the new growth criterion.

PM enablement migration is not a drop-in: it has its own migration journal,
immutable-input and locking contract, with 64 attempts. Product bootstrap opens
native runtime factories and activation/handoff, uses different operation/history
proof and raises on removed/superseded states. A207 directly reuses their common
lower authorities while preserving this SDK's separate fixed protocol.

## Failure, History And Retry

Scope/revision checks precede ledger IO. Each of 32 attempts takes a fresh
snapshot; a seen enabled state returns without comparing the requested revision.
Seen tombstones are not resurrected. Own-default recognition uses the last
matching mutation's disabled state, revision, actor, policy and approval; it does
not strengthen proof with an operation prefix or first transition.

Only the exact inventory-conflict result retries. Successful install also consumes
an attempt and continues; install on attempt 32 can persist and still end busy.
Missing/falsey management errors retain their original fallback. Error getters
and other BaseExceptions propagate at their original point. No rollback, cleanup
or async cancellation machinery is introduced for this synchronous program.

Private MRO, implementation globals/module/qualname and traceback frames evolve.
The profile captures private constants at module construction rather than reading
arbitrarily rebound module names on each call; arbitrary private hot replacement
is not promised. Existing self-dispatched command hooks are actually exercised
by the original inventory-race tests. Stored formats and operation-id repr/hash
inputs remain unchanged.

## Full Cost And Finite Evidence

Raw and uniform costs: Coding 1163→1035 (−128), existing PM assembly 273→454
(+181), system +53. All profile declarations, imports, scope role, annotations and
same-object adapters are included. This is complete responsibility convergence
with modest system growth, not system-wide net reduction.

Inverse AST checks restore only the eight profile facts, original error call and
constant label/namespace substitutions. Three entire methods match; original
Coding fields/decorators/other declarations and old Core code remain unchanged.
Core's module docstring explicitly reflects its expanded responsibility.

Old and actual main consumers pass the same 119 ordered nodes (269.79s /
270.47s), each with its respective final source manifest. Sixteen
local controlled cases plus one overlapping original revision-refusal node pass
before/after (17 each), and all sixteen JSON observations match byte for byte.
The distinct union is 135, not 136.
The constructor, three method signatures/resolved hints, twelve fields, slots,
match args and physical layout agree; three old method pickle references load
to the inherited methods. Combined import/metadata/pickle module names (341)
agree. Same-process API and test guards pin two modules' declared programs;
they do not cover generated dataclass code, all globals, carriers or children.
Controlled ledger/command ports and injected KeyboardInterrupt are not native
persistence failure or real Task cancellation. Ruff/full-format and selected
mypy pass for both sources. See the [A207 execution record](../coding-responsibility-convergence-progress.md).
