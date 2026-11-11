"""Explicit original canonical-catalog custody observations, without recapture.

Existing test programs remain the original scenario/assertion owners. Transcript
writers, native files, Store probes and actual task cancellation execute. The
fixture expected values come solely from frozen original-source observations;
this local probe adds no default route or production source-SHA gate.
"""

from __future__ import annotations

import asyncio
import dataclasses
import enum
import functools
import gzip
import hashlib
import importlib
import importlib.util
import inspect
import json
import os
import sys
import tempfile
import threading
from collections.abc import Mapping
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.coding import (
    test_hosted_catalog,
    test_hosted_discovery,
    test_hosted_owned_catalog,
    test_managed_catalog,
    test_managed_store_discovery,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Original Linux owned transcript and Store contract"
)


REUSED = {
    "unowned-create-resume": (
        "hosted_catalog",
        "test_G14_PRODUCT_canonical_transcript_create_and_fresh_owner_resume",
        {},
    ),
    "unowned-idempotent": (
        "hosted_catalog",
        "test_G14_RECOVERY_create_identity_is_idempotent_across_catalog_instances",
        {},
    ),
    "unowned-concurrent-create": (
        "hosted_catalog",
        "test_G14_PRODUCT_concurrent_same_key_creators_cannot_duplicate_sessions",
        {},
    ),
    "unowned-conflict": (
        "hosted_catalog",
        "test_G14_PRODUCT_scope_and_create_identity_conflicts_fail_closed",
        {},
    ),
    "unowned-legacy": (
        "hosted_catalog",
        "test_G14_PRODUCT_legacy_transcript_is_not_implicitly_adopted",
        {},
    ),
    "unowned-stale-claim": (
        "hosted_catalog",
        "test_G14_PRODUCT_candidate_revision_is_fenced_before_claim",
        {},
    ),
    "unowned-other-scope": (
        "hosted_catalog",
        "test_G14_PRODUCT_listing_another_scope_preserves_admitted_candidates",
        {},
    ),
    "unowned-bound-restore": (
        "hosted_catalog",
        "test_G14_PRODUCT_bound_restore_does_not_resolve_selected_leaf",
        {},
    ),
    "owned-create-busy-close": (
        "hosted_owned_catalog",
        "test_owned_catalog_real_create_busy_resume_and_close_preserves_delivered_candidate",
        {},
    ),
    "owned-manager-retained": (
        "hosted_owned_catalog",
        "test_owned_catalog_retains_raw_session_when_wrapper_and_cleanup_fail",
        {"stage": "manager"},
    ),
    "owned-candidate-retained": (
        "hosted_owned_catalog",
        "test_owned_catalog_retains_raw_session_when_wrapper_and_cleanup_fail",
        {"stage": "candidate"},
    ),
    "owned-fence-inflight": (
        "hosted_owned_catalog",
        "test_owned_catalog_close_fences_inflight_factory_before_waiting_lock",
        {},
    ),
    "owned-no-index": (
        "hosted_owned_catalog",
        "test_owned_catalog_does_not_publish_pathname_index_on_disposal",
        {},
    ),
    "owned-missing-root": (
        "hosted_owned_catalog",
        "test_owned_catalog_requires_prepared_safe_session_root",
        {},
    ),
    "discovery-scope-admission": (
        "hosted_discovery",
        "test_G17_PRODUCT_unknown_scope_rejected_before_directory_io",
        {},
    ),
    "discovery-cancel": (
        "hosted_discovery",
        "test_G17_PRODUCT_cancelled_waiter_waits_for_actual_read_worker",
        {},
    ),
    "discovery-all-task-cancel": (
        "hosted_discovery",
        "test_G17_PRODUCT_all_task_cancellation_retains_actual_worker_debt",
        {},
    ),
    "discovery-budget": (
        "hosted_discovery",
        "test_G17_PRODUCT_budget_exhaustion_cannot_offer_unverified_rows",
        {},
    ),
    "discovery-duplicate": (
        "hosted_discovery",
        "test_G17_PRODUCT_budget_external_duplicate_disables_partial_directory",
        {},
    ),
    "discovery-invalid-file-root": (
        "hosted_discovery",
        "test_G17_PRODUCT_invalid_roots_are_not_empty_success",
        {"case": "file"},
    ),
    "discovery-invalid-read-root": (
        "hosted_discovery",
        "test_G17_PRODUCT_invalid_roots_are_not_empty_success",
        {"case": "unreadable"},
    ),
    "managed-cross-workspace": (
        "managed_catalog",
        "test_cross_workspace_is_visible_only_globally_and_cannot_open",
        {},
    ),
    "managed-stale-header": (
        "managed_catalog",
        "test_changed_header_after_discovery_is_rejected_without_owned_admission",
        {},
    ),
    "managed-unsupported": (
        "managed_catalog",
        "test_unsupported_runtime_is_observed_but_not_bound",
        {},
    ),
    "managed-root-view-reject": (
        "managed_catalog",
        "test_old_catalog_still_rejects_same_root_views",
        {},
    ),
    "managed-commit-retry": (
        "managed_catalog",
        "test_committed_create_lost_receipt_recovers_same_canonical_file",
        {},
    ),
    "managed-restore-retained": (
        "managed_catalog",
        "test_post_restore_rejection_retains_original_session_on_cleanup_failure",
        {},
    ),
    "store-probe-retained": (
        "managed_store_discovery",
        "test_failed_probe_cleanup_is_retained_and_fences_additional_reads",
        {},
    ),
    "store-probe-cancel": (
        "managed_store_discovery",
        "test_cancelled_browse_and_close_keep_active_probe_until_real_worker_finishes",
        {},
    ),
    "store-submission-lost": (
        "managed_store_discovery",
        "test_lost_executor_submission_receipt_does_not_admit_untracked_discovery",
        {},
    ),
    "store-capacity": (
        "managed_store_discovery",
        "test_read_capacity_is_bounded_before_executor_submission",
        {},
    ),
}

