# Linux lmux preview

English | [中文](../../zh-CN/user-guide/lmux.md)

This guide describes the current development branch, not completed delivery
acceptance. The `lmux` command it documents was still uncommitted when this
guide landed, so a build from this commit has no `lmux` entrypoint yet; treat
the commands below as the intended interface, not a shipped one. Check `lmux --help` against your installed version. Automatic
background services currently target Linux only; GUI and cross-machine access
are not included. Managed scratch quotas, full Harnesstui parity, and final
installed/disconnection/performance acceptance remain in progress.

## Create and reconnect

Run `lmux new -s dev` in your workspace. It starts or reuses the workspace
service, creates an empty named Mux, and opens the terminal. Use
`/new cwd Work` for the first Session Tab, `/resume` to discover existing
sessions, and `/help` for supported operations. An empty Mux does not call a model.

`/detach` leaves the client without stopping the service. After reconnecting
over SSH to the same machine, run `lmux attach -t dev` from any directory.
Names are global within the machine/user namespace; no `server:mux` prefix
is needed. Multiple Muxes in one workspace share a service, and a Mux may
contain multiple Session Tabs. Another controller is not displaced; attach
may report busy until the previous connection releases its authority.

Attach never restarts an offline service implicitly; use `lmux start -t dev`.
A new instance is allowed only after the previous instance is proven cleanly
stopped. Crashes or insufficient cleanup evidence are refused; start does not
bypass those checks.
Accepted work belongs to the background service rather than the SSH terminal.
This is not protection against reboot, crashes, or host policies that terminate
user processes. An admitted restart restores durable Mux/Session state, not running work or
requests whose replies were lost.

Bare `lmux` creates `main` in cwd when no Mux name reservation exists;
untargeted `lmux attach` reports not_found in that case. When the entire namespace
has exactly one Mux reservation, and it belongs to Coding and is recorded as
committed with neither a stop request nor a clean stop, both commands directly
attempt an authenticated connection. For multiple candidates, a bounded,
read-only probe authenticates each eligible service and reads exact Mux IDs;
it never attaches or requests control. A sole confirmed Mux is selected only
when no candidate is unknown and the candidate set remains unchanged.
Otherwise, the selector shows the frozen observations: `n` advances a page,
`r` returns to the first page, and `f` explicitly refreshes and probes again.
Paging performs no new probe. Probe connections close before final attachment,
which authenticates again against the selected instance and Mux ID.
Recorded state does not prove availability:
a failed connection does not restart the service or choose another target.
Pending reservations are not treated as an empty list.
Terminal commands require TTY stdin and stdout; piped prompts are
not supported.

### Recover an interrupted creation

Before reserving a name, `new` (including bare `lmux`) prints a JSON
`planned_creation` with exact `serviceId` and `operationId`. This is **not** a
success receipt or proof that the reservation committed. `lmux ls` also reports
`creationOperationId` for retained reservations.

```bash
lmux create-status --server SERVICE_ID --operation OPERATION_ID
lmux create --server SERVICE_ID --operation OPERATION_ID --continue --yes
```

Replace both IDs with the original values; service aliases are not accepted.
`create-status`, and `create` without `--continue`, only read recorded facts:
they do not connect, start, issue permission, or resend creation. `unknown`
(exit 1) does not mean the original request had no effect. `created` is a
historical receipt, not proof that the Mux is still open or online.

Explicit `--continue` confirms the original name/workspace/operation and may
start or reuse that same service, then sends at most one idempotent create RPC.
It does not allocate a replacement operation, delete a reservation, or attach
automatically. Non-TTY continuation requires `--yes`. A known receipt needs no
RPC; otherwise, after successful continuation use `lmux attach -t NAME`.
The existing clean-stop and recovery checks still apply. A prior-instance
permission without sufficient durable creation history is refused, not guessed
safe to replay. Closed/released operations cannot reclaim a reused name.
Repeating `new -s NAME` remains a conflict, not a recovery action.

