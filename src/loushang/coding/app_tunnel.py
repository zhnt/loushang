"""Provision an app-only credential for an externally protected loopback tunnel."""

from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path

from loushang.appserver.local import APP_TUNNEL_ENDPOINT
from loushang.appserver.local_record import (
    LocalConnectionDirectoryV1,
    LocalConnectionRecordV1,
    LocalRecordError,
    LocalRecordErrorCodeV1,
    encode_connection_record,
)


def read_app_tunnel(home: Path) -> LocalConnectionRecordV1 | None:
    directory = LocalConnectionDirectoryV1(home / APP_TUNNEL_ENDPOINT)
    try:
        return directory.read(APP_TUNNEL_ENDPOINT)
    except LocalRecordError as error:
        if error.code != LocalRecordErrorCodeV1.NOT_FOUND:
            raise
        return None
    finally:
        directory.close()


def provision_app_tunnel(home: Path, port: int) -> Path:
    """Create a new credential without touching the running or local endpoint."""
    from secrets import token_bytes, token_hex

    from .managed_process import APPLICATION_ID

    record = LocalConnectionRecordV1(
        endpoint=APP_TUNNEL_ENDPOINT,
        application_id=APPLICATION_ID,
        product_id="coding",
        port=port,
        instance=token_hex(16),
        key=token_bytes(32),
        scopes=(),
        session_discovery=True,
        session_execution=True,
        mux_management=True,
        mux_closure=True,
    )
    directory = home / APP_TUNNEL_ENDPOINT
    directory.mkdir(mode=0o700)
    name = sha256(APP_TUNNEL_ENDPOINT.encode()).hexdigest() + ".json"
    path = directory / name
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encode_connection_record(record))
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        directory.rmdir()
        raise
    return path