OWN = (
    "unowned-wrapper-outside-try",
    "unowned-close-overrides",
    "unowned-lost-commit",
    "owned-lost-commit",
)

CASES = (*REUSED, *OWN)


class Recorder:
    def __init__(self, root):
        self.root = root
        self.trace = []
        self.lock = threading.RLock()
        self.objects = []
        self.object_ids = {}
        self.tokens = {}
        self.revisions = {}
        self.inodes = {}
        self.directory_generations = {}
        self.directory_results = {}
        self.catalogs = []
        self.sessions = []

    def token(self, value, role):
        if value not in self.tokens:
            self.tokens[value] = role
        return self.tokens[value]

    def string(self, value):
        for original, replacement in sorted(
            self.tokens.items(), key=lambda item: len(item[0]), reverse=True
        ):
            value = value.replace(original, replacement)
        return value.replace(str(self.root), "$TMP")

    def freeze(self, value, depth=0):
        if depth > 14:
            return {"depth-limit": type(value).__name__}
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, enum.Enum):
            return {"enum": type(value).__name__, "value": value.value}
        if isinstance(value, datetime):
            # Header creation is a fixed clock input. Other test message times
            # are retained raw and omitted from canonical runtime values only.
            return {"datetime": value.isoformat()}
        if isinstance(value, bytes):
            return {"bytes_hex": value.hex()}
        if isinstance(value, BaseException):
            return self.error(value)
        if hasattr(value, "_ownership_state") and hasattr(value, "_writer_owner"):
            identity = id(value)
            if identity not in self.object_ids:
                self.object_ids[identity] = len(self.object_ids) + 1
                self.objects.append(value)
            return {
                "session": self.object_ids[identity],
                "ownership": value.ownership_state,
                "session_file": str(value.context.session_file),
            }
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            fields = {
                field.name: self.freeze(getattr(value, field.name), depth + 1)
                for field in dataclasses.fields(value)
                if field.name not in {"_dispose_lock", "_writer_owner"}
            }
            return {"dataclass": type(value).__name__, "fields": fields}
        if isinstance(value, Mapping):
            return {
                str(key): self.freeze(item, depth + 1) for key, item in value.items()
            }
        if isinstance(value, (tuple, list)):
            return [self.freeze(item, depth + 1) for item in value]
        if isinstance(value, (set, frozenset)):
            return sorted(
                [self.freeze(item, depth + 1) for item in value],
                key=lambda item: json.dumps(item, sort_keys=True),
            )
        identity = id(value)
        if identity not in self.object_ids:
            self.object_ids[identity] = len(self.object_ids) + 1
            self.objects.append(value)
        return {"object": type(value).__name__, "role": self.object_ids[identity]}

    def error(self, error, seen=frozenset()):
        if id(error) in seen:
            return {"cycle": type(error).__name__}
        seen = seen | {id(error)}
        return {
            "type": type(error).__module__ + "." + type(error).__qualname__,
            "message": str(error),
            "code": getattr(error, "code", None),
            "errno": getattr(error, "errno", None),
            "filename": getattr(error, "filename", None),
            "notes": list(getattr(error, "__notes__", ())),
            "suppress_context": error.__suppress_context__,
            "cause": self.error(error.__cause__, seen) if error.__cause__ else None,
            "context": self.error(error.__context__, seen)
            if error.__context__
            else None,
        }

    def event(self, label, **values):
        with self.lock:
            self.trace.append(
                {
                    "event": label,
                    **{name: self.freeze(value) for name, value in values.items()},
                }
            )

    def state(self):
        return {
            "catalogs": [
                {
                    "role": self.freeze(owner),
                    "closing": owner._closing,
                    "pending": len(owner._pending_sessions),
                    "records": len(owner._records),
                    "factory_pending": len(owner._owned_factory.pending_preparations)
                    if owner._owned_factory
                    else None,
                    "factory_closing": owner._owned_factory._closing
                    if owner._owned_factory
                    else None,
                    "store_probes": len(getattr(owner, "_store_probes", {})),
                    "active_reads": getattr(owner, "_store_active_reads", None),
                }
                for owner in self.catalogs
            ],
            "sessions": [
                {
                    "role": self.freeze(session),
                    "ownership": session.ownership_state,
                    "writer_closing": session._writer_owner.closing
                    if session._writer_owner
                    else None,
                    "writer_pending": session._writer_owner.cleanup_pending
                    if session._writer_owner
                    else None,
                }
                for session in self.sessions
            ],
        }


