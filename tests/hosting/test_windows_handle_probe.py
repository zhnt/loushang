from __future__ import annotations

import ctypes
from ctypes import wintypes
from functools import partial

import pytest

from ._windows_handle_probe import WindowsHandleIdentityProbe


class _Kernel:
    """Distinct process handle tables, including a deterministic value collision."""

    def __init__(self) -> None:
        self.expected = 2**40 + 32
        self.child_process = 2**40 + 64
        self.duplicate = 2**40 + 96
        self.parent = {self.expected: "parent-pipe"}
        self.child = {self.expected: "child-unrelated-object"}
        self.error = 0
        self.duplicate_error = 0
        self.fail_compare = False
        self.fail_close = False
        self.closed: list[int] = []
        self.duplicate_calls: list[tuple[object, ...]] = []
        self.GetCurrentProcess = lambda: 777
        self.GetProcessId = lambda handle: 123 if handle.value == self.child_process else 0
        self.GetHandleInformation = lambda handle, flags: handle.value in self.parent
        self.DuplicateHandle = partial(self._duplicate)
        self.CompareObjectHandles = partial(self._compare)
        self.CloseHandle = partial(self._close)

    def _duplicate(self, process, source, target, output, access, inherit, options):
        self.duplicate_calls.append(
            (process.value, source.value, target, access, inherit, options)
        )
        if self.duplicate_error or source.value not in self.child:
            self.error = self.duplicate_error or 6
            return False
        self.parent[self.duplicate] = self.child[source.value]
        ctypes.cast(output, ctypes.POINTER(wintypes.HANDLE))[0] = self.duplicate
        return True

    def _compare(self, left, right):
        if self.fail_compare:
            raise RuntimeError("probe comparison failed")
        return self.parent[left.value] == self.parent[right.value]

    def _close(self, handle):
        self.closed.append(handle.value)
        if self.fail_close:
            self.error = 5
            return False
        del self.parent[handle.value]
        return True

    def probe(self):
        return WindowsHandleIdentityProbe(self, last_error=lambda: self.error)


def test_same_numeric_handle_in_another_process_is_not_inheritance() -> None:
    api = _Kernel()
    # The old child-side GetHandleInformation(numeric_value) reports leakage.
    assert api.expected in api.child
    assert not api.probe().matches(api.child_process, api.expected, api.expected)
    assert api.closed == [api.duplicate]
    assert api.parent == {api.expected: "parent-pipe"}
    assert api.duplicate_calls == [
        (api.child_process, api.expected, 777, 0, False, 0x2)
    ]
    assert api.DuplicateHandle.argtypes[:3] == (wintypes.HANDLE,) * 3
    assert api.GetCurrentProcess.restype is wintypes.HANDLE


@pytest.mark.parametrize("same_number", [False, True])
def test_actual_shared_object_is_detected_even_with_a_different_handle_value(
    same_number: bool,
) -> None:
    api = _Kernel()
    remote = api.expected if same_number else api.expected + 4
    api.child[remote] = api.parent[api.expected]
    assert api.probe().matches(api.child_process, remote, api.expected)
    assert api.closed == [api.duplicate]
    assert api.child[remote] == "parent-pipe"  # Never close the child source.


def test_absent_child_handle_is_negative_evidence_without_cleanup() -> None:
    api = _Kernel()
    api.child.clear()
    assert not api.probe().matches(api.child_process, api.expected, api.expected)
    assert not api.closed


@pytest.mark.parametrize("fault", ["process", "reference", "duplicate", "compare", "close"])
def test_probe_failure_cannot_be_reported_as_successful_isolation(fault: str) -> None:
    api = _Kernel()
    if fault == "process":
        api.GetProcessId = lambda handle: 0
    elif fault == "reference":
        api.parent.clear()
    elif fault == "duplicate":
        api.duplicate_error = 5
    elif fault == "compare":
        api.fail_compare = True
    else:
        api.fail_close = True
    with pytest.raises((OSError, RuntimeError)):
        api.probe().matches(api.child_process, api.expected, api.expected)
    assert api.closed == ([api.duplicate] if fault in {"compare", "close"} else [])
