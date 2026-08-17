from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts/ai/check_coverage_targets.py"
SPEC = importlib.util.spec_from_file_location("check_coverage_targets", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
check_coverage_targets_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_coverage_targets_module)
check_coverage_targets = check_coverage_targets_module.check_coverage_targets
main = check_coverage_targets_module.main


def test_check_coverage_targets_accepts_runtime_core_and_adapter_buckets(
    tmp_path: Path,
) -> None:
    coverage_xml = tmp_path / "coverage.xml"
    coverage_xml.write_text(
        """<?xml version="1.0" ?>
<coverage>
  <packages>
    <package>
      <classes>
        <class filename="context.py"><lines>
          <line number="1" hits="1"/><line number="2" hits="1"/>
          <line number="3" hits="1"/><line number="4" hits="1"/>
          <line number="5" hits="1"/><line number="6" hits="1"/>
          <line number="7" hits="1"/><line number="8" hits="1"/>
          <line number="9" hits="1"/><line number="10" hits="0"/>
        </lines></class>
        <class filename="protocols/unused.py"><lines>
          <line number="1" hits="0"/>
        </lines></class>
        <class filename="protocols/anthropic_messages.py"><lines>
          <line number="1" hits="1"/><line number="2" hits="0"/>
        </lines></class>
        <class filename="protocols/openai_chat_completions.py"><lines>
          <line number="1" hits="1"/><line number="2" hits="1"/>
        </lines></class>
        <class filename="protocols/openai_responses.py"><lines>
          <line number="1" hits="1"/><line number="2" hits="1"/>
        </lines></class>
        <class filename="protocols/_anthropic.py"><lines>
          <line number="1" hits="1"/>
        </lines></class>
        <class filename="protocols/_openai_responses.py"><lines>
          <line number="1" hits="1"/>
        </lines></class>
        <class filename="protocols/_helpers.py"><lines>
          <line number="1" hits="1"/>
        </lines></class>
      </classes>
    </package>
  </packages>
</coverage>
""",
        encoding="utf-8",
    )

    results = check_coverage_targets(coverage_xml)

    assert [(result.name, round(result.percent, 2)) for result in results] == [
        ("ai-runtime-core", 90.0),
        ("provider-adapters", 88.89),
        ("production-adapter-modules", 83.33),
    ]
    assert main([str(coverage_xml), "--adapter-min", "83"]) == 0
    assert main([str(coverage_xml)]) == 1
