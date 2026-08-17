from __future__ import annotations

import json
import runpy
from collections.abc import Callable


def test_import_graph_example_uses_public_api(capsys) -> None:
    namespace = runpy.run_path("examples/coding/arch/01_import_graph.py")
    main = namespace["main"]
    assert isinstance(main, Callable)

    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["language"] == "python"
    assert payload["nodes"] == 3
    assert payload["eager_cycles"] == [["sample.api", "sample.core"]]
