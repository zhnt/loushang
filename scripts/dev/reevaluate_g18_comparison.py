"""Re-evaluate an existing G18 campaign under the accepted ARD-004 contract.

This is a read-only re-evaluation, never a new measurement and never a rewrite:

- the original ``report.json`` is only read; its sha256 is recorded so the
  re-evaluation stays bound to the exact bytes it interpreted;
- the verdict is recomputed with the currently accepted constants in
  ``_g18_comparison`` (ARD-004: ``STABILITY_RATIO`` 1/4, ``REGRESSION_RATIO``
  3/10);
- output goes to a new file and refuses to overwrite anything.

A ``pass`` here means "no regression beyond the accepted ratio was detected
under the new gate". It is not proof that no regression exists: the accepted
ratio bounds what this design can detect, and that limit must travel with the
result. This module never prints or implies "performance accepted".
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent
CASES = (
    "embedded",
    "foreground",
    "local-mux",
    "g14-stdio",
    "recovery-cwd",
    "recovery-global",
    "product-first-use",
)
OPTIONAL_CASES = (
    "managed-mux",
    "managed-product-first-use",
    "managed-product-history-warm",
    "managed-product-history-restore",
)
HISTORY_CASES = (
    "managed-product-history-warm",
    "managed-product-history-restore",
)
SUPPORT_NAMES = (
    "_g18_comparison",
    "_g18_provenance",
    "_g18_recovery",
    "_g18_slot",
    "_g18_bytecode",
    "_g18_checkpoint",
)


def _support(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPT / (name + ".py"))
    if spec is None or spec.loader is None:
        raise ValueError(f"comparison support missing: {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def select_comparator(comparison, report):
    """Mirror the collector's own frozen dispatch, refusing anything else."""
    cases = report.get("cases")
    blocks = report.get("blocks")
    pairs = report.get("pairs_per_block")
    if type(cases) is not list or blocks != 2 or pairs != 10:
        raise ValueError(
            "re-evaluation requires the frozen two-block ten-pair policy"
        )
    if cases == ["managed-mux"]:
        return lambda samples, **kw: comparison.compare_managed(samples, **kw)
    if len(cases) == 1 and cases[0] in HISTORY_CASES:
        return lambda samples, **kw: comparison.compare_managed_history(
            samples, case=cases[0], **kw
        )
    if cases == ["managed-product-first-use"]:
        return lambda samples, **kw: comparison.compare_managed_product(
            samples, **kw
        )
    if set(cases) == set(CASES):
        return lambda samples, **kw: comparison.compare_native(samples, **kw)
    raise ValueError("campaign does not match a frozen comparison policy")


def reevaluate(report_path, output):
    comparison = _support("_g18_comparison")
    report_path = Path(report_path)
    output = Path(output)
    if output.exists():
        raise ValueError("refusing to overwrite an existing re-evaluation")
    source_sha256 = digest(report_path)
    report = json.loads(report_path.read_text())
    recorded = report.get("comparison") or {}
    samples = report.get("samples")
    if report.get("status") != "complete-record-only" or not isinstance(samples, list):
        raise ValueError("only a completed uninterrupted campaign can be re-evaluated")
    # A checkpoint-enabled campaign is fine only if it never actually resumed:
    # exactly one uninterrupted segment and automatically eligible. A real
    # resume records extra segments and sets eligible_for_automatic_acceptance
    # false, which needs its own separately declared calibration audit.
    segments = report.get("segments")
    if segments is not None:
        if type(segments) is not list or len(segments) != 1:
            raise ValueError("resumed campaigns need their own calibration audit")
        acceptance = report.get("segmented_acceptance")
        if (
            type(acceptance) is not dict
            or acceptance.get("eligible_for_automatic_acceptance") is not True
        ):
            raise ValueError("resumed campaigns need their own calibration audit")
    phase = recorded.get("phase")
    cache_mode = recorded.get("cache_mode")
    if phase not in {"aa", "ab"} or cache_mode not in {"warm", "absent"}:
        raise ValueError("recorded phase or cache condition is unusable")
    compare = select_comparator(comparison, report)
    result = compare(
        samples,
        cache_mode=cache_mode,
        phase=phase,
        blocks=report["blocks"],
        pairs_per_block=report["pairs_per_block"],
    )
    value = {
        "schema_version": 1,
        "record_kind": "g18-contract-reevaluation-not-a-new-measurement",
        "decision": "apphost/ARD-004 (accepted 2026-09-18)",
        "source_report": str(report_path.resolve()),
        "source_report_sha256": source_sha256,
        "source_status": report["status"],
        "source_cases": report["cases"],
        "source_phase": phase,
        "source_cache_mode": cache_mode,
        "source_verdict_before": recorded.get("verdict"),
        "contract": {
            "stability_ratio": str(comparison.STABILITY_RATIO),
            "regression_ratio": str(comparison.REGRESSION_RATIO),
            "reason": "unstaged judgement constants replaced by the accepted ADR pair",
        },
        "verdict": result["verdict"],
        "comparison": result,
        "claims": {
            "is_new_measurement": False,
            "is_performance_acceptance": False,
            "statements": [
                "verdict change is caused by the judgement contract, not by new data",
                "a pass means no regression beyond the accepted ratio was detected",
                "regressions below the accepted ratio are not detectable by this design",
                "the original report was not modified; this file references its sha256",
            ],
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    value = reevaluate(args.report, args.output)
    print(
        f"{value['source_report']}: "
        f"{value['source_verdict_before']} -> {value['verdict']} "
        f"(contract change, not a new measurement)",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
