# GUI restart recovery diagnosis

Date: 2026-11-06. Baseline: `lane/gui` at `17fa92920`.
Scope: diagnose the previously observed reconnect loop without changing failure
presentation or resetting stored state. Product code remains unchanged.

## Confirmed cause

The native attachment decoder rejects the legal optional Session snapshot field
`submissionMode: "execution"`. `app_client/projection.rs::Source` uses
`deny_unknown_fields` but does not declare that field. Consequently
`Attachment::validate` fails in `projection::source_value`, before execution
snapshot initialization and before publishing any initial snapshot to the GUI.
The native connection worker retries, so the GUI remains reconnecting.

The Python protocol already accepts this field. The canonical codec emits it
only for execution submission and rejects explicit `legacy`, null and unknown
values. See `src/loushang/appserver/protocol/codec.py::_decode_snapshot` and the
existing optional-mode tests in `tests/appserver/test_protocol.py`.

Restored writable history is constructed as `CodingDeferredHostedSessionV1` in
`coding/hosted_session.py`. `coding/hosted_execution.py` marks that binding for
execution submission, and `coding/appservice_adapter.py` includes the mode in
its snapshot. This explains why the restored path exposed the mismatch while
earlier newly-created Session tests passed. It is not an OS-specific failure.

## Reproduction and causal experiment

The original two-Session state under `/tmp/loushang-gui-real-ui/` was retained.
The standalone `loushang-mux ... serve` command was restarted against those exact
application and transcript directories; no history or configuration was cleared.

- A Python production client authenticated, attached to `gui-real-ui`, and read
  both execution snapshots successfully. The Sessions retained 2 and 1 records.
- The Rust `snapshot_probe`, built from the unchanged production AppClient,
  failed on the same service and state.
- Temporary non-secret phase logging established that record decoding,
  authentication and hello negotiation passed. Attachment validation reported:

  ```text
  unknown field `submissionMode`, expected one of
  `identity`, `title`, `cursor`, `revision`, `running`, `records`
  ```

- A temporary experiment declaring only that optional source field allowed the
  same probe to attach, initialize, and return both Session snapshots. No server
  implementation, state directory or authentication input was changed.
- All temporary logging and the permissive field experiment were reverted.
  The test AppHost was stopped normally; original state was preserved.

## Required production repair

Explicitly support the canonical optional field in native source decoding;
accept omission and the exact value `execution`, reject null/legacy/unknown
values, and retain strict rejection of unrelated unknown fields. Align bridge
generation and independent value validators with this codec exception rather
than treating the codec's static field table as the entire wire schema.

Add targeted regression coverage for attachment snapshots with this mode and
for restarting the same real AppHost state. Verify restored Session/history
identity, initial snapshot publication and subsequent execution. A native window
test should cover both GUI relaunch and an already-open GUI reconnecting after
the backend restarts. Do not clear history, strip the field at the server, or
disable unknown-field validation as a workaround.

This diagnosis does not claim the production repair or full restart acceptance
has been completed, and does not change CI gates.
