from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from loushang.coding.cli import lmux, lmux_command

from . import _lmux_product_entry as entry


@pytest.mark.parametrize("failure", [None, RuntimeError("startup"), KeyboardInterrupt()])
@pytest.mark.parametrize("diagnostic", [False, True, "interaction"])
@pytest.mark.parametrize("command", [["new", "-s", "perf"], ["start", "-t", "perf"]])
def test_fixed_parent_retains_cli_exit_and_restores_factory(monkeypatch, failure, diagnostic, command):
    original = lmux_command.coding_managed_process_request
    observed = []
    def selected():
        return None
    arguments = (["--interaction-diagnostic"] if diagnostic == "interaction" else
                 ["--admission-diagnostic"] if diagnostic else []) + command
    for module in (lmux, lmux_command):
        monkeypatch.setattr(module, "__file__", str(Path(sys.prefix) / "installed.py"))

    def load(path):
        if Path(path).name == "_hosted_boundary_trace.py":
            return {"BoundaryTrace": lambda root: root}
        if Path(path).name == "_lmux_interaction_receipt.py":
            @contextmanager
            def observe(client_type, trace):
                observed.append("enter")
                try:
                    yield
                finally:
                    observed.append("exit")
            return {"observe_interaction_receipts": observe}
        assert Path(path) == Path(entry.__file__).with_name("_lmux_product_child.py")
        return {"request_factory": selected}

    def main(argv):
        assert argv == command
        factory = lmux_command.coding_managed_process_request
        if diagnostic is True:
            assert factory.func is selected and factory.keywords == {"admission_diagnostic": True}
        else:
            assert factory is selected
        assert observed == (["enter"] if diagnostic == "interaction" else [])
        if failure is not None:
            raise failure
        return 130

    monkeypatch.setattr(entry.runpy, "run_path", load)
    monkeypatch.setattr(lmux, "main", main)
    if failure is None:
        assert entry.main(arguments) == 130
    else:
        with pytest.raises(type(failure)) as caught:
            entry.main(arguments)
        assert caught.value is failure
    assert lmux_command.coding_managed_process_request is original
    assert observed == (["enter", "exit"] if diagnostic == "interaction" else [])


@pytest.mark.parametrize("arguments", [["start"], ["start", "-t", "other"],
    ["start", "-t", "perf", "--workspace", "/tmp"], ["attach", "-t", "perf"],
    ["new", "-s", "other"], ["start", "--server", "perf"]])
def test_fixed_restart_does_not_accept_arbitrary_launch_arguments(monkeypatch, arguments):
    monkeypatch.setattr(entry.runpy, "run_path", lambda *_: pytest.fail("must not load helper"))
    with pytest.raises(ValueError, match="fixed Product parent"):
        entry.main(arguments)


@pytest.mark.parametrize("fault", ["arguments", "origin"])
def test_fixed_parent_rejects_before_loading_helpers(monkeypatch, tmp_path, fault):
    original = lmux_command.coding_managed_process_request
    monkeypatch.setattr(lmux, "__file__", str(tmp_path / "outside.py"))
    monkeypatch.setattr(entry.runpy, "run_path", lambda *_: pytest.fail("must reject before helper load"))
    with pytest.raises(ValueError):
        entry.main(["server", "start"] if fault == "arguments" else ["new", "-s", "perf"])
    assert lmux_command.coding_managed_process_request is original
