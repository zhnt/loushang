# G16 authentication and framing interoperability

Status: partial C1 transport evidence, 2026-09-14. Not a production adapter,
native record admission, socket connection or B2 acceptance.

## Implemented experiment

An isolated Rust binary `auth_probe` authenticates as a client against the
existing Python `authenticate_local_server`, exchanging real framed bytes over
child-process pipes. Both sides use public synthetic fixture credentials;
the binary has no real-record or credential-input API. Client nonces use OS
randomness. HMAC-SHA256 generation and constant-time verification use RustCrypto
`hmac`/`sha2`, not a handwritten primitive. Dependencies are locked in the
separate contract-probe crate, not added to the native Tauri application.

The independent Rust implementation includes:

- Four-byte big-endian lengths and bounded `read_exact` framing; invalid lengths
  are rejected before body allocation. Authentication messages are at most
  2,048 bytes; protected messages allow 1 MiB payload plus 40 envelope bytes.
- Closed challenge/proof objects, instance/profile checks, duplicate/unknown
  field rejection and strict UTF-8/hex input.
- Client/server role-separated proofs and directional `c2s`/`s2c` keys, using
  the existing `local-detachable/v1` transcript even for later execution profiles.
- Eight-byte sequence numbers starting at one, authenticated sequence and
  payload, separate send/receive counters and rejection after exhaustion.
- Fencing after frame/sequence/integrity failure; a failed client exits with
  a fixed redacted message rather than printing credentials or wire contents.

The Python supervisor enforces a ten-second scenario deadline and bounded
child cleanup. Rust IO is deliberately blocking in this probe: this does **not**
implement the production async first-byte/frame deadlines, pending-request
capacity, concurrent response reader or cancellation ownership.

## Reproduce

From the GUI lane root:

```text
pnpm --dir gui run check:auth-contract
cargo +1.98.1 test --locked --offline --manifest-path gui/contracts/rust/Cargo.toml --bin auth_probe
```

The first command builds the isolated binary with offline locked dependencies.
For a fresh cache, first use the existing contract crate's `cargo fetch` command.
It starts no application service or provider, opens no network socket, reads no
private connection records and exposes nothing to the WebView. The new command
is opt-in; default GUI `check` and CI remain unchanged.

Recorded Windows evidence: 11 Python/Rust scenarios and 3 Rust unit tests pass.
The scenarios cover a valid two-message exchange (Chinese/emoji, then exactly
1 MiB), wrong profile/instance, unknown/duplicate challenge fields, invalid
UTF-8, oversized/truncated auth frames, invalid server proof, payload tampering
and replay. Writes split header/body and readers handle byte-stream chunks.
Rust units additionally cover adjacent frames, invalid framing, closed-state
fencing and send sequence exhaustion. This is sampled interoperability, not
exhaustive cryptographic, concurrency or native-platform assurance.

## Native record admission follow-up

Inspection of `_windows_local_record.py` establishes that a Rust native adapter
cannot replace admission with `read_to_string` or trust JSON copied from React.
It must preserve the current owner SID/protected DACL checks, exact allowed ACEs,
handle-based file/directory identity, rejection of reparse points and multiple
file links, and root/path identity rechecks. Reading by an admitted handle and
closing it safely are part of this obligation, not just parsing record fields.

The subsequent [Windows private-file experiment](windows-record-evidence.md)
implements handle/ACL admission and tests it on native fixtures. Complete
service-record decoding and production IO cancellation remain pending. The GUI stays
offline and this probe must not be promoted to a Tauri command. Subsequent
attachment and composite-snapshot work still follows
[the connection plan](connection-plan.md).
