"""Explicit frozen pre-A182 public Product preview projection observations.

Real Catalog builders, owner-issued admissions, Desired records and public DTOs;
selected Store input/snapshot fields are seeded nominal values, not verified
Store bytes, native IO or live authority. Compilation/resource/epoch leaves are
controlled. Exactly six observations; no capture or default CI route.
"""

import dataclasses
import functools
import gzip
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.package.product_preview as code
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAuthority,
    OwnerContributionCandidateEnvelope,
    OwnerContributionPolicy,
    ResourceContributionSpec,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
)
from loushang.harness.plugin_management.current_preview import (
    PluginCurrentCompositionPreviewV1,
    PluginCurrentResourceAdmissionV1,
    PluginCurrentResourceSelectionV1,
)
from loushang.harness.plugin_management.ledger import PluginDesiredStateSnapshotV1
from loushang.harness.plugin_management.package_product import (
    PackageProductSelectedRootSnapshotV1,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredSelectionV1,
    PluginInstallationKeyV1,
    PluginInstallationStateV1,
    PluginPackageRevisionRefV1,
)
from loushang.harness.resource_catalog.product_snapshot_source import (
    ProductSelectedResourceInput,
)
from loushang.harness.resources._catalog_records import (
    VerifiedPluginResourceOrigin,
    build_candidate_summary,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef
from loushang.harness.resources.types import (
    PromptFragmentDescriptor,
    ResourceBundle,
    SkillDescriptor,
    ThemeDescriptor,
)
from tests.harness.resources.test_catalog_v2 import (
    _candidate,
    _compose,
    _source_snapshot,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="Frozen controlled Linux projection model, not native authority",
)

EXPECTED = (
    Path(__file__).with_name("fixtures") / "product_preview_projection_v1.json.gz"
)
CASES = (
    "complete-projection",
    "contribution-mismatch",
    "content-mismatch",
    "instance-mismatch",
    "after-read-failure",
    "admission-constructor-failure",
)


def error_data(error, sentinel):
    if error is None:
        return None
    return {
        "type": type(error).__module__ + "." + type(error).__qualname__,
        "args": list(error.args),
        "message": str(error),
        "same_sentinel": error is sentinel,
        "notes": getattr(error, "__notes__", []),
        "cause": error_data(error.__cause__, sentinel),
        "context": error_data(error.__context__, sentinel),
        "suppress": error.__suppress_context__,
    }


def metadata(owner):
    return {
        "owner_class": type(owner).__module__ + "." + type(owner).__qualname__,
        "owner_slots": list(type(owner).__slots__),
        "owner_fields": [[f.name, f.type] for f in dataclasses.fields(type(owner))],
        "owner_no_dict": not hasattr(owner, "__dict__"),
        "owner_signature": str(inspect.signature(type(owner))),
        "preview_signature": str(
            inspect.signature(type(owner).preview_current_data_resources)
        ),
        "preview_alias_same": code.CodingCurrentDataResourcePreviewV1
        is PluginCurrentCompositionPreviewV1,
        "admission_alias_same": code.CodingDataResourceAdmissionPreviewV1
        is PluginCurrentResourceAdmissionV1,
    }


def seeded(cls, **fields):
    value = object.__new__(cls)
    for key, item in fields.items():
        object.__setattr__(value, key, item)
    return value


def observe(case, monkeypatch, tmp_path):
    trace = []
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    scope = "workspace:controlled"
    instance = PluginInstanceRevisionRef("sample-instance", "sample", 1)
    revision = PluginPackageRevisionRefV1(
        "sample", "1", "a" * 64, "b" * 64, "controlled:sample"
    )
    key = PluginInstallationKeyV1("coding", "workspace", scope, "sample")
    contribution = ResourceContributionSpec(
        resource_kind="skill",
        locator="skills/review/SKILL.md",
        locator_kind="file",
        media_type="text/markdown",
        schema_id="loushang.resource.skill",
        schema_version=1,
    )
    envelope = OwnerContributionCandidateEnvelope(
        owner_id="resources.skill",
        plugin_id="sample",
        contribution_id="sample.skill",
        contribution=contribution,
        plugin_candidate_fingerprint="1" * 64,
        declaration_fingerprint="2" * 64,
        declaration_evidence_fingerprint="3" * 64,
        package_content_digest=revision.package_content_digest,
        dependency_lock_digest=revision.dependency_lock_digest,
        product_id="coding",
        scope_id=scope,
        product_policy_revision="policy:1",
        instance_revision_ref=instance,
        package_source_identity=revision.package_source_identity,
        source_trust_class="controlled",
        source_trust_policy_revision="trust:1",
        source_trusted=True,
    )
    admission = OwnerContributionAuthority(
        OwnerContributionPolicy(
            owner_id="resources.skill",
            contribution_kind="resource_item",
            product_id="coding",
            policy_revision="owner:1",
            revocation_epoch=0,
            allowed_source_trust_classes=("controlled",),
            allowed_collection_ids=("loushang.resource.skill",),
            allowed_requirement_bindings=("direct",),
            consumer_scope="session",
            consumer_refresh_boundary="sealed",
        )
    ).admit(envelope, issued_at=1, expires_at=100)
    # Only these original projection fields are consumed; this deliberately does
    # not bypass a real Store and then claim verified bytes or live selection.
    snapshot = seeded(
        PackageProductSelectedRootSnapshotV1,
        installation_key=key,
        package_revision=revision,
        instance_revision_ref=instance,
    )
    selected = seeded(PackageProductSelectedPluginManifestV1, snapshot=snapshot)
    product_input = seeded(
        ProductSelectedResourceInput,
        admission=admission,
        selected_manifest=selected,
        relative_path="skills/review/SKILL.md",
        source_root_order=0,
        _body=b"controlled",
    )
    origin = VerifiedPluginResourceOrigin(
        resource_contribution_id=(
            "wrong" if case == "contribution-mismatch" else admission.contribution_id
        ),
        resource_admission_fingerprint=admission.fingerprint,
        plugin_instance_revision_ref=(
            "wrong:sample@1"
            if case == "instance-mismatch"
            else "sample-instance:sample@1"
        ),
        package_content_digest=(
            "c" * 64 if case == "content-mismatch" else revision.package_content_digest
        ),
    )
    candidate = _candidate("review", source_class="external_package")
    kwargs = {
        name: getattr(candidate, name)
        for name in inspect.signature(build_candidate_summary).parameters
    }
    kwargs["content_origin"] = origin
    candidate = build_candidate_summary(**kwargs)
    catalog = _compose(
        _source_snapshot(
            candidate,
            _candidate("native"),
            _candidate("unknown", source_class="external_package"),
        )
    )
    base_key = PluginInstallationKeyV1("coding", "workspace", scope, "coding.base")
    base_revision = PluginPackageRevisionRefV1(
        "coding.base", "1", "d" * 64, "e" * 64, "controlled:base"
    )
    base_instance = PluginInstanceRevisionRef("base-instance", "coding.base", 1)
    states = tuple(
        sorted(
            (
                PluginInstallationStateV1(
                    key,
                    PluginDesiredSelectionV1("installed_enabled", revision, instance),
                    instance,
                ),
                PluginInstallationStateV1(
                    base_key,
                    PluginDesiredSelectionV1(
                        "installed_enabled", base_revision, base_instance
                    ),
                    base_instance,
                ),
            ),
            key=lambda state: state.installation_key,
        )
    )
    before = PluginDesiredStateSnapshotV1(5, states)
    after = PluginDesiredStateSnapshotV1(6, states)
    sentinel = (
        LookupError("after read failed")
        if case == "after-read-failure"
        else ValueError("admission constructor failed")
    )
    sentinel.add_note("controlled original sentinel")

    class Desired:
        calls = 0

        def capture_read_only(self):
            self.calls += 1
            trace.append(["desired", self.calls])
            if self.calls == 2 and case == "after-read-failure":
                raise sentinel
            return (before if self.calls == 1 else after), ()

    class Epoch:
        calls = 0

        def assert_current(self):
            self.calls += 1
            trace.append(["epoch", self.calls])
            if self.calls == 2 and case == "after-read-failure":
                raise RuntimeError("later epoch must not run")

    class Bundle(ResourceBundle):
        def __getattribute__(self, name):
            if name in {"skills", "prompts", "themes", "diagnostics"}:
                trace.append(["bundle", name])
            return super().__getattribute__(name)

    bundle = Bundle(
        cwd=workspace,
        skills=[
            SkillDescriptor("disabled", workspace / "s", enabled=False),
            SkillDescriptor("review", workspace / "s", source_kind="external_package"),
        ],
        prompts=[
            PromptFragmentDescriptor(
                "prompt", workspace / "p", "controlled", source_kind="built_in"
            )
        ],
        themes=[ThemeDescriptor("theme", workspace / "t", source_kind="project_local")],
        diagnostics=[
            SimpleNamespace(code="duplicate"),
            SimpleNamespace(code="duplicate"),
            SimpleNamespace(code="other"),
        ],
    )
    inputs = (product_input,)

    class Compiled:
        plan = SimpleNamespace(selected_plugin_ids=("coding.base", "sample"))

        @property
        def product_composition(self):
            trace.append(["compiled.composition"])
            return SimpleNamespace(resource_admissions=(admission,))

        def product_resource_inputs(self):
            trace.append(["compiled.inputs"])
            return inputs

    desired = Desired()
    epoch = Epoch()
    manifests = SimpleNamespace(
        root_reader=SimpleNamespace(desired_state=desired),
        selected_external_data_plugin_ids=lambda: (),
        capture_selected_manifest_for_plugin=lambda plugin_id, **kwargs: (
            SimpleNamespace(snapshot=SimpleNamespace(installation_key=base_key))
        ),
    )
    policy = SimpleNamespace(
        product_id="coding",
        project_scope_id=scope,
        policy_revision="policy:1",
        authority_revision="authority:1",
        bindings=(
            SimpleNamespace(
                plugin_id="coding.base", source_trust_class="host-equivalent-local"
            ),
            SimpleNamespace(plugin_id="sample", source_trust_class="local-data-only"),
        ),
    )
    owner = code.CodingFencedProductReadOnlyPreviewOwner(epoch, policy, manifests, None)
    composition = SimpleNamespace(
        set_id="coding-standard",
        plugin_requests=(
            SimpleNamespace(plugin_id="coding.base"),
            SimpleNamespace(plugin_id="sample"),
        ),
    )
    original_evidence = code._selection_evidence

    def evidence(*args):
        trace.append(["evidence"])
        if case == "after-read-failure":
            raise RuntimeError("later evidence must not run")
        return original_evidence(*args)

    def compile_base(*args, **kwargs):
        trace.append(["compile"])
        return Compiled()

    class Loader:
        def __init__(self, **kwargs):
            trace.append(["loader"])

        def prepare_catalog_input_receipt(self, workspace):
            trace.append(["input.receipt"])
            return object()

    class Adapter:
        def prepare_bootstrap_projection_with_receipt(self, **kwargs):
            trace.append(["catalog.receipt"])
            return SimpleNamespace(bundle=bundle, catalog=catalog)

    def build_adapter(*args, **kwargs):
        trace.append(["adapter", kwargs["product_snapshot_resources"] is inputs])
        return Adapter()

    def clock():
        trace.append(["clock", "seconds"])
        return 10

    def clock_ns():
        trace.append(["clock", "nanoseconds"])
        return 10000000001

    monkeypatch.setattr(code, "_workspace_scope_id", lambda path: scope)
    monkeypatch.setattr(
        code, "resolve_coding_composition_set", lambda name: composition
    )
    monkeypatch.setattr(code, "compile_coding_base_product_selection", compile_base)
    monkeypatch.setattr(
        code,
        "LocalHostEnvironmentProbe",
        lambda: SimpleNamespace(detect=lambda: "controlled-host"),
    )
    monkeypatch.setattr(code, "CodingResourceLoader", Loader)
    monkeypatch.setattr(
        code, "build_coding_initial_resource_catalog_adapter", build_adapter
    )
    monkeypatch.setattr(code, "_selection_evidence", evidence)
    monkeypatch.setattr(code, "time", SimpleNamespace(time=clock, time_ns=clock_ns))
    old_getattr = VerifiedPluginResourceOrigin.__getattribute__

    def origin_read(self, name):
        if self is origin and name in {
            "resource_contribution_id",
            "package_content_digest",
            "plugin_instance_revision_ref",
        }:
            trace.append(["origin", name])
        return old_getattr(self, name)

    monkeypatch.setattr(VerifiedPluginResourceOrigin, "__getattribute__", origin_read)
    old_selection = PluginCurrentResourceSelectionV1.__init__

    @functools.wraps(old_selection)
    def new_selection(self, **fields):
        trace.append(["selection.new"])
        old_selection(self, **fields)

    monkeypatch.setattr(PluginCurrentResourceSelectionV1, "__init__", new_selection)
    old_admission = PluginCurrentResourceAdmissionV1.__init__

    @functools.wraps(old_admission)
    def new_admission(self, **fields):
        trace.append(["admission.new"])
        if case == "admission-constructor-failure":
            raise sentinel
        old_admission(self, **fields)

    monkeypatch.setattr(PluginCurrentResourceAdmissionV1, "__init__", new_admission)
    result = None
    error = None
    try:
        result = owner.preview_current_data_resources(
            workspace=workspace, disabled_skills=()
        )
    except BaseException as exc:
        error = exc
    if case == "complete-projection":
        assert type(result) is PluginCurrentCompositionPreviewV1 and error is None
        assert len(result.selected_resources) == len(result.admitted_resources) == 1
        assert result.selected_resources[0].installation_key is key
        assert result.evidence_gaps == (
            "exact_catalog_generation",
            "session_invocation_options",
            "stale_snapshot",
        )
        assert result.catalog_resources == (
            ("prompt", "prompt", "built_in"),
            ("skill", "review", "external_package"),
            ("theme", "theme", "project_local"),
        )
        assert (
            trace.index(["desired", 2])
            < trace.index(["epoch", 2])
            < trace.index(["evidence"])
            < trace.index(["admission.new"])
            < trace.index(["bundle", "skills"])
            < trace.index(["clock", "nanoseconds"])
        )
    elif case.endswith("mismatch"):
        assert (
            isinstance(error, ValueError)
            and str(error) == "Product preview Catalog selection changed owner identity"
        )
        assert desired.calls == epoch.calls == 1
        expected_reads = ["resource_contribution_id"]
        if case in {"content-mismatch", "instance-mismatch"}:
            expected_reads.append("package_content_digest")
        if case == "instance-mismatch":
            expected_reads.append("plugin_instance_revision_ref")
        assert [item[1] for item in trace if item[0] == "origin"] == expected_reads
        assert ["selection.new"] not in trace and ["admission.new"] not in trace
    else:
        assert error is sentinel
        if case == "after-read-failure":
            assert desired.calls == 2 and epoch.calls == 1 and ["evidence"] not in trace
        else:
            assert ["evidence"] in trace and ["admission.new"] in trace
        assert not any(item[0] == "bundle" for item in trace)
        assert ["clock", "nanoseconds"] not in trace
    return {
        "trace": trace,
        "wire": result.to_dict() if result is not None else None,
        "error": error_data(error, sentinel),
        "metadata": metadata(owner) if case == "complete-projection" else None,
    }


@pytest.mark.parametrize("case", CASES)
def test_original_preview(case, monkeypatch, tmp_path):
    observed = json.loads(json.dumps(observe(case, monkeypatch, tmp_path)))
    assert observed == json.loads(gzip.decompress(EXPECTED.read_bytes()))[case]
