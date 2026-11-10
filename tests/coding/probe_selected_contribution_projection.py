"""Old-first inert selected-declaration projections; snapshot authority is controlled."""

import dataclasses
import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace as NS

import pytest

import loushang.coding._base_product_composition as code
import loushang.harness.session.product_composition_assembly as core
from loushang.coding._plugin_lifecycle import package_revision_ref
from loushang.harness.resources.packages.plugin_lifecycle.commit_records import (
    PluginRevisionRefV1,
)
from loushang.harness.resources.plugins.selection import (
    PluginContributionRef,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginInstanceRevisionRef,
    PluginPreflightContextV1,
    PluginSelectionPlanV2,
)
from tests.coding.probe_product_selected_revision_custody import (
    _selected_inputs,
    load_product,
)

F = Path(__file__).parent / "fixtures"
ROWS = [
    json.loads(line)
    for line in (F / "selected_contribution_projection_v1.jsonl")
    .read_text()
    .splitlines()
][1:]


def inputs():
    product = load_product()
    product.input_wheels = json.loads(
        (F / "product_selected_revision_input_wheels_v1.json").read_text()
    )
    product.external_files = json.loads(
        (F / "product_selected_revision_input_external_v1.json").read_text()
    )
    selected = _selected_inputs(product)
    plans = {}
    for plugin, s in selected.items():
        snapshot = s.snapshot
        revision = package_revision_ref(
            plugin_id=plugin,
            plugin_version=s.manifest.version,
            package_source_identity=snapshot.package_revision.package_source_identity,
            package_content_digest="a" * 64,
            dependency_lock_digest="b" * 64,
        )
        ref = PluginRevisionRefV1.create(
            store_identity="store-projection",
            store_revision="revision-1",
            installation_id="installation-" + plugin,
            plugin_id=plugin,
            distribution="loushang-projection",
            version="1",
            artifact_digest=snapshot.root_ref.artifact_digest,
            extraction_tree_digest="e" * 64,
        )
        instance = PluginInstanceRevisionRef("projection:" + plugin, plugin, 1)
        for key, value in dict(
            package_revision=revision,
            root_ref=ref,
            instance_revision_ref=instance,
            committed_record=NS(committed_set=NS(set_id="selected-set")),
        ).items():
            object.__setattr__(snapshot, key, value)
        reservations = s.manifest.contribution_index.items
        plans[plugin] = PluginSelectionPlanV2(
            context=PluginPreflightContextV1(
                "coding", "session:projection", "projection-v1", (instance,)
            ),
            selected_plugin_ids=(plugin,),
            selected_contributions=tuple(
                sorted(
                    PluginContributionRef(plugin, x.contribution_id)
                    for x in reservations
                )
            ),
            source_trust_snapshots=(s.source_trust_snapshot,),
            effective_configuration_set=PluginEffectiveConfigurationSetV1(
                tuple(
                    sorted(
                        (
                            PluginEffectiveConfigurationEntry(
                                plugin, x.contribution_id, x.configuration
                            )
                            for x in reservations
                        ),
                        key=lambda x: x.contribution_id,
                    )
                )
            ),
            allowed_authority_ceiling=(),
        )
    return selected, plans


