"""Real original partial tree/FD lifetime; native ACL/attributes/epoch are ports."""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import importlib
import json
import os
import stat
import sys
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

from tests.coding import probe_windows_stage_capture_compatibility as shared

HERE = Path(__file__).parent
REAL_OS, ATTEMPT, BODY = shared.REAL_OS, shared.ATTEMPT, shared.BODY
CASES = (
    "valid-flat",
    "valid-nested",
    "valid-deep",
    "empty-stage",
    "nested-empty",
    "empty-file",
    "depth16-file",
    "depth16-empty",
    "depth17-directory",
    "acl-enter-error",
    "acl-exit-error",
    "root-enter-error",
    "root-exit-error",
    "root-validate-error",
    "root-fstat-error",
    "root-lstat-error",
    "root-mismatch",
    "stage-open-error",
    "stage-validate-error",
    "stage-unsafe",
    "stage-link-unsafe",
    "stage-stream-unsafe",
    "expected-stage-none",
    "expected-stage-mismatch",
    "stage-name-mismatch",
    "initial-list-error",
    "loop-list-error",
    "multiple-members",
    "marker-only",
    "marker-casefold",
    "invalid-name",
    "symlink-member",
    "child-open-error",
    "child-validate-error",
    "child-name-change",
    "child-initial-list-error",
    "child-loop-list-error",
    "child-multiple",
    "child-marker",
    "second-child-open-error",
    "second-child-validate-error",
    "executable-open-error",
    "executable-validate-error",
    "executable-too-large",
    "executable-read-error",
    "executable-short-read",
    "executable-after-change",
    "executable-name-change",
    "executable-close-error",
    "executable-overflow",
    "child-final-change",
    "child-final-list-change",
    "child-final-validate-error",
    "final-stage-fstat-error",
    "final-stage-change",
    "final-stage-name-change",
    "final-tree-change",
    "child-close-error",
    "child-and-stage-close-error",
    "body-and-child-close-error",
    "stage-close-error",
    "stage-and-root-close-error",
    "all-close-error",
    "public-constructor-error",
    "public-constructor-close-error",
    "public-constructor-stop",
    "public-constructor-cancel",
    "invalid-public-revision",
    "stop-file-read",
    "stop-file-and-child-close",
    "cancel-child-open",
    "cancel-executable-read",
    "keyboardinterrupt-file-read",
)
MATRIX_CASES = tuple(
    f"matrix-{body}-{mask:02d}"
    for body in ("normal", "value", "stop")
    for mask in range(1, 16)
)
CASES = (*CASES, *MATRIX_CASES)
SUCCESS = {
    "valid-flat",
    "valid-nested",
    "valid-deep",
    "empty-stage",
    "nested-empty",
    "empty-file",
    "depth16-file",
    "depth16-empty",
}


def seeded(case):
    root = HERE / "physical-inputs" / case
    stage = root / ("worker-payload-" + ATTEMPT)
    if not stage.exists():
        stage.mkdir(parents=True, mode=0o700)
        depth = (
            0
            if case
            in {
                "valid-flat",
                "empty-stage",
                "marker-only",
                "marker-casefold",
                "invalid-name",
                "symlink-member",
                "multiple-members",
            }
            else 1
            if case == "valid-nested"
            else 16
            if case.startswith("depth16")
            else 17
            if case == "depth17-directory"
            else 2
        )
        relative = (
            "/".join(["bin", "deep"][:depth])
            if depth <= 2
            else "/".join(f"d{i}" for i in range(depth))
        )
        parent = stage / relative
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if case not in {
            "empty-stage",
            "nested-empty",
            "depth16-empty",
            "depth17-directory",
        }:
            name = (
                "WORKER-PAYLOAD.JSON"
                if case == "marker-casefold"
                else "worker-payload.json"
                if case == "marker-only"
                else "bad\\name.exe"
                if case == "invalid-name"
                else "worker.exe"
            )
            executable = parent / name
            if case == "symlink-member":
                executable.symlink_to("/dev/null")
            else:
                executable.write_bytes(
                    b""
                    if case == "empty-file"
                    else b"123456789"
                    if case == "executable-overflow"
                    else BODY
                )
            if case == "executable-too-large":
                with executable.open("r+b") as stream:
                    stream.truncate(16 * 1024 * 1024 + 1)
        if case == "multiple-members":
            (stage / "extra").write_bytes(b"extra")
        if case == "child-multiple":
            (stage / "bin" / "extra").write_bytes(b"extra")
        if case == "child-marker":
            (stage / "bin" / "WORKER-PAYLOAD.JSON").write_bytes(b"marker")
    return root, stage


