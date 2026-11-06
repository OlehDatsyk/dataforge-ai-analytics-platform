"""Password hashing, session tokens, CSRF tokens, credential encryption, and rate limiting."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import defaultdict, deque

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

SESSION_COOKIE = "dataforge_session"
CSRF_COOKIE = "dataforge_csrf"
CSRF_HEADER = "x-csrf-token"

_hasher = PasswordHasher()
# Verified when the e-mail is unknown, so login timing does not reveal which accounts exist.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str | None) -> bool:
    try:
        ok = _hasher.verify(stored_hash or _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        return False
    return bool(ok and stored_hash)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_for_session(session_token: str) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, f"csrf:{session_token}".encode(), hashlib.sha256).hexdigest()


def csrf_is_valid(session_token: str, supplied: str | None) -> bool:
    return bool(supplied) and hmac.compare_digest(csrf_for_session(session_token), supplied)


def _fernet() -> Fernet:
    raw = get_settings().encryption_key
    try:
        return Fernet(raw.encode())
    except ValueError:
        # Accept any sufficiently long passphrase by deriving a valid Fernet key from it.
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest()))


def encrypt_secret(values: dict) -> str:
    return _fernet().encrypt(json.dumps(values).encode()).decode()


def decrypt_secret(token: str) -> dict:
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken as exc:
        raise ValueError("Stored credentials cannot be decrypted with the current ENCRYPTION_KEY.") from exc


class RateLimiter:
    """In-memory sliding-window limiter. It applies per process; see SECURITY.md for scaling notes."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = RateLimiter()
