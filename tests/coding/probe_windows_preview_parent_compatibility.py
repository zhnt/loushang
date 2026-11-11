"""Original public Windows previews with inert Product/native custody.

Concrete plan DTOs and their fingerprints are observed, but the synthetic
native facts and Product port do not establish authority or native validation.
"""

import importlib
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from loushang.harness.plugin_management.records import PluginInstallationKeyV1

KINDS = ("restore", "expiry")
CASES = (
    "success",
    "invalid_id",
    "unremoved",
    "inspect",
    "open",
    "parent_acl",
    "identity",
    "listdir",
    "stage",
    "manifest",
    "binding",
    "deletion_missing",
    "verify",
    "close",
    "post",
    "manifest_post",
    "manifest_close",
    "identity_post",
    "acl_exit",
    "manifest_acl_exit",
    "root_present",
    "archive_missing",
)


def observe(kind, case, patch):
    suffix = "restore_preview" if kind == "restore" else "backup_expiry_preview"
    code = importlib.import_module(
        "loushang.coding.package_private_data_windows_" + suffix
    )
    core = importlib.import_module(
        "loushang.harness.plugin_management._private_data_backup_windows"
    )
    native = importlib.import_module(
        "loushang.harness.resources.packages._private_tree_windows"
    )
    trace = []
    opened = set()
    inspect_count = 0
    base = Path.cwd() / "inert"
    parent = base / "backups"
    root = base / "target"
    key = PluginInstallationKeyV1("coding", "workspace", "scope", "coding.arch.default")
    backup = "a" * 64
    identifier = "bad" if case == "invalid_id" else backup
    receipt = NS(
        installation_key=key,
        backup_id=("b" * 64 if case == "binding" else backup),
        source_target_id="present:source",
        receipt_id="arch-backup:" + backup,
    )
    source = NS(target_id="present:source")
    deleted = NS(receipt_id="deleted:receipt")
    confirmation = NS(confirmation_id="arch-restore-confirm:" + ("c" * 64))

    def effect(label):
        trace.append(label)
        if case == label or (
            case.startswith("manifest_") and label in {"manifest", case[9:]}
        ):
            raise RuntimeError(label)

    @contextmanager
    def offline():
        trace.append("offline:enter")
        try:
            yield
        finally:
            trace.append("offline:exit")

    @contextmanager
    def state():
        trace.append("state:enter")
        opened.add(20)
        try:
            yield 20
        finally:
            opened.remove(20)
            trace.append("state:exit")

    class ACL:
        def __enter__(self):
            trace.append("acl:enter")
            return self

        def validate(self, fd):
            trace.append(f"acl:{fd}")
            if fd == 10 and case == "parent_acl":
                raise RuntimeError("parent_acl")

        def __exit__(self, *args):
            effect("acl_exit")

    def inspect(path):
        nonlocal inspect_count
        assert path == parent
        inspect_count += 1
        effect("inspect" if inspect_count == 1 else "inspect_post")
        return (
            (9, 9)
            if inspect_count == 2 and case in {"post", "manifest_post", "identity_post"}
            else (1, 2)
        )

    def open_directory(path, **kwargs):
        assert path == parent and kwargs == dict(share_delete=False, read_control=True)
        effect("open")
        opened.add(10)
        return 10

    def identity(fd):
        assert fd == 10 and fd in opened
        trace.append("identity")
        return (9, 9) if case in {"identity", "identity_post"} else (1, 2)

    def close(fd):
        assert fd == 10 and fd in opened
        trace.append("close")
        if case in {"close", "manifest_close"}:
            raise OSError("close")
        opened.remove(fd)

    def names(fd):
        assert fd == 10 and fd in opened
        effect("listdir")
        return ("left.staging",) if case == "stage" else ()

    def manifest(fd, name, acl):
        assert fd in opened and name == backup
        effect("manifest")
        return receipt, source

    def verify(*args):
        assert 10 in opened
        effect("verify")

    def latest(*args):
        trace.append("latest_deletion")
        return None if case == "deletion_missing" else deleted

    class Deletion:
        def __init__(self, *args):
            trace.append("deletion:init")

        def events(self):
            trace.append("deletion:events")
            return (NS(phase="completed"),)

        def _close(self):
            trace.append("deletion:close")

    class Transaction:
        state_fd = 20

        def completed_plan_revision_for(self, plan):
            trace.append("restore:revision")
            return 5

        def verify_confirmation(self, plan, identifier):
            trace.append("restore:confirmation")
            return confirmation

        def _completed_restore(self, plan):
            trace.append("restore:completed")
            return NS(record_digest="d" * 64), NS(target_id="present:restored")

    @contextmanager
    def transaction():
        trace.append("restore_tx:enter")
        try:
            yield Transaction()
        finally:
            trace.append("restore_tx:exit")

    def archive(*args):
        trace.append("capture_archive")
        return NS(
            root_identity=None if case == "archive_missing" else (1, 2, 3, 4, 5),
            target_id="present:archive",
        )

    patch.setattr(code, "coding_arch_installation_private_data_root", lambda *a: root)
    patch.setattr(code, "backup_parent", lambda *a: parent)
    patch.setattr(code, "CodingWindowsArchPrivateDataDeletionTransaction", Deletion)
    patch.setattr(code, "latest_deleted_target_receipt", latest)
    patch.setattr(code, "_read_archive_manifest", manifest)
    for module in (code, core):
        patch.setattr(module, "WindowsPrivateDirectoryAcl", ACL)
        if hasattr(module, "open_windows_directory"):
            patch.setattr(module, "open_windows_directory", open_directory)
        patch.setattr(
            module, "inspect_windows_product_private_directory_identity", inspect
        )
        if hasattr(module, "os"):
            patch.setattr(module, "os", NS(close=close))
    patch.setattr(code, "windows_listdir_at", names)
    if hasattr(code, "_directory_identity"):
        patch.setattr(code, "_directory_identity", identity)
    patch.setattr(
        native.PrivateWindowsTreeIO, "directory_identity", lambda self, fd: identity(fd)
    )
    if kind == "restore":
        cls = code.CodingWindowsArchPrivateDataRestorePreview
        patch.setattr(
            code,
            "CodingWindowsArchPrivateDataReadPreview",
            lambda *a: NS(_offline=offline),
        )
        patch.setattr(code, "_verify_archive", verify)
        patch.setattr(
            code,
            "inspect_coding_windows_arch_installation_root",
            lambda *a, **k: (1, 2) if case == "root_present" else None,
        )
        patch.setattr(
            code, "_require_no_restore_stage", lambda *a: trace.append("target_stage")
        )
    else:
        cls = code.CodingWindowsArchPrivateDataBackupExpiryPreview
        patch.setattr(
            code,
            "CodingWindowsArchPrivateDataRestoreJournal",
            lambda *a: NS(transaction=transaction),
        )
        patch.setattr(code, "capture_windows_arch_backup_archive", archive)
    product = NS(
        state_root=base / "state",
        epoch_runtime=NS(borrow_product_state_root_descriptor=state),
        desired_state=NS(
            snapshot=lambda: NS(
                inventory_revision=7,
                installation=lambda k: NS(
                    latest_instance_revision_ref="selected",
                    selection=NS(
                        desired_state="installed_enabled"
                        if case == "unremoved"
                        else "absent"
                    ),
                ),
            )
        ),
    )
    owner = object.__new__(cls)
    object.__setattr__(owner, "layout", NS())
    object.__setattr__(owner, "product", product)
    value, error = None, None
    try:
        result = (
            owner.preview(key, identifier)
            if kind == "restore"
            else owner.preview(key, identifier, confirmation.confirmation_id)
        )
        value = {"plan": result.to_dict(), "fingerprint": result.fingerprint}
    except Exception as exc:
        error = []
        while exc is not None:
            error.append([type(exc).__name__, str(exc), exc.__suppress_context__])
            exc = exc.__context__
    return dict(trace=trace, value=value, error=error, unclosed=sorted(opened))


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("case", CASES)
def test_original_windows_previews(kind, case, monkeypatch):
    expected = json.loads(
        (
            Path(__file__).parent / "fixtures" / "windows_preview_parent_v1.json"
        ).read_text()
    )
    assert observe(kind, case, monkeypatch) == expected[f"{kind}:{case}"]
