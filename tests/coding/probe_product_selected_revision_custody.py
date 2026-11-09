"""Explicit original-source input custody observations, without recapture.

Product capture and Store-root authority are controlled. Selected DTO/parser,
package/binding/resolution, actual distribution evidence over real source files,
member reads and ZIP writes/cleanup execute their original implementations.
Interrupts are synchronous; this is not a Store transaction or native ACL test.
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import importlib
import io
import json
import zipfile
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest

RESOLUTION_CASES = (
    "normal",
    "public-builtin",
    "public-capability",
    "base-only",
    "wrong-runtime",
    "capture-second",
    "capture-last",
    "validation-second",
    "validation-last",
    "handle-constructor-second",
    "manifest-after-lock",
    "declarations-base",
    "resolver-unavailable",
    "resolver-ambiguous",
    "resolver-wrong-origin",
    "resolver-name",
    "resolver-init-evidence",
    "resolver-init-oserror",
    "source-root-oserror",
    "source-root-evidence",
    "source-root-interrupt",
    "source-root-cancel",
    "package-second",
    "binding-second",
    "installed-second",
    "installed-last",
    "resolution-constructor",
    "cleanup-prefix-first",
    "cleanup-current",
    "capture-interrupt",
    "capture-cancel",
    "retry-capture",
    "retry-installed",
    "wheel-member-read",
    "wheel-write",
    "wheel-close",
    "wheel-write-and-close",
    "wheel-interrupt",
    "wheel-cancel",
    "external-only",
    "public-external",
    "external-trust",
    "external-declarations",
    "public-empty-capabilities",
    "public-external-list",
    "public-external-mismatch",
    "public-external-overlap",
    "public-wrong-runtime",
)


def load_product() -> NS:
    return NS(
        revision=importlib.import_module("loushang.coding.package_product_revisions"),
        wheel=importlib.import_module("loushang.coding.package_builtin_wheel"),
    )


def _selected_inputs(product: NS):
    """Real selected-manifest DTO validation over controlled Store snapshots.

    The root snapshot's authority constructor is deliberately bypassed: Product
    capture is a controlled port, not a real Store transaction. The selected DTO
    constructor, manifest parser and declaration codec perform real validation.
    """
    local = importlib.import_module(
        "loushang.harness.package_product.product_local_wheel_runtime"
    )
    management = importlib.import_module(
        "loushang.harness.plugin_management.package_product"
    )
    manifest_module = importlib.import_module(
        "loushang.harness.resources.plugins.manifest"
    )
    declarations = importlib.import_module(
        "loushang.harness.resources.plugins.declarations"
    )
    selection = importlib.import_module("loushang.harness.resources.plugins.selection")
    selected = {}
    for plugin_id, package in (
        ("coding.base", "coding_base"),
        ("coding.arch.default", "coding_arch_default"),
        ("coding.lsp.default", "coding_lsp_default"),
        ("reviewpack", "reviewpack"),
    ):
        if plugin_id == "reviewpack":
            files = {
                name: base64.b64decode(body, validate=True)
                for name, body in product.external_files.items()
            }
            digest = sha256(b"controlled-external-artifact").hexdigest()
        else:
            body = base64.b64decode(
                product.input_wheels[plugin_id]["body_base64"], validate=True
            )
            assert sha256(body).hexdigest() == product.input_wheels[plugin_id]["sha256"]
            digest = sha256(body).hexdigest()
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                files = {
                    name: archive.read(name)
                    for name in archive.namelist()
                    if name.startswith(package + "/")
                }
        manifest = manifest_module.PluginManifestParser().parse_file_set(
            files, manifest_logical_path=f"{package}/plugin.json"
        )
        documents = tuple(
            sorted(
                (
                    (
                        name,
                        declarations.PluginDeclarationDocumentCodec.decode_bytes(value),
                    )
                    for name, value in files.items()
                    if name.startswith(package + "/declarations/")
                )
            )
        )
        snapshot = object.__new__(management.PackageProductSelectedRootSnapshotV1)
        for name, value in {
            "installation_key": NS(plugin_id=plugin_id, product_id="coding"),
            "root_ref": NS(plugin_id=plugin_id, version="1", artifact_digest=digest),
            "package_revision": NS(
                package_source_identity="controlled-product-source:" + plugin_id
            ),
            "files": tuple(sorted(files.items())),
        }.items():
            object.__setattr__(snapshot, name, value)
        trust = selection.PluginSourceTrustSnapshotV1(
            plugin_id,
            snapshot.package_revision.package_source_identity,
            "local-data-only" if plugin_id == "reviewpack" else "host-equivalent-local",
            "runtime-observer:1",
            True,
        )
        selected[plugin_id] = local.PackageProductSelectedPluginManifestV1(
            snapshot, manifest, documents, trust
        )
    return selected


def observe_resolution(product: NS, case: str) -> dict[str, object]:
    if case not in RESOLUTION_CASES:
        raise ValueError(case)
    module = product.revision
    local = importlib.import_module(
        "loushang.harness.package_product.product_local_wheel_runtime"
    )
    evidence_module = importlib.import_module(
        "loushang.harness.resources.plugins.distribution_evidence"
    )
    types_module = importlib.import_module("loushang.harness.resources.plugins.types")
    authority = importlib.import_module("loushang.harness.resources.plugins.authority")
    selected = _selected_inputs(product)
    if case == "external-trust":
        object.__setattr__(
            selected["reviewpack"].source_trust_snapshot,
            "source_trust_class",
            "host-equivalent-local",
        )
    trace: list[object] = []
    handles = []
    manifest_calls = {}
    capture_calls = 0
    root_calls = 0
    zip_closes = 0
    injected = False
    source_root = (
        Path(importlib.import_module("loushang").__file__).resolve().parent.parent
    )
    actual_runtime_type = module.PackageProductRuntimeBindingV1
    runtime = object.__new__(actual_runtime_type)
    object.__setattr__(runtime, "product_id", "coding")
    original_manifest = local.PackageProductSelectedPluginManifestV1.verified_manifest
    original_declarations = (
        local.PackageProductSelectedPluginManifestV1.verified_data_only_declarations
    )
    handle_type = module._ProductSelectedRevisionHandle
    original_handle_init, original_close = (handle_type.__init__, handle_type.close)
    original_resolver_init = (
        evidence_module.InstalledPythonDistributionEvidenceResolver.__init__
    )
    original_resolve = (
        evidence_module.InstalledPythonDistributionEvidenceResolver.resolve
    )
    original_path_resolve = Path.resolve
    original_zip_write, original_zip_close = (
        zipfile.ZipFile.writestr,
        zipfile.ZipFile.close,
    )
    original_read_bytes = Path.read_bytes

    class Distribution:
        version = "1.2.3"
        files = tuple(
            (
                Path(f"loushang/coding/_plugins/{package}/definition.py")
                for package in ("coding_arch_default", "coding_lsp_default")
            )
        )

        @property
        def metadata(self):
            trace.append(["distribution.metadata"])
            return {"Name": "foreign" if case == "resolver-name" else "loushang"}

        def locate_file(self, path):
            trace.append(["distribution.locate_file", str(path)])
            return source_root / path

        def read_text(self, filename):
            trace.append(["distribution.read_text", filename])
            return None

    def distributions_reader(name):
        trace.append(["distributions_reader", name])
        if case == "resolver-unavailable":
            return ()
        distribution = Distribution()
        if case == "resolver-wrong-origin":
            distribution.files = (Path("loushang/__init__.py"),)
        if case == "resolver-ambiguous":
            second = Distribution()
            second.version = "1.2.4"
            return (distribution, second)
        return (distribution,)

    def resolver_init(self, **kwargs):
        trace.append(["resolver.init", kwargs.get("allow_editable", False)])
        if case == "resolver-init-evidence":
            raise evidence_module.InstalledPythonDistributionEvidenceError(
                "resolver construction refused", code="probe"
            )
        if case == "resolver-init-oserror":
            raise OSError("resolver construction failed")
        kwargs.update(
            distributions_reader=distributions_reader,
            packages_distributions_reader=lambda: {"loushang": ["loushang"]},
        )
        return original_resolver_init(self, **kwargs)

    def resolve(self, distribution, **kwargs):
        trace.append(
            [
                "resolver.resolve",
                distribution,
                [
                    str(item.relative_to(source_root))
                    for item in kwargs.get("required_paths", ())
                ],
            ]
        )
        return original_resolve(self, distribution, **kwargs)

    def path_resolve(self, *args, **kwargs):
        nonlocal root_calls
        relevant = (
            self.name in {"plugin_dependency_grants.py", "package_builtin_wheel.py"}
            or self.parent.name == "_plugins"
            or str(self).startswith("/__loushang_product_snapshot__")
        )
        if relevant:
            try:
                path = str(self.relative_to(source_root))
            except ValueError:
                path = str(self)
            trace.append(["path.resolve", path, args, kwargs])
        if (
            self.name == "coding_arch_default"
            and self.parent.name == "_plugins"
            and kwargs.get("strict")
        ):
            root_calls += 1
            if root_calls == 3:
                failures = {
                    "source-root-oserror": OSError("host source root failed"),
                    "source-root-evidence": evidence_module.InstalledPythonDistributionEvidenceError(
                        "host source unavailable", code="probe"
                    ),
                    "source-root-interrupt": KeyboardInterrupt(
                        "host source interrupted"
                    ),
                    "source-root-cancel": asyncio.CancelledError(
                        "host source cancelled"
                    ),
                }
                if case in failures:
                    raise failures[case]
        return original_path_resolve(self, *args, **kwargs)

    def capture_selected(self, plugin_id, **kwargs):
        nonlocal capture_calls, injected
        assert self is runtime
        capture_calls += 1
        trace.append(["capture", plugin_id, kwargs])
        if (
            case in {"capture-second", "retry-capture"}
            and plugin_id == "coding.arch.default"
            and (not injected)
            or (case == "capture-last" and plugin_id == "coding.lsp.default")
        ):
            injected = True
            raise ValueError("capture refused")
        if plugin_id == "coding.arch.default" and case in {
            "capture-interrupt",
            "capture-cancel",
        }:
            raise (
                KeyboardInterrupt("capture interrupted")
                if case.endswith("interrupt")
                else asyncio.CancelledError("capture cancelled")
            )
        value = selected[plugin_id]
        if (
            case == "validation-second"
            and plugin_id == "coding.arch.default"
            or (case == "validation-last" and plugin_id == "coding.lsp.default")
        ):
            value.snapshot.installation_key.product_id = "foreign"
        return value

    def verified(self):
        plugin_id = self.snapshot.installation_key.plugin_id
        count = manifest_calls[plugin_id] = manifest_calls.get(plugin_id, 0) + 1
        trace.append(["verified_manifest", plugin_id, count])
        if plugin_id == "coding.arch.default" and (
            case == "handle-constructor-second"
            and count == 2
            or (case == "manifest-after-lock" and count == 3)
        ):
            raise ValueError("verified manifest refused")
        return original_manifest(self)

    def data_only(self):
        plugin_id = self.snapshot.installation_key.plugin_id
        trace.append(["verified_data_only_declarations", plugin_id])
        if case == "declarations-base" or (
            case == "external-declarations" and plugin_id == "reviewpack"
        ):
            raise ValueError("data declarations refused")
        return original_declarations(self)

    def handle_init(self, runtime_arg, selected_arg):
        trace.append(["handle.init", selected_arg.snapshot.installation_key.plugin_id])
        original_handle_init(self, runtime_arg, selected_arg)
        handles.append(self)

    def close(self):
        plugin_id = self._selected.snapshot.installation_key.plugin_id
        trace.append(["handle.close", plugin_id, self.closed])
        if case == "cleanup-prefix-first" and plugin_id == "coding.base":
            raise OSError("prefix close failed")
        if case == "cleanup-current" and plugin_id == "coding.lsp.default":
            raise OSError("current close failed")
        return original_close(self)

    def read_bytes(self):
        if (
            case == "wheel-member-read"
            and self.parent.name == "coding_arch_default"
            and (self.name == "definition.py")
        ):
            trace.append(["member.read.failure", self.name])
            raise OSError("wheel member read failed")
        return original_read_bytes(self)

    def zip_write(self, member, body, *args, **kwargs):
        name = member.filename if isinstance(member, zipfile.ZipInfo) else member
        trace.append(["zip.write", name, len(body)])
        if name == "coding_arch_default/definition.py":
            if case in {"wheel-write", "wheel-write-and-close"}:
                raise OSError("zip write failed")
            if case == "wheel-interrupt":
                raise KeyboardInterrupt("zip write interrupted")
            if case == "wheel-cancel":
                raise asyncio.CancelledError("zip write cancelled")
        return original_zip_write(self, member, body, *args, **kwargs)

    def zip_close(self):
        nonlocal zip_closes
        if self.fp is None:
            return original_zip_close(self)
        zip_closes += 1
        trace.append(["zip.close", zip_closes])
        original_zip_close(self)
        if zip_closes == 2 and case in {"wheel-close", "wheel-write-and-close"}:
            raise OSError("zip close failed")

    def dto_init(klass, label, fail_case):
        original = klass.__init__

        def initialize(self, *args, **kwargs):
            nonlocal injected
            manifest = kwargs.get("manifest")
            plugin_id = getattr(manifest, "name", kwargs.get("plugin_id"))
            trace.append([label, plugin_id])
            should_fail = case == fail_case and plugin_id == "coding.arch.default"
            if (
                label == "installed.init"
                and case
                in {"installed-last", "cleanup-prefix-first", "cleanup-current"}
                and (plugin_id == "coding.lsp.default")
            ):
                should_fail = True
            if (
                label == "installed.init"
                and case == "retry-installed"
                and (plugin_id == "coding.arch.default")
                and (not injected)
            ):
                should_fail = True
                injected = True
            if label == "resolution.init" and case == "resolution-constructor":
                should_fail = True
            if should_fail:
                raise RuntimeError(label + " failed")
            return original(self, *args, **kwargs)

        return initialize

    with ExitStack() as stack:
        for owner, name, replacement in (
            (
                actual_runtime_type,
                "capture_selected_plugin_manifest_for",
                capture_selected,
            ),
            (
                actual_runtime_type,
                "selected_external_data_plugin_ids",
                lambda self: (
                    trace.append(["external.ids"])
                    or (
                        ("reviewpack",)
                        if case in {"public-external", "public-external-mismatch"}
                        else ()
                    )
                ),
            ),
            (
                local.PackageProductSelectedPluginManifestV1,
                "verified_manifest",
                verified,
            ),
            (
                local.PackageProductSelectedPluginManifestV1,
                "verified_data_only_declarations",
                data_only,
            ),
            (handle_type, "__init__", handle_init),
            (handle_type, "close", close),
            (
                evidence_module.InstalledPythonDistributionEvidenceResolver,
                "__init__",
                resolver_init,
            ),
            (
                evidence_module.InstalledPythonDistributionEvidenceResolver,
                "resolve",
                resolve,
            ),
            (Path, "resolve", path_resolve),
            (Path, "read_bytes", read_bytes),
            (zipfile.ZipFile, "writestr", zip_write),
            (zipfile.ZipFile, "close", zip_close),
            (
                types_module.PublishedPluginPackage,
                "__init__",
                dto_init(
                    types_module.PublishedPluginPackage,
                    "package.init",
                    "package-second",
                ),
            ),
            (
                types_module.PluginSourceBinding,
                "__init__",
                dto_init(
                    types_module.PluginSourceBinding, "binding.init", "binding-second"
                ),
            ),
            (
                types_module.InstalledPlugin,
                "__init__",
                dto_init(
                    types_module.InstalledPlugin, "installed.init", "installed-second"
                ),
            ),
            (
                authority.PluginRuntimeResolution,
                "__init__",
                dto_init(
                    authority.PluginRuntimeResolution,
                    "resolution.init",
                    "resolution-constructor",
                ),
            ),
        ):
            stack.enter_context(patch.object(owner, name, replacement))

        def operation():
            if case == "wrong-runtime":
                resolution = module._open_selected_resolution(
                    object(), ("coding.base",)
                )
            elif case == "public-wrong-runtime":
                resolution = module.open_coding_product_builtin_resolution(object())
            elif case == "public-empty-capabilities":
                resolution = module.open_coding_product_builtin_resolution(
                    runtime, capability_plugin_ids=()
                )
            elif case == "public-external-list":
                resolution = module.open_coding_product_builtin_resolution(
                    runtime, external_data_plugin_ids=[]
                )
            elif case == "public-external-mismatch":
                resolution = module.open_coding_product_builtin_resolution(runtime)
            elif case == "public-external-overlap":
                resolution = module.open_coding_product_builtin_resolution(
                    runtime, external_data_plugin_ids=("coding.base",)
                )
            elif case == "public-external":
                resolution = module.open_coding_product_builtin_resolution(
                    runtime, external_data_plugin_ids=("reviewpack",)
                )
            elif case.startswith("external-"):
                resolution = module._open_selected_resolution(
                    runtime,
                    ("reviewpack",),
                    external_data_plugin_ids=frozenset({"reviewpack"}),
                )
            elif case == "public-builtin":
                resolution = module.open_coding_product_builtin_resolution(runtime)
            elif case == "public-capability":
                resolution = module.open_coding_product_capability_resolution(
                    runtime, plugin_ids=("coding.arch.default", "coding.lsp.default")
                )
            else:
                resolution = module._open_selected_resolution(
                    runtime,
                    ("coding.base",)
                    if case == "base-only"
                    else ("coding.base", "coding.arch.default", "coding.lsp.default"),
                )
            result = {
                "packages": [
                    {
                        "id": package.manifest.name,
                        "root": str(package.root),
                        "digest": package.content_digest,
                        "enabled": package.manifest.enabled,
                        "distributions": [
                            dataclasses.asdict(item)
                            for item in package.dependency_lock.python_distributions
                        ],
                        "closed": package.revision_handle.closed,
                    }
                    for package in resolution.packages
                ],
                "bindings": [
                    dataclasses.asdict(binding) for binding in resolution.bindings
                ],
                "plugins": [plugin.manifest.name for plugin in resolution.plugins],
            }
            trace.append(["observer.close_resolution"])
            resolution.close()
            return result

        first = capture(operation, trace)
        if case in {"retry-capture", "retry-installed"}:
            trace.append(["retry"])
            first["retry"] = capture(operation, trace)
        first["handles"] = [
            [handle._selected.snapshot.installation_key.plugin_id, handle.closed]
            for handle in handles
        ]
        first["manifest_calls"] = dict(manifest_calls)
        first["capture_calls"] = capture_calls
    for handle in handles:
        original_close(handle)
    return first


def exception(error: BaseException, seen: frozenset[int] = frozenset()) -> object:
    if id(error) in seen:
        return {"cycle": type(error).__name__}
    visited = seen | {id(error)}
    return {
        "type": f"{type(error).__module__}.{type(error).__qualname__}",
        "message": str(error),
        "code": getattr(error, "code", None),
        "errno": getattr(error, "errno", None),
        "filename": str(getattr(error, "filename", "")),
        "filename2": str(getattr(error, "filename2", "")),
        "winerror": getattr(error, "winerror", None),
        "path": str(getattr(error, "path", "")),
        "notes": list(getattr(error, "__notes__", ())),
        "suppress_context": error.__suppress_context__,
        "cause": exception(error.__cause__, visited) if error.__cause__ else None,
        "context": exception(error.__context__, visited) if error.__context__ else None,
    }


def capture(operation, trace: list[object]) -> dict[str, object]:
    try:
        result = operation()
    except BaseException as error:
        return {"error": exception(error), "trace": trace}
    return {"result": result, "trace": trace}


_FIXTURES = Path(__file__).parent / "fixtures"
_EXPECTED = json.loads(
    (_FIXTURES / "product_selected_revision_custody_v1.json").read_text()
)


@pytest.fixture(scope="module")
def product_input_observer():
    product = load_product()
    product.input_wheels = json.loads(
        (_FIXTURES / "product_selected_revision_input_wheels_v1.json").read_text()
    )
    product.external_files = json.loads(
        (_FIXTURES / "product_selected_revision_input_external_v1.json").read_text()
    )
    return product


@pytest.mark.parametrize("case", RESOLUTION_CASES)
def test_original_product_revision_custody(product_input_observer, case):
    actual = json.loads(
        json.dumps(observe_resolution(product_input_observer, case), sort_keys=True)
    )
    assert actual == _EXPECTED["cases"][case]["value"]
