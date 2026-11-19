# Build the macOS Intel installer

On an Intel Mac with the repository's Node/Rust toolchains and uv installed:

```sh
uv python install 3.11.15
rustup toolchain install 1.98.1 --profile minimal
rustup target add --toolchain 1.98.1 x86_64-apple-darwin
uv run --no-project --python 3.11 python scripts/gui/build_macos_full.py
```

The output is `dist/macos-full/loushang_<version>_<commit>_macos12_x86_64.pkg`,
with a SHA-256 checksum and native dependency manifest. The installer contains
GUI, Web, TUI, Mux and the backend Python runtime. Python, Node, uv and Homebrew
are not required on the destination machine.

Install the package, then open `/Applications/loushang-gui.app`. Commands are
available as `loushang`, `loushang-gui`, `loushang-web`, `loushang-mux` and
`loushang-host`. Start the backend through GUI Host settings or:

```sh
loushang-mux service start
loushang-mux service status --json
loushang-mux service logs
loushang-mux service stop
```

The Host stays alive when the GUI exits. It is not enabled for automatic login
startup. Supply provider credentials through normal application configuration
or the user launchd environment, then restart the Host to apply changes.
Close the GUI and stop the Host before replacing this test installation.

## GitHub Actions

Use [Package GUI](gui-package.md) with `platform=macos-x64-pkg` to build
the Intel test installer on demand. The workflow publishes the package,
checksum, and manifest as an Actions artifact. For installed verification,
run `check_macos_package.py` on the target Mac after installing the package.

The previously built installer and evidence remain downloadable from
[run 44276006846](https://github.com/zhnt/loushang/actions/runs/44276006846)
while its artifacts are retained:

```sh
gh run download 44276006846 -n loushang-macos12-intel
```

No existing PR checks, trigger paths or required runner matrices are expanded.
The runner uses macOS 15 Intel. The native build and package metadata target
macOS 12. An actual
macOS 12 Intel installation test is still needed. These artifacts are unsigned
test installers, not Developer ID signed/notarized releases.
