from __future__ import annotations

from types import SimpleNamespace

import pytest

from .test_measure_g18_native import runner


def cli_arguments(root):
    return ["--install-a", str(root / "a"), "--install-b", str(root / "b"),
            "--observer-install", str(root / "observer"), "--wheel", str(root / "baseline.whl"),
            "--output", str(root / "output")]


@pytest.mark.parametrize("explicit", [None, "managed-mux", "managed-product-first-use", *runner.HISTORY_CASES])
def test_managed_case_is_explicit_and_original_cli_default_is_unchanged(tmp_path, monkeypatch, explicit):
    captured = []
    monkeypatch.setattr(runner, "collect_main", lambda args, parser: captured.append(args) or 0)
    assert runner.main(cli_arguments(tmp_path) + (["--cases", explicit] if explicit else [])) == 0
    assert captured[0].cases == ([explicit] if explicit else list(runner.CASES))


@pytest.mark.parametrize("case", runner.OPTIONAL_CASES)
def test_managed_mixed_campaign_rejected_before_source_or_installation_io(tmp_path, monkeypatch, case):
    monkeypatch.setattr(runner.platform, "system", lambda: "Linux")
    monkeypatch.setattr(runner.inert, "source_pair", lambda *a, **k: pytest.fail("no source IO for invalid campaign"))
    with pytest.raises(SystemExit) as caught:
        runner.main(cli_arguments(tmp_path) + ["--cases", "embedded", case])
    assert caught.value.code == 2
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("case", ["managed", "legacy", "product"])
def test_exact_campaign_selects_its_original_policy(monkeypatch, case):
    samples, calls = [], []

    def compare(label):
        def run(values, **kwargs):
            assert values is samples
            calls.append((label, kwargs))
            return {"verdict": "inconclusive"}
        return run

    monkeypatch.setattr(runner.inert, "comparison_module", lambda: SimpleNamespace(
        compare_managed=compare("managed"), compare_native=compare("legacy"), compare_managed_product=compare("product"),
    ))
    args = SimpleNamespace(fixed_slot=True, blocks=2, pairs_per_block=10, cache_mode="warm",
                           cases={"managed": ["managed-mux"], "product": ["managed-product-first-use"], "legacy": list(runner.CASES)}[case])
    assert runner.compare_selected_samples(args, samples, phase="aa") == {"verdict": "inconclusive"}
    assert calls == [(case, {"cache_mode": "warm", "phase": "aa", "blocks": 2, "pairs_per_block": 10})]


@pytest.mark.parametrize("case", runner.OPTIONAL_CASES)
@pytest.mark.parametrize("fault", ["small", "unfixed", "subset", "mixed"])
def test_diagnostic_or_partial_selection_never_gets_a_statistical_pass(monkeypatch, fault, case):
    monkeypatch.setattr(runner.inert, "comparison_module", lambda: pytest.fail("must not compare partial diagnostics"))
    args = SimpleNamespace(fixed_slot=True, blocks=2, pairs_per_block=10, cases=[case])
    if fault == "small":
        args.pairs_per_block = 1
    elif fault == "unfixed":
        args.fixed_slot = False
    elif fault == "subset":
        args.cases = ["embedded"]
    else:
        args.cases = [case, "embedded"]
    assert runner.compare_selected_samples(args, [], phase="aa")["verdict"] == "not-evaluated"


@pytest.mark.parametrize("case", runner.HISTORY_CASES)
def test_history_campaign_selects_only_its_frozen_metrics(monkeypatch, case):
    calls = []

    def compare(values, **kwargs):
        calls.append(kwargs)
        return {"verdict": "inconclusive"}

    monkeypatch.setattr(runner.inert, "comparison_module", lambda: SimpleNamespace(compare_managed_history=compare))
    args = SimpleNamespace(fixed_slot=True, blocks=2, pairs_per_block=10, cases=[case], cache_mode="warm")
    assert runner.compare_selected_samples(args, [], phase="aa") == {"verdict": "inconclusive"}
    assert calls == [dict(case=case, cache_mode="warm", phase="aa", blocks=2, pairs_per_block=10)]