class Observer(shared.Observer):
    def __init__(self, case, root):
        super().__init__(case, root)
        self.fired = []

    def fail(self, event):
        self.add(event)
        if self.case.startswith("matrix-"):
            _, body, number = self.case.split("-")
            mask = int(number)
            selected = {
                event
                for bit, event in (
                    (1, "close:dir1"),
                    (2, "close:stage"),
                    (4, "root.exit"),
                    (8, "acl.exit"),
                )
                if mask & bit
            }
            if event == "public.construct" and body != "normal":
                self.fired.append(event)
                raise (ValueError if body == "value" else StopIteration)(
                    "injected " + event
                )
            if event in selected:
                self.fired.append(event)
                raise OSError("injected " + event)
            return
        target = {
            "acl-enter-error": "acl.enter",
            "acl-exit-error": "acl.exit",
            "root-enter-error": "root.enter",
            "root-exit-error": "root.exit",
            "root-validate-error": "acl.validate:root",
            "root-fstat-error": "fstat:root:1",
            "root-lstat-error": "root.lstat",
            "stage-open-error": "open.dir:stage",
            "stage-validate-error": "acl.validate:stage",
            "initial-list-error": "listdir:stage:1",
            "loop-list-error": "listdir:stage:2",
            "child-open-error": "open.dir:dir0",
            "child-validate-error": "acl.validate:dir0",
            "child-initial-list-error": "listdir:dir0:1",
            "child-loop-list-error": "listdir:dir0:2",
            "second-child-open-error": "open.dir:dir1",
            "second-child-validate-error": "acl.validate:dir1",
            "executable-open-error": "open.file:executable",
            "executable-validate-error": "acl.validate:executable",
            "executable-read-error": "read:executable:1",
            "executable-close-error": "close:executable",
            "child-final-validate-error": "fstat:dir0:2",
            "final-stage-fstat-error": "fstat:stage:2",
            "child-close-error": "close:dir1",
            "stage-close-error": "close:stage",
            "public-constructor-error": "public.construct",
            "public-constructor-close-error": "public.construct",
            "public-constructor-stop": "public.construct",
            "public-constructor-cancel": "public.construct",
            "stop-file-read": "read:executable:1",
            "stop-file-and-child-close": "read:executable:1",
            "cancel-child-open": "open.dir:dir0",
            "cancel-executable-read": "read:executable:1",
            "keyboardinterrupt-file-read": "read:executable:1",
        }.get(self.case)
        also = {
            "child-and-stage-close-error": {"close:dir1", "close:stage"},
            "body-and-child-close-error": {"read:executable:1", "close:dir1"},
            "stage-and-root-close-error": {"close:stage", "root.exit"},
            "all-close-error": {"close:dir1", "close:stage", "root.exit", "acl.exit"},
            "public-constructor-close-error": {"close:dir1", "close:stage"},
            "stop-file-and-child-close": {"close:dir1"},
        }.get(self.case, set())
        if event == target or event in also:
            self.fired.append(event)
            error = (
                asyncio.CancelledError
                if (
                    self.case.startswith("cancel-")
                    or self.case == "public-constructor-cancel"
                )
                and event == target
                else KeyboardInterrupt
                if self.case == "keyboardinterrupt-file-read"
                else StopIteration
                if self.case
                in {
                    "public-constructor-stop",
                    "stop-file-read",
                    "stop-file-and-child-close",
                }
                and event == target
                else ValueError
                if self.case.startswith("public-constructor-") and event == target
                else OSError
            )
            raise error("injected " + event)

    def open_dir(self, name, *, dir_fd, **kw):
        parent = self.role(dir_fd)
        role = (
            "stage"
            if parent == "root"
            else "dir0"
            if parent == "stage"
            else "dir" + str(int(parent[3:]) + 1)
        )
        self.fail("open.dir:" + role)
        fd = REAL_OS.open(
            name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd
        )
        self.acquire(fd, role, self.opened[dir_fd][1] / name)
        self.add("open.options", role=role, options=kw)
        return fd

    def stat_at(self, parent, name):
        parent_role = self.role(parent)
        raw = REAL_OS.stat(name, dir_fd=parent, follow_symlinks=False)
        role = (
            "stage"
            if parent_role == "root"
            else (
                "dir0"
                if parent_role == "stage"
                else "dir" + str(int(parent_role[3:]) + 1)
            )
            if stat.S_ISDIR(raw.st_mode)
            else "executable"
        )
        n = self.number("name.stat:" + role)
        self.fail(f"name.stat:{role}:{n}")
        v = self.metadata(raw, role)
        if (
            (self.case == "stage-name-mismatch" and role == "stage" and n == 1)
            or (self.case == "final-stage-name-change" and role == "stage" and n == 2)
            or (self.case == "child-name-change" and role == "dir0")
            or (self.case == "executable-name-change" and role == "executable")
        ):
            v.st_ino += 1
        self.add(
            "name.stat.result",
            role=role,
            identity=[v.st_dev, v.st_ino, v.st_nlink, v.st_size, v.st_mtime_ns],
        )
        return v

    def fstat(self, fd):
        v = super().fstat(fd)
        role = self.role(fd)
        n = self.counts["fstat:" + role]
        if (self.case == "child-final-change" and role == "dir0" and n == 2) or (
            self.case == "executable-overflow" and role == "executable" and n == 1
        ):
            if self.case == "child-final-change":
                v.st_ino += 1
            else:
                v.st_size = 8
            self.rows[-1]["identity"] = [
                v.st_dev,
                v.st_ino,
                v.st_nlink,
                v.st_size,
                v.st_mtime_ns,
            ]
        return v

    def listdir(self, fd):
        role = self.role(fd)
        n = self.number("listdir:" + role)
        self.fail(f"listdir:{role}:{n}")
        names = REAL_OS.listdir(fd)
        if (self.case == "child-final-list-change" and role == "dir0" and n == 3) or (
            self.case == "final-tree-change" and role == "stage" and n == 3
        ):
            names.append("later-added")
        self.add("listdir.result", role=role, names=sorted(names))
        return names


