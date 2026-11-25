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

The Host stays alive when the GUI exits. It is not enabled for automatic login
startup. Supply provider credentials through normal application configuration
or the user launchd environment, then restart the Host to apply changes.
Close the GUI and stop the Host before replacing this test installation.

Run `uv run --no-project --python 3.11 python scripts/gui/check_macos_package.py`
on the target Mac after installation. The Mach-O and PKG minimum version checks
set the deployment target. Actual macOS 12 installation remains to be verified.
