"""Keep large native request copies off the generic container dispatch path."""

from collections import UserDict, UserList
from types import MappingProxyType

import pytest

from loushang.ai import prepared_request
from loushang.harness.transcript import model_input_types


@pytest.mark.parametrize(
    ("module", "name"),
    [
        (prepared_request, "_thaw_json"),
        (model_input_types, "thaw_model_input_json"),
    ],
)
def test_native_request_copy_avoids_generic_container_dispatch(
    monkeypatch, module, name
):
    # One protocol check per scalar becomes thousands of ABC lookups in a
    # long request. Native owned/frozen trees need no protocol discovery.
    class UnexpectedProtocolCheck(type):
        def __instancecheck__(cls, value):
            raise AssertionError("native JSON requested generic container dispatch")

    class Protocol(metaclass=UnexpectedProtocolCheck):
        pass

    source = {
        "messages": [
            MappingProxyType({"content": ("hello", None, True, 42, 1.5)})
            for _ in range(1000)
        ]
    }
    monkeypatch.setattr(module, "Mapping", Protocol)
    monkeypatch.setattr(module, "Sequence", Protocol)
    copied = getattr(module, name)(source)
    assert copied == {"messages": [{"content": ["hello", None, True, 42, 1.5]}] * 1000}
    copied["messages"][0]["content"].append("draft")
    assert source["messages"][0]["content"] == ("hello", None, True, 42, 1.5)
    assert copied["messages"][1]["content"] == ["hello", None, True, 42, 1.5]


@pytest.mark.parametrize(
    "thaw", [prepared_request._thaw_json, model_input_types.thaw_model_input_json]
)
def test_request_copy_preserves_custom_container_support(thaw):
    source = UserDict({"messages": UserList([UserDict({"content": "hello"})])})
    assert thaw(source) == {"messages": [{"content": "hello"}]}
    with pytest.raises(TypeError, match="keys must be strings"):
        thaw(UserDict({1: "invalid"}))
