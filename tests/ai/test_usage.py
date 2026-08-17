from __future__ import annotations

import loushang.ai as ai_module
import loushang.ai.types as types_module
import loushang.ai.usage as usage_module
from loushang.ai.model import Pricing
from loushang.ai.pricing import calculate_usage_cost
from loushang.ai.types import Usage
from loushang.ai.usage import usage_payload


def test_usage_is_the_stable_response_usage_name() -> None:
    usage = Usage(
        input=10,
        output=5,
        cache_read=3,
        cache_write=2,
        total_tokens=20,
        cost=None,
    )

    assert usage_payload(usage) == {
        "present": True,
        "input": 10,
        "output": 5,
        "cacheRead": 3,
        "cacheWrite": 2,
        "totalTokens": 20,
        "cost": None,
    }

def test_removed_usage_observation_aliases_are_not_public_api() -> None:
    assert not hasattr(ai_module, "UsageObservation")
    assert not hasattr(types_module, "UsageObservation")
    assert not hasattr(ai_module, "usage_observation_from_message")
    assert not hasattr(ai_module, "usage_observation_payload")
    assert not hasattr(usage_module, "usage_observation_from_message")
    assert not hasattr(usage_module, "usage_observation_payload")


def test_platform_quota_helpers_are_not_core_usage_api() -> None:
    removed_names = (
        "EndpointQuotaQuery",
        "PlatformQuota",
        "PlatformQuotaError",
        "PlatformQuotaTransport",
        "PlatformQuotaUnsupportedError",
        "endpoint_quota_query_for_model",
        "platform_quota_from_payload",
        "platform_quota_payload",
        "query_platform_quota",
    )

    for name in removed_names:
        assert not hasattr(usage_module, name)


def test_calculate_usage_cost_uses_decimal_internally() -> None:
    cost = calculate_usage_cost(
        Pricing(input=0.1, output=0.2, cache_read=0, cache_write=0),
        Usage(
            input=3,
            output=7,
            cache_read=0,
            cache_write=0,
            total_tokens=10,
            cost=None,
        ),
    )

    assert cost == {
        "input": 0.0000003,
        "output": 0.0000014,
        "cacheRead": 0.0,
        "cacheWrite": 0.0,
        "total": 0.0000017,
    }