def observed(case):
    module = importlib.import_module(
        "loushang.coding.package_product_worker_windows_partial_stage_review"
    )
    io = importlib.import_module("loushang.harness.worker.payload._windows_stage_io")
    effect = importlib.import_module(
        "loushang.harness.package_product._worker_windows_attempt"
    )
    retirement = importlib.import_module(
        "loushang.harness.worker.payload._windows_stage_retirement"
    )
    consumption = importlib.import_module(
        "loushang.harness.resources.packages._file_consumption"
    )
    root, stage = seeded(case)
    observer = Observer(case, root)
    port = shared.OsPort(observer)
    metadata = stage.stat()
    expected = (metadata.st_dev, metadata.st_ino)
    if case == "expected-stage-none":
        expected = None
    if case == "expected-stage-mismatch":
        expected = (metadata.st_dev, metadata.st_ino + 1)
    product = NS(
        epoch_runtime=NS(borrow_product_state_root_descriptor=observer.root_borrow),
        state_root=NS(lstat=observer.root_lstat),
    )
    result = error = None
    with ExitStack() as patches:
        for owner in (module, effect, io):
            patches.enter_context(patch.object(owner, "os", port))
            for name, replacement in [
                ("open_windows_directory", observer.open_dir),
                ("windows_stat_at", observer.stat_at),
                ("windows_listdir_at", observer.listdir),
            ]:
                if hasattr(owner, name):
                    patches.enter_context(patch.object(owner, name, replacement))
        for owner in (module, effect):
            if hasattr(owner, "WindowsPrivateDirectoryAcl"):
                patches.enter_context(
                    patch.object(
                        owner, "WindowsPrivateDirectoryAcl", observer.acl_type()
                    )
                )
        patches.enter_context(
            patch.object(io, "open_windows_regular_file_at", observer.open_file)
        )
        for name in (
            "windows_directory_stream_names",
            "windows_regular_file_stream_names",
        ):
            patches.enter_context(patch.object(io, name, observer.streams))
        for owner in (consumption, retirement):
            patches.enter_context(patch.object(owner, "os", port))
        if case == "executable-overflow":
            patches.enter_context(patch.object(module, "_MAX_PAYLOAD_BYTES", 8))
        if case.startswith("public-constructor-") or case.startswith(
            ("matrix-value-", "matrix-stop-")
        ):

            def construct(self, **kw):
                observer.add(
                    "public.constructor.fields", fields=shared.value(tuple(kw.items()))
                )
                observer.fail("public.construct")

            patches.enter_context(
                patch.object(
                    module.CodingWindowsWorkerPartialStageReviewV1,
                    "__init__",
                    construct,
                )
            )
        try:
            review = module._review_partial_tree(
                product,
                attempt_id=ATTEMPT,
                expected_stage=expected,
                lease_owner_revision=True if case == "invalid-public-revision" else 7,
            )
            result = {
                "type": type(review).__module__ + "." + type(review).__qualname__,
                "fields": shared.value(review)["fields"],
                "wire": review.to_bytes().hex(),
                "fingerprint": review.fingerprint,
            }
        except BaseException as exc:
            error = shared.error_data(exc)
    outstanding = [role for role, _ in observer.opened.values()]
    for fd, (role, _path) in list(observer.opened.items()):
        REAL_OS.close(fd)
        observer.opened.pop(fd)
        observer.raw.append({"event": "observer.cleanup", "fd": fd, "role": role})
    assert (error is None) == (case in SUCCESS), (case, error)
    if case.endswith("-error") and case not in {"root-mismatch"}:
        assert observer.fired, case
    if case in {"public-constructor-stop", "stop-file-read"}:
        assert error["type"] == "builtins.StopIteration"
    if (case.startswith("matrix-") and int(case.rsplit("-", 1)[1]) & 1) or case in {
        "child-close-error",
        "child-and-stage-close-error",
        "body-and-child-close-error",
        "all-close-error",
        "public-constructor-close-error",
        "stop-file-and-child-close",
    }:
        assert outstanding == ["dir0"], (case, outstanding)
    else:
        assert outstanding == [], (case, outstanding)
    if case == "executable-overflow":
        assert (
            observer.counts.get("fstat:executable") == 1
            and observer.counts.get("read:executable") == 1
        )
    if case == "child-final-change":
        assert (
            observer.counts.get("fstat:dir1") == 1
            and observer.counts.get("fstat:stage") == 1
        )
    if case == "expected-stage-none":
        assert not observer.counts.get("name.stat:stage")
    return {
        "case": case,
        "result": result,
        "error": error,
        "trace": observer.rows,
        "fired": observer.fired,
        "outstanding_before_observer_cleanup": outstanding,
        "outstanding_after_observer_cleanup": [],
    }, observer.raw


