import json

import pytest

from loushang.appserver.protocol import (
    AppOperationV1, AppRequestV1, AppResponseV1, InvalidAppMessageError,
    SessionScopeV1, WorkspaceInfoV1, WorkspaceRequestV1, WorkspaceResultV1,
    decode_request, decode_response, encode_request, encode_response,
)


@pytest.mark.parametrize('action,path', [('list', None), ('register', '/project'), ('open', '/project'), ('unregister', '/project')])
def test_workspace_requests_roundtrip(action, path):
    request = AppRequestV1('request-1', AppOperationV1.WORKSPACE, WorkspaceRequestV1(action, path))
    assert decode_request(encode_request(request)) == request


def test_workspace_results_preserve_host_path_and_admitted_scope():
    response = AppResponseV1('request-1', WorkspaceResultV1((WorkspaceInfoV1('/project', SessionScopeV1.CWD, 'a' * 64),)))
    assert decode_response(encode_response(response)) == response


@pytest.mark.parametrize('path', ['relative', '', '/bad\0path'])
def test_workspace_request_rejects_invalid_paths_at_protocol_boundary(path):
    with pytest.raises(ValueError):
        WorkspaceRequestV1('open', path)


def test_workspace_request_rejects_unknown_authority_fields():
    request = AppRequestV1('request-1', AppOperationV1.WORKSPACE, WorkspaceRequestV1('open', '/project'))
    wire = json.loads(encode_request(request))
    wire['payload']['controlGeneration'] = 42
    with pytest.raises(InvalidAppMessageError):
        decode_request(json.dumps(wire).encode())
