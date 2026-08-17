from __future__ import annotations

import asyncio
from io import StringIO

from loushang.harness.scenario import run_fake_workflow_cli


def test_fake_workflow_cli_runs_without_product_runtime(tmp_path) -> None:
    workflow = tmp_path / "workflow.yaml"
    workflow.write_text(
        """
name: fake
backend: fake
steps:
  - prompt: hello
""".lstrip(),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    async def runner(**kwargs: object) -> int:
        captured.update(kwargs)
        return 7

    result = asyncio.run(
        run_fake_workflow_cli(
            str(workflow),
            project_root=tmp_path,
            runner=runner,
            stdout=StringIO(),
            stderr=StringIO(),
            verbose=True,
            output_mode="json",
        )
    )

    assert result == 7
    assert captured["runtime"] is None
    assert captured["session"] is None
    assert captured["output_mode"] == "json"
