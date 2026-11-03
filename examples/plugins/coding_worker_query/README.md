# Explicit Coding Worker candidate

This example is a single read-only `capability.query` Provider. The executable
accepts the bounded canonical frames of the current H6 query profile and
responds to the symbol `review` with `Review symbol`. It requests no file or
network authority. The following commands build and smoke a Linux x86-64 or
Windows AMD64 candidate. They do not select the Worker in a real workspace or
change the default Coding route.

From the Loushang repository root, with the Loushang CLI entry points installed:

```sh
example_dir="$(pwd)/examples/plugins/coding_worker_query"
build_dir="/absolute/path/to/a/new-build-directory"
mkdir -p "$build_dir"
cc -static -O2 -s -Wall -Wextra -Werror \
  -o "$build_dir/query-worker" "$example_dir/query_worker.c"
loushang-plugin build-coding-worker-candidate "$build_dir/query-worker" \
  --plugin-id reviewworker --version 1 \
  --contribution-id query-provider --owner-id coding \
  --native-platform linux-x86_64 --output-dir "$build_dir"
loushang-coding-plugin-smoke \
  "$build_dir/reviewworker-1-py3-none-manylinux_2_17_x86_64.whl" \
  --kind worker --plugin-id reviewworker \
  --contribution-id query-provider --owner-id coding
```

From the repository root in an x64 Native Tools Command Prompt for Visual
Studio, with the Loushang CLI entry points installed, build the Windows
candidate from the same source:

```bat
set "example_dir=%CD%\examples\plugins\coding_worker_query"
set "build_dir=C:\absolute\path\to\a\new-build-directory"
mkdir "%build_dir%"
cl /nologo /O2 /MT /Fo:"%build_dir%\query_worker.obj" ^
  /Fe:"%build_dir%\query-worker.exe" "%example_dir%\query_worker.c" ^
  /link /SUBSYSTEM:CONSOLE /MANIFEST:NO
loushang-plugin build-coding-worker-candidate "%build_dir%\query-worker.exe" ^
  --plugin-id reviewworker --version 1 --contribution-id query-provider ^
  --owner-id coding --native-platform windows-amd64 --output-dir "%build_dir%"
loushang-coding-plugin-smoke ^
  "%build_dir%\reviewworker-1-py3-none-win_amd64.whl" ^
  --kind worker --plugin-id reviewworker ^
  --contribution-id query-provider --owner-id coding
```

The smoke uses a disposable Product workspace. A passing result establishes
`productAdmission: passed` and `productSelection: passed`; `nativeRelease` and
`productUse` remain `not_checked`. Do not read that result as approval to run
the executable in another workspace.

The P4 ordinary-turn candidate has four separate checkpoints:

| Checkpoint | Evidence to retain |
| --- | --- |
| Inert Wheel | Builder digest and disposable smoke admission/selection result |
| Native release | `loushang-worker-native review`, `approve`, `install`, and exact release status |
| Workspace selection | `candidate-capture`, install, enable, allow, then current `candidate-status` for the same Plugin and revision |
| Product turn | A new persisted `coding-standard` Session with `--worker-query-plugin reviewworker`, its startup selection receipt, and a `worker_query_symbol` Tool result in the transcript |

The Linux checkpoint was approved for the explicit x86-64 scope in
[PR #653](https://github.com/zhnt/loushang/pull/653). This authored Wheel on
Windows requires its own native Product Session result. Each installation needs
its exact native release, current Product selection, per-install opt-in, and a
host that passes the platform query containment profile. The CLI request never
changes the default route.

To use an exact Wheel in an already fenced Coding workspace, follow the
[Worker operator sequence](../../../docs/internals/architecture/harness/plugin/plugin-authoring-guide.md):
capture and install the candidate, enable its exact revision, approve and
install the native H6 release, record per-install opt-in, then use an explicit
Python SDK Session on Linux, the P4 explicit ordinary-turn flag on the accepted
platform, or the bounded Linux `loushang-worker-native query` command. The
same guide covers version update, revocation, removal, and offline Package GC.
The Product checks those stages independently. This example does not open
dependency-bearing Workers, general third-party self-service, Windows author
activation without its native Product proof, or a default Worker route.
