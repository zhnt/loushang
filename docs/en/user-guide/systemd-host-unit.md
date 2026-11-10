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
StateDirectory=loushang-host
StateDirectoryMode=0700
ExecStart=%h/.local/bin/loushang-mux --connection-root "%t/loushang-host/connections" --endpoint workspace serve --systemd --workspace "%h" --application-root "%S/loushang-host/application" --cwd-sessions "%h/.loushang/data/workspace-sessions" --home-sessions "%h/.loushang/data/sessions"
KillMode=mixed
TimeoutStartSec=75s
TimeoutStopSec=40s
Restart=on-failure
RestartSec=2s

[Install]
WantedBy=default.target
```
