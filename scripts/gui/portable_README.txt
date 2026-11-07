Loushang Linux x86_64 portable candidate

Extract the whole archive, then run:
  ./loushang --workspace /absolute/path/to/your/workspace

Includes the native GUI, CPython 3.11, Loushang/AppHost and locked Python runtime
dependencies. Does not require Python, uv, Node, npm or Rust on the target machine.
This is a Linux desktop package, not a statically linked operating system image.
The host must provide compatible glibc, GTK 3, WebKitGTK 4.1, libayatana-appindicator3
and their system dependencies. This candidate is built and tested on Ubuntu 26.10
x86_64; compatibility with other distributions is not yet established.

The launcher starts AppHost when needed and reuses it for subsequent windows.
Closing the GUI leaves AppHost running so sessions remain available. To stop it:
  ./loushang --workspace /same/workspace --stop
To inspect it:
  ./loushang --workspace /same/workspace --status

AppHost state is separate from the extracted application, beneath
$XDG_STATE_HOME/loushang/desktop/v1 (default ~/.local/state/loushang/desktop/v1),
keyed by the resolved workspace path. --state-root overrides the parent directory.
Keep using the same state root and workspace when replacing this package.
Stop the host before moving/removing the extracted application directory.
Existing workspace settings and normal user provider configuration are used.
Credentials, user settings, sessions and model API access are NOT included.
Configure your normal Loushang provider before sending real model requests.

This candidate does not register a desktop shortcut, install system packages,
configure automatic startup, or include optional external tools such as Git,
language servers or plugin-specific worker runtimes. It is not a signed release.
