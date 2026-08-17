from __future__ import annotations

import inspect
from dataclasses import fields
from types import SimpleNamespace

import loushang.harness.session.composition as composition_module
from loushang.harness.config.agent import CompactionSettings
from loushang.harness.session import ProductCompactionExecutor
from loushang.harness.session.composition import (
    ProductCompactionExecutor as CompositionProductCompactionExecutor,
)
from loushang.harness.session.composition import (
    SessionComposition,
    SessionCompositionPorts,
    SessionFoundationInputs,
    SessionMaintenanceInputs,
    SessionProductInputs,
    _compaction_policy,
    _resolve_compaction_capability,
    supports_prepare_model_call,
)
from loushang.harness.transcript import (
    TURN_AWARE_SUMMARY_IMPLEMENTATION,
    TURN_AWARE_SUMMARY_VERSION,
    TranscriptCompactionPolicy,
)


def test_product_compaction_executor_is_a_public_session_contract() -> None:
    assert ProductCompactionExecutor is CompositionProductCompactionExecutor


def test_summary_executor_preparation_compatibility_is_explicit() -> None:
    async def legacy(*, preparation):
        return preparation

    async def current(*, preparation, prepare_model_call=None):
        return preparation, prepare_model_call

    async def extensible(**kwargs):
        return kwargs

    async def misleading(*prepare_model_call):
        return prepare_model_call

    assert supports_prepare_model_call(legacy) is False
    assert supports_prepare_model_call(current) is True
    assert supports_prepare_model_call(extensible) is True
    assert supports_prepare_model_call(misleading) is False


def test_compaction_capability_fallback_uses_supported_integer_version() -> None:
    capability = _resolve_compaction_capability(object())

    assert capability.implementation == TURN_AWARE_SUMMARY_IMPLEMENTATION
    assert capability.implementation_version == TURN_AWARE_SUMMARY_VERSION


def test_session_composition_ports_exclude_runtime_owned_forwarders() -> None:
    names = {field.name for field in fields(SessionCompositionPorts)}

    assert names.isdisjoint(
        {
            "exec_service",
            "project_event",
            "refresh_agent_transcript_context",
            "refresh_resources_for_extension_runtime",
            "refresh_resources_for_extension_runtime_async",
            "serialize_context_usage",
            "compact_before_prompt",
            "compact_internal",
            "continue_run",
        }
    )


def test_session_composition_ports_are_grouped_by_assembly_phase() -> None:
    assert [field.name for field in fields(SessionCompositionPorts)] == [
        "agent",
        "session_manager",
        "settings",
        "capability_runtime",
        "foundation",
        "maintenance",
        "product",
    ]
    assert len(fields(SessionFoundationInputs)) < 30
    assert {field.name for field in fields(SessionMaintenanceInputs)} == {
        "execute_compaction",
        "before_compaction",
        "after_compaction",
        "sleep_for_retry",
    }
    assert {field.name for field in fields(SessionProductInputs)}.issuperset(
        {"model_registry", "extension_runner", "command_controller"}
    )


def test_session_composition_ports_accept_the_former_flat_keyword_contract() -> None:
    sentinel = object()
    names = {
        field.name
        for group in (
            SessionFoundationInputs,
            SessionMaintenanceInputs,
            SessionProductInputs,
        )
        for field in fields(group)
    }

    ports = SessionCompositionPorts(
        agent=sentinel,  # type: ignore[arg-type]
        session_manager=sentinel,  # type: ignore[arg-type]
        settings=sentinel,  # type: ignore[arg-type]
        capability_runtime=sentinel,  # type: ignore[arg-type]
        **dict.fromkeys(names, sentinel),
    )

    assert ports.foundation.resource_loader is sentinel
    assert ports.maintenance.execute_compaction is sentinel
    assert ports.product.model_registry is sentinel


def test_session_composition_is_a_frozen_assembly_result() -> None:
    assert SessionComposition.__dataclass_params__.frozen is True
    assert [field.name for field in fields(SessionComposition)] == [
        "capability_runtime",
        "foundation",
        "maintenance",
        "product",
        "package_controller",
        "command_controller",
        "extension_event_sink",
        "session_runtime",
        "extension_bridge",
    ]


def test_session_composition_uses_private_staged_builders() -> None:
    source = inspect.getsource(composition_module.compose_session_runtime)
    builder_names = {
        "_build_foundation_runtimes",
        "_build_maintenance_runtimes",
        "_build_product_bindings",
    }

    assert all(name in source for name in builder_names)
    assert builder_names.isdisjoint(composition_module.__all__)
    assert len(source.splitlines()) <= 150
    assert "SessionDiagnosticsRuntime(" not in source
    assert "AgentTranscriptCompactionRuntime(" not in source
    assert "SessionModelBinding(" not in source
    for container in (
        composition_module._FoundationRuntimes,
        composition_module._MaintenanceRuntimes,
        composition_module._ProductBindings,
    ):
        assert all("callback" not in field.name for field in fields(container))


def test_compaction_policy_uses_capability_without_product_override() -> None:
    capability = TranscriptCompactionPolicy(
        enabled=False,
        reserve_tokens=1_234,
        compact_percent=67,
        keep_recent_tokens=456,
    )

    assert _compaction_policy(None, capability) is capability


def test_compaction_policy_uses_capability_with_default_product_settings() -> None:
    capability = TranscriptCompactionPolicy(
        enabled=False,
        reserve_tokens=1_234,
        compact_percent=67,
        keep_recent_tokens=456,
    )

    assert _compaction_policy(CompactionSettings(), capability) == capability


def test_compaction_policy_applies_only_explicit_product_fields() -> None:
    capability = TranscriptCompactionPolicy(
        enabled=True,
        reserve_tokens=1_234,
        compact_percent=67,
        keep_recent_tokens=456,
    )

    assert _compaction_policy(
        CompactionSettings(enabled=False), capability
    ) == TranscriptCompactionPolicy(
        enabled=False,
        reserve_tokens=1_234,
        compact_percent=67,
        keep_recent_tokens=456,
    )


def test_compaction_policy_applies_explicit_product_override() -> None:
    capability = TranscriptCompactionPolicy(
        enabled=False,
        reserve_tokens=1_234,
        compact_percent=67,
        keep_recent_tokens=456,
    )
    override = SimpleNamespace(
        enabled=True,
        reserve_tokens=8_192,
        compact_percent=80,
        keep_recent_tokens=32_768,
    )

    assert _compaction_policy(override, capability) == TranscriptCompactionPolicy(
        enabled=True,
        reserve_tokens=8_192,
        compact_percent=80,
        keep_recent_tokens=32_768,
    )
