"""Observe original inert Linux release custody. Never executes launcher bytes."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import stat
import zipfile
from asyncio import CancelledError
from base64 import urlsafe_b64encode
from contextlib import contextmanager, suppress
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from loushang.coding import package_product_worker_installed_native as installed
from loushang.coding import package_product_worker_native_install as install
from loushang.coding import package_product_worker_native_release as raw
from loushang.coding.package_product_worker_native_approval import (
    CodingWorkerNativeApprovalDecisionV1 as Decision,
)
from loushang.coding.package_product_worker_native_approval import (
    CodingWorkerNativeApprovalError as ApprovalError,
)
from loushang.coding.package_product_worker_native_approval import (
    CodingWorkerNativeApprovalJournal as Journal,
)
from loushang.coding.package_product_worker_native_approval import (
    CodingWorkerNativeReleaseApprovalV1 as Approval,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner as Product,
)
from tests.coding.probe_native_release_readers_compatibility import error_graph
from tests.harness.worker.test_native_executable_format import _static_elf

CASES = tuple(
    "review-" + c
    for c in (
        "valid",
        "empty",
        "not-bytes",
        "oversize",
        "zip",
        "extra-member",
        "duplicate",
        "stored",
        "member-mode",
        "member-link",
        "metadata",
        "initializer",
        "catalog-json",
        "catalog-canonical",
        "catalog-source",
        "launcher",
        "version-error",
        "owner-id",
        "owner-trust",
        "stale",
    )
)
CASES += tuple(
    "install-" + c
    for c in (
        "valid",
        "idempotent",
        "wrong-owner",
        "wrong-approval",
        "wrong-journal",
        "other-product",
        "empty",
        "wheel-mismatch",
        "catalog-mismatch",
        "launcher-mismatch",
        "profile-mismatch",
        "zip",
        "stored",
        "member-mode",
        "metadata",
        "initializer",
        "catalog-source",
        "launcher",
        "owner-trust",
        "stale",
        "private-root",
        "approval-missing",
        "approval-error",
        "approval-value-error",
        "approval-late",
        "stage-debt",
        "stage-symlink",
        "target-symlink",
        "write-partial",
        "write-zero",
        "write-error",
        "write-cancel",
        "write-interrupt",
        "fsync-file",
        "fsync-stage",
        "fsync-parent",
        "close-file",
        "close-stage",
        "close-parent",
        "stage-swap",
        "root-swap",
        "rename-error",
        "rename-collision",
        "stage-post-swap",
        "readback-source",
        "version-error",
        "version-late-error",
    )
)
CASES += tuple(
    "repair-" + c
    for c in (
        "valid",
        "wrong-owner",
        "wrong-approval",
        "wrong-journal",
        "other-product",
        "owner-trust",
        "stale",
        "private-root",
        "approval-missing",
        "approval-error",
        "approval-late",
        "no-stage",
        "partial-stage",
        "multi-stage",
        "stage-symlink",
        "target-exists",
        "target-symlink",
        "fsync-stage",
        "fsync-parent",
        "close-stage",
        "close-parent",
        "stage-swap",
        "root-swap",
        "rename-error",
        "rename-collision",
        "stage-post-swap",
        "readback-source",
    )
)
CASES += tuple(
    "receipt-" + c
    for c in (
        "valid",
        "scope",
        "digest",
        "digest-case",
        "version-bool",
        "version-float",
        "field",
        "canonical",
        "newline",
        "json",
        "missing",
        "source-change",
        "source-oversize",
        "root-relative",
        "root-symlink",
    )
)
CASES += tuple(
    "material-" + c
    for c in (
        "valid",
        "approval-missing",
        "approval-error",
        "approval-value-error",
        "approval-revoke",
        "approval-other",
        "generation",
        "source-change",
    )
)

CASES += (
    "install-retry-write-error",
    "install-retry-rename-error",
    "install-retry-fsync-parent",
    "repair-retry-rename-error",
    "repair-retry-fsync-stage",
    "repair-retry-fsync-parent",
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def wheel_bytes(source, case):
    package = "loushang_h6_native"
    di = package + "-0.1.0.dist-info"
    launcher = b"not ELF" if case == "launcher" else _static_elf()
    catalog = {
        "catalogVersion": 1,
        "platform": "linux-x86_64",
        "profileSourceSha256": sha256(source).hexdigest(),
        "launcherSha256": sha256(launcher).hexdigest(),
        "launcherFile": "containment-launcher",
        "buildFlags": [],
    }
    if case == "catalog-source":
        catalog["profileSourceSha256"] = "0" * 64
    catalog_body = (
        b"not json"
        if case == "catalog-json"
        else json.dumps(catalog).encode()
        if case == "catalog-canonical"
        else canonical(catalog) + b"\n"
    )
    files = {
        package + "/__init__.py": b"bad initializer" if case == "initializer" else b"",
        package + "/release/catalog.json": catalog_body,
        package + "/release/containment-launcher": launcher,
        di + "/METADATA": b"bad metadata"
        if case == "metadata"
        else b"Metadata-Version: 2.1\nName: loushang-h6-native\nVersion: 0.1.0\n\n",
        di
        + "/WHEEL": b"Wheel-Version: 1.0\nGenerator: loushang-h6-release\nRoot-Is-Purelib: false\nTag: py3-none-linux_x86_64\n\n",
    }
    record = io.StringIO()
    rows = [
        [
            n,
            "sha256=" + urlsafe_b64encode(sha256(b).digest()).rstrip(b"=").decode(),
            str(len(b)),
        ]
        for n, b in sorted(files.items())
    ]
    rows.append([di + "/RECORD", "", ""])
    csv.writer(record, lineterminator="\n").writerows(rows)
    files[di + "/RECORD"] = record.getvalue().encode()
    if case == "extra-member":
        files["unrelated"] = b"extra"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, body in files.items():
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = (
                zipfile.ZIP_STORED if case == "stored" else zipfile.ZIP_DEFLATED
            )
            mode = 0o500 if name.endswith("/containment-launcher") else 0o644
            if case == "member-mode":
                mode = 0o755
            info.external_attr = (
                (stat.S_IFLNK if case == "member-link" else stat.S_IFREG) | mode
            ) << 16
            archive.writestr(info, body)
        if case == "duplicate":
            archive.writestr(info, body)
    return (
        stream.getvalue(),
        files,
        Approval(
            sha256(stream.getvalue()).hexdigest(),
            sha256(catalog_body).hexdigest(),
            sha256(launcher).hexdigest(),
            catalog["profileSourceSha256"],
        ),
    )


def observe(name, base, patch):
    kind, case = name.split("-", 1)
    retry = case.startswith("retry-")
    case = case.removeprefix("retry-")
    trace = []
    active = {}
    fd_seq = 0
    current_count = 0
    approval_count = 0
    version_count = 0
    armed = False
    source = b"inert H6 profile source input\n"
    source_path = base / "profile-source.c"
    source_path.write_bytes(source)
    patch.setattr(raw, "_SOURCE", source_path)
    wheel, files, approved = wheel_bytes(source, case)
    if case == "catalog-mismatch":
        approved = Approval(
            approved.wheel_sha256,
            "0" * 64,
            approved.launcher_sha256,
            approved.profile_sha256,
        )
    if case == "launcher-mismatch":
        approved = Approval(
            approved.wheel_sha256,
            approved.catalog_sha256,
            "0" * 64,
            approved.profile_sha256,
        )
    if case == "profile-mismatch":
        approved = Approval(
            approved.wheel_sha256,
            approved.catalog_sha256,
            approved.launcher_sha256,
            "0" * 64,
        )
    state = base / "state"
    state.mkdir(mode=0o700)

    def norm(value):
        return re.sub(
            r"\.worker-native-release-stage-[a-zA-Z0-9_]+",
            ".worker-native-release-stage-<ID>",
            str(value).replace(str(base), "<ROOT>"),
        )

    class Gate:
        @contextmanager
        def guard(self, *, require_write=False):
            trace.append(["guard", require_write])
            try:
                yield
            finally:
                trace.append(["unguard", require_write])

    product = Product.__new__(Product)
    for field, value in {
        "state_root": state,
        "policy": NS(
            product_id="coding",
            project_scope_id="scope",
            authority_revision="policy-v1",
            bindings=(NS(source_trust_class="local-worker-candidate"),),
        ),
        "gc_gate": Gate(),
    }.items():
        object.__setattr__(product, field, value)

    def current(_self):
        nonlocal current_count
        current_count += 1
        trace.append(["product-current", current_count])
        if armed and case == "stale":
            raise ValueError("injected stale Product")

    patch.setattr(Product, "assert_root_gc_authority_current", current)
    original_init = Journal.__init__

    def journal_init(self, owner):
        trace.append(["approval-owner"])
        original_init(self, owner)

    def approval_current(self):
        nonlocal approval_count
        approval_count += 1
        trace.append(["approval-current", approval_count])
        if armed and case == "approval-error":
            raise ApprovalError("injected-approval")
        if armed and case == "approval-value-error":
            raise ValueError("injected approval value")
        if armed and (
            case == "approval-missing"
            or (case == "approval-late" and approval_count == 2)
        ):
            return None
        action = "revoke" if armed and case == "approval-revoke" else "approve"
        value = (
            Approval(
                "0" * 64,
                approved.catalog_sha256,
                approved.launcher_sha256,
                approved.profile_sha256,
            )
            if armed and case == "approval-other"
            else approved
        )
        return Decision.create(
            journal_revision=7 if case == "generation" else 3,
            scope_id="scope",
            operation_id="op",
            generation=7 if case == "generation" else 3,
            action=action,
            approval=None if action == "revoke" else value,
        )

    patch.setattr(Journal, "__init__", journal_init)
    patch.setattr(Journal, "current", approval_current)

    def version_leaf(tag):
        def version(_name):
            nonlocal version_count
            version_count += 1
            trace.append(["version", tag])
            if armed and (
                case == "version-error"
                or (case == "version-late-error" and version_count == 2)
            ):
                raise ValueError("injected version query")
            return "0.1.0"

        return version

    patch.setattr(installed, "version", version_leaf("installed"))
    patch.setattr(install, "version", version_leaf("install"))
    owner = Journal(product)
    target = state / "worker-native-release-v1"
    stage = state / ".worker-native-release-stage-fixed"
    if kind in ("receipt", "material") or (kind == "install" and case == "idempotent"):
        install.install_coding_product_worker_native_release(
            product, approval_owner=owner, approved=approved, wheel=wheel
        )
    if kind == "repair":
        if case != "no-stage":
            stage.mkdir(mode=0o700)
            if case not in ("partial-stage", "stage-symlink"):
                install._write_stage(stage, files, wheel, approved, product)
        if case == "multi-stage":
            (state / ".worker-native-release-stage-other").mkdir(mode=0o700)
        if case == "stage-symlink":
            stage.rmdir()
            stage.symlink_to(base, target_is_directory=True)
        if case == "target-exists":
            target.mkdir(mode=0o700)
    if case in ("stage-debt", "stage-symlink") and kind == "install":
        stage.mkdir(mode=0o700) if case == "stage-debt" else stage.symlink_to(
            base, target_is_directory=True
        )
    if case == "target-symlink":
        if target.exists():
            target.rename(state / "old-target")
        target.symlink_to(base, target_is_directory=True)
    if case == "private-root":
        state.chmod(0o755)
    if case == "owner-id":
        product.policy.product_id = "other"
    if case == "owner-trust":
        product.policy.bindings = ()
    if kind == "receipt" and case not in (
        "valid",
        "missing",
        "source-change",
        "source-oversize",
        "root-relative",
        "root-symlink",
    ):
        path = target / "product-native-release.json"
        value = json.loads(path.read_bytes())
        if case == "scope":
            value["scopeId"] = "other"
        if case == "digest":
            value["recordDigest"] = "0" * 64
        if case == "digest-case":
            value["wheelSha256"] = value["wheelSha256"].upper()
        if case in ("version-bool", "version-float"):
            value["version"] = True if case == "version-bool" else 1.0
        if case == "field":
            value["extra"] = True
        if case not in ("digest", "version-float"):
            value["recordDigest"] = sha256(
                canonical({k: v for k, v in value.items() if k != "recordDigest"})
            ).hexdigest()
        path.write_bytes(
            b"bad json"
            if case == "json"
            else json.dumps(value).encode()
            if case == "canonical"
            else canonical(value)
            if case == "newline"
            else canonical(value) + b"\n"
        )
    if kind == "receipt" and case == "missing":
        (target / "product-native-release.json").unlink()
    if case in ("source-change", "source-oversize"):
        (target / "source.whl").write_bytes(
            b"changed" if case == "source-change" else b"x" * (4 * 1024 * 1024 + 1)
        )
    if case == "root-symlink":
        target.rename(state / "old-target")
        target.symlink_to(state / "old-target", target_is_directory=True)
    real_open, real_close, real_fstat, real_fsync, real_write, real_read = (
        os.open,
        os.close,
        os.fstat,
        os.fsync,
        os.write,
        os.read,
    )

    def opened(path, flags, *args, **kwargs):
        nonlocal fd_seq
        parent = active.get(kwargs.get("dir_fd"))
        full = norm(parent[1] + "/" + str(path)) if parent else norm(path)
        selected = parent is not None or str(path).startswith(str(state))
        if selected:
            trace.append(["open", full, flags, list(args)])
        fd = real_open(path, flags, *args, **kwargs)
        if selected:
            fd_seq += 1
            active[fd] = (f"fd{fd_seq}", full)
        return fd

    def fstat(fd):
        if fd in active:
            trace.append(["fstat", active[fd][0]])
        return real_fstat(fd)

    def read(fd, count):
        if fd in active:
            trace.append(["read", active[fd][0], count])
        return real_read(fd, count)

    def fsync(fd):
        if fd in active:
            label, path = active[fd]
            trace.append(["fsync", label])
            if armed and (
                (case == "fsync-file" and path.endswith("/METADATA"))
                or (
                    case == "fsync-stage"
                    and ".worker-native-release-stage-" in path
                    and path.count("/") == 2
                )
                or (case == "fsync-parent" and path == "<ROOT>/state")
            ):
                raise OSError("injected fsync " + case)
        return real_fsync(fd)

    write_fault = False

    def write(fd, data):
        nonlocal write_fault
        if fd in active:
            label, path = active[fd]
            if armed and path.endswith("/METADATA"):
                if case == "write-partial":
                    data = data[:3]
                if case == "write-zero":
                    trace.append(["write", label, len(data), 0])
                    return 0
                if (
                    case in ("write-error", "write-cancel", "write-interrupt")
                    and not write_fault
                ):
                    write_fault = True
                    trace.append(["write-error", label])
                    raise {
                        "write-error": OSError,
                        "write-cancel": CancelledError,
                        "write-interrupt": KeyboardInterrupt,
                    }[case]("injected write")
            result = real_write(fd, data)
            trace.append(["write", label, len(data), result])
            return result
        return real_write(fd, data)

    def close(fd):
        if fd in active:
            label, path = active[fd]
            trace.append(["close", label])
            if armed and (
                (case == "close-file" and path.endswith("/METADATA"))
                or (
                    case == "close-stage"
                    and ".worker-native-release-stage-" in path
                    and path.count("/") == 2
                )
                or (case == "close-parent" and path == "<ROOT>/state")
            ):
                raise OSError("injected close " + case)
        real_close(fd)
        active.pop(fd, None)

    patch.setattr(os, "open", opened)
    patch.setattr(os, "fstat", fstat)
    patch.setattr(os, "fsync", fsync)
    patch.setattr(os, "write", write)
    patch.setattr(os, "read", read)
    patch.setattr(os, "close", close)
    # Pin the same actual effect point before and after its owner migration.
    if hasattr(installed, "_product_native_release_custody"):
        from loushang.harness.package_product import (
            _linux_worker_native_release as effects,
        )

        hook_owner = effects._LinuxWorkerNativeReleaseCustody
        verify_name = "verify_descriptor"
        original_verify = getattr(hook_owner, verify_name)

        def verify(self, fd, owner):
            result = original_verify(self, fd, owner)
            after_verify()
            return result
    else:
        effects = install
        hook_owner = install
        verify_name = "verify_coding_product_native_release_descriptor"
        original_verify = getattr(hook_owner, verify_name)

        def verify(fd, owner):
            result = original_verify(fd, owner)
            after_verify()
            return result

    def after_verify():
        if case == "stage-swap":
            p = next(
                p
                for p in state.iterdir()
                if p.name.startswith(".worker-native-release-stage-")
            )
            p.rename(state / "original-stage")
            p.symlink_to(base, target_is_directory=True)
        if case == "root-swap":
            state.rename(base / "old-state")
            state.mkdir(mode=0o700)

    patch.setattr(hook_owner, verify_name, verify)
    real_rename = effects._rename_directory_noreplace

    def rename(parent, name, parent2, target_name):
        trace.append(["rename", norm(name), target_name])
        if case == "rename-error":
            raise OSError("injected rename")
        if case == "rename-collision":
            target.mkdir(mode=0o700)
        result = real_rename(parent, name, parent2, target_name)
        if case == "stage-post-swap":
            target.rename(state / "original-target")
            target.symlink_to(base, target_is_directory=True)
        if case == "readback-source":
            (target / "source.whl").write_bytes(b"changed")
        return result

    patch.setattr(effects, "_rename_directory_noreplace", rename)
    trace.clear()
    current_count = approval_count = version_count = 0
    armed = True
    supplied_product = object() if case == "wrong-owner" else product
    supplied_approval = object() if case == "wrong-approval" else approved
    supplied_journal = object() if case == "wrong-journal" else owner
    if case == "other-product":
        supplied_journal = Journal(product)
        supplied_journal._product_owner = Product.__new__(Product)
    supplied_wheel = (
        b""
        if case == "empty"
        else "not bytes"
        if case == "not-bytes"
        else b"x" * (4 * 1024 * 1024 + 1)
        if case == "oversize"
        else b"invalid zip"
        if case in ("zip", "wheel-mismatch")
        else wheel
    )
    if case == "zip" and kind == "install":
        supplied_approval = Approval(
            sha256(supplied_wheel).hexdigest(),
            approved.catalog_sha256,
            approved.launcher_sha256,
            approved.profile_sha256,
        )

    def serialize(result):
        if isinstance(result, installed.CodingProductInstalledWorkerReleaseReader):
            return {
                "type": type(result).__module__ + "." + type(result).__qualname__,
                "same_owner": result.product_owner is product,
                "same_gate": result.gc_gate is product.gc_gate,
            }
        if isinstance(result, installed.CodingWorkerNativeLaunchMaterialV1):
            return {
                "type": type(result).__module__ + "." + type(result).__qualname__,
                "path": norm(result.launcher_path),
                "closure": result.closure.to_dict(),
            }
        if isinstance(result, tuple):
            return [result[0].to_dict(), result[1]]
        return result.to_dict() if hasattr(result, "to_dict") else result

    try:
        try:

            def operation():
                if kind == "review":
                    result = install.review_coding_product_worker_native_release(
                        supplied_product, wheel=supplied_wheel
                    )
                elif kind == "install":
                    result = install.install_coding_product_worker_native_release(
                        supplied_product,
                        approval_owner=supplied_journal,
                        approved=supplied_approval,
                        wheel=supplied_wheel,
                    )
                elif kind == "repair":
                    result = install.repair_coding_product_worker_native_release(
                        supplied_product,
                        approval_owner=supplied_journal,
                        approved=supplied_approval,
                    )
                elif kind == "receipt":
                    result = installed.verify_coding_product_native_release_root(
                        Path("relative") if case == "root-relative" else target, product
                    )
                else:
                    result = installed.CodingProductInstalledWorkerReleaseReader(
                        product_owner=product
                    ).current_launch_material()
                return result

            first = None
            if retry:
                try:
                    first = {"result": serialize(operation()), "error": None}
                except BaseException as exc:
                    first = {"result": None, "error": error_graph(exc, norm)}
                armed = False
                case = "retried"
                trace.append(["retry"])
            result = serialize(operation())
            error = None
        except BaseException as exc:
            result = None
            error = error_graph(exc, norm)
        if retry:
            result = {"first": first, "second": result}
        outstanding = [label for label, path in active.values()]
        tree = {}
        for root in (state, base / "old-state"):
            if not root.exists():
                continue
            for path in [root, *sorted(root.rglob("*"))]:
                st = path.lstat()
                item = {"mode": oct(stat.S_IMODE(st.st_mode))}
                if path.is_symlink():
                    item["link"] = norm(os.readlink(path))
                elif path.is_file():
                    data = path.read_bytes()
                    item.update(size=len(data), sha256=sha256(data).hexdigest())
                    item.update(
                        body=data.decode()
                        if path.name == "product-native-release.json"
                        else None
                    )
                tree[norm(path)] = item
        return {
            "result": result,
            "error": error,
            "trace": trace,
            "outstanding": outstanding,
            "tree": tree,
        }
    finally:
        for fd in tuple(active):
            with suppress(OSError):
                real_close(fd)


FIXTURE = json.loads(
    (
        Path(__file__).parent / "fixtures" / "linux_product_native_release_v1.json"
    ).read_text()
)


@pytest.mark.parametrize("case", CASES)
def test_original_linux_product_release_custody(case, tmp_path, monkeypatch):
    assert observe(case, tmp_path, monkeypatch) == FIXTURE["observations"][case]
    if case == "repair-multi-stage":
        # Trace normalization intentionally hides random suffixes. Check actual
        # names as well so two retained debt directories cannot collapse here.
        assert {
            path.name
            for path in (tmp_path / "state").iterdir()
            if path.name.startswith(".worker-native-release-stage-")
        } == {
            ".worker-native-release-stage-fixed",
            ".worker-native-release-stage-other",
        }
