import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

_ph = PasswordHasher()
_dummy = None


def _dummy_hash():
    """Lazily built so importing the app stays fast; equalises timing for unknown accounts."""
    global _dummy
    if _dummy is None:
        _dummy = _ph.hash("not-a-real-password-for-timing")
    return _dummy


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str | None) -> bool:
    try:
        return _ph.verify(hashed or _dummy_hash(), pw) and hashed is not None
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_problem(pw: str) -> str | None:
    if len(pw) < 8:
        return "Password must be at least 8 characters."
    if not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        return "Password must contain letters and numbers."
    return None


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def temp_password() -> str:
    return secrets.token_urlsafe(9) + "7a"


def now() -> datetime:
    return datetime.now(timezone.utc)


def in_hours(h: float) -> datetime:
    return now() + timedelta(hours=h)
