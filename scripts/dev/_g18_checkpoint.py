"""Opt-in Linux collection checkpoints, not process recovery or acceptance.

Only a committed pause is resumable. Consume it durably before any probe or
mutable operation; never roll back an in-flight/failed attempt to an old pause.
Files live in a trusted task-owned directory, not an authenticated archive.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import platform
import stat
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


class Paused(Exception):
    """The collector committed a safe checkpoint and must return without work."""


def now():
    return datetime.now(timezone.utc).isoformat()


def identity(path):
    path = Path(path)
    info = path.lstat()
    if path.resolve() != path or not stat.S_ISDIR(info.st_mode):
        raise ValueError("checkpoint directory must be canonical and real")
    return [info.st_dev, info.st_ino]


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024 * 1024:
        raise ValueError("invalid checkpoint JSON file")
    return json.loads(path.read_text())


def durable_write(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".checkpoint-next")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        # An incomplete publication is evidence, not permission to reuse a token.
        raise


def machine():
    return {
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "node": platform.node(),
        "platform": platform.platform(),
        "python": sys.version,
        "interpreter": str(Path(sys.executable).resolve()),
        "affinity": sorted(os.sched_getaffinity(0)),
        "uid": os.getuid(),
    }


def tree_manifest(root):
    """Read-only state seal, including symlink targets without following them."""
    root = Path(root)
    identity(root)
    result = {}
    pending = [root]
    size = 0
    while pending:
        path = pending.pop()
        info = path.lstat()
        entry = {
            "mode": stat.S_IMODE(info.st_mode),
            "identity": [info.st_dev, info.st_ino],
        }
        if stat.S_ISDIR(info.st_mode):
            entry["kind"] = "directory"
            pending.extend(path.iterdir())
        elif stat.S_ISLNK(info.st_mode):
            entry.update(kind="symlink", target=os.readlink(path))
        elif stat.S_ISREG(info.st_mode):
            size += info.st_size
            if size > 512 * 1024 * 1024:
                raise ValueError("checkpoint tree exceeds size bound")
            entry.update(
                kind="file",
                size=info.st_size,
                mtime_ns=info.st_mtime_ns,
                sha256=file_hash(path),
            )
        else:
            raise ValueError("non-regular checkpoint state")
        result[path.relative_to(root).as_posix()] = entry
        if len(result) + len(pending) > 100000:
            raise ValueError("checkpoint tree exceeds entry bound")
    return result


def schedule(cases, blocks, pairs):
    return [
        (block, pair, case, side)
        for block in range(blocks)
        for pair in range(-1, pairs)
        for case in (cases if block % 2 == 0 else list(reversed(cases)))
        for side in (("a", "b") if (block + pair) % 2 == 0 else ("b", "a"))
    ]


def validate_prefix(report):
    expected = schedule(report["cases"], report["blocks"], report["pairs_per_block"])
    samples = report["samples"]
    if not samples or len(samples) >= len(expected):
        raise ValueError("resume requires a nonempty incomplete observation prefix")
    for index, (sample, wanted) in enumerate(zip(samples, expected), 1):
        actual = tuple(sample[key] for key in ("block", "pair", "case", "side"))
        if (
            actual != wanted
            or sample.get("status") != "complete"
            or sample.get("valid") is not True
            or sample.get("failure") is not None
            or sample.get("warmup") != (wanted[1] == -1)
            or sample.get("iteration", index) != index
        ):
            raise ValueError(
                "checkpoint contains an incomplete or non-prefix observation"
            )


def evidence_files(report):
    """Existing raw/cache receipts already bound by the native collector."""
    paths = set()
    for sample in [*report.get("seed_setup", []), *report["samples"]]:
        if "receipt" in sample:
            if (
                "receipt_sha256" in sample
                and file_hash(sample["receipt"]) != sample["receipt_sha256"]
            ):
                raise ValueError("raw observation changed before checkpoint")
            paths.add(sample["receipt"])
        for value in sample.get("cache", {}).values():
            path = Path(value["path"])
            if file_hash(path) != value["sha256"]:
                raise ValueError("cache receipt changed before checkpoint")
            paths.add(str(path))
    return paths


def request_pause(output):
    output = Path(output).absolute()
    value = read_json(output / "checkpoint.json")
    if value.get("version") != 1 or value.get("phase") != "inflight":
        raise ValueError("only a running checkpoint-enabled campaign can be paused")
    request = {"run_id": value["run_id"], "segment": value["segment"], "at": now()}
    path = output / f"pause-request-{value['segment']}.json"
    if path.exists():
        old = read_json(path)
        if (old.get("run_id"), old.get("segment")) != (
            request["run_id"],
            request["segment"],
        ):
            raise ValueError("stale pause request")
        return
    durable_write(path, request)


class Campaign:
    @staticmethod
    def is_pause(error):
        return isinstance(error, Paused)

    def __init__(self, output, *, resume=False, pause_after=None):
        if sys.platform != "linux":
            raise ValueError("checkpoint collection is Linux-only")
        self.output = Path(output).absolute()
        self.resuming = resume
        self.pause_after = pause_after
        self.fd = None
        self.consumed = False
        self.report = None
        self.resources = None

    def __enter__(self):
        if not self.resuming:
            self.output.mkdir(parents=True, exist_ok=False)
        self.output_identity = identity(self.output)
        self.path = self.output / "checkpoint.json"
        lock = self.output / "checkpoint.lock"
        self.fd = os.open(
            lock, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600
        )
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            info = os.fstat(self.fd)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("checkpoint lock is not a regular file")
            self.lock_identity = [info.st_dev, info.st_ino]
            if self.resuming:
                self.value = read_json(self.path)
                if (
                    self.value.get("version") != 1
                    or self.value.get("phase") != "paused"
                    or self.value.get("output_identity") != self.output_identity
                    or self.value.get("lock_identity") != self.lock_identity
                    or self.value.get("machine") != machine()
                ):
                    raise ValueError("checkpoint is not a compatible safe pause")
                # A leftover failed write is ambiguous even if the older file parses.
                if list(self.output.glob("*.checkpoint-next")):
                    raise ValueError("checkpoint publication was interrupted")
                report_path = self.output / "report.json"
                if file_hash(report_path) != self.value["report_sha256"]:
                    raise ValueError("report/checkpoint mismatch")
                self.report = read_json(report_path)
                if (
                    self.report.get("schema_version") != 3
                    or self.report.get("status") != "paused"
                ):
                    raise ValueError("legacy or non-paused report cannot resume")
                validate_prefix(self.report)
                if len(self.report["samples"]) != self.value["next_index"]:
                    raise ValueError("checkpoint cursor mismatch")
                for name, digest in self.value["evidence"].items():
                    if file_hash(name) != digest:
                        raise ValueError("raw evidence changed during pause")
                self.resources = self.value["resources"]
            else:
                self.value = {
                    "version": 1,
                    "phase": "inflight",
                    "run_id": uuid.uuid4().hex,
                    "segment": 0,
                    "output_identity": self.output_identity,
                    "lock_identity": self.lock_identity,
                    "machine": machine(),
                }
                self._write()
                self.consumed = True
            return self
        except BaseException:
            os.close(self.fd)
            self.fd = None
            raise

    def _write(self):
        if identity(self.output) != self.output_identity:
            raise ValueError("checkpoint output identity changed")
        info = (self.output / "checkpoint.lock").lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or [info.st_dev, info.st_ino] != self.lock_identity
        ):
            raise ValueError("checkpoint lock identity changed")
        durable_write(self.path, self.value)

    def begin(self, report, plan):
        if self.resuming:
            if self.pause_after is not None and self.pause_after <= len(
                report["samples"]
            ):
                raise ValueError(
                    "pause-after must exceed the completed observation count on resume"
                )
            if report["checkpoint_plan"] != plan:
                raise ValueError("resume plan or immutable inputs changed")
            self.value.update(phase="inflight", segment=self.value["segment"] + 1)
            self._write()  # Consume the old pause before probes, restore or cache work.
            self.consumed = True
        else:
            report.update(schema_version=3, checkpoint_plan=plan, segments=[])
        report["status"] = "running"
        report["segments"].append(
            {
                "number": self.value["segment"],
                "started_at_utc": now(),
                "first_index": len(report["samples"]),
                "load_before": os.getloadavg(),
            }
        )
        report["segmented_acceptance"] = {
            "eligible_for_automatic_acceptance": not self.resuming,
            "reason": "resumed segments require separately declared calibration and environment audit"
            if self.resuming
            else "single uninterrupted segment; original gates still required",
        }

    def wants_pause(self, report):
        count = len(report["samples"])
        total = len(
            schedule(report["cases"], report["blocks"], report["pairs_per_block"])
        )
        if not count or count == total:
            return False  # Completion always includes the original final verification.
        requested = self.pause_after is not None and count >= self.pause_after
        path = self.output / f"pause-request-{self.value['segment']}.json"
        if path.exists():
            value = read_json(path)
            if (value.get("run_id"), value.get("segment")) != (
                self.value["run_id"],
                self.value["segment"],
            ):
                raise ValueError("foreign or stale pause request")
            requested = True
        return requested

    def pause(self, report, resources):
        validate_prefix(report)
        report["status"] = "paused"
        report["comparison"] = {
            "verdict": "not-evaluated",
            "reason": "collection paused",
        }
        report["segments"][-1].update(
            ended_at_utc=now(),
            next_index=len(report["samples"]),
            reason="requested pause",
        )
        evidence = {}
        for name in evidence_files(report):
            with Path(name).open("rb") as stream:
                evidence[name] = hashlib.file_digest(stream, "sha256").hexdigest()
                os.fsync(stream.fileno())
        durable_write(self.output / "report.json", report)
        self.value.update(
            phase="paused",
            report_sha256=file_hash(self.output / "report.json"),
            next_index=len(report["samples"]),
            resources=resources,
            evidence=evidence,
        )
        self._write()
        raise Paused

    def finish(self, report):
        report["segments"][-1].update(
            ended_at_utc=now(), next_index=len(report["samples"])
        )
        self.value["phase"] = "complete"
        durable_write(self.output / "report.json", report)
        self._write()

    def __exit__(self, kind, error, traceback):
        try:
            if kind is not None and self.consumed:
                self.value["phase"] = "failed"
                try:
                    self._write()
                except BaseException as publication_error:
                    error.add_note(
                        f"checkpoint failure publication also failed: {publication_error!r}"
                    )
        finally:
            if self.fd is not None:
                os.close(self.fd)
        return False
