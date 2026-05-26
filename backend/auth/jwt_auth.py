import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt

from backend.config.loader import _env

_ALGORITHM = "HS256"
_ACCESS_TOKEN_EXPIRE_MINUTES = 480

_jwt_secret: Optional[str] = None


def _get_secret() -> str:
    global _jwt_secret
    if _jwt_secret is None:
        _jwt_secret = _env("JWT_SECRET", "")
    if not _jwt_secret:
        _jwt_secret = hashlib.sha256(os.urandom(32)).hexdigest()
    return _jwt_secret


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600000)
    return salt.hex() + ":" + dk.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600000)
        return dk.hex() == dk_hex
    except (ValueError, AttributeError):
        return False


def create_access_token(data: dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=_ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, _get_secret(), algorithm=_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    try:
        return jwt.decode(token, _get_secret(), algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        return None