PUBLIC_FQN = "loushang.coding.package_product_worker_windows_partial_stage_review.CodingWindowsWorkerPartialStageReviewV1"
DOMAIN = b"loushang.coding-windows-worker-partial-stage-review/v1\0"


def input_context(case, root):
    stage = root / ("worker-payload-" + ATTEMPT)
    depth = (
        0
        if case
        in {
            "valid-flat",
            "empty-stage",
            "marker-only",
            "marker-casefold",
            "invalid-name",
            "symlink-member",
            "multiple-members",
        }
        else 1
        if case == "valid-nested"
        else 16
        if case.startswith("depth16")
        else 17
        if case == "depth17-directory"
        else 2
    )
    parts = ["bin", "deep"][:depth] if depth <= 2 else [f"d{i}" for i in range(depth)]
    paths = {"root": root, "stage": stage}
    directories = {}
    for index in range(depth):
        name = "/".join(parts[: index + 1])
        role = "dir" + str(index)
        paths[role] = stage / name
        directories[name] = role
    has_file = case not in {
        "empty-stage",
        "nested-empty",
        "depth16-empty",
        "depth17-directory",
    }
    basename = (
        "WORKER-PAYLOAD.JSON"
        if case == "marker-casefold"
        else "worker-payload.json"
        if case == "marker-only"
        else "bad\\name.exe"
        if case == "invalid-name"
        else "worker.exe"
    )
    entrypoint = "/".join([*parts, basename]) if has_file else None
    data = (
        b""
        if case == "empty-file"
        else b"123456789"
        if case == "executable-overflow"
        else BODY
    )
    if has_file:
        paths["executable"] = stage / entrypoint
        if case != "symlink-member":
            with paths["executable"].open("rb") as file:
                assert file.read(len(data)) == data
    stats = {
        role: (v.st_dev, v.st_ino, v.st_nlink, v.st_size, v.st_mtime_ns)
        for role, path in paths.items()
        for v in (path.lstat(),)
    }
    assert len({v[:2] for v in stats.values()}) == len(stats), (
        "distinct physical roles required"
    )
    if has_file:
        assert stats["executable"][3] == (
            16 * 1024 * 1024 + 1
            if case == "executable-too-large"
            else len("/dev/null")
            if case == "symlink-member"
            else len(data)
        )
    return {
        "stats": stats,
        "paths": paths,
        "directory_roles": directories,
        "entrypoint": entrypoint,
        "bytes": data,
    }


