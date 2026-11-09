"""Original-source values observer; no expected generation in the check entry."""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import inspect
import io
import json
import os
import pickle
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from loushang.coding import package_builtin_wheel as wheels
from loushang.coding import package_product_revisions as revisions
from loushang.coding import plugin_dependency_grants as grants

MODULES = (wheels, revisions, grants)
CASES = (
    "reflection",
    "artifact-base",
    "artifact-capability",
    "spec-value",
    "wheel-base",
    "wheel-arch",
    "wheel-lsp",
    "wheel-repeat",
    "unknown-str",
    "unknown-none",
    "unknown-list",
    "unknown-dict",
    "member-file",
    "member-hardlink",
    "member-symlink",
    "member-parent-symlink",
    "member-oversize",
    "member-mutated",
    "member-removed",
    "member-read-error",
    "handle-values",
    "handle-dot-root",
    "handle-nested-root",
    "handle-missing",
    "handle-traversal",
    "handle-closed",
    "handle-acquire",
    "handle-stale-value",
    "handle-stale-runtime",
    "handle-stale-os",
    "handle-stale-cancel",
    "handle-closed-before-path",
    "handle-stale-before-path",
)


def _fq(value):
    return f"{value.__module__}.{value.__qualname__}"


def _exception(error, seen=None):
    seen = set() if seen is None else seen
    if id(error) in seen:
        return {"cycle": _fq(type(error))}
    seen.add(id(error))
    result = {
        "type": _fq(type(error)),
        "args": list(error.args),
        "notes": list(getattr(error, "__notes__", ())),
        "suppress": error.__suppress_context__,
    }
    for key in ("code", "path", "errno", "filename", "filename2", "winerror"):
        if hasattr(error, key):
            value = getattr(error, key)
            result[key] = str(value) if isinstance(value, Path) else value
    result["cause"] = _exception(error.__cause__, seen) if error.__cause__ else None
    result["context"] = (
        _exception(error.__context__, seen) if error.__context__ else None
    )
    return result


