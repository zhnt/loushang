"""One supervised native observation, opened before its controller can spawn.

This is a test-only receipt guard, not a process observer or signal capability.
Only the native observer may complete it, after physical exit/reaping proof.
The supervisor keeps its expected token independently of the receipt file.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

ENVIRONMENT_KEY = "G17_NATIVE_OBSERVATION"


def _decode(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate native observation field")
            value[key] = item
        return value

    return json.loads(raw, object_pairs_hook=unique)


def _identities(controller, children):
    if (type(controller) is not int or controller <= 1 or type(children) is not list
            or not 1 <= len(children) <= 8
            or any(type(pid) is not int or pid <= 1 for pid in children)
            or len(set(children)) != len(children) or controller in children):
        raise ValueError("invalid native observation identities")


def _read(path):
    with Path(path).open(encoding="utf-8") as source:
        raw = source.read(4097)
    if len(raw) > 4096:
        raise ValueError("native observation receipt exceeds bound")
    value = _decode(raw)
    if (type(value) is not dict or type(value.get("token")) is not str
            or len(value["token"]) != 32
            or any(c not in "0123456789abcdef" for c in value["token"])
            or value.get("phase") not in {"unused", "open", "admitted", "unknown", "closed", "aborted"}):
        raise ValueError("invalid native observation receipt")
    expected = {"token", "phase"}
    if value["phase"] in {"admitted", "closed"} or (
        value["phase"] == "unknown" and "controller" in value
    ):
        expected |= {"controller", "children"}
    if set(value) != expected:
        raise ValueError("invalid native observation fields")
    if "controller" in value:
        _identities(value["controller"], value["children"])
    return value


def _publish(path, value):
    path = Path(path)
    pending = path.with_suffix(".pending")
    # All publication is serialized by the registry lock. A failed prior write
    # may leave this exact scratch path; retry replaces it, not the proof state.
    with pending.open("w", encoding="utf-8") as target:
        json.dump(value, target)
        target.flush()
        os.fsync(target.fileno())
    pending.replace(path)


@contextmanager
def _locked(root):
    import fcntl

    with (root / "registry.lock").open("r+") as lock:
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("native observation registry lock pending")
                time.sleep(0.01)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _registry(root):
    with (root / "registry.json").open(encoding="utf-8") as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError("native observation registry exceeds bound")
    entries = _decode(raw)
    if type(entries) is not dict or len(entries) > 128:
        raise ValueError("invalid native observation registry")
    for token, entry in entries.items():
        if (len(token) != 32 or any(c not in "0123456789abcdef" for c in token)
                or type(entry) is not dict or set(entry) != {"parent", "sealed"}
                or type(entry["sealed"]) is not bool):
            raise ValueError("invalid native observation scope")
        seen, current = set(), token
        while current is not None:
            if current in seen or current not in entries or len(seen) >= 32:
                raise ValueError("invalid native observation ancestry")
            seen.add(current)
            current = entries[current]["parent"]
    if entries and sum(entry["parent"] is None for entry in entries.values()) != 1:
        raise ValueError("ambiguous native observation root")
    return entries


def create(root, *, parent=None, observation=True):
    if parent is None:
        root = Path(root).resolve() / "native-observations"
        root.mkdir(mode=0o700)
        (root / "registry.lock").touch(mode=0o600)
        _publish(root / "registry.json", {})
    else:
        parent = Path(parent)
        if not parent.is_absolute() or parent.suffix != ".json":
            raise ValueError("invalid native observation parent")
        root = parent.parent
    with _locked(root):
        entries = _registry(root)
        current = parent.stem if parent is not None else None
        depth = 1
        if len(entries) >= 128:
            raise ValueError("native observation scope bound exceeded")
        while current is not None:
            depth += 1
            if depth > 32:
                raise ValueError("native observation ancestry bound exceeded")
            entry = entries[current]
            receipt = _read(root / f"{current}.json")
            if (receipt["token"] != current or entry["sealed"]
                    or receipt["phase"] in {"closed", "unknown", "aborted"}):
                raise RuntimeError("native observation registration sealed")
            current = entry["parent"]
        token = uuid.uuid4().hex
        path = root / f"{token}.json"
        _publish(path, {"token": token, "phase": "open" if observation else "unused"})
        entries[token] = {"parent": parent.stem if parent is not None else None, "sealed": False}
        _publish(root / "registry.json", entries)
    return {"path": path, "token": token}


def admit(path, controller, children):
    _identities(controller, children)
    with _locked(Path(path).parent):
        value = _read(path)
        if value["phase"] != "open":
            raise ValueError("native observation is not open")
        _publish(path, {**value, "phase": "admitted", "controller": controller, "children": children})


def unknown(path):
    with _locked(Path(path).parent):
        value = _read(path)
        if value["phase"] in {"closed", "aborted", "unused"}:
            raise ValueError("native observation is not active")
        _publish(path, {**value, "phase": "unknown"})


def complete(path):
    """Observer proved physical exit/reaping; any failed terminal verdict remains a test failure."""
    with _locked(Path(path).parent):
        value = _read(path)
        if value["phase"] == "closed":
            return  # Retrying publication after a lost acknowledgement is safe.
        if value["phase"] != "admitted":
            raise ValueError("native observation was not admitted or became unknown")
        _publish(path, {**value, "phase": "closed"})


def require_closed(ticket, *, not_started=False):
    try:
        root, token = ticket["path"].parent, ticket["token"]
        with _locked(root):
            entries = _registry(root)
            if ticket["path"].stem != token:
                raise ValueError("native observation owner changed")
            # This and registration share one interprocess lock. After sealing,
            # no descendant can register an observation and then spawn a child.
            entries[token]["sealed"] = True
            _publish(root / "registry.json", entries)
            for candidate in entries:
                current = candidate
                while current is not None and current != token:
                    current = entries[current]["parent"]
                if current is None:
                    continue
                path = root / f"{candidate}.json"
                value = _read(path)
                if value["token"] != candidate:
                    raise ValueError("native observation token changed")
                if not_started and candidate == token and value["phase"] == "open":
                    value = {**value, "phase": "aborted"}
                    _publish(path, value)
                if value["phase"] not in {"unused", "closed", "aborted"}:
                    raise ValueError("native observation not completed")
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise RuntimeError("native observation cleanup pending") from error