def instrumentation(recorder, stack):
    hosted = importlib.import_module("loushang.coding.hosted_catalog")
    managed = importlib.import_module("loushang.coding.managed_catalog")
    factory_module = importlib.import_module(
        "loushang.harness.transcript.session_factory"
    )
    lifecycle = importlib.import_module("loushang.harness.transcript.lifecycle")
    writer = importlib.import_module("loushang.harness.transcript.writer_lifecycle")
    admission = importlib.import_module("loushang.harness.transcript.store_admission")
    relocated_header = (
        importlib.import_module("loushang.harness.transcript._canonical_header")
        if importlib.util.find_spec("loushang.harness.transcript._canonical_header")
        is not None
        else None
    )
    read_dispatch = threading.local()

    def wrap(owner, name, label, after=None):
        original = getattr(owner, name)
        if inspect.iscoroutinefunction(original):

            @functools.wraps(original)
            async def asynchronous(self, *args, **kwargs):
                recorder.event(label + ".enter", owner=self, args=args, kwargs=kwargs)
                try:
                    result = await original(self, *args, **kwargs)
                except BaseException as error:
                    recorder.event(label + ".error", error=error)
                    raise
                if after:
                    after(self, result, args, kwargs)
                recorder.event(label + ".return", result=result)
                return result

            replacement = asynchronous
        else:

            @functools.wraps(original)
            def synchronous(self, *args, **kwargs):
                # Managed's old independent override and the new shared method
                # are the same logical read. Do not record an extra inherited
                # Hosted dispatch layer introduced by observer wrappers.
                if label == "catalog._read_record" and getattr(
                    read_dispatch, "managed", False
                ):
                    return original(self, *args, **kwargs)
                prior = getattr(read_dispatch, "managed", False)
                if label == "managed._read_record":
                    read_dispatch.managed = True
                recorder.event(label + ".enter", owner=self, args=args, kwargs=kwargs)
                try:
                    result = original(self, *args, **kwargs)
                except BaseException as error:
                    recorder.event(label + ".error", error=error)
                    raise
                finally:
                    if label == "managed._read_record":
                        read_dispatch.managed = prior
                if after:
                    after(self, result, args, kwargs)
                recorder.event(label + ".return", result=result)
                return result

            replacement = synchronous
        stack.enter_context(patch.object(owner, name, replacement))

    def catalog_created(owner, result, args, kwargs):
        recorder.catalogs.append(owner)

    def session_returned(owner, result, args, kwargs):
        if isinstance(result, lifecycle.AgentTranscriptLifecycleSession) and all(
            result is not old for old in recorder.sessions
        ):
            recorder.sessions.append(result)

    def directory_returned(owner, result, args, kwargs):
        if result is None:
            return
        pair = tuple(result[:2])
        if pair not in recorder.inodes:
            recorder.inodes[pair] = "ROOT:" + str(len(recorder.inodes) + 1)
        key = recorder.string(str(args[0]))
        generations = recorder.directory_generations.setdefault(key, [])
        if result[2] not in generations:
            generations.append(result[2])
        recorder.directory_results[tuple(result)] = {
            "identity": recorder.inodes[pair],
            "generation": generations.index(result[2]) + 1,
        }

    wrap(
        hosted.CodingHostedSessionCatalogV1, "__init__", "catalog.init", catalog_created
    )
    for name in (
        "create_candidate",
        "find_created_candidate",
        "_find",
        "open_candidate",
        "_open",
        "_candidate_from_owned",
        "list_identities",
        "discover_sessions",
        "_read_discovery",
        "_read_record",
        "fence",
        "close",
        "_discard_session",
    ):
        wrap(hosted.CodingHostedSessionCatalogV1, name, "catalog." + name)
    wrap(
        hosted.CodingHostedSessionCatalogV1,
        "_directory_revision",
        "catalog._directory_revision",
        directory_returned,
    )
    for name in (
        "_directory_revision",
        "_read_record",
        "_finish_store_probe",
        "_close_store_probes",
        "fence",
        "close",
    ):
        wrap(
            managed.CodingManagedSessionCatalogV1,
            name,
            "managed." + name,
            directory_returned if name == "_directory_revision" else None,
        )
    for name in ("new", "restore_context", "close", "fence"):
        wrap(
            factory_module.AgentTranscriptSessionFactory,
            name,
            "factory." + name,
            session_returned,
        )
    for name in ("create", "restore", "dispose", "_fence_unpublished"):
        wrap(writer.TranscriptWriterPreparation, name, "preparation." + name)
    wrap(lifecycle.AgentTranscriptLifecycleSession, "dispose", "session.dispose")
    for name in ("inspect", "check", "close"):
        wrap(admission.TranscriptStoreAdmission, name, "store." + name)
    for name in ("verify_current", "claim", "close"):
        wrap(hosted._Candidate, name, "candidate." + name)
    wrap(hosted.CodingHostedCandidateBindingV1, "close", "binding.close")

    # Fixed input clock, without adding a new preparation or changing owners.
    header = factory_module.AgentTranscriptSessionFactory._new_header

    def new_header(owner, *args, **kwargs):
        clock = owner._clock
        owner._clock = lambda: datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        try:
            return header(owner, *args, **kwargs)
        finally:
            owner._clock = clock

    stack.enter_context(
        patch.object(
            factory_module.AgentTranscriptSessionFactory, "_new_header", new_header
        )
    )
    resolve_id = factory_module.AgentTranscriptSessionFactory._resolve_conversation_id
    generated_ids = 0

    def resolve_conversation_id(owner, conversation_id):
        nonlocal generated_ids
        if conversation_id is not None:
            return resolve_id(owner, conversation_id)
        generated_ids += 1
        factory = owner._conversation_id_factory
        owner._conversation_id_factory = lambda: "ordinary-" + str(generated_ids)
        try:
            return resolve_id(owner, conversation_id)
        finally:
            owner._conversation_id_factory = factory

    stack.enter_context(
        patch.object(
            factory_module.AgentTranscriptSessionFactory,
            "_resolve_conversation_id",
            resolve_conversation_id,
        )
    )

    for module in (hosted, managed):
        original_scope = module._scope_fingerprint

        def scope_identity(scope, root, cwd, original=original_scope):
            value = original(scope, root, cwd)
            role = (
                "SCOPE:"
                + scope.value
                + ":"
                + recorder.string(str(root))
                + ":"
                + (recorder.string(cwd) if scope.value == "cwd" else "")
            )
            recorder.token(value, role)
            return value

        stack.enter_context(patch.object(module, "_scope_fingerprint", scope_identity))
    revision_owners = (
        ((relocated_header, "canonical_transcript_revision"),)
        if relocated_header is not None
        else ((hosted, "_revision"), (managed, "_revision"))
    )
    for module, name in revision_owners:
        original_revision = getattr(module, name)

        def revision(path, *args, original=original_revision, **kwargs):
            value = original(path, *args, **kwargs)
            normalized = recorder.string(str(path))
            variants = recorder.revisions.setdefault(normalized, [])
            if value not in variants:
                variants.append(value)
            recorder.token(
                value, "REV:" + normalized + ":" + str(variants.index(value) + 1)
            )
            recorder.event("source.revision", path=path, result=value)
            return value

        stack.enter_context(patch.object(module, name, revision))
    original_create = hosted._create_identity

    def create_identity(request):
        value = original_create(request)
        recorder.token(
            value,
            "CREATE:"
            + recorder.string(request.creator_scope_id)
            + ":"
            + request.operation_id,
        )
        return value

    stack.enter_context(patch.object(hosted, "_create_identity", create_identity))
    return hosted, managed


