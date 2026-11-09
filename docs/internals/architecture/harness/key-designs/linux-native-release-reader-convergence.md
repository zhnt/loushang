# Linux Native Release Reader Convergence

- Authority: bounded design and implementation record under COD-RESP-GOAL-002.
- Design status: accepted for reversible implementation on 2026-11-09.
- Implementation status: implemented; bounded technical acceptance on 2026-11-09.
- Owner: existing Harness Worker; Coding retains Product policy and authority.
- Source baseline: `0bddeb516`; local clean archmethod master
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`.

## Complete Scenario And Existing Reuse

The generated H6 reader opens a private directory, reads bounded catalog and
launcher members, checks stable file metadata, then verifies canonical catalog,
profile-source digest and inert ELF format before constructing closure facts.
The installed reader also verifies the complete installed RECORD, exact package
and release membership, supported metadata and distribution identity. Both
programs supply evidence only; neither issues approval nor launches a Worker.

These complete read programs now reside in Worker `_linux_native_release.py`.
The verifier has three pure bindings: source Path, original error constructor
and original closure value constructor. Construction has no IO or admission.
Installed reads take a zero-argument package-version leaf, evaluated at the
original platform → version → root-stat point. There are no lifecycle-stage
callbacks, layout DSL, registry, new state engine or borrowed Product authority.

The complete member program reuses the existing Resources `read_bounded_prefix`
at 64KiB and the existing Worker ELF verifier. The original overflow check remains
before after-stat. RootedFileIO would add write-bit/named-identity and different
read-length conditions; the Wheel inspector admits different metadata and archive
semantics. Neither is substituted for this installed-directory contract. The
fixed H6 layout is already produced by the two existing platform build scripts;
it is not an independently configured Coding package format.

## Code Boundary And Compatibility

Coding retains its public error/DTO identities, Reader declarations, constructors
and GC properties. Its source binding still reads the Hosting C source anew at
verification, before JSON parsing. The three actually consumed legacy private
entry points remain thin delegates; unused `_open_directory` and `_verify_record`
shims are not added. Product receipt, retained Wheel, approval/current generation,
launch locator, GC and install/repair remain with their original Code owners.

All seven Product/receipt/launch-material declarations in the installed module
are AST-identical to the baseline. Native install/repair is byte-identical.
The generated Reader still checks platform before opening root; installed checks
after root open. Exceptions retain exact catch sets, message and cause/context.
Directory and member descriptors close in the original nested order; a borrowed
root is not closed by descriptor verification.

Generated launchers require mode0500; installed requires owner execution. Both
retain permissive non-executable write bits. RECORD accepts 6–16 rows and safe
extra metadata, with exact digests/sizes, required members, empty initializer and
METADATA/WHEEL bytes. Extra root siblings remain allowed. Canonical catalog,
source/launcher digests and the eight stable-stat fields retain their checks.

One baseline defect was explicitly preserved in pure-move commit `b4f44cd6e`: `_open_directory`
leaks its new child descriptor if its initial fstat raises. The original fixture
records `outstanding=["fd2"]`. The separate cleanup fix below preserves that
historical fixture and explicitly accounts for the intentional difference.

## Evidence And Cost

The baseline source frame records all 1,953 production sources and complete
original modules outside Product. Before editing any production source, 105
real-file/descriptor observations plus one original inert-format unit passed.
A second independent capture uses fixed source bytes and package-version input
for durable replay; its 105 expected observations are immutable. Both before
runs passed106, and the replacement passed the same106 (2.76s). Runs overlap
and are not additive coverage.

The durable probe has no capture path. It exercises both public readers, Product
`current_launch_material` including generation3 and missing approval, and direct
member consumption. Valid/rejected case sets are asserted before comparisons.
Physical files, catalog, RECORD, receipt and FD operations are real. Product
admission/approval journal are controlled; launcher ELF bytes are never executed.
This does not prove native launch, full Product authority, a real installed
distribution upgrade, Windows execution, ABI or performance.

Three independent responsibility/reuse, runtime/failure and data/compatibility
design reviews accepted this complete direction. Actual code reviews are
accepted by `/root/responsibility_review`, `/root/runtime_review` and
`/root/compatibility_review`. They independently checked actual source/AST,
exception/FD contracts and the captured evidence; they did not run pytest.
Code hashes are `e35589d292213168aa180238bc92db707e592e92a607a3873b245f212c224e4b`
and `37a6d190243e660f7f64fda98440025715401976b3e8a37a2b17c16fda54c9c2`;
Pure-move Core is `dc6a657f74bc7158655d42d5d0f37083c562bbd646c967c89d8f97459f7c3c11`.
The implementation owner accepts this bounded move after actual terminal checks.
The explicit local
probe does not add default discovery, a CI route, platform or required gate.
The existing C54 assertions only refresh the exact observed import entries;
their function bodies and acceptance rules remain unchanged.

The durable probe and original C54/CLI consumers passed117, with one existing
host-runtime deselected (109.45s). The same105 observations overlap the
before/after run. Three source files pass mypy; changed Python passes Ruff and
formatting. Existing documentation validation, dependency freshness, check-plan
generation and diff checks pass. The earlier passing AI suite is retained:
no relevant AI source or input changed. No native/host route was enabled.

| Production source | Before | Pure move | After cleanup | Final difference |
| --- | ---: | ---: | ---: | ---: |
| Code generated Reader | 201 | 83 | 83 | −118 |
| Code installed Reader and Product policy | 472 | 295 | 295 | −177 |
| Worker verifier, including binding/interface/import/format costs | 0 | 361 | 365 | +365 |
| Total | 673 | 739 | 743 | +70 |

Coding becomes118373 lines/430files, system644548 lines/1954sources.
All1,951 other old sources are unchanged. This is responsibility convergence
with existing component reuse, not system net reduction. Full P1–P4 and the
Coding≤15K Goal remain incomplete. KD011/A33 pending user work is not adopted.

Rollback the verifier and both Code delegates together. No data schema or
installation identity changes; Product source, receipt and approval stay valid.

## Separate Directory Admission Cleanup Fix

After the pure move was committed, only the initial `os.fstat(descriptor)` in
`_open_directory` acquired a try/except BaseException close-and-reraise. The
following unsafe-directory branch is outside it: its own close failure must not
trigger a second close. Normal operations, bytes, schemas and Code policy do
not change. The new child is closed on fstat failure or interruption; if close
itself fails, the close exception retains the original failure as context and
parent finally scopes still execute. This is not a promise that a failed OS
close has physically released its descriptor.

The 105 original observations remain byte-identical. Only the expectation copy
for the original leaked-fstat case explicitly inserts one child-close and clears
the original outstanding FD; its exception graph is compared unchanged. Seven
additional explicit-local cases cover package/release/metadata fstat, child-close,
child-plus-root-close, KeyboardInterrupt and CancelledError. All failures use
real opened descriptors and the probe independently reclaims injected leftovers.

First verification passed111 and exposed two probe-matching failures: release
also matched the root name, and the compound close case did not match the
child-close substring. Only these probe conditions were corrected. The same two
nodes then passed2 in2.60s; the original111 passes remain valid. These113 distinct
nodes have terminal passing evidence across those runs, not one clean113 rerun.
Original failures and fixture bytes are retained. Earlier pure-move consumers
are not relabeled as rerun after cleanup. Core mypy, Ruff/format, documentation
and final diff validation pass.

All three independent reviewers accepted this bounded fix after source/cost
review; runtime and compatibility views also checked corrected terminal evidence.
The implementation owner accepts the cleanup fix separately from the move.
Final Core SHA256 is `35f0336a4a811298b21c4d63c221ce306edd020701ae96a62386cf1985451e62`.
It costs four additional production lines. The full P1–P4/15K Goal remains active.
