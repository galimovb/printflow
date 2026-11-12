"""Studio sign-in: the API token is entered once, the browser then keeps a signed JWT (HS256) in a cookie.

The signing key is derived from PRINTFLOW_WB_API_TOKEN (or set by PRINTFLOW_WB_JWT_SECRET), so changing the API
token signs everyone out. Scripts keep using the bearer API token.
"""

import base64
import hashlib
import hmac
import json
import time

COOKIE = "wb_studio_session"
TTL_SEC = 30 * 24 * 3600


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def signing_key(env: dict) -> bytes:
    secret = env.get("PRINTFLOW_WB_JWT_SECRET", "")
    if secret:
        return secret.encode()
    token = env.get("PRINTFLOW_WB_API_TOKEN", "")
    return hashlib.sha256(b"wb-studio-session:" + token.encode()).digest() if token else b""


def issue(key: bytes, ttl: int = TTL_SEC, now: float | None = None) -> str:
    now = int(now if now is not None else time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims = _b64(json.dumps({"sub": "wb-studio", "iat": now, "exp": now + ttl}, separators=(",", ":")).encode())
    signature = hmac.new(key, f"{header}.{claims}".encode(), hashlib.sha256).digest()
    return f"{header}.{claims}.{_b64(signature)}"


def valid(token: str, key: bytes, now: float | None = None) -> bool:
    if not key or not token or token.count(".") != 2:
        return False
    header, claims, signature = token.split(".")
    expected = hmac.new(key, f"{header}.{claims}".encode(), hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(_unb64(signature), expected):
            return False
        if json.loads(_unb64(header)).get("alg") != "HS256":
            return False
        data = json.loads(_unb64(claims))
    except (ValueError, json.JSONDecodeError):
        return False
    return data.get("sub") == "wb-studio" and int(data.get("exp", 0)) > (now if now is not None else time.time())
