"""Explicit conformance declaration for caller-supplied model transports."""

from __future__ import annotations

from typing import TypeVar, cast

from loushang.agent.types import StreamFn

_PREPARED_REQUEST_CONFORMANCE = "__loushang_prepared_request_conformance_v1__"
_SYNTHETIC_MODEL_TRANSPORT = "__loushang_synthetic_model_transport_v1__"
StreamFnT = TypeVar("StreamFnT", bound=StreamFn)


def prepared_request_conformant(stream_fn: StreamFnT) -> StreamFnT:
    """Declare that a custom stream honors CallOptions' commit-before-send seam.

    This is a trusted extension-boundary declaration.  Durable Product profiles
    use it to reject unconstrained custom transports before any model call.
    """

    if not callable(stream_fn):
        raise TypeError("prepared-request conformant stream must be callable")
    setattr(stream_fn, _PREPARED_REQUEST_CONFORMANCE, True)
    return stream_fn


def synthetic_model_transport(stream_fn: StreamFnT) -> StreamFnT:
    """Explicitly opt a test/simulation transport out of durable Model Input."""

    if not callable(stream_fn):
        raise TypeError("synthetic model stream must be callable")
    setattr(stream_fn, _SYNTHETIC_MODEL_TRANSPORT, True)
    return stream_fn


def is_prepared_request_conformant(stream_fn: object) -> bool:
    return bool(getattr(stream_fn, _PREPARED_REQUEST_CONFORMANCE, False))


def is_synthetic_model_transport(stream_fn: object) -> bool:
    return bool(getattr(stream_fn, _SYNTHETIC_MODEL_TRANSPORT, False))


def require_prepared_request_conformant(stream_fn: object) -> StreamFn:
    if not callable(stream_fn) or not is_prepared_request_conformant(stream_fn):
        raise ValueError(
            "durable Product sessions require the standard AI stream or a "
            "prepared_request_conformant custom stream"
        )
    return cast(StreamFn, stream_fn)


__all__ = [
    "is_prepared_request_conformant",
    "is_synthetic_model_transport",
    "prepared_request_conformant",
    "require_prepared_request_conformant",
    "synthetic_model_transport",
]
