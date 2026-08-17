"""Analyze a small Python package without loading or executing it."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from loushang.coding.arch import analyze_import_graph, query_import_graph


def main() -> None:
    with TemporaryDirectory(prefix="loushang-arch-example-") as temporary:
        package = Path(temporary) / "sample"
        package.mkdir()
        (package / "__init__.py").write_text(
            "from . import api\n",
            encoding="utf-8",
        )
        (package / "api.py").write_text(
            "from sample import core\n",
            encoding="utf-8",
        )
        (package / "core.py").write_text(
            "from sample import api\n",
            encoding="utf-8",
        )

        graph = analyze_import_graph(
            package,
            package_prefix="sample",
            imports="all",
        )
        result = query_import_graph(graph, "summary", limit=10)
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