def own_scenario(case, root, monkeypatch, tests, recorder):
    hosted = importlib.import_module("loushang.coding.hosted_catalog")
    file_module = importlib.import_module("loushang.harness.conversation.stores.file")

    async def scenario():
        scope = tests["hosted_catalog"]._scope(root)
        owned = case == "owned-lost-commit"
        if owned:
            scope.session_dir.mkdir(mode=0o700)
        owner = hosted.CodingHostedSessionCatalogV1((scope,), owned_transcripts=owned)
        intent = tests["hosted_catalog"]._intent(scope)
        if case.endswith("lost-commit"):
            original = file_module._write_unlocked

            def fail_after_commit(*args, **kwargs):
                original(*args, **kwargs)
                raise OSError("observer write receipt lost")

            with monkeypatch.context() as control:
                control.setattr(file_module, "_write_unlocked", fail_after_commit)
                try:
                    candidate = await owner.create_candidate(intent)
                except BaseException as error:
                    recorder.event("action.create.error", error=error)
                else:
                    recorder.event(
                        "action.create.recovered", projection=candidate.projection
                    )
                    await candidate.close()
            await owner.close()
            fresh = hosted.CodingHostedSessionCatalogV1(
                (scope,), owned_transcripts=owned
            )
            candidate = await fresh.find_created_candidate(intent.request)
            assert candidate is not None
            recorder.event("action.reopen", projection=candidate.projection)
            await candidate.close()
            await fresh.close()
            return
        initial = await owner.create_candidate(intent)
        await initial.close()
        rows = await owner.list_identities((scope.discovery_scope,), limit=256)
        restore = hosted._HOSTED_FACTORY.restore_context
        retained = []

        async def restore_capture(*args, **kwargs):
            session = await restore(*args, **kwargs)
            retained.append(session)
            return session

        def broken_wrapper(*args, **kwargs):
            raise ValueError("observer wrapper failed")

        binder = hosted.CODING_TRANSCRIPT_RUNTIME._binder

        async def bad_dispose(binding):
            raise OSError("observer inner close failed")

        with monkeypatch.context() as control:
            control.setattr(hosted._HOSTED_FACTORY, "restore_context", restore_capture)
            if case == "unowned-wrapper-outside-try":
                control.setattr(owner._legacy_transcript_type, "__init__", broken_wrapper)
            else:
                control.setattr(hosted, "_Candidate", broken_wrapper)
            if case == "unowned-close-overrides":
                control.setattr(binder, "dispose", bad_dispose)
            try:
                await owner.open_candidate(rows[0].reference)
            except BaseException as error:
                recorder.event("action.open.error", error=error)
            else:
                raise AssertionError("fault was not reached")
            assert len(retained) == 1
            assert retained[0].ownership_state == "root_owned"
            assert not owner.pending_sessions
            recorder.event(
                "action.raw_session_unretained",
                ownership=retained[0].ownership_state,
                pending=owner.pending_sessions,
            )
        recorder.event("observer.cleanup")
        await retained[0].dispose()
        await owner.close()

    asyncio.run(scenario())


