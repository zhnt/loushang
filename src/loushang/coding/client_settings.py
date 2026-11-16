"""Coding client request policy over Host-owned connections and navigation."""

from __future__ import annotations

import sys
from pathlib import Path

from loushang.apphost.client_preferences import (
    ClientPreferences,
)
from loushang.apphost.client_preferences import (
    connection_list as connection_list,
)
from loushang.apphost.client_preferences import (
    connections as connections,
)
from loushang.apphost.client_preferences import (
    mutate_connections as mutate_connections,
)
from loushang.apphost.client_preferences import (
    remember_workspace as remember_workspace,
)
from loushang.apphost.client_preferences import (
    write_connections as write_connections,
)

TEMPORARY_WORKSPACE = "@temporary"


def settings_request(request: dict):
    if request.get("operation") == "connections/list":
        return connection_list()
    if request.get("operation") == "connections/select":
        selected = request["connectionId"]
        if selected not in {item["id"] for item in connection_list()["connections"]}:
            raise ValueError("unknown_connection")

        def select(value):
            if selected == "local":
                value.pop("defaultConnection", None)
            else:
                value["defaultConnection"] = selected

        mutate_connections(select)
        return connection_list()
    if request.get("operation") == "environment":
        return {
            "supported": sys.platform == "linux",
            "workspace": connections().get("lastWorkspace", ""),
            "connections": connection_list()["connections"],
        }
    if request.get("operation") == "remember-workspace":
        path = request["workspace"]
        if (
            not isinstance(path, str)
            or (path != TEMPORARY_WORKSPACE and not Path(path).is_absolute())
            or len(path) > 4096
        ):
            raise ValueError("invalid_workspace")
        remember_workspace(path)
        return {}
    if request.get("operation") == "preferences":
        return ClientPreferences().apply(
            request["scope"], request.get("action", "read"), request.get("session", "")
        )
    raise ValueError("unknown_operation")