def observe(case, monkeypatch):
    selected, plans = inputs()
    plugin = (
        "reviewpack"
        if case == "external" or case == "directory" or case.startswith("directory-")
        else "coding.base"
    )
    s = selected[plugin]
    plan = plans[plugin]
    pairs = s.verified_data_only_declarations()

    def category(pair):
        res, decl = pair
        if decl.kind == "resource_item":
            return (
                "directory"
                if decl.to_dict()["payload"]["locatorKind"] == "directory"
                else "file"
            )
        return "tool" if decl.kind == "tool_pack" else "command"

    targets = (
        pairs
        if case == "all-base"
        else (
            next(
                pair
                for pair in pairs
                if category(pair)
                == (
                    case
                    if case in ("directory", "tool", "command")
                    else "directory"
                    if case.startswith("directory-")
                    else "file"
                    if plugin == "coding.base"
                    else "directory"
                )
            ),
        )
    )
    trace = []
    count = 0
    errors = {}
    overrides = {}
    output = []
    fault = OSError("controlled projection payload refusal")
    if case == "unicode-policy":
        object.__setattr__(plan.context, "policy_revision", "policy-版本")
    if case == "untrusted":
        object.__setattr__(s.source_trust_snapshot, "trusted", False)
    if case == "missing-trust" or case in (
        "document-before-trust",
        "digest-before-trust",
    ):
        object.__setattr__(plan, "source_trust_snapshots", ())
    if case == "duplicate-trust":
        object.__setattr__(
            plan,
            "source_trust_snapshots",
            (
                s.source_trust_snapshot,
                dataclasses.replace(
                    s.source_trust_snapshot, package_source_identity="later-source"
                ),
            ),
        )
    if case == "no-selected-membership":
        object.__setattr__(plan, "selected_contributions", ())
    if case == "root-dot":
        prefix = s.manifest.root_relative_path.as_posix() + "/"
        object.__setattr__(s.manifest, "root_relative_path", PurePosixPath("."))
        object.__setattr__(
            s.snapshot,
            "files",
            tuple((name.removeprefix(prefix), raw) for name, raw in s.snapshot.files),
        )
        object.__setattr__(
            s,
            "declaration_documents",
            tuple(
                (name.removeprefix(prefix), value)
                for name, value in s.declaration_documents
            ),
        )

    class View:
        def __init__(self, value, label):
            self.value = value
            self.label = label

        def __getattr__(self, name):
            key = self.label + "." + name
            trace.append(key)
            value = overrides[key] if key in overrides else getattr(self.value, name)
            return (
                View(value, key)
                if key in ("selected.snapshot", "selected.manifest", "plan.context")
                else value
            )

    original_digest = core._digest_document

    def digest(domain, payload):
        nonlocal count
        count += 1
        trace.append("digest:" + domain)
        if (case in ("first-hash", "digest-before-trust") and count == 1) or (
            case == "second-hash" and count == 2
        ):
            raise OSError("controlled hash " + str(count))
        return original_digest(domain, payload)

    module = core
    name = "_digest_document"
    with monkeypatch.context() as patch:
        patch.setattr(module, name, digest)
        for reservation, declaration in targets:
            payload = declaration.to_dict()["payload"]
            root = s.manifest.root_relative_path.as_posix()
            locator = payload.get("locator", "")
            full = locator if root == "." else root + "/" + locator
            if case in (
                "file-absent",
                "file-child-only",
                "directory-absent",
                "directory-prefix-peer",
                "locator-before-owner",
            ):
                files = tuple(
                    (n, b)
                    for n, b in s.snapshot.files
                    if n != full and not n.startswith(full + "/")
                )
                if case == "file-child-only":
                    files += ((full + "/child", b"child"),)
                if case == "directory-prefix-peer":
                    files += ((full + "-peer/SKILL.md", b"peer"),)
                object.__setattr__(s.snapshot, "files", files)
            if case == "directory-is-file":
                object.__setattr__(
                    s.snapshot,
                    "files",
                    (*s.snapshot.files, (full, b"directory name is a file")),
                )
            if case in ("missing-document", "document-before-trust"):
                object.__setattr__(s, "declaration_documents", ())
            if case == "changed-document":
                object.__setattr__(
                    s,
                    "declaration_documents",
                    tuple(
                        (n, NS(bytes_digest="f" * 64))
                        for n, _ in s.declaration_documents
                    ),
                )
            if case == "plugin-mismatch":
                overrides["declaration.plugin_id"] = "peer"
            if case in ("unknown-kind", "payload-before-kind"):
                overrides["declaration.kind"] = "provider"
            if case in ("bad-owner", "locator-before-owner"):
                overrides["reservation.owner"] = "other.owner"
            if case == "requested-authority":
                overrides["reservation.requested_authorities"] = ("process.execute",)
            if case == "bad-payload":
                overrides["declaration.to_dict"] = lambda: dict(payload={})
            if case in ("payload-error", "payload-before-kind"):

                def refuse():
                    raise fault

                overrides["declaration.to_dict"] = refuse
            try:
                value = code._candidate(
                    View(s, "selected"),
                    View(plan, "plan"),
                    View(reservation, "reservation"),
                    View(declaration, "declaration"),
                )
                output.append(
                    dict(record=value.to_dict(), fingerprint=value.fingerprint)
                )
            except BaseException as error:

                def graph(e):
                    return (
                        None
                        if e is None
                        else dict(
                            type=type(e).__module__ + "." + type(e).__qualname__,
                            args=list(e.args),
                            code=getattr(e, "code", None),
                            cause=graph(e.__cause__),
                            context=graph(e.__context__),
                            suppress=e.__suppress_context__,
                        )
                    )

                errors = graph(error)
                break
    return dict(trace=trace, output=output, error=errors or None)


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row["case"])
def test_original_projection(row, monkeypatch):
    source = Path(__file__).resolve().parents[2] / "src"
    for module, relative in (
        (code, "loushang/coding/_base_product_composition.py"),
        (core, "loushang/harness/session/product_composition_assembly.py"),
    ):
        assert Path(module.__file__).resolve() == (source / relative).resolve()
    value = json.loads(json.dumps(observe(row["case"], monkeypatch), sort_keys=True))
    assert value == row["observation"], value