def observe(case, root, monkeypatch, tests):
    recorder = Recorder(root)
    unexpected = None
    with ExitStack() as stack:
        instrumentation(recorder, stack)
        try:
            if case in REUSED:
                module, name, parameters = REUSED[case]
                function = getattr(tests[module], name)
                kwargs = dict(parameters)
                signature = inspect.signature(function)
                if "scope_kind" in signature.parameters and "scope_kind" not in kwargs:
                    kwargs["scope_kind"] = tests["hosted_catalog"].SessionScopeV1.CWD
                if "tmp_path" in signature.parameters:
                    kwargs["tmp_path"] = root
                if "monkeypatch" in signature.parameters:
                    kwargs["monkeypatch"] = monkeypatch
                function(**kwargs)
                monkeypatch.undo()
                recorder.event("original_asserted_program.return")
            else:
                own_scenario(case, root, monkeypatch, tests, recorder)
        except BaseException as error:
            recorder.event("observer.unexpected_error", error=error)
            unexpected = recorder.error(error)
        finally:
            recorder.event("final.resources", state=recorder.state())
    # Raw strings are kept; canonicalization is limited to observed exact role
    # tokens and the known per-case input root. No general hash rewriting.
    raw = {
        "trace": recorder.trace,
        "resource_state": recorder.state(),
        "token_map": recorder.tokens,
        "unexpected_error": unexpected,
    }
    canonical = json.loads(json.dumps(raw, default=str))
    canonical.pop("token_map")

    def native_identity(value):
        identity = tuple(value)
        if identity not in recorder.inodes:
            recorder.inodes[identity] = "ROOT:" + str(len(recorder.inodes) + 1)
        return recorder.inodes[identity]

    def normalize(value):
        if isinstance(value, str):
            return recorder.string(value)
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            result = {key: normalize(item) for key, item in value.items()}
            if (
                value.get("event", "").endswith("._directory_revision.return")
                and value.get("result") is not None
            ):
                result["result"] = recorder.directory_results[tuple(value["result"])]
            if value.get("dataclass") == "TranscriptStoreBinding":
                for name in ("root_identity", "parent_identity"):
                    result["fields"][name] = native_identity(value["fields"][name])
                if value["fields"]["shared_identities"] is not None:
                    result["fields"]["shared_identities"] = [
                        native_identity(item)
                        for item in value["fields"]["shared_identities"]
                    ]
                for name in ("family_id", "member_id"):
                    item = value["fields"][name]
                    if item is not None:
                        recorder.token(
                            item,
                            name.upper()
                            + ":"
                            + native_identity(value["fields"]["root_identity"]),
                        )
                        result["fields"][name] = recorder.string(item)
            return result
        return value

    return raw, normalize_role_details(raw, normalize(canonical))


