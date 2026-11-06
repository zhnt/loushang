# Loushang application artwork

Source: the user-supplied `Loushang-icons.zip` (2026-11-06).
`app-icon.png` is the supplied 1024 × 1024 blue square artwork. `mark.png`
and `mark.svg` are the supplied transparent variants, reserved for future
small-surface use. The transparent artwork differs slightly from the square
artwork; it is not a lossless vector source for the square version.

## Current integration

The square artwork generates the desktop assets in `../../src-tauri/icons`:
PNG sizes, Windows ICO/Appx logos and macOS ICNS. The existing
`tauri.conf.json` bundle paths stay stable. The browser favicon in
`../../public/favicon.ico` is the supplied square ICO, preserving its authored
small sizes. No tray, notification service, close-to-tray behavior or custom
icon loader is added here.

To regenerate with the locked Tauri CLI, run from `gui/`:

```sh
npm exec -- tauri icon assets/branding/app-icon.png --output /tmp/loushang-desktop-icons
```

Copy the files already present in `src-tauri/icons/` from that output directory
back into `src-tauri/icons/`. Do not add generated mobile assets to this desktop
shell. If the source artwork changes, also update `public/favicon.ico` with the
new ICO. See [Tauri app icons](https://v2.tauri.app/develop/icons/).

## Future user override proposal (not implemented)

Resolve the user configuration root through the future shared local
configuration facility; do not independently hard-code a home directory in
React or introduce another settings store. If that facility chooses
`~/.loushang`, a candidate convention is `<config-root>/gui/icons/app.png`
and an optional `<config-root>/gui/icons/tray.png`. These names are proposals,
not supported settings yet. An eventual settings picker should copy a chosen
image into that managed location rather than depend on its original path.

The native desktop integration owns reading and decoding overrides. Start with
square PNG, require bounded file size and decoded dimensions, and fall back to
the compiled default for missing, invalid or unreadable files. An invalid
override must not prevent startup or require resetting existing user state.
Replacing or removing an override should take effect at the next launch;
hot reload can be added separately. No local file access needs to be exposed to
the WebView to support this.

Apply overrides per supported native surface. Runtime window/tray images,
installed application/shortcut images, macOS Dock images and notification
identity have different platform rules; do not promise that changing one PNG
rewrites all of them. Keep the built-in bundle artwork as the installation
default. Verify each supported platform before advertising an override there.

When adding a tray, verify the transparent mark at 16–32 px on light and dark
panels. macOS template rendering needs a dedicated monochrome silhouette;
the supplied colored transparent SVG is not that asset. Add show/quit actions
and decide the window-close lifecycle as part of that feature, preserving
connection cleanup. See [Tauri system tray](https://v2.tauri.app/learn/system-tray/).
