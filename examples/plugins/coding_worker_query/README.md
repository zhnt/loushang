# Explicit Coding Worker candidate

This example is a single read-only `capability.query` Provider. The executable
accepts the bounded canonical frames of the current H6 query profile and
responds to the symbol `review` with `Review symbol`. It requests no file or
network authority. The following build and smoke run on Linux x86-64; they do
not select the Worker in a real workspace or change the default Coding route.

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

The smoke uses a disposable Product workspace. A passing result establishes
`productAdmission: passed` and `productSelection: passed`; `nativeRelease` and
`productUse` remain `not_checked`. Do not read that result as approval to run
the executable in another workspace.

To use this exact Wheel in an already fenced Linux Coding workspace, follow the
[Worker operator sequence](../../../docs/internals/architecture/harness/plugin/plugin-authoring-guide.md):
capture and install the candidate, enable its exact revision, approve and
install the native H6 release, record per-install opt-in, then use an explicit
Python SDK Session or the bounded `loushang-worker-native query` command. The
same guide covers version update, revocation, removal, and offline Package GC.
The Product checks those stages independently. This example does not open
dependency-bearing Workers, general third-party self-service, Windows author
activation, or a default Worker route.
