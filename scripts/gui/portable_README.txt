Loushang Linux x86_64 portable candidate

Extract the whole archive, then double-click the native executable named
"loushang". Keep the other extracted
files beside it. This entry is an ELF program, not a shell script; executable
permissions are included in the tar archive.

Includes the native GUI, CPython 3.11, Loushang/AppHost and locked Python runtime
dependencies. Does not require Python, uv, Node, npm or Rust on the target machine.
This is a Linux desktop package, not a statically linked operating system image.
The host must provide compatible glibc, GTK 3, WebKitGTK 4.1, libayatana-appindicator3
and their system dependencies. This candidate is built and tested on Ubuntu 26.10
x86_64; compatibility with other distributions is not yet established.

Choose Start and connect in the desktop. Use the Host settings to stop or
restart AppHost. Closing the GUI leaves AppHost running.
The same operations are available through ./loushang-mux service.
AppHost state stays outside the package in LOUSHANG_HOME (default ~/.loushang).
Stop the host before moving/removing the extracted application directory.
Existing workspace settings and normal user provider configuration are used.
Credentials, user settings, sessions and model API access are NOT included.
Configure your normal Loushang provider before sending real model requests.

This candidate does not register a desktop shortcut, install system packages,
configure automatic startup, or include optional external tools such as Git,
language servers or plugin-specific worker runtimes. It is not a signed release.