def normalize_role_details(raw, canonical):
    """Normalize only identities satisfying the frozen original wire formulas.

    These are independent original formulas, not calls to the target decoder or
    scope/create methods. Raw values and their complete original trace survive.
    """
    replacements = {}

    def gather(value):
        if isinstance(value, list):
            for item in value:
                gather(item)
        elif isinstance(value, dict):
            if value.get("dataclass") == "_Record":
                fields = value["fields"]
                identity = fields["identity"]["fields"]
                metadata = fields["header"]["fields"]["metadata"]
                if "coding.hosted" not in metadata:
                    root = fields["scope"]["fields"]["session_dir"]
                    sid = identity["session_id"]
                    expected = hashlib.sha256(
                        "\0".join(
                            ("coding.managed.continuity/v1", "coding", root, sid)
                        ).encode("utf-8")
                    ).hexdigest()
                    if identity["continuity_id"] == expected:
                        replacements[expected] = "MANAGED-CONTINUITY:" + sid
            for item in value.values():
                gather(item)

    gather(raw)

    def replace(value):
        if isinstance(value, str):
            for original, role in replacements.items():
                value = value.replace(original, role)
            return value
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        return value

    result = replace(canonical)

    def titles(original, normalized):
        if isinstance(original, list) and isinstance(normalized, list):
            return [titles(x, y) for x, y in zip(original, normalized)]
        if isinstance(original, dict) and isinstance(normalized, dict):
            output = {
                key: titles(original[key], item) if key in original else item
                for key, item in normalized.items()
            }
            if original.get("dataclass") == "SessionDiscoveryCandidateV1":
                fields = original["fields"]
                sid = fields["identity"]["fields"]["session_id"]
                if fields["title"] == "Session " + sid[:12]:
                    output["fields"]["title"] = {
                        "exact_session_title": output["fields"]["identity"]["fields"][
                            "session_id"
                        ],
                        "prefix": "Session ",
                        "id_prefix_length": 12,
                    }
            return output
        return normalized

    return titles(raw, result)


