"""One shared browser adapter per user directory, independent of desktop lifetime."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time

import httpx

from loushang.foundation.platform_paths import resolve_platform_home


def local_endpoint() -> tuple[str, str]:
    home = resolve_platform_home()
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    (home / "state").mkdir(mode=0o700, exist_ok=True)
    state = home / "state" / "web"
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    token_path = home / "auth" / "server" / "web-token"

    def existing():
        try:
            endpoint = json.loads((state / "endpoint.json").read_text())
            token = token_path.read_text().strip()
        except FileNotFoundError:
            return None
        url = endpoint["url"]
        # Discovery never grants arbitrary network access; local adapter only.
        from urllib.parse import urlsplit

        parsed = urlsplit(url)
        if (
            parsed.hostname not in {"localhost", "127.0.0.1"}
            or parsed.scheme != "http"
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("configure_tls_server_as_connection")
        try:
            with httpx.Client(timeout=2, trust_env=False) as client:
                response = client.post(
                    url + "/api/loushang",
                    json={"operation": "environment"},
                    headers={
                        "Authorization": "Bearer " + token,
                        "X-Loushang-Client": "1",
                    },
                )
                response.raise_for_status()
                if "result" not in response.json():
                    raise ValueError("invalid_adapter")
        except httpx.ConnectError:
            return None
        return url, token

    found = existing()
    if found:
        return found
    # Serialize startup across Vite processes and native helper invocations.
    with sqlite3.connect(state / "startup.sqlite3", timeout=30) as lock:
        lock.execute("BEGIN IMMEDIATE")
        found = existing()
        if found:
            return found
        with (state / "server.log").open("ab") as log:
            child = subprocess.Popen(
                [sys.executable, "-m", "loushang.coding.web_server"],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
                env=os.environ.copy(),
            )
        for _ in range(150):
            if child.poll() is not None:
                raise ValueError("adapter_start_failed")
            found = existing()
            if found:
                return found
            time.sleep(0.1)
        raise TimeoutError("adapter_start_timeout")
