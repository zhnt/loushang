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

The `macOS Intel Package` workflow supports manual builds with a `source_ref`.
It uploads the installer, checksum, manifest and native acceptance evidence as
`loushang-macos12-intel`. It does not run for pull requests or branch pushes.

Before that new workflow is present on the default branch, the existing
`Change-aware Quality` dispatch entry can run the package job from this task
branch without merging the GUI into main:

```sh
gh workflow run quality.yml --ref feature/gui-macos-intel-package -f macos_package=true
gh run list --workflow quality.yml --branch feature/gui-macos-intel-package
gh run view <run-id>
gh run download <run-id> -n loushang-macos12-intel
```

Once the standalone workflow entry is on the default branch:

```sh
gh workflow run macos-package.yml -f source_ref=lane/gui
```

No existing PR checks, trigger paths or required runner matrices are expanded.
The runner uses macOS 15 Intel, while native build and package minimum versions
target macOS 12. The evidence explicitly distinguishes those facts. An actual
macOS 12 Intel installation test is still needed. These artifacts are unsigned
test installers, not Developer ID signed/notarized releases.
