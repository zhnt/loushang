"""Original A80 public values, transfer states, and canonical header bytes."""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import enum
import hashlib
import inspect
import json
import os
import pickle
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from loushang.apphost import SessionCreateIntentV1, SessionCreateRequestV1
from loushang.appserver.protocol import SessionScopeV1
from loushang.coding import hosted_catalog as hosted
from loushang.coding import managed_catalog as managed
from loushang.coding.hosted_session import CodingHostedHistoryBindingV1
from loushang.coding.resume_history import (
    CodingResumeHeaderPreview,
    CodingResumeHistoryPreview,
)
from loushang.harness.conversation import ConversationHeader
from loushang.harness.transcript import _canonical_header

HERE = Path(__file__).resolve().parent
INPUTS = None
CASES = (
    "reflection",
    "scope-cwd",
    "scope-home",
    "scope-relative",
    "scope-enum",
    "metadata-cwd",
    "metadata-home",
    "metadata-compat-unknown",
    "metadata-bool",
    "metadata-float",
    "metadata-extra",
    "metadata-session-mismatch",
    "metadata-scope-mismatch",
    "metadata-empty-continuity",
    "record-projections",
    "record-duplicate-policies",
    "binding-transfer",
    "binding-close-retry",
    "binding-retained-owner",
    "candidate-claim",
    "candidate-close-retry",
    "candidate-stale",
    "history-transfer",
    "history-close-retry",
    "resume-source-values",
    "resume-source-close-failure",
    "validator-valid",
    "validator-wrong-type",
    "canonical-legacy",
    "canonical-owned",
    "canonical-managed",
)
REJECTED = {
    "scope-relative": ("builtins.ValueError",),
    "scope-enum": ("builtins.ValueError",),
    **{
        name: ("loushang.coding.hosted_catalog.CodingHostedCatalogError",)
        for name in (
            "metadata-bool",
            "metadata-float",
            "metadata-extra",
            "metadata-session-mismatch",
            "metadata-scope-mismatch",
            "candidate-stale",
            "validator-wrong-type",
        )
    },
    "metadata-empty-continuity": (
        "loushang.apphost.errors.InvalidAppHostContractError",
    ),
}


def fq(value):
    module = getattr(value, "__module__", None)
    if module is None:
        module = value.__objclass__.__module__
    return f"{module}.{value.__qualname__}"


def exception(error, seen=None):
    seen = set() if seen is None else seen
    if id(error) in seen:
        return {"cycle": fq(type(error))}
    seen.add(id(error))
    result = {
        "type": fq(type(error)),
        "args": freeze(error.args),
        "suppress": error.__suppress_context__,
        "notes": list(getattr(error, "__notes__", ())),
        "cause": exception(error.__cause__, seen) if error.__cause__ else None,
        "context": exception(error.__context__, seen) if error.__context__ else None,
    }
    for key in ("code", "errno", "filename", "filename2"):
        if hasattr(error, key):
            result[key] = freeze(getattr(error, key))
    return result


