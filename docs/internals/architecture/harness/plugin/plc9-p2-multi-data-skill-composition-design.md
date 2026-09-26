# PLC9 P2: independent data Skill composition

Status: implemented and reviewed.
Tracking: PLC9 issue #509.

## Goal and boundary

Prove that two independently authored local, data-only Resource/Skill wheels
can be selected together with `coding.base` in one explicitly fenced Coding
workspace and Session. Each Plugin must retain its own Source, Desired State,
selected revision, Resource admission, and retirement evidence. Use the PLC9
Product, Package, management, and Resource Catalog owners already present.

This slice does not change Coding's default legacy Package mode, expose a new
authoring kind, add a PluginContext or generic registry, admit executable
contributions, or make Worker/remote plugins public. It does not activate
automatic GC, migrate an old workspace, or add a management transport.

## Current evidence and gap

P1 covers one external Skill wheel from real CLI installation to Session
consumption and version update. Product selection and base compilation already
accept an ordered tuple of external data Plugins; the Product-owned Source
catalog accepts separate wheel identities. The current vertical test never
puts two external Plugins through these paths at the same time. Therefore the
tuple-shaped code is not yet evidence of independent composition, failure
isolation, or deterministic name-conflict behavior.

## Acceptance path

1. Build two distinct wheel identities with the public `loushang.plugin`
   `resource.skill` authoring API. Each wheel has one document-backed Skill and
   a different Skill name. Use a fresh workspace, explicit cutover, and the
   existing `--install-package`, `--enable-plugin`, and list commands. Do not
   prepopulate Product policy bindings in the test.
2. In one real Coding Session, verify both external Skills and the built-in
   `coding.base` Resource path are admitted through the same Product plan and
   Resource Catalog generation. A Skill load must record the exact external
   Source/revision; a Plugin inventory row alone is insufficient proof.
3. Update only Plugin A through the existing staged Product update. A new
   Session must select A v2 and B v1; the old Session keeps its captured A v1
   and B v1 evidence. A retired Consumer may require restart for a later load,
   as in the existing Resource Catalog contract. Disable B through the
   management CLI, then open a new Session **before** removing A: A v2 must
   still load from its exact Source/revision, while B must be unavailable.
   Remove A through the existing management CLI; a later Session must not
   acquire either Skill, while the management projection still distinguishes
   A `absent` from B installed but disabled. Re-enable B and verify B alone
   returns. For A's update and removal and B's disable, inspect the existing
   retirement intent/set evidence for the target Installation and predecessor
   Instance/Package revision; each intervening step must leave the other
   Plugin's Desired State and selected revision unchanged.
4. With separate Plugin IDs but the same legal Skill locator/name, Product's
   existing exact owner-identity rule must reject Session composition with
   `duplicate_owner_contribution_identity` and both admission fingerprints.
   Neither Plugin may become an arbitrary winner or load a body because no
   Session is published. Both installations remain intact; this is a Product
   composition rejection, not an installation or Package failure. Disabling
   one Plugin must let the remaining Skill load in a new Session with an exact
   Source/revision receipt. For this narrow wheel shape, the valid Skill name
   must match its locator directory, so the Resource Catalog's separate
   same-precedence conflict rule is not reached. Do not weaken Product owner
   identity uniqueness solely to reach that Catalog rule.
5. With A and B enabled, reject a malformed A update and verify B's Source,
   Desired State, revision, and real Skill load remain unchanged. Reuse the
   existing Product handoff interruption seam for a separate A update; change
   B's Desired State through an already-open management Owner before replay.
   The current global inventory CAS may reject A's stale update, but replay
   must not overwrite B, partially select A, or block a subsequent startup.

## Implementation rule

Add the smallest end-to-end regressions first. If the existing Product and
Catalog paths pass, leave Product code alone. If a test reveals a missing
seam, repair its exact Owner boundary and add a focused adversarial case; do
not broaden wheel shape, trust class, or default activation. Preserve Product's
exact owner-identity rejection and Resource Catalog's existing merge policy.

Keep the new vertical tests in the Coding offline suite and the existing PLC9
architecture module in the Harness suite. Verify that the change-aware plan
selects these suites for the touched files; only change CI routing if this
check exposes a gap. Local pytest and make targets that invoke pytest run
outside the managed sandbox with existing non-live/host-runtime selectors.

## Review and exit

Before implementation, request architecture/Owner, security/recovery, and
Product/author-experience reviews with `gpt-6-astra xhigh`. Repeat these three
reviews on the final code diff. Resolve blocking findings before merge. Exit
requires real CLI and Session evidence for the acceptance path, existing P1
regressions, affected architecture checks, Ruff and mypy, and the selected
remote CI checks. Merge, push, and synchronize local `main` and `lane/harness`
only after the reviews and local checks pass.

## Implementation evidence

The end-to-end regressions live in
`tests/coding/test_package_external_data_wheel.py`. They exercise the real
Coding CLI and Session path for two wheels, old and new Session revision
capture, exact Skill load receipts, independent enablement and removal,
retirement intent/set evidence, Product's structured same-name rejection,
malformed update isolation, and interrupted update recovery while the peer's
Desired State changes. No Product Owner or admission code changes were needed.
The current CLI renders a generic composition error for the same-name case;
the code and both admission fingerprints are available in the Product
exception, not in CLI text.

The change-aware selector maps this Coding test file to `coding` and its
`host_runtime` dependency, and maps this design document to `docs`. The
existing PLC9 architecture module remains in the Harness test inventory.
