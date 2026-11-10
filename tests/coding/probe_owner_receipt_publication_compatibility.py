"""Frozen publication traces: actual receipt/generation methods and controlled ports."""

from __future__ import annotations

import asyncio
import gzip
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from loushang.coding._base_plugin import CodingBasePluginAssembly
from loushang.coding._capability_plugin_composition import (
    CodingCapabilityPluginCompositionAssembly,
)
from loushang.coding.session.agent_session import AgentSession
from loushang.harness.capabilities import StagedResourceCompositionCandidate
from loushang.harness.runtime.registration import (
    OwnerGenerationRetirementReceipt as Receipt,
)
from loushang.harness.session.agent_product import AgentProductSession
from loushang.harness.session.capability_composition_inputs import (
    StagedSessionCapabilityOwnerGeneration as Generation,
)
from loushang.harness.session.capability_composition_inputs import (
    commit_session_capability_owner_generations,
)

HERE = Path(__file__).parent
FLOW_CASES = [
    {"name": "both"},
    {"name": "base_only", "cap": False},
    {"name": "cap_only", "base": False},
    {"name": "no_assemblies", "base": False, "cap": False},
    {"name": "cap_present_empty", "cap_ids": []},
    {"name": "base_present_no_lease", "base_lease": False},
    *[
        {"name": name, "fail": [failure]}
        for name, failure in [
            ("cap_first_prepare", "cap-a.prepare"),
            ("cap_second_prepare", "cap-b.prepare"),
            ("base_prepare", "base.prepare"),
            ("cap_publish", "cap-a.publish"),
            ("base_publish", "base.publish"),
            ("base_retire", "base.retire"),
            ("cap_retire", "cap-b.retire"),
            ("graph_close", "graph.close"),
            ("cap_runtime_close", "cap-runtime.close"),
            ("cap_capture", "cap-a.receipt"),
            ("base_capture", "base.receipt"),
            ("resource_capture", "resource.receipt"),
            ("generation_dispose", "cap-a.dispose"),
            ("cap_management_close", "cap-a.close"),
            ("private_cleanup", "cap-private.cleanup"),
        ]
    ],
    {"name": "both_publish", "fail": ["cap-a.publish", "base.publish"]},
    {"name": "cap_publish_cancel", "fail": ["cap-a.publish"], "error": "cancel"},
    {"name": "base_capture_interrupt", "fail": ["base.receipt"], "error": "interrupt"},
    {"name": "cap_mapping_empty_tuple", "empty_cap": True},
    {"name": "repeat_stage_after_commit", "repeat_stage": True},
]
EDGE_NAMES = [
    "resource_only",
    "missing_candidate",
    "no_prepared_resource",
    "invalid_resource_receipt",
    "invalid_generation_receipt",
    "sort_ties_and_duplicates",
    "resource_ids_sorted_unique",
    "base_none_after_binding",
    "base_no_lease_after_binding",
    "base_empty_contributions",
    "base_none_during_capture",
    "base_capture_fails_before_absent_assembly",
    "cap_none_after_binding",
    "cap_map_replaced",
    "cap_map_empty_replacement",
    "target_map_cleared",
    "cap_mapping_reordered",
    "base_uncommitted_live",
    "base_disposed_prepared",
    "cap_uncommitted_live",
    "cap_disposed_prepared",
    "pending_error_before_facts",
    "empty_targets_before_error",
    "second_commit_overwrites",
    "success_keeps_pending_error",
    "capture_failure_preserves_receipts",
    "retire_unpublished",
    "retire_retry",
    "live_require_candidate_missing",
    "live_cap_does_not_read_candidate",
]
CASES = FLOW_CASES + [{"name": name, "edge": True} for name in EDGE_NAMES]


def encoded(item):
    if isinstance(item, Receipt):
        return {
            "type": f"{type(item).__module__}.{type(item).__qualname__}",
            "fields": item.to_dict(),
        }
    if isinstance(item, BaseException):
        return error_data(item)
    if isinstance(item, dict):
        return {key: encoded(value) for key, value in item.items()}
    if isinstance(item, (tuple, list)):
        return [encoded(value) for value in item]
    return item


def error_data(error, seen=None):
    if error is None:
        return None
    seen = set() if seen is None else seen
    if id(error) in seen:
        return {"cycle": type(error).__name__}
    seen.add(id(error))
    return {
        "type": f"{type(error).__module__}.{type(error).__qualname__}",
        "message": str(error),
        "notes": list(getattr(error, "__notes__", ())),
        "suppress_context": error.__suppress_context__,
        "cause": error_data(error.__cause__, seen),
        "context": error_data(error.__context__, seen),
    }


