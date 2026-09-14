"""Generate candidate bridge shapes, never a wire decoder or security policy.

The Python model and codec remain authoritative. Unknown annotations and integer
fields fail closed; explicit field policies prevent accidental JS precision loss.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import fields
from enum import Enum
from pathlib import Path
from types import UnionType
from typing import get_args, get_origin, get_type_hints

from loushang.appserver.execution import codec as execution
from loushang.appserver.protocol import model as app

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "gui/contracts/generated"
SOURCES = (
    "src/loushang/appserver/protocol/model.py",
    "src/loushang/appserver/protocol/errors.py",
    "src/loushang/appserver/protocol/codec.py",
    "src/loushang/appserver/execution/model.py",
    "src/loushang/appserver/execution/codec.py",
)
# Only integer representations are bridge policy. Bounds and cross-field
# invariants still require independent validators and reference codec evidence.
DECIMAL = {
    "SessionSnapshotV1.cursor",
    "SessionSnapshotV1.revision",
    "SessionEventV1.cursor",
    "SessionSnapshotRequestV1.controller_generation",
    "MuxSpaceMemberV1.position",
    "MuxSpaceV1.revision",
    "MuxAttachmentV1.controller_generation",
    "MuxDetachV1.controller_generation",
}
SAFE = {
    "ExecutionStateV1.revision",
    "ExecutionObservationV1.final_cursor",
    "ExecutionSessionViewV1.revision",
    "ExecutionUpdateV1.revision",
    "MuxAttachV1.mailbox_capacity",
}
EXTRA = (
    app.MuxSelectorV1,
    app.MuxAttachV1,
    app.MuxDetachV1,
    app.MuxSpaceMemberV1,
    app.MuxSpaceV1,
    app.AttachedSessionV1,
    app.MuxAttachmentV1,
)


def camel(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(part.title() for part in rest)


def generate() -> dict[str, str]:
    shapes = dict(execution._FIELDS)  # Deliberate, pinned reference-codec input.
    for cls in EXTRA:
        shapes[cls] = tuple(field.name for field in fields(cls))
    enums: dict[str, type[Enum]] = {}
    unions: dict[str, tuple[object, ...]] = {}
    used: set[str] = set()

    def annotation(value: object, key: str, rust: bool) -> str:
        if value is str:
            return "String" if rust else "string"
        if value is bool:
            return "bool" if rust else "boolean"
        if value is int:
            used.add(key)
            if key in DECIMAL:
                return "DecimalCounter"
            if key in SAFE:
                return "u64" if rust else "number"
            raise ValueError(f"Unclassified integer: {key}")
        args, origin = get_args(value), get_origin(value)
        if origin is UnionType:
            if type(None) in args:
                members = tuple(item for item in args if item is not type(None))
                if len(members) != 1:
                    raise ValueError(f"Unsupported nullable union: {key}")
                inner = annotation(members[0], key, rust)
                return f"Option<{inner}>" if rust else f"{inner} | null"
            if rust:
                name = "".join(
                    part[:1].upper() + part[1:]
                    for part in key.replace(".", "_").split("_")
                )
                unions[name] = args
                return name
            return " | ".join(annotation(item, key, False) for item in args)
        if origin is tuple and len(args) == 2 and args[1] is Ellipsis:
            inner = annotation(args[0], key, rust)
            return f"Vec<{inner}>" if rust else f"ReadonlyArray<{inner}>"
        if isinstance(value, type) and issubclass(value, Enum):
            enums[value.__name__] = value
            return value.__name__
        if value in shapes:
            return value.__name__
        raise ValueError(f"Unsupported annotation at {key}: {value}")

    ts = ["export type DecimalCounter = string;"]
    rs = ["pub type DecimalCounter = String;"]
    for cls, names in sorted(shapes.items(), key=lambda item: item[0].__name__):
        hints = get_type_hints(cls)
        ts.append(f"export interface {cls.__name__} {{")
        rs.extend(
            ["#[derive(Debug, serde::Serialize)]", f"pub struct {cls.__name__} {{"]
        )
        for name in names:
            key = f"{cls.__name__}.{name}"
            ts.append(
                f"  readonly {camel(name)}: {annotation(hints[name], key, False)};"
            )
            rs.extend(
                [
                    f'    #[serde(rename = "{camel(name)}")]',
                    f"    pub {name}: {annotation(hints[name], key, True)},",
                ]
            )
        ts.append("}")
        rs.append("}")
    for name, members in sorted(unions.items()):
        rs.extend(
            [
                "#[derive(Debug, serde::Serialize)]",
                "#[serde(untagged)]",
                f"pub enum {name} {{",
            ]
        )
        for index, member in enumerate(members):
            rs.append(f"    Variant{index}({annotation(member, name, True)}),")
        rs.append("}")
    for name, cls in sorted(enums.items()):
        ts.append(
            f"export type {name} = "
            + " | ".join(json.dumps(item.value) for item in cls)
            + ";"
        )
        rs.extend(["#[derive(Debug, serde::Serialize)]", f"pub enum {name} {{"])
        for index, item in enumerate(cls):
            rs.extend(
                [
                    f"    #[serde(rename = {json.dumps(item.value)})]",
                    f"    Variant{index},",
                ]
            )
        rs.append("}")
    if used != DECIMAL | SAFE:
        raise ValueError(f"Stale integer policies: {(DECIMAL | SAFE) - used}")
    hashes = {
        source: hashlib.sha256(
            (ROOT / source).read_text(encoding="utf-8").encode("utf-8")
        ).hexdigest()
        for source in SOURCES
    }
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    header = f"// Generated by scripts/gui/generate_contract_types.py; source digest {digest}\n// Candidate bridge shapes only; NOT wire validators. Do not edit.\n"
    manifest = {
        "format": "gui-bridge-shapes/v1",
        "status": "candidate",
        "sourceDigest": digest,
        "sources": hashes,
        "scope": "execution nested values plus attachment model shapes; not complete envelopes or auth",
        "modelOnlyTypes": sorted(cls.__name__ for cls in EXTRA),
        "decimalFields": sorted(DECIMAL),
        "safeNumericFields": sorted(SAFE),
    }
    return {
        "bridge.ts": header + "\n".join(ts) + "\n",
        "bridge.rs": header + "\n".join(rs) + "\n",
        "manifest.json": json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="regenerate checked-in artifacts"
    )
    args = parser.parse_args()
    artifacts = generate()
    if args.write:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        for name, content in artifacts.items():
            (OUTPUT / name).write_text(content, encoding="utf-8", newline="\n")
    else:
        for name, content in artifacts.items():
            path = OUTPUT / name
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                raise SystemExit(f"Generated contract drift: {name}; run with --write")
    print(
        f"Contract shapes {'generated' if args.write else 'verified'}: {len(artifacts)} artifacts"
    )


if __name__ == "__main__":
    main()
