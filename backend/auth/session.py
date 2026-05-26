import base64
import os
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_SALT_PATH = None


def _get_salt_path() -> str:
    global _SALT_PATH
    if _SALT_PATH is None:
        from pathlib import Path
        _SALT_PATH = str(Path(__file__).resolve().parent.parent.parent / ".session_salt")
    return _SALT_PATH


def _load_or_create_salt() -> bytes:
    salt_path = _get_salt_path()
    try:
        with open(salt_path, "rb") as f:
            salt = f.read()
            if len(salt) == 16:
                return salt
    except (OSError, FileNotFoundError):
        pass
    salt = os.urandom(16)
    try:
        with open(salt_path, "wb") as f:
            f.write(salt)
    except OSError:
        pass
    return salt


def _derive_key(secret: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600000)
    return base64.urlsafe_b64encode(kdf.derive(secret.encode()))


def make_key_from_secret(secret: str) -> Optional[bytes]:
    if not secret or not secret.strip():
        return None
    salt = _load_or_create_salt()
    return _derive_key(secret, salt)


def encrypt_state(state: Dict[str, Any], key: bytes) -> str:
    import json
    f = Fernet(key)
    data = json.dumps(state).encode()
    return f.encrypt(data).decode()


def decrypt_state(token: str, key: bytes) -> Optional[Dict[str, Any]]:
    import json
    try:
        f = Fernet(key)
        data = f.decrypt(token.encode())
        return json.loads(data)
    except Exception:
        return None