def receipt(name, *, ids=None):
    return Receipt(
        owner_reference=f"owner:{name}",
        owner_generation_reference=f"generation:{name}",
        retirement_handle=f"handle:{name}",
        contribution_ids=ids or (f"tool:{name}",),
    )


class Scenario:
    def __init__(self, case, monkeypatch):
        self.case, self.trace, self.counts, self.errors = case, [], {}, {}
        self.generation_receipts = {}
        self.read_fail = set()
        self.mutate_on_receipt = None
        self.resource_invalid = False
        self.resource_missing = False
        self.generation_invalid = False
        self.session = self._session()
        self.base = self._base() if case.get("base", True) else None
        self.cap = self._cap() if case.get("cap", True) else None
        self.original_map = {} if self.cap is None else self.cap.management_leases
        self.session._coding_base_plugin_assembly = self.base
        self.session._coding_capability_plugin_assembly = self.cap
        self.resource = self._resource()
        self.session._staged_resource_candidate = self.resource
        self.session._mounted_resource_candidate = self.resource
        names = [("base", "coding.base"), ("cap-b", "cap-b"), ("cap-a", "cap-a")]
        if case.get("empty_cap"):
            names = names[:1]
        self.generations = tuple(
            self._generation(name, plugin) for name, plugin in names
        )
        self.session._capability_owner_generations = self.generations
        self.session._owner_publication_hooks = (
            self.session._create_coding_owner_publication_bindings()
        )
        self.trace.append(["bound"])
        confirm = CodingCapabilityPluginCompositionAssembly.confirm_runtime_retirement

        def confirmed(assembly, **kw):
            self.event("cap.confirm_retirement", kw)
            return confirm(assembly, **kw)

        monkeypatch.setattr(
            CodingCapabilityPluginCompositionAssembly,
            "confirm_runtime_retirement",
            confirmed,
        )

        async def graph_close(session):
            self.event("graph.close")
            for generation in self.generations:
                await generation.dispose_once()
            session._capability_owner_generations = ()
            session._capability_graph_runtime.is_closed = True

        monkeypatch.setattr(
            AgentProductSession, "_dispose_session_runtime_profile", graph_close
        )

    def event(self, name, data=None):
        count = self.counts[name] = self.counts.get(name, 0) + 1
        self.trace.append(["call", name, encoded(data)])
        requested = self.case.get("fail", ())
        profile = self.case.get("fail_counts", {})
        if (name in requested and count == 1) or count in profile.get(name, ()):
            cls = {
                "cancel": asyncio.CancelledError,
                "interrupt": KeyboardInterrupt,
            }.get(self.case.get("error"), OSError)
            error = cls(f"injected:{name}:{count}")
            self.errors[name, count] = error
            raise error

    def _session(self):
        observer = self

        class ObservedSession(AgentSession):
            def __getattribute__(session, name):
                if name in {
                    "_coding_base_plugin_assembly",
                    "_coding_capability_plugin_assembly",
                    "_capability_owner_generations",
                    "_mounted_resource_candidate",
                }:
                    observer.trace.append(["read", name])
                    if name in observer.read_fail:
                        raise LookupError(f"forbidden fact read:{name}")
                return super().__getattribute__(name)

        session = object.__new__(ObservedSession)
        session._deferred_lsp_slot = None
        session._coding_worker_turn_tool_lease = None
        session._sandbox_runtime = None
        session._capability_graph_runtime = NS(
            is_closed=False, has_pending_retirements=False
        )
        session._pending_capability_components = ()
        return session

    def _leaf(self, name):
        observer = self

        class Leaf:
            def __init__(self):
                self.prepared, self.retired = False, False
                self.contributions = (
                    (
                        ("resources.core", ("resource:z", "resource:a")),
                        ("tools.core", ("tool:ignored",)),
                    )
                    if name == "base"
                    else ()
                )

            @property
            def owner_contributions(self):
                observer.event(name + ".contributions", self.contributions)
                return self.contributions

            def prepare_owner_generations(self, receipts):
                observer.event(name + ".prepare", receipts)
                if not receipts:
                    raise ValueError("controlled_leaf_rejects_empty_receipts")
                self.prepared = True

            def publish_owner_generations(self, receipts):
                observer.event(name + ".publish", receipts)
                if not self.prepared:
                    raise ValueError("controlled_leaf_requires_prepared")

            def retire_owner_generations(self, receipts):
                observer.event(name + ".retire", receipts)
                if not self.prepared:
                    raise ValueError("controlled_leaf_requires_prepared")
                self.retired = True

            def close(self):
                observer.event(name + ".close")
                if self.prepared and not self.retired:
                    raise RuntimeError("controlled_leaf_cleanup_pending")

        return Leaf()

    def _base(self):
        base = object.__new__(CodingBasePluginAssembly)
        base.runtime = NS(close=lambda: self.event("base-runtime.close"))
        base.management_lease = (
            self._leaf("base") if self.case.get("base_lease", True) else None
        )
        base.state_cleanup = lambda: self.event("base-state.cleanup")
        for flag in (
            "_runtime_closed",
            "_management_released",
            "_state_cleaned",
            "_closed",
        ):
            setattr(base, flag, False)
        return base

    def _cap(self):
        cap = object.__new__(CodingCapabilityPluginCompositionAssembly)
        cap.runtime = NS(close=lambda: self.event("cap-runtime.close"))
        cap.management_leases = {
            key: self._leaf(key) for key in self.case.get("cap_ids", ["cap-a", "cap-b"])
        }
        cap.state_cleanup = lambda: self.event("cap-state.cleanup")
        cap.management_state_cleanup = lambda: self.event("cap-management.cleanup")
        cap.private_state_cleanup = lambda: self.event("cap-private.cleanup")
        for flag in (
            "_runtime_closed",
            "_management_released",
            "_state_cleaned",
            "_private_state_cleaned",
            "_runtime_retired",
            "_closed",
        ):
            setattr(cap, flag, False)
        return cap

    def _generation(self, name, plugin):
        observer = self
        self.generation_receipts.setdefault(name, receipt(name))

        class Binding:
            @property
            def plugin_id(self):
                observer.event(name + ".plugin_id", plugin)
                return plugin

            authority_gate = NS(
                validate=lambda admission: observer.event(name + ".validate")
            )

            def retirement_receipt(self, value):
                observer.event(name + ".receipt", value)
                if observer.mutate_on_receipt is not None and name == "base":
                    operation, observer.mutate_on_receipt = (
                        observer.mutate_on_receipt,
                        None,
                    )
                    operation()
                return (
                    None
                    if observer.generation_invalid
                    else observer.generation_receipts[name]
                )

            def commit(self, value):
                observer.event(name + ".commit", value)

            def rollback_commit(self, value):
                observer.event(name + ".rollback", value)

            async def dispose(self, value):
                observer.event(name + ".dispose", value)
                await asyncio.sleep(0)

        return Generation(Binding(), NS(), name)

    def _resource(self):
        observer = self

        class ResourceOwner:
            def retirement_receipt(self, *, contribution_ids):
                observer.event("resource.receipt", contribution_ids)
                return (
                    None
                    if observer.resource_invalid
                    else receipt("resources", ids=contribution_ids)
                )

        candidate = object.__new__(StagedResourceCompositionCandidate)
        candidate._StagedResourceCompositionCandidate__candidate = NS(
            owner_generation=ResourceOwner()
        )
        return candidate

    def publication(self, kind):
        return object.__getattribute__(
            self.session, f"_coding_{kind}_owner_publication"
        )

    def state(self, label):
        publications = {}
        for name in ("base", "capability"):
            pub = self.publication(name)
            publications[name] = (
                None
                if pub is None
                else {
                    "receipts": encoded(pub.receipts),
                    "prepared": pub.prepared,
                    "published": pub.published,
                    "retired": pub.retired,
                    "error": error_data(pub.publication_error),
                }
            )
        self.trace.append(
            [
                "state",
                label,
                publications,
                [
                    [
                        generation.value,
                        generation.commit_started,
                        generation.committed,
                        generation.disposed,
                    ]
                    for generation in self.generations
                ],
            ]
        )

    def attempt(self, label, operation):
        try:
            result = operation()
        except BaseException as error:
            self.trace.append(
                [
                    "error",
                    label,
                    error_data(error),
                    [
                        f"{name}:{count}"
                        for (name, count), stored in self.errors.items()
                        if stored is error
                    ],
                ]
            )
            self.state(label + "-failed")
            return False
        self.trace.append(["return", label, encoded(result)])
        self.state(label + "-done")
        return True

    def stage(self):
        return self.session._prepare_session_owner_generation_evidence(self.generations)

    def commit(self):
        self.event("graph.publish")
        commit_session_capability_owner_generations(self.generations)
        return self.session._commit_session_owner_generation_evidence()

    def require(self, kind):
        return getattr(
            self.session, f"_publish_coding_{kind}_owner_retirement_receipts"
        )()

    def flow(self):
        committed = False
        for index in range(4):
            if not committed:
                if not self.attempt(f"prepare-{index}", self.stage):
                    continue
                if not self.attempt("commit", self.commit):
                    continue
                committed = True
                if self.case.get("repeat_stage"):
                    self.attempt("repeat-stage", self.stage)
                    self.attempt("repeat-commit", self.commit)
            if not self.attempt(
                f"cap-require-{index}", lambda: self.require("capability")
            ):
                continue
            if self.attempt(f"base-require-{index}", lambda: self.require("base")):
                break
        for index in range(3):
            if self.attempt(
                f"dispose-{index}",
                lambda: asyncio.run(self.session._dispose_session_runtime_profile()),
            ):
                break
        if self.case["name"] == "both":
            assert all(
                self.publication(kind).retired for kind in ("base", "capability")
            )
            assert (
                self.base._closed
                and self.cap._management_released
                and self.cap._private_state_cleaned
            )

    def edge(self):
        name, basepub, cappub = (
            self.case["name"],
            self.publication("base"),
            self.publication("capability"),
        )
        if name == "resource_only":
            self.generations = self.generations[1:]
        elif name == "missing_candidate":
            self.session._staged_resource_candidate = None
        elif name == "no_prepared_resource":
            self.resource._StagedResourceCompositionCandidate__candidate.owner_generation = None
        elif name == "invalid_resource_receipt":
            self.resource_invalid = True
        elif name == "invalid_generation_receipt":
            self.generation_invalid = True
        elif name == "sort_ties_and_duplicates":
            first = self._generation("base-tie", "coding.base")
            self.generation_receipts["base-tie"] = receipt("base", ids=("tie:second",))
            self.generations = (
                self.generations[0],
                first,
                self.generations[0],
                *self.generations[1:],
            )
        elif name == "resource_ids_sorted_unique":
            self.base.management_lease.contributions = (
                ("resources.x", ("r:z", "r:a", "r:a")),
                ("resources.y", ("r:b", "r:a")),
                ("resources", ("ignored",)),
                ("other", ("ignored:2",)),
            )
        elif name in (
            "base_none_after_binding",
            "base_capture_fails_before_absent_assembly",
        ):
            self.session._coding_base_plugin_assembly = None
            if name.endswith("absent_assembly"):
                self.case["fail"] = ["base.receipt"]
        elif name == "base_no_lease_after_binding":
            self.base.management_lease = None
        elif name == "base_empty_contributions":
            self.base.management_lease.contributions = ()
        elif name == "base_none_during_capture":
            self.mutate_on_receipt = lambda: setattr(
                self.session, "_coding_base_plugin_assembly", None
            )
        elif name == "cap_none_after_binding":
            self.session._coding_capability_plugin_assembly = None
        elif name == "cap_map_replaced":
            self.cap.management_leases = {
                "cap-b": self._leaf("replacement-b"),
                "cap-c": self._leaf("replacement-c"),
            }
        elif name == "cap_map_empty_replacement":
            self.cap.management_leases = {}
        elif name == "target_map_cleared":
            self.original_map.clear()
        elif name == "cap_mapping_reordered":
            self.cap.management_leases = dict(
                reversed(tuple(self.original_map.items()))
            )
        elif name in (
            "base_uncommitted_live",
            "cap_uncommitted_live",
            "live_require_candidate_missing",
            "live_cap_does_not_read_candidate",
        ):
            if name == "live_require_candidate_missing":
                self.session._mounted_resource_candidate = None
                commit_session_capability_owner_generations(self.generations)
            if name == "live_cap_does_not_read_candidate":
                self.read_fail.add("_mounted_resource_candidate")
                commit_session_capability_owner_generations(self.generations)
            self.attempt(
                "live-require",
                lambda: self.require(
                    "capability" if name.startswith(("cap_", "live_cap")) else "base"
                ),
            )
            return
        elif name in ("base_disposed_prepared", "cap_disposed_prepared"):
            generation = self.generations[0 if name.startswith("base") else 2]
            asyncio.run(generation.dispose_once())
        elif name in (
            "pending_error_before_facts",
            "empty_targets_before_error",
            "second_commit_overwrites",
            "success_keeps_pending_error",
        ):
            self.case["fail_counts"] = {
                "cap-a.publish": [1, 2] if name == "second_commit_overwrites" else [1]
            }
            assert self.attempt("stage", self.stage)
            assert self.attempt("commit-one", self.commit)
            first_error = cappub.publication_error
            assert first_error is not None
            if name in ("second_commit_overwrites", "success_keeps_pending_error"):
                assert self.attempt("commit-two", self.commit)
                self.trace.append(
                    ["error_identity", cappub.publication_error is first_error]
                )
                assert (cappub.publication_error is first_error) == (
                    name == "success_keeps_pending_error"
                )
            if name == "pending_error_before_facts":
                self.session._coding_capability_plugin_assembly = None
                assert not self.attempt("empty-restage", self.stage)
                assert not cappub.receipts and cappub.publication_error is first_error
            if name == "empty_targets_before_error":
                self.original_map.clear()
            self.read_fail.update(
                {"_capability_owner_generations", "_mounted_resource_candidate"}
            )
            self.attempt("pending-error-require", lambda: self.require("capability"))
            self.trace.append(
                ["pending_error_after", error_data(cappub.publication_error)]
            )
            if name == "empty_targets_before_error":
                assert cappub.publication_error is first_error
            else:
                assert cappub.publication_error is None
            if name == "pending_error_before_facts":
                assert not self.attempt(
                    "facts-fault-is-active", lambda: self.require("capability")
                )
            return
        elif name == "capture_failure_preserves_receipts":
            assert self.attempt("stage-first", self.stage)
            before = basepub.receipts
            self.case["fail_counts"] = {"base.receipt": [2]}
            assert not self.attempt("stage-second", self.stage)
            assert basepub.receipts is before
            self.trace.append(["receipt_identity", True])
            return
        elif name in ("retire_unpublished", "retire_retry"):
            assert self.attempt("stage", self.stage)
            if name == "retire_retry":
                self.case["fail"] = ["base.retire"]
            self.attempt("retire-first", basepub.retire_after_graph)
            self.attempt("retire-second", basepub.retire_after_graph)
            assert basepub.retired and not basepub.published
            return
        self.attempt("edge-stage", self.stage)
        # For absent/empty maps compare lazy require after clearing staged receipt facts.
        if name in (
            "cap_none_after_binding",
            "cap_map_empty_replacement",
            "target_map_cleared",
        ):
            self.attempt("edge-require", lambda: self.require("capability"))

    def validate_observation(self):
        errors = [row for row in self.trace if row[0] == "error"]
        assert not any(row[2]["type"].endswith(".AttributeError") for row in errors)
        name = self.case["name"]
        success = {
            "both",
            "base_only",
            "cap_only",
            "no_assemblies",
            "cap_present_empty",
            "base_present_no_lease",
            "repeat_stage_after_commit",
            "resource_only",
            "sort_ties_and_duplicates",
            "resource_ids_sorted_unique",
            "base_empty_contributions",
            "cap_mapping_reordered",
            "target_map_cleared",
            "live_cap_does_not_read_candidate",
            "retire_unpublished",
            "empty_targets_before_error",
        }
        if name in success:
            assert not errors, (name, errors)
        elif self.case.get("edge") or self.case.get("fail"):
            assert errors, name
        if name == "sort_ties_and_duplicates":
            result = self.publication("base").receipts
            assert [item.contribution_ids for item in result[:3]] == [
                ("tool:base",),
                ("tie:second",),
                ("tool:base",),
            ]
        if name == "resource_ids_sorted_unique":
            calls = [
                row for row in self.trace if row[:2] == ["call", "resource.receipt"]
            ]
            assert calls == [["call", "resource.receipt", ["r:a", "r:b", "r:z"]]]
        if name == "cap_mapping_reordered":
            assert list(self.publication("capability").receipts) == ["cap-b", "cap-a"]
        if name == "cap_map_replaced":
            assert list(self.publication("capability").receipts) == ["cap-b", "cap-c"]
        if name in (
            "base_none_after_binding",
            "base_no_lease_after_binding",
            "base_none_during_capture",
        ):
            assert self.publication("base").receipts == ()
            assert any(row[:2] == ["call", "base.receipt"] for row in self.trace)
        if name == "cap_present_empty":
            publication = self.publication("capability")
            assert (
                publication.receipts == {}
                and publication.prepared
                and not publication.published
            )
        if not self.case.get("edge") and name != "cap_mapping_empty_tuple":
            assert self.session._capability_graph_runtime.is_closed
            assert all(generation.disposed for generation in self.generations)

    def run(self):
        self.edge() if self.case.get("edge") else self.flow()
        self.validate_observation()
        return {"case": self.case["name"], "trace": self.trace}


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_publication(case, monkeypatch):
    # Fault schedules are local to each exercise. Expected values come only from
    # the frozen pre-refactor source; no current implementation builds them.
    case = json.loads(json.dumps(case))
    observed = Scenario(case, monkeypatch).run()
    expected = json.loads(
        gzip.decompress(
            (HERE / "fixtures" / "owner_receipt_publication_v1.json.gz").read_bytes()
        )
    )[case["name"]]
    assert observed == expected
