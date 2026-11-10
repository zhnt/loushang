# Complete Ubuntu deb candidate

Product source: `lane/gui` at `fcf96875e`.
Packaging task: `feature/gui-complete-deb`, dedicated worktree.
Platform: Ubuntu 26.10 amd64.

The test package includes the freshly compiled Tauri GUI/tray, CPython 3.11.15,
the installed Loushang wheel (including AppHost and AppService), hash-locked
Python dependencies and actual Web frontend assets. It installs under
`/opt/loushang` with a native `/usr/bin/loushang` entry and application menu icon.
The entry uses the current Product `gui_local_host` management interface and
passes the bundled interpreter to native GUI helpers. It does not enable the
legacy explicit-connection UI path. Saved remote selection remains authoritative.

## Validation

- Native release rebuilt from the dedicated worktree using the shared Cargo
  build cache; frontend production build and Rust release compilation passed.
- Change-aware checks against `lane/gui`: 116 GUI tests and 9 documentation
  checks passed. Focused Ruff check/format and diff whitespace checks passed.
- `check_deb_package.py` extracted the actual deb and followed its installed
  launcher symlink, outside the checkout, using a workspace containing spaces.
- Target processes had an isolated home and state, `PATH=/nonexistent`, no
  inherited provider credentials and no development Python import path.
- Package-local Python, AppHost, AppService and Coding import origins verified.
- Real Host startup, authenticated status, repeated-start reuse, normal stop,
  restart with a new instance and retained mux identity all passed. The checker
  stopped its test Host before removing temporary state.
- Web `index.html`, native GUI ELF and desktop entry syntax verified. Native
  Debian dependencies calculated from GUI, launcher, Python and extension ELFs;
  the stable-ABI libpython shim is represented by its scanned libpython target.
- An initial checker failure was caused by group-writable temporary home
  permissions from the host umask. The checker now explicitly creates private
  directories; production permission validation was retained.

This run did not install the package system-wide, call a provider, replay native
GUI interactions, or validate upgrades or other Ubuntu versions. The user will
test the desktop package. Optional external tools and Plugin worker runtimes
are not included. Systemd integration remains a separate delivery.

## Scope review

The implementing agent accepts the packaging composition within the authorized
deb test-package scope: process/Session ownership remains in existing AppHost
code, user settings and history remain outside the installation tree, no service
starts during installation, and no additional mandatory PR gate is introduced.
Running Hosts must be stopped before replacing/removing this candidate because
they use files from its installation tree. Lifecycle-safe automatic upgrade and
post-install integration remain open work; no user acceptance is claimed.
