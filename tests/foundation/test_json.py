import loushang.foundation.json as foundation_json


def test_foundation_json_is_the_canonical_public_surface() -> None:
    assert set(foundation_json.__all__) == {
        "JSONPrimitive",
        "JSONValue",
        "JsonValueError",
        "dump_json_value",
        "require_json_mapping",
        "require_json_value",
    }
    assert foundation_json.require_json_value({"ok": [True]}) == {"ok": [True]}
