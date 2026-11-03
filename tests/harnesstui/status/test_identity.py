from loushang.harnesstui.status.identity import short_session_ids


def test_visible_prefix_collisions_extend_only_as_far_as_needed():
    identifiers = (
        "d8525f5e12aaa",
        "d8525f5e12bbb",
        "d8525f5efaaa",
        "other-session",
        "short",
    )
    labels = short_session_ids(identifiers)
    assert labels == {
        "d8525f5e12aaa": "d8525f5e12a",
        "d8525f5e12bbb": "d8525f5e12b",
        "d8525f5efaaa": "d8525f5ef",
        "other-session": "other-se",
        "short": "short",
    }
    assert len(set(labels.values())) == len(identifiers)
    assert short_session_ids(reversed(identifiers)) == labels


def test_complete_prefix_and_repeated_ids_remain_unambiguous():
    assert short_session_ids(("abcdefgh", "abcdefgh1", "abcdefgh1")) == {
        "abcdefgh": "abcdefgh",
        "abcdefgh1": "abcdefgh1",
    }
