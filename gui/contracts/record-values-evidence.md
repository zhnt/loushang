# Closed record decoding and admission composition

Status: partial C1 evidence, 2026-09-14. No production connection or B2 acceptance.

The independent Rust `record_value.rs` now follows `_local_record_values.py`:
closed root/scope fields, strict UTF-8, duplicate rejection, 8 KiB limit,
identifier/key/instance/port bounds, one or two unique scopes and the four exact
ordered capability lists. Capabilities determine the semantic profile; the
record's authentication transport profile remains `local-detachable/v1`.
Explicit endpoint or expected-profile mismatch is rejected, without fallback.

Public record fields are canonically encoded with sorted keys and hashed with
SHA-256. Key material is excluded; scope order is preserved. Endpoint-derived
filenames use the same SHA-256 naming rule as `LocalConnectionDirectoryV1.read`.
The record type does not implement Debug or Serialize; private keys are never
part of the probe output or a WebView value.

Two compositions now have evidence:

1. The Windows probe's `--decode-record` mode computes the selected endpoint's
   filename, performs native file admission, decodes those bytes and validates
   endpoint/profile. It exposes only public fixture facts for comparison.
2. The authentication probe includes the public synthetic
   [record fixture](fixtures/local-record.json), decodes it and uses its actual
   instance/key/public-record digest against Python's reference authenticator.
   This replaces the old arbitrary digest constants. It does not read live keys.

These are still separate experiments, not one live native connection pipeline.
The first also does not claim complete canonical-root admission, race injection,
native cleanup-failure reporting or sensitive-buffer erasure guarantees.

Opt-in reproduction from the lane root:

```text
pnpm --dir gui run check:record-values
pnpm --dir gui run check:record-contract
pnpm --dir gui run check:auth-contract
```

Recorded results: 53 record-value/selection cases (10 accepted, 43 rejected),
15 Windows scenarios (11 existing plus valid/endpoint/profile/ACL composition),
and 11 authentication pipe scenarios pass. The value comparison explicitly
checks that changing only a key does not change the public digest, while
changing scope order does. No new default gates or service-owner changes.

Next: integrate admitted credentials with a production-owned connection that
has bounded startup, cancellation and reliable close. Only then negotiate
execution hello, attach and publish initial snapshots; keep GUI offline until
that integration has its own evidence.
