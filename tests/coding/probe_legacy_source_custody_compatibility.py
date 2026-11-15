"""Frozen pre-A168 Source custody and installed Wheel artifact observations.

Explicit local probe, excluded from default discovery. Actual source/revision/
ZIP IO with controlled fault ports; cancellation is a port raise, not Task.cancel.
Fixed artifact lengths/digests are retained, not full original Wheel archives.
"""

import asyncio
import gzip
import json
import os
import shutil
import zipfile
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path

import pytest

import loushang.coding.package_legacy_local_wheel as module
from loushang.coding import package_builtin_wheel as wheel
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.resources.plugins.revisions import PluginRevisionStore
from tests.coding.test_package_legacy_local_wheel import _evidence, _source

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="POSIX pre-A168 observations"
)

SOURCE_EXPECTED = (
    Path(__file__).parent / "fixtures" / "legacy_source_custody_v1.json.gz"
)
INSTALLED_EXPECTED = (
    Path(__file__).parent / "fixtures" / "installed_product_wheels_v1.json.gz"
)
CASES = (
    "ok",
    "executable",
    "root-git",
    "verify-1",
    "verify-2",
    "verify-3",
    "open",
    "read",
    "parse-file-set",
    "zip",
    "cancel",
    "constructor",
    "close-before",
    "close-after",
    "remove-before",
    "remove-after",
    "zip+close-before",
    "constructor+close-after",
    "verify-2+remove-before",
    "parse-file-set+close-before",
)


def exception_value(exc, root):
    if exc is None:
        return None
    return {
        "type": f"{type(exc).__module__}.{type(exc).__qualname__}",
        "message": str(exc).replace(str(root), "$CASE"),
        "notes": [
            str(note).replace(str(root), "$CASE")
            for note in getattr(exc, "__notes__", ())
        ],
        "cause": exception_value(exc.__cause__, root),
        "context": exception_value(exc.__context__, root),
        "suppress": exc.__suppress_context__,
    }


