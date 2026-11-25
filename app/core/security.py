# app/core/security.py

import hashlib
import hmac
import re
import secrets

_SESSION_ID = re.compile(r"^[0-9a-f]{64}$")


def new_session_id() -> str:
    return secrets.token_hex(32)


def _signature(key: bytes, session_id: str) -> str:
    return hmac.new(key, session_id.encode(), hashlib.sha256).hexdigest()[:32]


def sign_session(session_id: str, key: bytes) -> str:
    return f"{session_id}.{_signature(key, session_id)}"


def verify_session(token: str | None, key: bytes) -> str | None:
    if not token or len(token) > 128:
        return None
    session_id, _, signature = token.partition(".")
    if not _SESSION_ID.match(session_id) or not hmac.compare_digest(signature, _signature(key, session_id)):
        return None
    return session_id


def safe_equals(left: str, right: str) -> bool:
    return bool(left) and bool(right) and hmac.compare_digest(left.encode(), right.encode())


def is_legacy_session_id(token: str | None) -> bool:
    return bool(token) and bool(_SESSION_ID.match(token))
