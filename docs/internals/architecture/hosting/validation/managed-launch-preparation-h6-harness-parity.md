# H6.4 Harness Managed-Preparation Parity Record

## Status

- ID: `HOST-H6.4-HARNESS-PARITY`
- Scope: `hosting / Harness Worker`
- Parent: `HOST-H6`
- Authority: descriptive — implementation validation record
- Design status: not-applicable
- Implementation status: implemented
- Native activation: none; no Product composition supplies a Worker profile
- Runtime posture: default-dark; Current remains the default Worker owner
- Delivery parent: `c3fca03c`
- Owner: Harness Worker maintainers

## Result

H6.4 extends the existing H5 Worker meaning adapter across Hosting's private,
nominal managed-preparation seam. When trusted composition injects an object
that is both the public caller preparation capability and the private
`_ManagedLaunchPreparationPort`, the Worker adapter preserves that nominal
type, delegates the reservation-scoped capture unchanged, and wraps only the
returned caller lease with the existing Worker final semantic fence.

An ordinary `LaunchPreparationPort` still follows the H5 public path. The
adapter does not construct a capture specification, choose a platform profile,
inspect an opaque binding, acquire a native resource, or interpret Sandbox and
Approval evidence. This keeps the bridge cohesive: Harness adds Worker meaning;
Hosting retains capture, native material, spawn, and cleanup mechanics.

## Private Friend Seam

The dependency on `loushang.hosting._launch_preparation` is intentional and
closed. Only `src/loushang/harness/worker/hosting_adapter.py` may import that
private protocol. No public Harness symbol mentions it, and Hosting continues
to import no Harness module. Promoting this friend seam to a public contract
requires a separate versioned design decision; H6.4 does not widen
`loushang.hosting/v1`.

The wrapper preserves ownership at the return boundary:

1. before `prepare_managed` returns, the injected caller adapter owns any
   semantic candidate and must close it on failure or cancellation;
2. native material is already attached to the Hosting reservation by the
   capture authority;
3. after a valid result returns, the wrapper synchronously decorates only its
   caller lease and returns the original opaque binding; and
4. Hosting joins that decorated lease to the native material and owns all later
   verification, spawn, rollback, and close ordering.

No additional await point or independent cleanup owner is introduced between
the delegate result and the returned managed result.

## H5 Semantic Parity Matrix

| Concern | Current owner evidence | H5 public Hosting evidence | H6.4 managed Hosting evidence |
| --- | --- | --- | --- |
| exact Worker identity and request evidence | `tests/harness/worker/test_launch.py::test_owner_only_worker_port_seals_identity_and_returns_redacted_evidence` | `test_hosting_adapter_maps_worker_and_publishes_atomic_session` | `test_hosting_adapter_preserves_managed_capture_and_worker_semantic_fence` and `test_hosting_adapter_managed_preparation_runs_through_real_child_session` |
| pre-transaction and final semantic validation | `tests/harness/worker/test_launch.py::test_owner_only_worker_port_seals_identity_and_returns_redacted_evidence` | mapping test plus `test_hosting_adapter_rechecks_abort_at_final_pre_spawn_fence` | `test_hosting_adapter_managed_final_fence_failure_reclaims_real_child_session` proves typed failure and joined cleanup through the real Child Session Host |
| aggregate process plus protocol endpoint | `tests/harness/worker/test_supervisor.py::test_supervisor_handshake_query_heartbeat_and_ordered_shutdown` | mapping test and `test_supervisor_can_handshake_through_hosting_aggregate` | the real-host test proves opaque bind, native verify/claim/transfer, publication, and process/endpoint/preparation close exactly once |
| failure and cancellation ownership | `tests/harness/worker/test_supervisor.py::test_launch_cancellation_is_not_collapsed_into_launch_failure` and `tests/harness/worker/test_supervisor.py::test_healthy_journal_failure_fences_and_cleans_owned_resources` | H5 invalid-session and final-fence rollback tests | `test_hosting_adapter_managed_capture_cancellation_retains_delegate_cleanup` and `test_hosting_adapter_managed_capture_cancellation_reclaims_real_reservation` prove both caller-candidate and real reservation rollback |
| selection and fallback | explicit Current compatibility owner | `test_owner_router_defaults_current_and_never_falls_back` | unchanged router; managed preparation adds no selector or retry branch |

This is semantic and lifecycle-adapter parity, not a claim that the Current
Python Worker satisfies either native H6 profile. H6.2 admits only exact static
Linux x86_64 closure profiles. H6.3 admits one narrow Windows AMD64
restricted-token/direct-import PE profile whose stream and environment contract
also differs from the Current Worker request. A Product route remains
unavailable until trusted composition supplies an eligible caller-admitted
profile and PLC9C5 separately accepts activation.

## Retained Fences

- `WorkerHostingActivationV1()` still selects `current`.
- a selected attempt never falls back to another owner;
- no non-Worker production module composes the adapter;
- no production module constructs an H6 native capture specification for a
  Worker;
- the public Hosting export set is unchanged; and
- Linux, macOS, and Windows Hosting workflows run the H5/H6.4 adapter and
  architecture deletion gates; and
- native profile eligibility and Product activation remain separate gates.
