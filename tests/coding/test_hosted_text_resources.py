from base64 import b64encode
from hashlib import sha256
from types import SimpleNamespace

import pytest

from loushang.appserver.execution.model import ResourceRefV1
from loushang.appserver.execution.resources import SessionResourceQueryV1
from loushang.appserver.protocol import AppServiceError
from loushang.coding.hosted.resources import HostedResourceAccess


def test_managed_text_is_readable_only_after_its_user_record_is_committed(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    records = []
    access = HostedResourceAccess("chat", sessions, lambda: records)
    data = "第一行\nsecond line\n".encode()
    digest = sha256(data).hexdigest()
    result = access.exchange(SessionResourceQueryV1(
        "upload", digest, 0, len(data), "text/plain",
        b64encode(data).decode(), name="example.py",
    ))
    assert result.resources[0].name == "example.py"
    assert not access.exchange(SessionResourceQueryV1("list")).resources
    ref = ResourceRefV1(digest, digest)
    assert not access.images((ref,))
    with pytest.raises(AppServiceError):
        access.read_text(digest, offset=4)

    records.append(SimpleNamespace(payload=None, metadata=access.input_metadata((ref,))))
    restored = HostedResourceAccess("chat", sessions, lambda: records)
    assert restored.exchange(SessionResourceQueryV1("list")).resources == result.resources
    assert restored.read_text(digest, offset=4) == {"text": "second line\n", "nextOffset": None}
    unrelated = HostedResourceAccess("other", sessions, lambda: records)
    with pytest.raises(AppServiceError):
        unrelated.read_text(digest)
