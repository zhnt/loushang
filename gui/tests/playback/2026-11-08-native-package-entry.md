# Native package entry acceptance

Date: 2026-11-08. Base: `lane/gui` at `77dc56f70`.

The user reported that double-clicking the portable package's `loushang` opened
a terminal. The entry was an executable shell script, whose desktop handling
depends on the file manager's script policy. Replace it with a small native
Linux ELF entry that resolves its own package directory and execs the packaged
Python launcher with isolated mode and unchanged argument boundaries.

The build explicitly produces ELF ET_EXEC so desktop MIME detection identifies
it as `application/x-executable`, not a text script or shared library. No terminal
settings, file associations, AppHost protocol or session storage were changed.
Existing `--workspace`, `--status`, `--start-only` and `--stop` behavior is retained.

## Checks

- Rust entry compiled with the pinned toolchain and warnings denied; rustfmt passed.
- Ruff and diff whitespace checks passed.
- `npm --prefix gui run check:full` passed, including 92 frontend tests and native
  format/Clippy/check steps.
- Rebuilt the complete package, reusing the byte-identical accepted GUI binary;
  the changed native entry was freshly compiled. The package remains approximately
  53 MiB and includes its own Python/AppHost dependencies.
- Extracted outside the checkout to `/tmp/Loushang double click/`.
- `file` reports ELF executable; GIO reports `application/x-executable` and
  `access::can-execute: TRUE`.
- Real packaged lifecycle checks passed with a new regression asserting ELF
  magic, ET_EXEC type and executable permissions. Relocation, paths with spaces,
  host reuse and retained-mux restart passed.
- GNOME GIO launched the root executable with `AppInfoCreateFlags.NONE` (no
  terminal), using the default desktop display backend. The actual GUI showed
  `已连接`, the `desktop` mux and a real AppHost session. AT-SPI application
  inventory showed the GUI and no new terminal application.

This desktop acceptance used GNOME's no-terminal launch API rather than claiming
a reliable physical double-click replay: global mouse movement was ignored by
the current Wayland automation setup, and an attempted file-manager replay opened
the internal `bin/harness-gui` instead. That internal binary alone lacks the
AppHost launcher parameters and shows the offline fixture. The documented user
entry is the package-root `loushang`, not `bin/harness-gui` or the Python file.

Existing developer windows were preserved. Temporary D-Bus tools were only
downloaded/extracted under `/tmp` for the isolated file-manager attempt, not
installed on the system or included in the product package. No provider request
was needed for this launcher-only change. Broader package/system-library limits
remain as documented in the portable README.
