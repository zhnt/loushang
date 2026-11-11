"""Fixed old approval handoffs; explicit probe outside default test discovery.

Actual journals, subject/record values and JSONL bytes are exercised. Resolver,
Definition, Provider, authority and Resume ports are controlled. The frozen seed
bypasses upstream package admission to isolate this coordination boundary; this
probe does not prove real package execution or Resume enrollment. No recapture.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from loushang.coding import _capability_plugin_composition as code
from loushang.harness.approval.plugin_activation import PluginActivationDecisionJournal
from loushang.harness.approval.plugin_execution import (
    PluginApprovalAuthorizationV1,
    PluginExecutionDecisionJournal,
)
from loushang.harness.capabilities import component_host as component_module
from loushang.harness.plugin_authoring import host as host_module
from loushang.harness.resources.plugins import selection as values
from loushang.harness.resources.plugins.import_realm import PluginImportRealm
from loushang.harness.session.product_composition_assembly import (
    ProductPluginCompositionAssembly,
    ProductPluginPlanSeed,
)
from tests.coding.probe_native_release_readers_compatibility import error_graph
from tests.harness.approval.test_plugin_activation_journal import (
    _subject as activation_subject,
)
from tests.harness.approval.test_plugin_execution_journal import (
    _subject as definition_subject,
)

CASES = tuple(
    "definition-" + c
    for c in (
        "direct",
        "pending",
        "two",
        "empty-pending",
        "first-denied",
        "first-rejected",
        "second-denied",
        "second-rejected",
        "still-pending",
        "wrong-type",
        "wrong-subject",
        "unrecorded",
        "issuer-error",
        "second-issuer-error",
        "first-resolve-error",
        "second-resolve-error",
        "journal-error",
        "realm-error",
        "distribution-error",
        "resume-leaf-error",
        "evaluator-error",
        "host-error",
        "resume-guard-error",
        "invalid-parent",
        "late-error",
    )
)
CASES += ("definition-issuer-cancel", "definition-second-issuer-cancel")
CASES += tuple(
    "activation-" + c
    for c in (
        "zero",
        "one",
        "two",
        "wrong-type",
        "wrong-subject",
        "unrecorded",
        "different-record",
        "denied",
        "revoked",
        "second-issuer-error",
        "subject-error",
        "second-subject-error",
        "owner-missing",
        "owner-error",
        "trust-missing",
        "trust-duplicate",
        "product-changed",
        "scope-changed",
        "bind-error",
        "recovery-error",
        "journal-error",
        "realm-error",
        "distribution-error",
        "resume-leaf-error",
        "raw-snapshot-error",
        "raw-resume-error",
        "late-error",
    )
)

CASES += ("activation-issuer-cancel", "activation-second-issuer-cancel")


def observe(name, base, patch):
    kind, case = name.split("-", 1)
    trace = []
    journals = []
    issued = []
    resolve_count = 0
    issue_count = 0
    subject_count = 0
    host_objects = []
    scope = "session:test"

    def clock():
        return 150

    def norm(value):
        return value.replace(str(base), "<ROOT>")

    def_subject = replace(definition_subject(), scope_id=scope)
    act_subject = replace(
        activation_subject(), scope_id=scope, product_policy_revision="policy-1"
    )
    selected = def_subject if kind == "definition" else act_subject
    trust = values.PluginSourceTrustSnapshotV1(
        selected.plugin_id,
        selected.package_source_identity
        if kind == "definition"
        else "registry:example",
        "registry_signed",
        "trust-1",
        True,
    )
    plan = values.PluginSelectionPlanV2(
        context=values.PluginPreflightContextV1(
            product_id="coding",
            scope_id=scope,
            policy_revision="policy-1",
            instance_revision_refs=(selected.instance_revision_ref,),
        ),
        selected_plugin_ids=(selected.plugin_id,),
        selected_contributions=(
            values.PluginContributionRef(selected.plugin_id, "semantic-provider"),
        ),
        source_trust_snapshots=(trust,),
        effective_configuration_set=values.PluginEffectiveConfigurationSetV1(
            entries=(
                values.PluginEffectiveConfigurationEntry(
                    selected.plugin_id, "semantic-provider", {}
                ),
            )
        ),
        allowed_authority_ceiling=(),
    )
    selection = values.PluginSelection(plan, ())
    seed = ProductPluginPlanSeed.__new__(ProductPluginPlanSeed)
    for field, value in {
        "plan": plan,
        "packages": (),
        "bindings": (),
        "owner_bindings": (),
    }.items():
        object.__setattr__(seed, field, value)
    # Controlled preflight and authority values do not assert production selection
    # or Provider/Definition execution. Actual journal records and IO remain real.
    activation_selection = NS(
        plan=NS(
            source_trust_snapshots=(trust, trust)
            if case == "trust-duplicate"
            else ()
            if case == "trust-missing"
            else (trust,),
            context=plan.context,
        )
    )
    subject2 = replace(def_subject, package_content_digest="9" * 64)
    subjects = (
        tuple(sorted((def_subject, subject2), key=lambda item: item.digest))
        if case in ("two", "second-issuer-error", "second-issuer-cancel")
        else (def_subject,)
    )
    pending = values.PluginPreflightPendingApprovalOutcome(subjects, ())
    if case == "empty-pending":
        object.__setattr__(pending, "subjects", ())
    diagnostic = values.PluginPreflightDiagnostic(
        "denied-test", "denied", selected.plugin_id
    )
    rejected = values.PluginPreflightRejectedOutcome(
        (diagnostic, values.PluginPreflightDiagnostic("plan-test", "plan"))
    )
    denied = values.PluginPreflightDeniedOutcome((diagnostic,))
    snapshot_fault = False

    def journal_factory(real, tag):
        def factory(path, **kwargs):
            trace.append(
                [
                    "journal",
                    tag,
                    norm(str(path)),
                    kwargs.get("scope_kind"),
                    kwargs["scope_id"],
                    sorted(kwargs.get("required_writer_capabilities", ())),
                ]
            )
            if case == "journal-error":
                raise OSError("injected journal constructor")
            counter = iter(range(1, 100))
            factories = (
                {
                    "decision_id_factory": lambda: format(next(counter), "048x"),
                    "execution_use_id_factory": lambda: format(next(counter), "048x"),
                }
                if tag == "definition"
                else {"identity_factory": lambda: format(next(counter), "048x")}
            )
            obj = real(path, **kwargs, **factories)
            journals.append(obj)
            real_snapshot = obj.snapshot

            def snapshot(*args, **kwargs):
                trace.append(["snapshot", tag, dict(kwargs)])
                if snapshot_fault:
                    raise OSError(
                        "injected raw Resume snapshot"
                        if case == "raw-resume-error"
                        else "injected raw snapshot"
                    )
                return real_snapshot(*args, **kwargs)

            obj.snapshot = snapshot
            return obj

        return factory

    adopted = hasattr(host_module.PluginDeclarationHost, "resolve_for_product")
    definition_effects = host_module if adopted else code
    activation_effects = component_module if adopted else code
    patch.setattr(
        definition_effects,
        "PluginExecutionDecisionJournal",
        journal_factory(PluginExecutionDecisionJournal, "definition"),
    )
    patch.setattr(
        activation_effects,
        "PluginActivationDecisionJournal",
        journal_factory(PluginActivationDecisionJournal, "activation"),
    )

    def realm():
        trace.append(["realm"])
        if case == "realm-error":
            raise OSError("injected realm")
        return PluginImportRealm(import_realm_id_factory=lambda: "4" * 32)

    patch.setattr(definition_effects, "PluginImportRealm", realm)
    if activation_effects is not definition_effects:
        patch.setattr(activation_effects, "PluginImportRealm", realm)

    def distribution():
        trace.append(["distribution"])
        if case == "distribution-error":
            raise OSError("injected distribution")
        return "controlled-distribution"

    patch.setattr(code, "coding_plugin_distribution_evidence_resolver", distribution)

    class Parents:
        @property
        def activation(self):
            trace.append(["resume-leaf", "activation"])
            if case == "resume-leaf-error":
                raise OSError("injected Resume leaf")
            return None

        @property
        def definition(self):
            trace.append(["resume-leaf", "definition"])
            if case == "resume-leaf-error":
                raise OSError("injected Resume leaf")
            return None

        def require_open(self, **kwargs):
            trace.append(
                ["resume-guard", kwargs["session_id"], norm(str(kwargs["state_root"]))]
            )
            if case == "resume-guard-error":
                raise OSError("injected Resume guard")

    # Preserve the original exact-type check while controlling only parent policy.
    patch.setattr(code, "CodingResumePluginParents", Parents)
    parents = (
        object()
        if case == "invalid-parent"
        else Parents()
        if case in ("resume-leaf-error", "resume-guard-error", "raw-resume-error")
        else None
    )

    class Evaluator:
        def __init__(self, **kwargs):
            trace.append(
                [
                    "evaluator",
                    kwargs["distribution_evidence_resolver"],
                    kwargs["resume_parent_context"],
                ]
            )
            if case == "evaluator-error":
                raise OSError("injected evaluator")
            self.journal = kwargs["decision_journal"]

    patch.setattr(definition_effects, "PluginDefinitionEvaluator", Evaluator)

    class DeclarationHost(host_module.PluginDeclarationHost):
        def __init__(self, *, execution_evaluator):
            trace.append(["declaration-host"])
            if case == "host-error":
                raise OSError("injected host")
            self.journal = execution_evaluator.journal

        def resolve(self, packages, *, bindings, plan, decision_lookup):
            nonlocal resolve_count
            resolve_count += 1
            trace.append(
                [
                    "resolve",
                    resolve_count,
                    list(packages),
                    list(bindings),
                    decision_lookup is self.journal,
                ]
            )
            if case == (
                "first-resolve-error" if resolve_count == 1 else "second-resolve-error"
            ):
                raise OSError("injected resolve")
            if resolve_count == 1:
                if case == "direct":
                    return selection
                if case == "first-denied":
                    return denied
                if case == "first-rejected":
                    return rejected
                return pending
            if case in ("second-denied", "unrecorded"):
                return denied
            if case == "second-rejected":
                return rejected
            if case == "still-pending":
                return pending
            return selection

    patch.setattr(code, "PluginDeclarationHost", DeclarationHost)

    class ComponentHost(component_module.CapabilityComponentHost):
        def __init__(self, **kwargs):
            trace.append(
                [
                    "component-host",
                    kwargs["distribution_evidence_resolver"],
                    kwargs["resume_parent_context"],
                ]
            )
            self._lifecycle = NS(journal=kwargs["decision_journal"])
            self.readers = kwargs
            host_objects.append(self)
            trace.append(["recover"])
            if case == "recovery-error":
                raise OSError("injected constructor recovery")

        def activation_subject(self, resolved, *, owner_snapshot, trust_snapshot):
            nonlocal subject_count
            subject_count += 1
            trace.append(["subject", resolved.capability_id, subject_count])
            if case in ("subject-error", "second-subject-error") and subject_count == (
                2 if case.startswith("second") else 1
            ):
                raise OSError("injected activation subject")
            self.readers["owner_snapshot_reader"](resolved.capability_id)
            self.readers["trust_snapshot_reader"](
                trust.plugin_id, trust.package_source_identity
            )
            self.readers["product_policy_revision_reader"](
                "other" if case == "product-changed" else "coding",
                "other" if case == "scope-changed" else scope,
            )
            return (
                act_subject
                if subject_count == 1
                else replace(act_subject, candidate_fingerprint="f" * 64)
            )

    patch.setattr(code, "CapabilityComponentHost", ComponentHost)

    def owner_snapshot():
        trace.append(["owner-snapshot"])
        if case == "owner-error":
            raise OSError("injected owner")
        return "owner-snapshot"

    authorities = (
        {}
        if case == "owner-missing"
        else {
            "synthetic.semantic": NS(snapshot=owner_snapshot),
            "synthetic.semantic.second": NS(snapshot=owner_snapshot),
        }
    )
    result_marker = object()

    class Assembly:
        component_candidates = tuple(
            NS(
                capability_id="synthetic.semantic"
                if i == 0
                else "synthetic.semantic.second",
                resolved=NS(
                    capability_id="synthetic.semantic"
                    if i == 0
                    else "synthetic.semantic.second"
                ),
                owner_snapshot="owner-snapshot",
                trust_snapshot=trust,
            )
            for i in range(
                0
                if case == "zero"
                else 2
                if case
                in (
                    "two",
                    "second-issuer-error",
                    "second-subject-error",
                    "second-issuer-cancel",
                )
                else 1
            )
        )
        if adopted:
            approve_and_bind_session_inputs = (
                ProductPluginCompositionAssembly.approve_and_bind_session_inputs
            )

        def bind_session_inputs(self, decision_ids):
            trace.append(["bind", dict(decision_ids)])
            if case == "bind-error":
                raise OSError("injected bind")
            return result_marker

    class Issuer:
        def approve_definition(self, *, journal, subject):
            return self.issue(journal, subject, True)

        def approve_activation(self, *, journal, subject):
            return self.issue(journal, subject, False)

        def issue(self, journal, subject, is_definition):
            nonlocal issue_count, snapshot_fault
            issue_count += 1
            trace.append(
                [
                    "issuer",
                    "definition" if is_definition else "activation",
                    issue_count,
                    subject.digest,
                ]
            )
            if (
                case == "issuer-cancel"
                or case == "second-issuer-cancel"
                and issue_count == 2
            ):
                raise KeyboardInterrupt("injected approval cancellation")
            if (
                case == "issuer-error"
                or case == "second-issuer-error"
                and issue_count == 2
            ):
                raise OSError("injected issuer")
            if case == "wrong-type":
                return object()
            auth = PluginApprovalAuthorizationV1.direct(
                actor_id="operator:test", source="fixed-product-approval"
            )
            kwargs = dict(
                disposition="denied" if case == "denied" else "approved",
                authorization=auth,
                issued_at_unix_ms=140,
                expires_at_unix_ms=300,
                expected_journal_revision=journal.snapshot().journal_revision,
            )
            if is_definition:
                kwargs["revocation_epoch"] = 0
            decision = (
                journal.issue_execution_decision
                if is_definition
                else journal.issue_activation_decision
            )(subject, **kwargs)
            issued.append(decision)
            if case == "unrecorded":
                (
                    base
                    / (
                        "definition-decisions.jsonl"
                        if is_definition
                        else "activation-decisions.jsonl"
                    )
                ).unlink()
            if case == "different-record":
                decision = replace(decision, expires_at_unix_ms=301)
            if case == "revoked":
                journal.revoke_activation_decision(
                    decision.decision_id,
                    actor_id="operator:test",
                    source="fixed-revoke",
                    revoked_at_unix_ms=150,
                    expected_journal_revision=journal.snapshot().journal_revision,
                )
                decision = journal.snapshot().decisions[-1]
            if case in ("wrong-subject", "late-error"):
                if case == "late-error":

                    class LateError(RuntimeError):
                        def __init__(self, message, *, code):
                            super().__init__(message)
                            self.code = code

                    patch.setattr(
                        code, "CodingCapabilityPluginCompositionError", LateError
                    )
                decision = (
                    replace(decision, subject_digest="e" * 64)
                    if is_definition
                    else replace(
                        decision,
                        subject=replace(subject, candidate_fingerprint="e" * 64),
                    )
                )
            if case in ("raw-snapshot-error", "raw-resume-error"):
                snapshot_fault = True
            return decision

    request = NS(approval_owner=Issuer())
    try:
        try:
            if kind == "definition":
                result = code._finalize_selection(
                    seed,
                    request=request,
                    scope_id=scope,
                    state_root=base,
                    clock=clock,
                    resume_parents=parents,
                )
                value = {"selection_identity": result is selection}
            else:
                host, inputs = code._approve_activation_and_bind_inputs(
                    activation_selection,
                    Assembly(),
                    request=request,
                    provider_authorities=authorities,
                    scope_id=scope,
                    state_root=base,
                    host_boot_id="3" * 32,
                    clock=clock,
                    resume_parents=parents,
                )
                value = {
                    "host_identity": bool(host_objects) and host is host_objects[-1],
                    "inputs_identity": inputs is result_marker,
                }
            error = None
        except BaseException as exc:
            value = None
            error = error_graph(exc, norm)
            error["code"] = getattr(exc, "code", None)
        return {
            "value": value,
            "error": error,
            "trace": trace,
            "issued": [v.to_dict() for v in issued],
            "files": {
                p.name: p.read_bytes().hex() for p in sorted(base.glob("*.jsonl"))
            },
        }
    finally:
        pass


@pytest.mark.parametrize("case", CASES)
def test_original_product_approval_closure(case, tmp_path, monkeypatch):
    fixture = json.loads(
        (
            Path(__file__).with_name("fixtures") / "product_approval_closure_v1.json"
        ).read_text()
    )
    assert observe(case, tmp_path, monkeypatch) == fixture["observations"][case]
