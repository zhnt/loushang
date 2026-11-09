"""Original initialized Windows history read scope using inert native ports.

No native ACL, file durability, marker repair or Product authority is claimed.
"""

import importlib
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

KINDS = ("receipt", "native_approval", "opt_in")
CASES = (
    "present",
    "absent",
    "missing_lock",
    "orphan",
    "empty_lock",
    "uninitialized_file",
    "root",
    "acl_init",
    "acl_enter",
    "acl_validate",
    "visible_before",
    "lock_stat",
    "data_stat",
    "lock_enter",
    "validate",
    "read",
    "decode",
    "visible_after",
    "lock_exit",
    "acl_exit",
    "decode_lock_exit",
    "decode_acl_exit",
)
NAMES = dict(
    receipt="CodingWindowsWorkerReceiptJournal",
    native_approval="CodingWindowsWorkerNativeApprovalJournal",
    opt_in="CodingWindowsWorkerOptInJournal",
)


def observe(kind, case, patch):
    code = importlib.import_module(
        f"loushang.coding.package_product_worker_windows_{kind}_journal"
    )
    io = importlib.import_module(
        "loushang.harness.resources.packages._windows_journal_file"
    )
    trace = []
    active = set()
    visible_count = 0
    name = code._NAME

    def effect(label):
        trace.append(label)
        if case == label or (
            case.startswith("decode_") and label in {"decode", case[7:]}
        ):
            raise RuntimeError(label)

    class ACL:
        def __init__(self):
            effect("acl_init")

        def __enter__(self):
            effect("acl_enter")
            active.add("acl")
            return self

        def validate(self, fd):
            assert fd == 10
            effect("acl_validate")

        def __exit__(self, *args):
            active.remove("acl")
            effect("acl_exit")

    def stat(root, entry):
        assert root == 10 and "acl" in active
        label = "lock_stat" if entry == name + ".lock" else "data_stat"
        assert entry in {name, name + ".lock"}
        effect(label)
        if label == "lock_stat" and case in {"absent", "missing_lock", "data_stat"}:
            raise FileNotFoundError("lock missing")
        if label == "data_stat" and case == "absent":
            raise FileNotFoundError("data missing")
        return NS()

    @contextmanager
    def lock(root, entry, mode):
        assert (root, entry, mode) == (10, name + ".lock", "shared")
        assert active == {"acl"}
        effect("lock_enter")
        active.add("lock")
        try:
            yield "borrowed-lock"
        finally:
            active.remove("lock")
            effect("lock_exit")

    def validate(self, root, acl, *, locked_handle):
        assert active == {"acl", "lock"} and locked_handle == "borrowed-lock"
        effect("validate")
        return case not in {"empty_lock", "uninitialized_file"}

    def read(self, root, acl):
        assert active == {"acl", "lock"}
        effect("read")
        return None if case in {"empty_lock", "orphan"} else b"raw\n"

    def require_root(root):
        assert root == 10 and not active
        effect("root")

    def visible(root):
        nonlocal visible_count
        assert root == 10 and "acl" in active
        visible_count += 1
        effect("visible_before" if visible_count == 1 else "visible_after")
        if case in {"absent", "empty_lock"} and visible_count == 2:
            assert ("lock" in active) == (case == "empty_lock")
        elif visible_count == 2:
            assert "lock" not in active

    def decode(raw):
        assert active == {"acl", "lock"} and raw == b"raw\n"
        effect("decode")
        return ("decoded",)

    for module in (io,):
        patch.setattr(module, "WindowsPrivateDirectoryAcl", ACL)
        patch.setattr(module, "windows_stat_at", stat)
        patch.setattr(module, "journal_file_lock_at", lock, raising=False)
    patch.setattr(io.WindowsJournalFileIO, "validate_lock", validate)
    patch.setattr(io.WindowsJournalFileIO, "read", read)
    # Constructor input only: the native ports below never open this path.
    owner = getattr(code, NAMES[kind])(Path.cwd() / "inert" / name, scope_id="scope")
    patch.setattr(owner, "_require_root", require_root)
    patch.setattr(owner, "_assert_visible_root", visible)
    patch.setattr(owner, "_decode", decode)
    value, error = None, None
    try:
        method = owner.records if kind == "receipt" else owner.history_read_only
        value = list(method(directory_fd=10))
    except Exception as exc:

        def details(error):
            return [
                type(error).__name__,
                str(error),
                getattr(error, "code", None),
                error.__suppress_context__,
            ]

        error = [details(exc)]
        prior = exc.__context__
        while prior is not None:
            error.append(details(prior))
            prior = prior.__context__
    return dict(trace=trace, value=value, error=error, active=sorted(active))


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("case", CASES)
def test_windows_worker_original_read_scope(kind, case, monkeypatch):
    expected = json.loads(
        (
            Path(__file__).parent / "fixtures" / "windows_worker_read_scopes_v1.json"
        ).read_text()
    )
    assert observe(kind, case, monkeypatch) == expected[f"{kind}:{case}"]
