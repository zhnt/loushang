# Windows package acceptance

The Windows 10 x64 desktop run used `lane/gui` at `f3e75c93b`, which matched
`main` after fetching from `origin`. The tests ran in the dedicated
`feature/gui-windows-package-acceptance` worktree on November 18, 2026.

## Standalone binaries

- `npm run tauri -- build --no-bundle` built the native release executable
  with the production frontend. The relocated GUI opened a responsive native
  window with a fresh data directory, no AppHost, and a system-only `PATH`.
- `scripts/gui/build_windows_tui.py` built the single-file TUI with CPython
  3.11.15 and PyInstaller 6.22.3. The relocated executable returned `0.1.0`
  from `--version` and printed its CLI help. It reached idle in Windows ConPTY
  and `/quit` returned exit code 0.
- Both tests ran from temporary directories outside the source checkout.

## Full installer

The first installer build hit `EPERM` when `npm ci` tried to replace the Tauri
CLI module that the standalone GUI build still had open. The retry started
after the standalone build exited.

`scripts/gui/build_windows_full.py` produced
`loushang-gui_0.1.0_x64-setup.exe` (293,831,029 bytes) with the offline WebView2
runtime. The installer SHA-256 was
`7faf3258004255345b1f6a53a61e8722ae46829f9a72c9e156f1697f460371c1`.

`scripts/gui/check_windows_full.ps1` passed on a signed-in desktop with a
fresh Loushang install and isolated `LOUSHANG_HOME`:

- Silent install laid down the GUI, TUI, Web, Mux, bundled Python, Web assets,
  and VC runtime. The installed TUI returned `0.1.0` and the GUI opened before
  AppHost was started.
- AppHost started, restarted under a new instance ID, and stopped cleanly.
  The installed Web service served HTML over loopback, connected to that same
  AppHost instance, and registered and listed a temporary workspace.
- Silent uninstall removed the installed program and preserved `host.json`.
  Teardown removed the isolated test directory and verified that no test
  installation entry, shortcut, or process remained.

## GUI checks

`npm run check` passed TypeScript and all 165 Vitest tests across 22 files
with `VITEST_MAX_WORKERS=2`. The default worker run overlapped the native
release build and hit four 5-second test timeouts. The repeat used the
original timeouts.
