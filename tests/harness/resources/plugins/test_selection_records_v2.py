from __future__ import annotations

from dataclasses import replace

import pytest

from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.declarations import (
    PluginDeclarationCodecError,
)
from loushang.harness.resources.plugins.selection import (
    PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION,
    PLUGIN_EXECUTION_DECISION_RECORD_VERSION,
    PluginExecutionApprovalSubject,
    PluginExecutionDecisionRecord,
    PluginInstanceRevisionRef,
)


def test_subject_v2_matches_the_normative_wrapper_sentinel() -> None:
    subject = _subject()
    expected = {
        "allowedAuthorityCeiling": ["process.launch"],
        "ambientHostAuthority": True,
        "configurationMapFingerprint": "1" * 64,
        "dependencyLockDigest": "2" * 64,
        "entrypoint": "definition.py:define",
        "instanceRevisionRef": {
            "instanceId": "coding.lsp@product",
            "pluginId": "coding.lsp",
            "revision": 1,
        },
        "packageContentDigest": "3" * 64,
        "packageSourceIdentity": "registry:example",
        "pluginId": "coding.lsp",
        "policyRevision": "policy-1",
        "productId": "coding",
        "requestedAuthorities": ["process.launch"],
        "reservationClosureFingerprint": "4" * 64,
        "schemaVersion": 2,
        "scopeId": "workspace",
        "sourceDescriptorFingerprint": (
            "c24ebbab018030bda115eee4257003ef8ac86423faa480fe158bce31fc0377b7"
        ),
        "sourceTrustClass": "registry_signed",
        "sourceTrustPolicyRevision": "trust-1",
    }
    wrapper = {
        "domain": "loushang.plugin-execution-approval-subject/v2",
        "subject": expected,
    }

    assert PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION == 2
    assert subject.to_dict() == expected
    assert PluginExecutionApprovalSubject.from_dict(expected) == subject
    assert StrictPluginJsonCodec.encode(wrapper) == (
        b'{"domain":"loushang.plugin-execution-approval-subject/v2","subject":'
        b'{"allowedAuthorityCeiling":["process.launch"],"ambientHostAuthority":true,'
        b'"configurationMapFingerprint":"1111111111111111111111111111111111111111111111111111111111111111",'
        b'"dependencyLockDigest":"2222222222222222222222222222222222222222222222222222222222222222",'
        b'"entrypoint":"definition.py:define","instanceRevisionRef":{"instanceId":'
        b'"coding.lsp@product","pluginId":"coding.lsp","revision":1},'
        b'"packageContentDigest":"3333333333333333333333333333333333333333333333333333333333333333",'
        b'"packageSourceIdentity":"registry:example","pluginId":"coding.lsp",'
        b'"policyRevision":"policy-1","productId":"coding","requestedAuthorities":'
        b'["process.launch"],"reservationClosureFingerprint":'
        b'"4444444444444444444444444444444444444444444444444444444444444444",'
        b'"schemaVersion":2,"scopeId":"workspace","sourceDescriptorFingerprint":'
        b'"c24ebbab018030bda115eee4257003ef8ac86423faa480fe158bce31fc0377b7",'
        b'"sourceTrustClass":"registry_signed","sourceTrustPolicyRevision":"trust-1"}}'
    )
    assert subject.digest == "cfa8e2bbeb73cc55c4e67149c4d6bc0b452b7d93c9d76bfa2bb610a3ebd330fb"


def test_decision_record_v2_has_independent_record_and_subject_versions() -> None:
    decision = PluginExecutionDecisionRecord(
        decision_id="decision-1",
        subject_digest=_subject().digest,
        policy_revision="policy-1",
        disposition="approved",
    )
    expected = {
        "decisionId": "decision-1",
        "decisionRecordVersion": 2,
        "disposition": "approved",
        "policyRevision": "policy-1",
        "subjectDigest": _subject().digest,
        "subjectSchemaVersion": 2,
    }

    assert PLUGIN_EXECUTION_DECISION_RECORD_VERSION == 2
    assert decision.to_dict() == expected
    assert PluginExecutionDecisionRecord.from_dict(expected) == decision


@pytest.mark.parametrize(
    ("document", "code"),
    [
        ({"schemaVersion": 1}, "unsupported_plugin_execution_approval_subject_version"),
        (
            {
                "decisionId": "legacy",
                "disposition": "approved",
                "policyRevision": "policy-1",
                "subjectDigest": "0" * 64,
            },
            "unsupported_plugin_execution_decision_record_version",
        ),
        (
            {
                "decisionId": "decision-1",
                "decisionRecordVersion": 2,
                "disposition": "approved",
                "policyRevision": "policy-1",
                "subjectDigest": "0" * 64,
                "subjectSchemaVersion": 1,
            },
            "unsupported_plugin_execution_approval_subject_version",
        ),
    ],
)
def test_subject_and_decision_legacy_versions_fail_exact_codes(
    document: dict[str, object],
    code: str,
) -> None:
    decoder = (
        PluginExecutionApprovalSubject.from_dict
        if "schemaVersion" in document
        else PluginExecutionDecisionRecord.from_dict
    )

    with pytest.raises(PluginDeclarationCodecError) as caught:
        decoder(document)

    assert caught.value.code == code


def test_subject_rejects_cross_field_authority_and_instance_mismatch() -> None:
    subject = _subject()
    with pytest.raises(ValueError, match="subset"):
        replace(
            subject,
            requested_authorities=("filesystem.write",),
        )
    with pytest.raises(ValueError, match="source descriptor"):
        replace(subject, source_descriptor_fingerprint="0" * 64)
    with pytest.raises(ValueError, match="Plugin id"):
        replace(
            subject,
            instance_revision_ref=PluginInstanceRevisionRef(
                instance_id="other@product",
                plugin_id="other",
                revision=1,
            ),
        )


def _subject() -> PluginExecutionApprovalSubject:
    return PluginExecutionApprovalSubject(
        plugin_id="coding.lsp",
        package_content_digest="3" * 64,
        dependency_lock_digest="2" * 64,
        entrypoint="definition.py:define",
        package_source_identity="registry:example",
        source_trust_class="registry_signed",
        source_trust_policy_revision="trust-1",
        product_id="coding",
        scope_id="workspace",
        policy_revision="policy-1",
        ambient_host_authority=True,
        configuration_map_fingerprint="1" * 64,
        requested_authorities=("process.launch",),
        allowed_authority_ceiling=("process.launch",),
        reservation_closure_fingerprint="4" * 64,
        source_descriptor_fingerprint=(
            "c24ebbab018030bda115eee4257003ef8ac86423faa480fe158bce31fc0377b7"
        ),
        instance_revision_ref=PluginInstanceRevisionRef(
            instance_id="coding.lsp@product",
            plugin_id="coding.lsp",
            revision=1,
        ),
    )