@pytest.mark.parametrize("scenario", CASES)
def test_reacquire(monkeypatch, tmp_path, scenario):
    flags = set(scenario.split("+"))
    source = _source(tmp_path)
    if scenario == "executable":
        (source / "resources/prompts/review.md").chmod(0o755)
    if scenario == "root-git":
        (source / ".git").mkdir()
        (source / ".git/ignored").write_text("ignored")
    digest, manifest_digest, lock = _evidence(tmp_path, source)
    old_package = tmp_path / "old-package"
    old_package.mkdir(mode=0o700)
    staging = tmp_path / "private-stage"
    staging.mkdir(mode=0o700)
    trace = []
    handles = []
    counts = {"verify": 0, "open": 0, "zip": 0}

    def fail(name):
        if name in flags:
            raise RuntimeError(f"controlled {name} failure")

    real_publish = PluginRevisionStore.publish

    class Handle:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def verify(self):
            counts["verify"] += 1
            trace.append(["verify", counts["verify"]])
            fail(f"verify-{counts['verify']}")
            self.inner.verify()

        @contextmanager
        def open_file(self, relative):
            counts["open"] += 1
            trace.append(["open", relative])
            fail("open")
            with self.inner.open_file(relative) as stream:

                class Stream:
                    def read(self, limit):
                        trace.append(["read", relative, limit])
                        fail("read")
                        return stream.read(limit)

                yield Stream()

        def close(self):
            trace.append(["close", self.inner.closed])
            fail("close-before")
            self.inner.close()
            fail("close-after")

    def publish(store, package):
        trace.append(
            [
                "publish",
                str(store.root)
                .replace(str(tmp_path), "$CASE")
                .replace(next((p.name for p in staging.iterdir()), "!none"), "$STAGE"),
            ]
        )
        published = real_publish(store, package)
        handles.append(published.revision_handle)
        object.__setattr__(
            published, "revision_handle", Handle(published.revision_handle)
        )
        return published

    monkeypatch.setattr(PluginRevisionStore, "publish", publish)
    real_parse = PluginManifestParser.parse_file_set

    def parse(parser, files, **kwargs):
        trace.append(["parse-file-set", kwargs["manifest_logical_path"], sorted(files)])
        fail("parse-file-set")
        return real_parse(parser, files, **kwargs)

    monkeypatch.setattr(PluginManifestParser, "parse_file_set", parse)
    real_write = zipfile.ZipFile.writestr

    def write(archive, member, body):
        counts["zip"] += 1
        trace.append(["zip", member.filename, member.external_attr, len(body)])
        if "cancel" in flags:
            raise asyncio.CancelledError("controlled cancellation")
        fail("zip")
        return real_write(archive, member, body)

    monkeypatch.setattr(zipfile.ZipFile, "writestr", write)
    real_remove = shutil.rmtree

    def remove(path, *args, **kwargs):
        if Path(path).name.startswith("legacy-local-source-"):
            trace.append(["remove", Path(path).exists()])
            fail("remove-before")
            result = real_remove(path, *args, **kwargs)
            fail("remove-after")
            return result
        return real_remove(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", remove)
    real_candidate = module.CodingLegacyLocalWheelCandidateV1

    def candidate(*args, **kwargs):
        trace.append(
            [
                "constructor",
                [handle.closed for handle in handles],
                bool(list(staging.iterdir())),
            ]
        )
        fail("constructor")
        return real_candidate(*args, **kwargs)

    monkeypatch.setattr(module, "CodingLegacyLocalWheelCandidateV1", candidate)
    try:
        try:
            result = module.reacquire_coding_legacy_local_plugin_wheel(
                source,
                legacy_package_root=old_package,
                staging_parent=staging,
                plugin_id="review-pack",
                expected_source_identity=f"local:{source}",
                expected_content_digest=digest,
                expected_manifest_digest=manifest_digest,
                expected_dependency_lock=lock,
            )
            value = {
                key: getattr(result, key)
                for key in result.__dataclass_fields__
                if key != "wheel_bytes"
            }
            value["original_source_identity"] = value[
                "original_source_identity"
            ].replace(str(tmp_path), "$CASE")
            value["wheel_size"] = len(result.wheel_bytes)
            assert sha256(result.wheel_bytes).hexdigest() == value["artifact_digest"]
            observed = {"result": value, "error": None}
        except BaseException as exc:
            observed = {"result": None, "error": exception_value(exc, tmp_path)}
        observed.update(
            trace=trace,
            handles_closed=[h.closed for h in handles],
            stage_exists=bool(list(staging.iterdir())),
        )
        if scenario in {"ok", "executable", "root-git"}:
            assert observed["error"] is None, observed
            assert counts["verify"] == 3 and counts["open"] == 2 and counts["zip"] == 5
            assert observed["handles_closed"] == [True] and not observed["stage_exists"]
        else:
            assert observed["error"] is not None, observed
        expected = json.loads(gzip.decompress(SOURCE_EXPECTED.read_bytes()))
        assert observed == expected[scenario]
    finally:
        # Own injected pre-close/pre-remove failures can leave resources; settle after observation.
        for handle in handles:
            handle.close()
        for path in staging.iterdir():
            real_remove(path)


IDS = ("coding.base", *sorted(wheel._CAPABILITY_SPECS))


@pytest.mark.parametrize("plugin_id", IDS)
def test_installed_wheel(plugin_id):
    body = (
        wheel.build_coding_base_product_wheel()
        if plugin_id == "coding.base"
        else wheel.build_coding_capability_product_wheel(plugin_id)
    )
    observed = {"bytes": len(body), "sha256": sha256(body).hexdigest()}
    expected = json.loads(gzip.decompress(INSTALLED_EXPECTED.read_bytes()))
    assert observed == expected[plugin_id]
