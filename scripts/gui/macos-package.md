# macOS installed package acceptance

Build and install a native PKG following the [Full packaging guide](../build/README.md).

Install the package, then open `/Applications/loushang-gui.app`. Commands are
available as `loushang`, `loushang-gui`, `loushang-web`, `loushang-mux` and
`loushang-host`. Start the backend through GUI Host settings or:

```sh
loushang-mux service start
loushang-mux service status --json
loushang-mux service logs
loushang-mux service stop
```

The Host stays alive when the GUI exits. Start it on demand from the GUI or
with the CLI. Configure provider credentials in Loushang or in the environment
of the command that starts AppHost, then restart AppHost to apply changes.

For an upgrade from a launchd-based installation, close the GUI and run
`loushang-mux service stop` using the old installation before replacing it.
If a start returns `legacy_service_active`, unload the old job and retry.
To locate it, read the Label in
`~/.loushang/state/macos-host/host.plist` (use your configured product home if
different), then run `launchctl bootout "user/$(id -u)/<Label>"`.
Keep the old state directory. Managed Service uses the same workspace and
Session locations and imports the existing Mux records on first start.
Close all Loushang programs before replacing the package.

Run `uv run --no-project --python 3.11 python scripts/gui/check_macos_package.py`
on the target Mac after installation. The Mach-O and PKG minimum version checks
set the deployment target. Actual macOS 12 installation remains to be verified.
