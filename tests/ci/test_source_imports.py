from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

imports = importlib.import_module("tests.architecture._source_imports")


class SourceImportFactsTests(unittest.TestCase):
    def setUp(self):
        imports._import_facts.cache_clear()

    def test_resolves_absolute_relative_members_aliases_and_guarded_imports(self):
        path = Path("src/loushang/example/nested/module.py")
        source = (
            "import os as renamed\n"
            "from loushang import apphost as host\n"
            "from .. import parent\n"
            "if False:\n    from .child import Thing as alias\n"
        )
        self.assertEqual(imports.resolved_imports(path, source), {
            "os", "loushang", "loushang.apphost", "loushang.example",
            "loushang.example.parent", "loushang.example.nested.child",
            "loushang.example.nested.child.Thing",
        })
        self.assertEqual(imports.resolved_imports(path, source, include_members=False), {
            "os", "loushang", "loushang.example", "loushang.example.nested.child",
        })

    def test_reuses_one_parse_but_returns_independent_results(self):
        path = Path("src/example/module.py")
        with patch.object(imports.ast, "parse", wraps=imports.ast.parse) as parse:
            first = imports.resolved_imports(path, "import os\n")
            first.add("mutated")
            self.assertEqual(imports.resolved_imports(path, "import os\n"), {"os"})
            self.assertEqual(parse.call_count, 1)

    def test_content_change_is_visible_even_with_identical_size_and_timestamp(self):
        with tempfile.TemporaryDirectory(dir="src") as tmp:
            path = Path(tmp) / "module.py"
            path.write_text("import os\n")
            before = path.stat()
            self.assertEqual(imports.resolved_imports(path), {"os"})
            path.write_text("import re\n")
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
            self.assertEqual(imports.resolved_imports(path), {"re"})

    def test_invalid_relative_and_syntax_remain_failures(self):
        path = Path("src/example/module.py")
        self.assertEqual(imports.resolved_imports(path, "from .... import thing\n"),
                         {"<invalid-relative-import>"})
        with self.assertRaises(SyntaxError):
            imports.resolved_imports(path, "from . import\n")


if __name__ == "__main__":
    unittest.main()