def token(identity, role, context, case, event):
    if (case == "child-final-change" and event == "fstat:dir0:2") or (
        case == "executable-overflow" and event == "fstat:executable:1"
    ):
        before = context["stats"][role]
        inode_offset = 1 if case == "child-final-change" else 0
        size_offset = 8 - before[3] if case == "executable-overflow" else 0
        assert identity == [
            before[0],
            before[1] + inode_offset,
            1,
            before[3] + size_offset,
            before[4],
        ]
        return [
            "input.dev:" + role,
            "input.ino:" + role + "+" + str(inode_offset),
            1,
            "input.size:" + role + "+" + str(size_offset),
            "input.mtime:" + role + "+0",
        ]
    return shared._metadata_token(identity, role, context, case, event)


def expected_fields(context):
    def identity(role):
        v = context["stats"][role]
        return [v[0], v[1], 1, v[3], v[4]]

    return {
        "attempt_id": ATTEMPT,
        "lease_owner_revision": 7,
        "stage_identity": identity("stage"),
        "directory_identities": [
            [name, identity(role)] for name, role in context["directory_roles"].items()
        ],
        "entrypoint": context["entrypoint"],
        "executable_identity": None
        if context["entrypoint"] is None
        else identity("executable"),
        "executable_digest": None
        if context["entrypoint"] is None
        else hashlib.sha256(context["bytes"]).hexdigest(),
    }


def public_document(fields):
    assert set(fields) == {
        "attempt_id",
        "lease_owner_revision",
        "stage_identity",
        "directory_identities",
        "entrypoint",
        "executable_identity",
        "executable_digest",
    }
    return {
        "attemptId": fields["attempt_id"],
        "directoryIdentities": fields["directory_identities"],
        "entrypoint": fields["entrypoint"],
        "executableDigest": fields["executable_digest"],
        "executableIdentity": fields["executable_identity"],
        "leaseOwnerRevision": fields["lease_owner_revision"],
        "stageIdentity": fields["stage_identity"],
        "version": 1,
    }


