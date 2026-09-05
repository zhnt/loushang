"""Contract-only AppServer structural Product port surface.

No protocol, listener, service, connection, or transport runtime is activated
by this package.
"""

from .ports import (
    APPSERVER_PORT_CONTRACT_VERSION,
    AppServerProductPortsV1,
    AppServerSessionIdentityV1,
)

__all__ = [
    "APPSERVER_PORT_CONTRACT_VERSION",
    "AppServerProductPortsV1",
    "AppServerSessionIdentityV1",
]
