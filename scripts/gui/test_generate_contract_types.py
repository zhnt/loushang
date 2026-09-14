"""Focused generator tests, opt-in and independent of runtime suites."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import generate_contract_types as generator


class ContractGenerationTests(unittest.TestCase):
    def test_reproducible_and_checked_in(self) -> None:
        first = generator.generate()
        self.assertEqual(first, generator.generate())
        for name, content in first.items():
            self.assertEqual(
                content, (generator.OUTPUT / name).read_text(encoding="utf-8")
            )

    def test_integer_policies_and_explicit_nullability(self) -> None:
        artifacts = generator.generate()
        self.assertIn(
            "readonly controllerGeneration: DecimalCounter;", artifacts["bridge.ts"]
        )
        self.assertIn("readonly finalCursor: number | null;", artifacts["bridge.ts"])
        self.assertIn("pub final_cursor: Option<u64>", artifacts["bridge.rs"])
        self.assertNotIn("serde::Deserialize", artifacts["bridge.rs"])
        manifest = json.loads(artifacts["manifest.json"])
        self.assertEqual("candidate", manifest["status"])
        self.assertEqual(set(generator.SOURCES), set(manifest["sources"]))

    def test_missing_integer_policy_fails_closed(self) -> None:
        with patch.object(
            generator, "DECIMAL", generator.DECIMAL - {"SessionSnapshotV1.cursor"}
        ):
            with self.assertRaisesRegex(ValueError, "Unclassified integer"):
                generator.generate()

    def test_stale_integer_policy_fails_closed(self) -> None:
        with patch.object(generator, "SAFE", generator.SAFE | {"MissingV1.cursor"}):
            with self.assertRaisesRegex(ValueError, "Stale integer policies"):
                generator.generate()


if __name__ == "__main__":
    unittest.main()
