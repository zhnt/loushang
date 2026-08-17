from __future__ import annotations

_SENSITIVE_KEYS = {
    "accountid",
    "accesstoken",
    "apikey",
    "apitoken",
    "authorization",
    "bearertoken",
    "clientsecret",
    "credential",
    "credentials",
    "cookie",
    "idtoken",
    "oauth",
    "oauthcredentials",
    "password",
    "proxyauthorization",
    "refreshtoken",
    "secret",
    "setcookie",
    "token",
    "tokens",
    "xaccesstoken",
    "xamzsecuritytoken",
    "xapikey",
    "xauthtoken",
    "xgoogapikey",
}
_SENSITIVE_KEY_MARKERS = (
    "accountid",
    "accesstoken",
    "apikey",
    "apitoken",
    "authorization",
    "bearertoken",
    "clientsecret",
    "credential",
    "credentials",
    "cookie",
    "idtoken",
    "oauth",
    "password",
    "proxyauthorization",
    "refreshtoken",
    "secret",
    "setcookie",
    "xamzsecuritytoken",
)
_SAFE_TOKEN_KEYS = {
    "cachecreationinputtokens",
    "cacheinputtokens",
    "cacheread",
    "cachereadinputtokens",
    "cachewrite",
    "cachewriteinputtokens",
    "inputtokens",
    "maxtokens",
    "maxoutputtokens",
    "outputtokens",
    "totaltokens",
}


def is_sensitive_key(key: str) -> bool:
    compacted = "".join(char for char in key.lower() if char.isalnum())
    if compacted in _SAFE_TOKEN_KEYS:
        return False
    if compacted in _SENSITIVE_KEYS:
        return True
    if any(marker in compacted for marker in _SENSITIVE_KEY_MARKERS):
        return True
    return compacted.endswith("token") or compacted.endswith("tokens")


def is_header_container_key(key: str) -> bool:
    compacted = "".join(char for char in key.lower() if char.isalnum())
    return compacted == "headers" or compacted.endswith("headers")


__all__ = ["is_header_container_key", "is_sensitive_key"]
