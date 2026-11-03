from __future__ import annotations

import sys
from pathlib import Path

import pytest

from loushang.coding import managed_process

from . import _lmux_product_child as child
from .test_managed_process_arguments import invocation

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux managed test child")


@pytest.mark.parametrize("diagnostic", [False, True])
def test_fixed_request_preserves_production_environment_streams_and_arguments(tmp_path, diagnostic):
    selected = invocation(tmp_path)
    environment = {"LOUSHANG_HOME": "/other", "LABEL": "test"}
    options = dict(executable=sys.executable, environment=environment,
                   session_root=tmp_path / "sessions")
    original = managed_process.coding_managed_process_request(selected, 7, **options)
    fixed = child.request_factory(selected, 7, **options, admission_diagnostic=diagnostic)
    from dataclasses import replace

    assert replace(fixed, argv=original.argv) == original
    assert fixed.argv == (sys.executable, "-I", str(Path(child.__file__).resolve()), *original.argv[3:],
                          *(("--admission-diagnostic",) if diagnostic else ()))
    assert environment == {"LOUSHANG_HOME": "/other", "LABEL": "test"}


@pytest.mark.parametrize("fault", [None, "origin", "permissions", "run"])
@pytest.mark.parametrize("diagnostic", [False, True])
@pytest.mark.parametrize("gated", [False, True])
def test_fixed_child_uses_only_fixed_helpers_and_original_arguments(tmp_path, monkeypatch, fault, diagnostic, gated):
    selected = invocation(tmp_path)
    arguments = [selected.to_json(), str(tmp_path / "sessions"), "7"]
    original_arguments = list(arguments)
    if diagnostic:
        arguments.append("--admission-diagnostic")
    root = tmp_path / "lmux-test-observations"
    root.mkdir(mode=0o700)
    if gated:
        (root / "completion-gates").mkdir(mode=0o700)
    if fault == "permissions":
        root.chmod(0o755)
    monkeypatch.setattr(
        managed_process, "__file__",
        str(tmp_path / "foreign.py" if fault == "origin" else Path(sys.prefix) / "installed-module.py"),
    )
    events, helpers = [], []
    failure = RuntimeError("fixed composition failed")

    class Trace:
        def __init__(self, selected_root):
            assert selected_root == root

        def emit(self, phase, **fields):
            events.append((phase, fields))

    def run_product(argv, witness, **options):
        assert argv == original_arguments
        assert set(options) == (({"admission_diagnostic"} if diagnostic else set())
                                | ({"completion_gate"} if gated else set()))
        if fault == "run":
            raise failure
        witness("tool_executed", "lmux-call-1")
        return 17

    def load(path):
        name = Path(path).name
        helpers.append(name)
        if name == "_hosted_boundary_trace.py":
            return {"BoundaryTrace": Trace, "install": lambda: pytest.fail("must not install tracing")}
        if name == "_lmux_completion_gate.py":
            def gate(selected_root, instance):
                assert selected_root == root / "completion-gates"
                assert instance == selected.instance.instance_id
                return object()
            return {"CompletionGate": gate}
        assert name == "_lmux_synthetic_product.py"
        return {"run_product": run_product}

    monkeypatch.setattr(child.runpy, "run_path", load)
    if fault in {"origin", "permissions"}:
        with pytest.raises(ValueError):
            child.main(arguments)
        assert helpers == [] and events == []
    elif fault == "run":
        with pytest.raises(RuntimeError) as caught:
            child.main(arguments)
        assert caught.value is failure
        assert [phase for phase, _ in events] == ["fixed_product_selected"]
    else:
        assert child.main(arguments) == 17
        assert helpers == ["_hosted_boundary_trace.py", "_lmux_synthetic_product.py",
                           *(["_lmux_completion_gate.py"] if gated else [])]
        assert events == [
            ("fixed_product_selected", {"instance_id": selected.instance.instance_id}),
            ("tool_executed", {"call_id": "lmux-call-1"}),
            ("fixed_product_returned", {"status": 17}),
        ]
