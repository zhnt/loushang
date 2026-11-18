# AppHost systemd user unit

Save the following as `~/.config/systemd/user/loushang-host.service`.
Adjust the executable and data paths for your installation.

```ini
[Unit]
Description=Loushang Coding AppHost

[Service]
Type=notify
NotifyAccess=main
WorkingDirectory=%h
RuntimeDirectory=loushang-host
RuntimeDirectoryMode=0700
Environment=LOUSHANG_RUNTIME_DIR=%t/loushang-host
ExecStart=%h/.local/bin/loushang-mux service run
KillMode=mixed
TimeoutStartSec=75s
TimeoutStopSec=40s
Restart=on-failure
RestartSec=2s

[Install]
WantedBy=default.target
```