def project_fields(fields, context, case):
    assert json.dumps(fields, sort_keys=True) == json.dumps(
        expected_fields(context), sort_keys=True
    ), (
        case,
        "public field differs from prior input formula",
    )
    fields = dict(fields)
    fields["stage_identity"] = token(
        fields["stage_identity"], "stage", context, case, "return"
    )
    fields["directory_identities"] = [
        [
            name,
            token(identity, context["directory_roles"][name], context, case, "return"),
        ]
        for name, identity in fields["directory_identities"]
    ]
    if fields["executable_identity"] is not None:
        fields["executable_identity"] = token(
            fields["executable_identity"], "executable", context, case, "return"
        )
    return fields


def portable_observation(observation, context, case, raw):
    # Raw identity bases and path roles must match independent prior input data.
    for row in raw:
        if row["event"] == "acquire":
            assert Path(row["path"]) == context["paths"][row["role"]]
        if row["event"] == "stat":
            assert row["identity"] == list(context["stats"][row["role"]])
    rows = []
    event = ""
    cursor = consumed = 0
    pending_seek = False
    for original in observation["trace"]:
        row = dict(original)
        name = row["event"]
        if name.startswith(("fstat:", "name.stat:")):
            event = name
        if name in {"stat.result", "name.stat.result"}:
            row["identity"] = token(row["identity"], row["role"], context, case, event)
        if name == "injected.seek_eof":
            pending_seek = True
        if name == "read.result":
            data = context["bytes"]
            body = bytes.fromhex(row["body"])
            end = cursor + len(body)
            maximum = 8 if case == "executable-overflow" else 16 * 1024 * 1024
            assert row["requested"] == min(1024 * 1024, maximum + 1 - consumed), (
                case,
                "bounded read request changed",
            )
            assert body == data[cursor:end] and (body or cursor == len(data)), (
                case,
                "read bytes/cursor differ from input",
            )
            consumed += len(body)
            cursor = len(data) if pending_seek else end
            pending_seek = False
            # Partial payload bytes and budgets are input-stable: retain all literals.
        if name == "public.constructor.fields":
            assert json.dumps(row["fields"], sort_keys=True) == json.dumps(
                [[key, value] for key, value in expected_fields(context).items()],
                sort_keys=True,
            )
            row["fields"] = [
                [key, value]
                for key, value in project_fields(
                    dict(row["fields"]), context, case
                ).items()
            ]
        rows.append(row)
    result = observation["result"]
    if result is not None:
        assert (
            set(result) == {"type", "fields", "wire", "fingerprint"}
            and result["type"] == PUBLIC_FQN
        )
        assert json.dumps(result["fields"], sort_keys=True) == json.dumps(
            expected_fields(context), sort_keys=True
        )
        document = public_document(expected_fields(context))
        wire = json.dumps(
            document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        assert result["wire"] == wire.hex(), (
            case,
            "public wire differs from independent original schema",
        )
        assert result["fingerprint"] == hashlib.sha256(DOMAIN + wire).hexdigest(), (
            case,
            "public domain hash differs",
        )
        fields = project_fields(result["fields"], context, case)
        schema = public_document(fields)
        result = {
            "type": result["type"],
            "fields": fields,
            "wire": {"canonical_json_utf8": schema},
            "fingerprint": {
                "sha256_domain_hex": DOMAIN.hex(),
                "canonical_json_utf8": schema,
            },
        }
    return {**observation, "result": result, "trace": rows}


_FIXTURE = (
    Path(__file__).parent / "fixtures" / "windows_partial_stage_capture_v1.json.gz"
)


@pytest.mark.parametrize("case", CASES)
def test_partial_stage_capture(case, tmp_path, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "HERE", tmp_path)
    root, _stage = seeded(case)
    context = input_context(case, root)
    observation, raw = observed(case)
    assert (
        portable_observation(observation, context, case, raw)
        == json.loads(gzip.decompress(_FIXTURE.read_bytes()))[case]
    )