def freeze(value):
    if isinstance(value, enum.Enum):
        return {"enum": fq(type(value)), "value": value.value}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {
            "base64": base64.b64encode(value).decode(),
            "sha256": hashlib.sha256(value).hexdigest(),
            "length": len(value),
        }
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            "class": fq(type(value)),
            "fields": {
                field.name: freeze(getattr(value, field.name))
                for field in dataclasses.fields(value)
            },
        }
    if isinstance(value, Mapping):
        return {str(k): freeze(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [freeze(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, type):
        return {"type": fq(value)}
    return {"object_type": fq(type(value))}


def caught(function):
    try:
        return {"value": freeze(function())}
    except BaseException as error:
        return {"error": exception(error)}


async def acaught(function):
    try:
        return {"value": freeze(await function())}
    except BaseException as error:
        return {"error": exception(error)}


def dtype(value):
    cls = type(value)
    fields = []
    for field in dataclasses.fields(value):
        fields.append(
            {
                "name": field.name,
                "type": str(field.type),
                "init": field.init,
                "repr": field.repr,
                "compare": field.compare,
                "kw_only": field.kw_only,
                "default": "<MISSING>"
                if field.default is dataclasses.MISSING
                else freeze(field.default),
                "factory": "<MISSING>"
                if field.default_factory is dataclasses.MISSING
                else fq(field.default_factory),
            }
        )

    def roundtrip():
        restored = pickle.loads(pickle.dumps(value))
        return {"class": fq(type(restored)), "equal": restored == value}

    return {
        "class": fq(cls),
        "constructor": str(inspect.signature(cls)),
        "own_annotations": {
            k: str(v) for k, v in cls.__dict__.get("__annotations__", {}).items()
        },
        "fields": fields,
        "dataclass_params": {
            name: getattr(cls.__dataclass_params__, name)
            for name in ("init", "repr", "eq", "order", "unsafe_hash", "frozen")
        },
        "slots": list(cls.__dict__.get("__slots__", ())),
        "has_dict": hasattr(value, "__dict__"),
        "repr": re.sub(r"0x[0-9a-f]+", "0x<ADDRESS>", repr(value)),
        "pickle": caught(roundtrip),
    }


def reflection():
    result = {}
    for module in (hosted, managed):
        rows = {}
        for name in module.__all__:
            value = getattr(module, name)
            if not callable(value):
                rows[name] = freeze(value)
                continue
            row = {
                "class": fq(value),
                "constructor": str(inspect.signature(value)),
                "own_annotations": {
                    k: str(v)
                    for k, v in value.__dict__.get("__annotations__", {}).items()
                },
            }
            methods = {}
            for key in dir(value):
                if key.startswith("_") and key != "__init__":
                    continue
                item = inspect.getattr_static(value, key)
                function = (
                    item.fget if isinstance(item, property) else getattr(value, key)
                )
                if inspect.isfunction(function) or inspect.ismethod(function):
                    methods[key] = {
                        "fq": fq(function),
                        "signature": str(inspect.signature(function)),
                        "annotations": {
                            k: str(v)
                            for k, v in getattr(function, "__annotations__", {}).items()
                        },
                    }
            row["methods"] = methods
            rows[name] = row
        result[module.__name__] = rows
    return result


def paths(case):
    assert INPUTS is not None
    root = INPUTS / case
    root.mkdir(parents=True, mode=0o700)
    workspace = root / "workspace"
    workspace.mkdir(mode=0o700)
    return root, workspace


def scope_at(root, workspace, scope=SessionScopeV1.CWD):
    return hosted.CodingHostedScopeV1(scope, root / "sessions", workspace)


def request_for(scope):
    return SessionCreateRequestV1(
        "coding",
        scope.fingerprint,
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        requested_continuity_id="fixed-continuity",
        requested_scope=scope.discovery_scope,
    )


def record_for(scope, *, compatibility="coding-hosted-v1"):
    request = request_for(scope)
    sid = hosted._create_identity(request)
    metadata = {
        "version": 1,
        "compatibilityId": compatibility,
        "continuityId": "fixed-continuity",
        "sessionId": sid,
        "scope": scope.scope.value,
        "scopeFingerprint": scope.fingerprint,
        "operationId": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    }
    header = ConversationHeader(
        sid,
        1,
        "2026-11-09T00:00:00Z",
        metadata={"cwd": str(scope.cwd), "coding.hosted": metadata},
    )
    identity, compat, operation = hosted._hosted_header_identity(
        header, scope=scope.scope, fingerprint=scope.fingerprint
    )
    envelope = hosted.SessionIdentityEnvelopeV1(
        "coding",
        compat,
        identity.continuity_id,
        identity.session_id,
        "coding.jsonl",
        sid,
    )
    projection = hosted.SessionIdentityProjectionV1(
        hosted.SessionCandidateRefV1(scope.source_id, sid, "a" * 64),
        scope.discovery_scope,
        hosted.SessionCandidateMode.CANONICAL,
        envelope,
    )
    return hosted._Record(
        projection,
        identity,
        scope,
        scope.session_dir / f"hosted-{sid}.jsonl",
        operation,
        header,
    )


def empty_history(record):
    return CodingResumeHistoryPreview(
        CodingResumeHeaderPreview(record.header, "coding", None),
        (),
        (),
        None,
        None,
        False,
        "none",
        None,
        None,
        "a" * 64,
        "b" * 64,
    )


class Disposal:
    def __init__(self):
        self.calls = []
        self.fail = False

    async def dispose_runtime_profile(self):
        self.calls.append("manager-dispose")
        if self.fail:
            raise OSError("controlled manager dispose failure")

    async def constructed(self):
        self.calls.append("constructed-dispose")
        if self.fail:
            raise OSError("controlled constructed dispose failure")


class Current:
    def __init__(self):
        self.calls = []

    def __call__(self):
        self.calls.append("current")


async def binding_case(case, record):
    manager = Disposal()
    binding = hosted.CodingHostedCandidateBindingV1(record, manager)
    if case == "binding-transfer":
        assert binding.manager_for_construction() is manager
        taken = binding.take_manager()
        await binding.close()
        return {
            "same": taken is manager,
            "after_take": caught(binding.manager_for_construction),
            "twice": caught(binding.take_manager),
            "calls": manager.calls,
        }
    if case == "binding-retained-owner":
        binding.retain_constructed_owner(manager.constructed)
        await binding.close()
        await binding.close()
        return {
            "calls": manager.calls,
            "after_close": caught(binding.manager_for_construction),
        }
    if case == "binding-close-retry":
        manager.fail = True
        first = await acaught(binding.close)
        retained = binding.manager_for_construction() is manager
        manager.fail = False
        await binding.close()
        await binding.close()
        return {
            "first": first,
            "retained": retained,
            "calls": manager.calls,
            "after_close": caught(binding.manager_for_construction),
        }
    candidate = hosted._Candidate(record, binding)
    with patch.object(
        _canonical_header, "canonical_transcript_revision", return_value="a" * 64
    ):
        if case == "candidate-stale":
            with patch.object(
                _canonical_header,
                "canonical_transcript_revision",
                return_value="c" * 64,
            ):
                return await candidate.claim()
        if case == "candidate-close-retry":
            manager.fail = True
            first = await acaught(candidate.close)
            state = (candidate._closed, candidate._claimed)
            manager.fail = False
            await candidate.close()
            return {
                "first": first,
                "state_after_failure": state,
                "calls": manager.calls,
            }
        claimed = await candidate.claim()
        second = await acaught(candidate.claim)
        await candidate.close()
        calls_before_claim_close = list(manager.calls)
        await claimed.close()
        return {
            "candidate_class": fq(type(candidate)),
            "claim_class": fq(type(claimed)),
            "same_binding": claimed.opaque_binding is binding,
            "same_reference": claimed.reference == record.projection.reference,
            "second": second,
            "calls_before_claim_close": calls_before_claim_close,
            "calls": manager.calls,
        }


async def history_case(case, record):
    history = empty_history(record)
    actual = CodingHostedHistoryBindingV1(record.identity, history)
    current = Current()
    binding = hosted.CodingHostedHistoryCandidateBindingV1(
        record,
        actual,
        current,
        manager_type=hosted._HostedTranscript,
        writer_factory=hosted._HOSTED_FACTORY,
    )
    with patch.object(hosted, "_revision", return_value="a" * 64):
        if case == "history-transfer":
            source = binding.take_resume_source()
            assert source.history_binding is actual
            source.require_current_source()
            result = {
                "source_class": fq(type(source)),
                "history_same": source.history is history,
                "manager_type": fq(source.manager_type),
                "writer_same": source.writer_factory is hosted._HOSTED_FACTORY,
                "supports": binding.supports_writable_resume,
                "after_take": caught(binding.take_binding),
                "calls": current.calls,
            }
            await binding.close()
            await source.close()
            result["after_source_close"] = caught(source.require_current_source)
            return result
        if case == "history-close-retry":
            calls = []
            original = actual.close

            async def fail():
                calls.append("failed-close")
                raise OSError("controlled history close failure")

            actual.close = fail
            first = await acaught(binding.close)
            retained = binding._binding is actual
            actual.close = original
            await binding.close()
            return {
                "first": first,
                "retained": retained,
                "after": binding._binding is None,
                "calls": calls,
            }
        source = hosted.CodingHostedResumeSourceV1(
            record, actual, hosted._HostedTranscript, hosted._HOSTED_FACTORY, current
        )
        if case == "resume-source-values":
            result = {
                "dtype": dtype(source),
                "record_dtype": dtype(record),
                "history_same": source.history is history,
            }
            await source.close()
            result["closed"] = source._closed
            result["history_after_close"] = caught(lambda: source.history)
            return result
        calls = []

        async def fail():
            calls.append("failed-close")
            raise OSError("controlled source close failure")

        actual.close = fail
        first = await acaught(source.close)
        second = await acaught(source.close)
        return {
            "first": first,
            "second": second,
            "closed": source._closed,
            "history_after_close": caught(lambda: source.history),
            "calls": calls,
        }


async def canonical(case, scope):
    scope.session_dir.mkdir(mode=0o700)
    if case == "canonical-managed":
        catalog = managed.CodingManagedSessionCatalogV1(
            session_root=scope.session_dir, workspace=scope.cwd
        )
        scope = catalog.scopes[0]
    else:
        catalog = hosted.CodingHostedSessionCatalogV1(
            (scope,), owned_transcripts=case == "canonical-owned"
        )
    factory = catalog._owned_factory or hosted._HOSTED_FACTORY
    original_clock = factory._clock
    factory._clock = lambda: datetime(2026, 11, 9, tzinfo=UTC)
    candidate = None
    try:
        candidate = await catalog.create_candidate(
            SessionCreateIntentV1(
                request_for(scope), hosted.CODING_HOSTED_COMPATIBILITY_ID
            )
        )
        record = candidate._record
        path = record.path
        body = path.read_bytes()
        manager = candidate._binding.manager_for_construction()
        assert record.projection.reference.revision == hosted._revision(path)
        result = {
            "catalog_class": fq(type(catalog)),
            "manager_class": fq(type(manager)),
            "scope": freeze(scope),
            "identity": freeze(record.identity),
            "envelope": freeze(record.projection.envelope),
            "header": freeze(record.header),
            "full_bytes": freeze(body),
            "metadata": freeze(record.header.metadata),
            "filename": path.name,
            "create_id": hosted._create_identity(request_for(scope)),
            "reference_revision_is_sha256": len(record.projection.reference.revision)
            == 64,
            "pending": len(catalog.pending_sessions),
        }
        await candidate.close()
        candidate = None
        repeated = await catalog.find_created_candidate(request_for(scope))
        assert repeated is not None
        result["retry_same_identity"] = (
            repeated.projection.envelope == record.projection.envelope
        )
        await repeated.close()
        result["bytes_after_retry"] = freeze(path.read_bytes())
        return result
    finally:
        factory._clock = original_clock
        if candidate is not None:
            await candidate.close()
        await catalog.close()


async def _observe(case):
    if case == "reflection":
        return reflection()
    root, workspace = paths(case)
    scope = scope_at(
        root,
        workspace,
        SessionScopeV1.USER_HOME
        if case in ("scope-home", "metadata-home")
        else SessionScopeV1.CWD,
    )
    if case == "scope-relative":
        return hosted.CodingHostedScopeV1(
            SessionScopeV1.CWD, Path("relative"), workspace
        )
    if case == "scope-enum":
        return hosted.CodingHostedScopeV1("cwd", root / "sessions", workspace)
    if case.startswith("scope-"):
        return {
            "dtype": dtype(scope),
            "fingerprint": scope.fingerprint,
            "source_id": scope.source_id,
            "discovery_scope": freeze(scope.discovery_scope),
        }
    record = record_for(scope)
    if case.startswith("metadata-"):
        raw = dict(record.header.metadata["coding.hosted"])
        changes = {
            "metadata-bool": ("version", True),
            "metadata-float": ("version", 1.0),
            "metadata-extra": ("extra", "value"),
            "metadata-session-mismatch": ("sessionId", "other"),
            "metadata-scope-mismatch": ("scopeFingerprint", "c" * 64),
            "metadata-empty-continuity": ("continuityId", ""),
            "metadata-compat-unknown": ("compatibilityId", "future-hosted-v9"),
        }
        if case in changes:
            key, value = changes[case]
            raw[key] = value
        header = dataclasses.replace(
            record.header, metadata={"cwd": str(scope.cwd), "coding.hosted": raw}
        )
        return {
            "identity": freeze(
                hosted._hosted_header_identity(
                    header, scope=scope.scope, fingerprint=scope.fingerprint
                )
            ),
            "metadata": freeze(header.metadata),
            "create_id": hosted._create_identity(request_for(scope)),
        }
    if case.startswith("binding-") or case.startswith("candidate-"):
        return await binding_case(case, record)
    if case.startswith("history-") or case.startswith("resume-source-"):
        return await history_case(case, record)
    if case.startswith("validator-"):
        binding = hosted.CodingHostedCandidateBindingV1(record, Disposal())
        claimed = hosted._Claimed(
            record.projection.reference,
            binding if case == "validator-valid" else object(),
        )
        opened = await hosted.CodingHostedCandidateValidatorV1().open_product_candidate(
            claimed, record.projection.envelope
        )
        await opened.close()
        return {
            "opened_class": fq(type(opened)),
            "binding_same": opened.opaque_binding is binding,
            "key": freeze(opened.binding_key),
            "manager_retained": binding._manager is not None,
        }
    if case.startswith("canonical-"):
        return await canonical(case, scope)
    base = hosted.CodingHostedSessionCatalogV1((scope,))
    other = managed.CodingManagedSessionCatalogV1(
        session_root=scope.session_dir, workspace=scope.cwd
    )
    try:
        home_scope = other.scopes[1]
        home_record = dataclasses.replace(record, scope=home_scope)
        if case == "record-projections":
            changed = dataclasses.replace(
                record,
                header=dataclasses.replace(
                    record.header,
                    metadata={
                        **record.header.metadata,
                        "cwd": str(root / "historical-workspace"),
                    },
                ),
            )
            unsupported = dataclasses.replace(record, compatible=False)
            return {
                "base": {
                    "display": freeze(base._display_identity(changed)),
                    "visible": base._record_visible(changed),
                    "available": base._record_available(changed),
                },
                "managed": {
                    "display": freeze(other._display_identity(changed)),
                    "visible": other._record_visible(changed),
                    "available": other._record_available(changed),
                },
                "base_open_unsupported": caught(
                    lambda: base._validate_open_record(unsupported)
                ),
                "managed_open_unsupported": caught(
                    lambda: other._validate_open_record(unsupported)
                ),
            }
        return {
            "base_same": caught(lambda: base._validate_records([record, record])),
            "managed_two_views": caught(
                lambda: other._validate_records([record, home_record])
            ),
            "managed_same_view": caught(
                lambda: other._validate_records([record, record])
            ),
            "managed_other_file": caught(
                lambda: other._validate_records(
                    [
                        record,
                        dataclasses.replace(home_record, path=root / "other.jsonl"),
                    ]
                )
            ),
        }
    finally:
        await base.close()
        await other.close()


def observe(case):
    try:
        result = asyncio.run(_observe(case))
        observed = {"result": freeze(result)}
    except BaseException as error:
        observed = {"error": exception(error)}
    expected_types = REJECTED.get(case)
    if expected_types is None:
        assert "error" not in observed, (case, observed)
    else:
        assert observed.get("error", {}).get("type") in expected_types, (case, observed)
    return observed


# Frozen original input formulas; these helpers never read observed identities.
_PORTABLE_INPUT_ROOT = Path("/__loushang_a80_values__")
_PORTABLE_OPERATION_ID = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _portable_scope_digest(scope: str, session_dir: Path, cwd: Path) -> str:
    parts = ["coding.hosted.scope/v1", scope, os.path.normcase(str(session_dir))]
    if scope == "cwd":
        parts.append(os.path.normcase(str(cwd)))
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


def _portable_create_digest(scope_digest: str) -> str:
    return hashlib.sha256(
        "\0".join(
            (
                "coding.hosted.create/v1",
                "coding",
                scope_digest,
                _PORTABLE_OPERATION_ID,
            )
        ).encode()
    ).hexdigest()


def _portable_input_replacements(case: str, input_root: Path) -> dict[str, str]:
    source = Path(input_root) / case
    target = _PORTABLE_INPUT_ROOT / case
    replacements = {str(source): str(target)}
    # JSON string fragments are declaration encodings, not observed hash roles.
    for ensure_ascii in (False, True):
        replacements[json.dumps(str(source), ensure_ascii=ensure_ascii)[1:-1]] = (
            json.dumps(str(target), ensure_ascii=ensure_ascii)[1:-1]
        )
    for scope in ("cwd", "user_home"):
        source_scope = _portable_scope_digest(
            scope, source / "sessions", source / "workspace"
        )
        target_scope = _portable_scope_digest(
            scope, target / "sessions", target / "workspace"
        )
        replacements[source_scope] = target_scope
        replacements[_portable_create_digest(source_scope)] = _portable_create_digest(
            target_scope
        )
    assert len(set(replacements.values())) == len(replacements)
    return replacements


def normalize_declared_inputs(value, *, case: str, input_root: Path):
    replacements = _portable_input_replacements(case, input_root)
    pattern = re.compile(
        "|".join(re.escape(key) for key in sorted(replacements, key=len, reverse=True))
    )

    def text(value: str) -> str:
        return pattern.sub(lambda match: replacements[match.group(0)], value)

    def visit(value):
        if isinstance(value, str):
            return text(value)
        if isinstance(value, list):
            return [visit(item) for item in value]
        if isinstance(value, dict):
            if set(value) == {"base64", "sha256", "length"}:
                body = base64.b64decode(value["base64"], validate=True)
                assert len(body) == value["length"]
                assert hashlib.sha256(body).hexdigest() == value["sha256"]
                # Preserve all bytes except encoded declared inputs/derived IDs.
                normalized = text(body.decode("utf-8")).encode("utf-8")
                return {
                    "base64": base64.b64encode(normalized).decode(),
                    "sha256": hashlib.sha256(normalized).hexdigest(),
                    "length": len(normalized),
                }
            return {key: visit(item) for key, item in value.items()}
        return value

    return visit(value)


_PORTABLE_EXPECTED = json.loads(
    (Path(__file__).parent / "fixtures/hosted_catalog_values_v1.json").read_text()
)


@pytest.mark.parametrize("case", CASES)
def test_original_hosted_catalog_values(case, tmp_path, monkeypatch):
    monkeypatch.setitem(globals(), "INPUTS", tmp_path)
    actual = observe(case)
    assert (
        normalize_declared_inputs(actual, case=case, input_root=tmp_path)
        == _PORTABLE_EXPECTED["observations"][case]
    )