## Start ahead of time and inspect

```bash
lmux server start --name build --workspace /absolute/path/to/project
lmux status
lmux status --server build
lmux logs --server build --limit 20
```

Replace the example path with an existing workspace. Server start is scriptable
and creates neither a Mux nor a Session. The optional alias is separate from
Mux names. Repeating the same alias/workspace reuses the service; a different
workspace or a second alias for the same service conflicts rather than rebinds.
Successful startup returns exact service and instance IDs.

For an explicit, time-limited diagnostic request, use
`lmux server start --trace-for 60` (1–3600 seconds). The duration starts when
the command is prepared, not when startup finishes. Only a newly started
instance can apply this request; reusing a service never renews or replaces its
trace. Trace contains bounded timing aggregates and fixed problem codes, not
prompts, replies, tool bodies, or credentials.

The JSON result separates `service_ready` from `trace.status`: `applied` records
historical configuration, not a guarantee of future writes; `expired` means
that configuration's deadline has passed; `not_applied_reused_instance` means
this request did not configure the reused instance; `not_confirmed` means no
matching fact was confirmed within the startup budget.
`observation_failed` reports a separate safe `errorCode` if observation fails;
the already authenticated service/instance result is preserved. `deadlineMs`
uses this machine's monotonic clock, not Unix time. With a trace request,
only `applied` returns exit code 0; other trace outcomes return 1 even if the
service is ready. Trace failure does not stop a ready service.

`lmux ls` lists Mux reservations. Untargeted `status` also includes services
without Muxes. Status is explicitly `recorded_only` / `not_probed`, not a live
health check. Logs are bounded lifecycle tails, not complete history or
conversation content. Diagnostics never start a service.

## Detach, close, or stop

- `/detach`: leave this client; retain the service and sessions.
- `lmux close -t dev`: confirm closure of one Mux and its active members;
  persistent Session history is retained.
- `lmux stop --server build`: confirm stopping the service and affecting all
  Muxes it hosts. Exact service IDs are also accepted.
- `lmux stop --all`: confirm a frozen target set in this namespace, not all
  Loushang processes on the machine.

Noninteractive close/stop requires `--yes`; it does not force-kill or bypass
cleanup. Stop without a target does not guess from cwd. Preserve the operation
ID and follow-up command printed for incomplete closes. Historical close
reconciliation still requires an exact service ID, not an alias.

## Storage and preview upgrades

Management state and bounded lifecycle logs default to
`~/.loushang/lmux/machines/<machine>/`, partitioned by service ID. Targeted
status reports paths. Credentials and runtime control use a separate private
platform runtime namespace; `LOUSHANG_RUNTIME_DIR` overrides that root.
Do not treat live runtime control as disposable cache.
Durable admission witnesses also live under `$LOUSHANG_HOME/state/managed-deployments/`
(defaulting beneath `~/.loushang/state/`); they retain deployment identity and initialization records
and are not disposable cache either.

Instance scratch defaults to the service's `tmp/<instance-id>` directory,
with an explicit `LOUSHANG_TMPDIR` taking precedence. This does not yet impose
a disk quota on all tool output. Sessions retain their existing policy,
defaulting to `$LOUSHANG_HOME/data/sessions`; cwd and user_home are discovery
scopes, not separate default write stores.

`LOUSHANG_HOME` defaults to `~/.loushang`. Reconnect using the same user,
machine, and root overrides. Switching roots is not a way to bypass cleanup
or restart an uncertain old instance.

The current development Registry format is **14**. Older preview formats
are rejected without automatic migration. Do not delete state, locks, or
runtime records, or edit version numbers to bypass this refusal. Retain the
old state, use a matching old version to manage its service, and wait for an
explicit upgrade procedure. The legacy `loushang-mux` explicit-argument entry
remains separate and is not automatically imported or adopted.

See the [lmux contract record](../../internals/architecture/apphost/lmux-contract-m0.md)
for development and acceptance status.
