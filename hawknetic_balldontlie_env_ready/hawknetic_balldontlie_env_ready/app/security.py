from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Optional

from itsdangerous import BadSignature, URLSafeSerializer

from app.config import settings


SESSION_COOKIE = "hawknetic_session"


class SessionManager:
    def __init__(self, secret_key: str) -> None:
        self.serializer = URLSafeSerializer(secret_key=secret_key, salt="hawknetic-session")

    def dumps(self, payload: dict) -> str:
        return self.serializer.dumps(payload)

    def loads(self, token: str) -> Optional[dict]:
        try:
            return self.serializer.loads(token)
        except BadSignature:
            return None


session_manager = SessionManager(settings.secret_key)


def hash_password(password: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 240_000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    candidate = hash_password(password=password, salt=salt)
    return hmac.compare_digest(candidate, stored)