def _freeze(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {
            "base64": base64.b64encode(value).decode(),
            "sha256": hashlib.sha256(value).hexdigest(),
            "length": len(value),
        }
    if isinstance(value, (tuple, list)):
        return [_freeze(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _freeze(item) for key, item in value.items()}
    return value


def _dataclass(value):
    cls = type(value)
    try:
        value.path = Path("/changed")
    except BaseException as error:
        frozen_error = _exception(error)
    else:
        frozen_error = None
    restored = pickle.loads(pickle.dumps(value))
    return {
        "class": _fq(cls),
        "constructor": str(inspect.signature(cls)),
        "own_annotations": {
            key: str(item) for key, item in cls.__annotations__.items()
        },
        "fields": [
            {
                "name": field.name,
                "type": str(field.type),
                "init": field.init,
                "repr": field.repr,
                "compare": field.compare,
                "kw_only": field.kw_only,
            }
            for field in dataclasses.fields(cls)
        ],
        "slots": list(cls.__slots__),
        "has_dict": hasattr(value, "__dict__"),
        "values": _freeze(dataclasses.asdict(value)),
        "repr": repr(value),
        "pickle_class": _fq(type(restored)),
        "pickle_equal": restored == value,
        "frozen_error": frozen_error,
    }


def _wheel(body):
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        members = [
            {
                "name": item.filename,
                "timestamp": list(item.date_time),
                "system": item.create_system,
                "attrs": item.external_attr,
                "compression": item.compress_type,
                "flags": item.flag_bits,
                "extra": _freeze(item.extra),
                "body": _freeze(archive.read(item)),
            }
            for item in archive.infolist()
        ]
    return {"bytes": _freeze(body), "members": members}


def _reflection():
    result = {}
    for module in MODULES:
        public = {}
        for name in module.__all__:
            value = getattr(module, name)
            if callable(value):
                public[name] = {
                    "fq": _fq(value),
                    "signature": str(inspect.signature(value)),
                    "annotations": {
                        key: str(item)
                        for key, item in getattr(value, "__annotations__", {}).items()
                    },
                }
            else:
                public[name] = _freeze(value)
        result[module.__name__] = public
    return result


class _Witness:
    def __init__(self):
        self.calls = []
        self.failure = None

    def assert_selected_plugin_manifest_current(self, selected):
        self.calls.append("assert-current")
        if self.failure is not None:
            raise self.failure

    def capture_selected_plugin_manifest_for(self, *args, **kwargs):
        raise AssertionError("The pinned handle must never recapture bytes")


def _handle(root_relative="pkg"):
    witness = _Witness()
    snapshot = SimpleNamespace(
        root_ref=SimpleNamespace(artifact_digest="a" * 64),
        installation_key=SimpleNamespace(plugin_id="coding.probe"),
        files=(
            ("pkg/file.txt", b"first"),
            ("pkg/file.txt", b"last"),
            ("pkg/dir/deep", b"inner"),
            ("other/foreign", b"outside"),
        ),
    )

    def verified():
        witness.calls.append("verified-manifest")
        return object()

    selected = SimpleNamespace(
        snapshot=snapshot,
        manifest=SimpleNamespace(root_relative_path=PurePosixPath(root_relative)),
        verified_manifest=verified,
    )
    handle = revisions._ProductSelectedRevisionHandle(witness, selected)
    return witness, handle


def _handle_case(case):
    import asyncio

    witness, handle = _handle("." if case == "handle-dot-root" else "pkg")
    if case == "handle-values":
        stream = handle.open_file("file.txt")
        stream.write(b"edit")
        return {
            "root": str(handle.root),
            "digest": handle.content_digest,
            "bytes": handle.open_file("file.txt").read(),
            "file": handle.entry_kind("file.txt"),
            "directory": handle.entry_kind("dir"),
            "identity": handle.file_identity("file.txt"),
            "calls": witness.calls,
        }
    if case == "handle-dot-root":
        return {
            "bytes": handle.open_file("other/foreign").read(),
            "calls": witness.calls,
        }
    if case == "handle-nested-root":
        return {"bytes": handle.open_file("dir/deep").read(), "calls": witness.calls}
    if case == "handle-acquire":
        acquired = handle.acquire()
        handle.close()
        try:
            return {
                "same": acquired is handle,
                "parent_closed": handle.closed,
                "child_closed": acquired.closed,
                "bytes": acquired.open_file("file.txt").read(),
                "calls": witness.calls,
            }
        finally:
            acquired.close()
    if case in ("handle-closed", "handle-closed-before-path"):
        handle.close()
    failures = {
        "handle-stale-value": ValueError("changed"),
        "handle-stale-runtime": RuntimeError("runtime"),
        "handle-stale-os": OSError("os"),
        "handle-stale-cancel": asyncio.CancelledError("cancel"),
        "handle-stale-before-path": ValueError("changed"),
    }
    witness.failure = failures.get(case)
    path = (
        "../outside"
        if case
        in ("handle-traversal", "handle-closed-before-path", "handle-stale-before-path")
        else "missing"
        if case == "handle-missing"
        else "file.txt"
    )
    try:
        return {"bytes": handle.open_file(path).read(), "calls": witness.calls}
    except BaseException as error:
        return {"error": _exception(error), "calls": witness.calls}
    finally:
        handle.close()


def _member_case(case):
    with tempfile.TemporaryDirectory(prefix="a79-member-") as raw:
        root = Path(raw)
        path = root / "member"
        path.write_bytes(b"original")
        relative = "member"
        original_read = Path.read_bytes
        if case == "member-hardlink":
            os.link(path, root / "linked")
        elif case == "member-symlink":
            path.unlink()
            path.symlink_to(root / "target")
            (root / "target").write_bytes(b"target")
        elif case == "member-parent-symlink":
            (root / "actual").mkdir()
            (root / "actual" / "member").write_bytes(b"parent")
            (root / "linked").symlink_to(root / "actual", target_is_directory=True)
            relative = "linked/member"
        elif case == "member-oversize":
            path.write_bytes(b"x" * (256 * 1024 + 1))

        def read(candidate):
            if candidate != path:
                return original_read(candidate)
            if case == "member-read-error":
                raise OSError("controlled member read failure")
            result = original_read(candidate)
            if case == "member-mutated":
                candidate.write_bytes(b"changed-longer")
            elif case == "member-removed":
                candidate.unlink()
            return result

        try:
            with patch.object(Path, "read_bytes", read):
                body = wheels._read_member(root, relative)
            return {"bytes": body, "nlink": path.lstat().st_nlink}
        except BaseException as error:
            serialized = json.dumps(_exception(error), default=str)
            return {"error": json.loads(serialized.replace(str(root), "$TMP"))}


def observe(case):
    try:
        if case == "reflection":
            result = _reflection()
        elif case == "artifact-base":
            result = _dataclass(
                wheels.CodingBaseProductWheelArtifactV1(
                    Path("/fixed/coding_base-1-py3-none-any.whl"), "a" * 64, 123
                )
            )
        elif case == "artifact-capability":
            result = _dataclass(
                wheels.CodingCapabilityProductWheelArtifactV1(
                    "coding.arch.default",
                    Path("/fixed/coding_arch_default-1-py3-none-any.whl"),
                    "b" * 64,
                    456,
                )
            )
        elif case == "spec-value":
            spec = wheels._BuiltinWheelSpec(
                "coding.probe", "coding_probe", ("plugin.json",)
            )
            result = {
                "dataclass": _dataclass(spec),
                "filename": spec.filename,
                "dist_info": spec.dist_info,
                "distribution_name": spec.distribution_name,
            }
        elif case.startswith("wheel-"):
            if case == "wheel-repeat":
                first = wheels.build_coding_base_product_wheel()
                result = {
                    "equal": first == wheels.build_coding_base_product_wheel(),
                    "bytes": _freeze(first),
                }
            else:
                result = _wheel(
                    wheels.build_coding_base_product_wheel()
                    if case == "wheel-base"
                    else wheels.build_coding_capability_product_wheel(
                        "coding.arch.default"
                        if case == "wheel-arch"
                        else "coding.lsp.default"
                    )
                )
        elif case.startswith("unknown-"):
            argument = {
                "unknown-str": "unknown",
                "unknown-none": None,
                "unknown-list": [],
                "unknown-dict": {},
            }[case]
            result = wheels.build_coding_capability_product_wheel(argument)
        elif case.startswith("member-"):
            result = _member_case(case)
        else:
            result = _handle_case(case)
        return {"result": _freeze(result)}
    except BaseException as error:
        return {"error": _exception(error)}


_EXPECTED = json.loads(
    (
        Path(__file__).parent / "fixtures/product_selected_revision_values_v1.json"
    ).read_text()
)


@pytest.mark.parametrize("case", CASES)
def test_original_product_revision_values(case):
    assert observe(case) == _EXPECTED["observations"][case]
