# Optional external systemd unit for an explicit foreground AppHost

This example runs `loushang-mux serve` directly. Save it under a separate
unit name, such as `~/.config/systemd/user/loushang-foreground.service`.
Adjust the executable and data paths for your installation.

```ini
[Unit]
Description=Loushang foreground Coding AppHost

[Service]
Type=notify
WorkingDirectory=%h
RuntimeDirectory=loushang-foreground
RuntimeDirectoryMode=0700
StateDirectory=loushang-foreground
StateDirectoryMode=0700
ExecStart=%h/.local/bin/loushang-mux --connection-root %t/loushang-foreground/connections --endpoint workspace serve --systemd --workspace %h --application-root %S/loushang-foreground/application --cwd-sessions %S/loushang-foreground/cwd-sessions --home-sessions %S/loushang-foreground/home-sessions
TimeoutStopSec=40s

[Install]
WantedBy=default.target
```

Use `systemctl --user` with this unit name. Configure your client with the
absolute connection record directory or pass it explicitly to `loushang-mux`.