def frozen_budget_inputs(root):
    """Original CWD scope/create/filename formulas, independent of target code."""
    root = Path(root)
    scope = hashlib.sha256(
        "\0".join(
            (
                "coding.hosted.scope/v1",
                "cwd",
                os.path.normcase(str(root / "cwd")),
                os.path.normcase(str(root)),
            )
        ).encode()
    ).hexdigest()
    files = {}
    for number in range(2):
        operation = f"operation-{number:024d}"
        identity = hashlib.sha256(
            "\0".join(("coding.hosted.create/v1", "coding", scope, operation)).encode()
        ).hexdigest()
        files["hosted-" + identity + ".jsonl"] = operation
    filename = min(files)
    return {
        "scope_fingerprint": scope,
        "filenames": files,
        "first_filename": filename,
        "first_operation": files[filename],
    }


def assert_budget_variant(raw, root):
    expected = frozen_budget_inputs(root)
    entered = False
    paths = []
    for row in raw["trace"]:
        if row["event"] == "catalog.discover_sessions.enter":
            assert (
                row["args"][0]["fields"]["scope_fingerprint"]
                == expected["scope_fingerprint"]
            )
        if row["event"] == "catalog._read_discovery.enter":
            entered = True
        if entered and row["event"] == "catalog._read_record.enter":
            paths.append(row["args"][1])
    assert len(paths) == 1, paths
    assert Path(paths[0]).name == expected["first_filename"], (paths, expected)
    return expected["first_operation"]


def assert_equal_concurrent_inputs(raw):
    """Only this original test has two indistinguishable creator inputs."""
    for label in (
        "catalog.init.enter",
        "catalog.create_candidate.enter",
        "factory.new.enter",
    ):
        rows = [row for row in raw["trace"] if row["event"] == label]
        assert len(rows) == 2, (label, len(rows))
        assert rows[0]["args"] == rows[1]["args"], label
        assert rows[0]["kwargs"] == rows[1]["kwargs"], label


_FIXTURE = Path(__file__).parent / "fixtures/hosted_catalog_custody_v1.json.gz"
_EXPECTED = json.loads(gzip.decompress(_FIXTURE.read_bytes()))
_EXISTING = {
    "hosted_catalog": test_hosted_catalog,
    "hosted_owned_catalog": test_hosted_owned_catalog,
    "hosted_discovery": test_hosted_discovery,
    "managed_catalog": test_managed_catalog,
    "managed_store_discovery": test_managed_store_discovery,
}


@pytest.fixture
def catalog_private_input():
    with tempfile.TemporaryDirectory(prefix="loushang-a80-") as directory:
        yield Path(directory)


@pytest.mark.parametrize("case", CASES)
def test_original_canonical_catalog_custody(case, catalog_private_input, monkeypatch):
    entry = _EXPECTED["cases"][case]
    selector = (
        frozen_budget_inputs(catalog_private_input)["first_operation"]
        if case == "discovery-budget"
        else "default"
    )
    choices = (
        list(entry["variants"].values())
        if entry.get("same_input_scheduler_variants")
        else [entry["variants"][selector]]
    )
    monkeypatch.setenv("LOUSHANG_HOME", str(catalog_private_input / "platform"))
    raw, actual = observe(case, catalog_private_input, monkeypatch, _EXISTING)
    assert raw["unexpected_error"] is None
    if case == "discovery-budget":
        assert assert_budget_variant(raw, catalog_private_input) == selector
    if entry.get("same_input_scheduler_variants"):
        assert_equal_concurrent_inputs(raw)
    assert any(actual == variant["value"] for variant in choices)
