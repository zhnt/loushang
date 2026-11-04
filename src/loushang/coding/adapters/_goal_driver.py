"""Trusted finite calculator verifier, runnable with Python -I -S.

This is a deliberately bounded source language, not a general Python sandbox.
Inputs are immutable bytes supplied through the existing SDK command's stdin.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import sys
import unittest
from pathlib import Path

SIGNATURES = {"subtract": ("a", "b"), "clamp": ("value", "lower", "upper")}
CASE_KEYS = {"id", "function", "requirement", "args", "expected"}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strict_json(data: bytes | str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("nonfinite JSON constant")

    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant)


def validate_source(source: bytes) -> ast.Module:
    if len(source) > 16 * 1024:
        raise ValueError("source exceeds profile")
    try:
        tree = ast.parse(source.decode("utf-8"))
    except SyntaxError as error:
        raise ValueError("source syntax is invalid") from error
    nodes = list(ast.walk(tree))

    def depth(node):
        return 1 + max((depth(c) for c in ast.iter_child_nodes(node)), default=0)

    if len(nodes) > 128 or depth(tree) > 16:
        raise ValueError("source AST exceeds profile")
    allowed = (
        ast.Module,
        ast.FunctionDef,
        ast.arguments,
        ast.arg,
        ast.Return,
        ast.If,
        ast.Name,
        ast.Load,
        ast.Constant,
        ast.BinOp,
        ast.Add,
        ast.Sub,
        ast.Compare,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.BoolOp,
        ast.And,
        ast.Or,
        ast.UnaryOp,
        ast.USub,
        ast.UAdd,
        ast.Not,
    )
    if any(not isinstance(n, allowed) for n in nodes):
        raise ValueError("source syntax outside finite calculator profile")
    if len(tree.body) != 2 or {getattr(n, "name", None) for n in tree.body} != set(
        SIGNATURES
    ):
        raise ValueError("fixed functions required")
    if sum(isinstance(n, ast.FunctionDef) for n in nodes) != 2:
        raise ValueError("only the two top-level function definitions are allowed")
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef):
            raise ValueError("only functions allowed")
        args = function.args
        expected = SIGNATURES[function.name]
        if (
            tuple(a.arg for a in args.args) != expected
            or args.posonlyargs
            or args.kwonlyargs
            or args.defaults
            or args.kw_defaults
            or args.vararg
            or args.kwarg
            or function.decorator_list
            or function.returns
            or function.type_comment
            or any(a.annotation for a in args.args)
        ):
            raise ValueError("fixed unannotated function signatures required")
        for node in ast.walk(function):
            if isinstance(node, ast.Name) and node.id not in expected:
                raise ValueError("only parameter reads allowed")
            if isinstance(node, ast.Constant) and (
                type(node.value) is not int or abs(node.value) > 1000
            ):
                raise ValueError("only bounded integer constants allowed")
    return tree


def validate_tests(content: bytes) -> list[dict]:
    if len(content) > 16 * 1024:
        raise ValueError("test package exceeds profile")
    value = strict_json(content)
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "cases", "domain_policy", "requirements"}
        or type(value["version"]) is not int
        or value["version"] != 1
    ):
        raise ValueError("unsupported tests")
    if (
        value["domain_policy"] != "python-pure-functions-v1"
        or not isinstance(value["requirements"], dict)
        or set(value["requirements"]) != {"R-SUB", "R-CLAMP", "R-FILES"}
        or any(
            type(v) is not str or not v or len(v) > 4096
            for v in value["requirements"].values()
        )
    ):
        raise ValueError("unsupported test requirement mapping")
    cases = value["cases"]
    if not isinstance(cases, list) or not 1 <= len(cases) <= 64:
        raise ValueError("invalid case count")
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != CASE_KEYS:
            raise ValueError("invalid test case fields")
        cid, name, args, expected = (
            case["id"],
            case["function"],
            case["args"],
            case["expected"],
        )
        if (
            type(cid) is not str
            or not cid
            or len(cid) > 100
            or cid in ids
            or name not in SIGNATURES
        ):
            raise ValueError("invalid or duplicate test identity")
        ids.add(cid)
        if (
            case["requirement"] != {"subtract": "R-SUB", "clamp": "R-CLAMP"}[name]
            or not isinstance(args, list)
            or len(args) != len(SIGNATURES[name])
            or any(type(n) is not int or abs(n) > 1000 for n in args)
            or type(expected) is not int
            or abs(expected) > 10000
        ):
            raise ValueError("invalid bounded case data")
        if name == "clamp" and args[1] > args[2]:
            raise ValueError("invalid clamp interval")
    if {c["requirement"] for c in cases} != {"R-SUB", "R-CLAMP"}:
        raise ValueError("fixed requirements need case coverage")
    return cases


def content_entry(content: bytes) -> dict:
    return {
        "content": base64.b64encode(content).decode("ascii"),
        "sha256": digest(content),
        "bytes": len(content),
    }


def read_entry(value: object) -> bytes:
    if not isinstance(value, dict) or set(value) != {"content", "sha256", "bytes"}:
        raise ValueError("invalid input bytes entry")
    result = base64.b64decode(value["content"], validate=True)
    if (
        type(value["bytes"]) is not int
        or value["bytes"] != len(result)
        or value["sha256"] != digest(result)
    ):
        raise ValueError("input content mismatch")
    return result


def verify(bundle: bytes) -> dict:
    if len(bundle) > 64 * 1024:
        raise ValueError("input bundle exceeds profile")
    value = strict_json(bundle)
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "identity", "source", "tests", "driver_sha256"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or value["driver_sha256"] != digest(Path(__file__).read_bytes())
    ):
        raise ValueError("unsupported input/driver")
    identity = value["identity"]
    if (
        not isinstance(identity, dict)
        or set(identity) != {"goal_id", "revision", "epoch", "operation_id"}
        or any(
            type(identity[k]) is not str or not identity[k]
            for k in ["goal_id", "operation_id"]
        )
        or any(
            type(identity[k]) is not int or identity[k] < 1
            for k in ["revision", "epoch"]
        )
    ):
        raise ValueError("invalid verification identity")
    source, tests = read_entry(value["source"]), read_entry(value["tests"])
    tree, cases = validate_source(source), validate_tests(tests)
    namespace: dict[str, object] = {"__builtins__": {}}
    exec(compile(tree, "calculator.py", "exec"), namespace)
    observed = []

    class FixedCase(unittest.TestCase):
        def __init__(self, case):
            super().__init__("runTest")
            self.case = case

        def id(self):
            return self.case["id"]

        def runTest(self):
            actual = namespace[self.case["function"]](*self.case["args"])
            observed.append({"id": self.id(), "actual": actual})
            self.assertIs(type(actual), int)
            self.assertEqual(actual, self.case["expected"])

    result = unittest.TestResult()
    unittest.TestSuite(FixedCase(c) for c in cases).run(result)
    failed_ids = {c.id() for c, _ in result.failures}
    error_ids = {c.id() for c, _ in result.errors}
    outcomes = [
        {"id": c["id"], "passed": c["id"] not in failed_ids | error_ids} for c in cases
    ]
    return {
        "version": 1,
        "identity": identity,
        "input_bundle_sha256": digest(bundle),
        "source_sha256": digest(source),
        "tests_sha256": digest(tests),
        "driver_sha256": value["driver_sha256"],
        "results": outcomes,
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
    }


def main() -> int:
    try:
        result = verify(sys.stdin.buffer.read(64 * 1024 + 1))
    except Exception as error:
        print(json.dumps({"version": 1, "admission_error": str(error)}))
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0 if not (result["failures"] or result["errors"] or result["skipped"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
