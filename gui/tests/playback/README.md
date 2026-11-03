# GUI-B1 playback evidence

The committed case manifest is the minimum first-slice inventory. L0 and L1
run under `pnpm run test`; L2 requires the named native platform and cannot be
replaced by the Web Mock.

## Windows baseline — 2026-09-10

- Host: Windows x86_64, Rust `1.98.1` with the MSVC target, Node `24.19.0`,
  pnpm `11.19.0`.
- `pnpm run check`: TypeScript, production Web build, four Vitest checks,
  rustfmt, default/fixture Clippy, and default/fixture Cargo checks passed.
- Browser interaction: switched two sessions, retained separate drafts,
  submitted one prompt, applied two stream deltas, opened the fixture Diff,
  interrupted the execution, and observed no console warnings.
- `pnpm run dev:fixture-native`: Windows UI Automation identified the exact
  `harness-gui.exe` window and read `Rust invoke + event verified` from its
  accessibility tree.
- `pnpm run dev`: the same window reported `Native bridge locked`, proving the
  fixture command is not registered by the default feature set.

This is not macOS/Linux L2 evidence and does not claim native IME, clipboard,
DPI, packaging, real AppService transport, or B2 completion. The Windows
Graphics Capture provider returned unsupported for this WebView; the successful
canary evidence is the native window identity plus accessibility tree, while
the browser slice has a visual screenshot from the same layout.
